"""Seeded, resumable simulation of one hypothetical game (nfl-seq v0.1).

Prediction only: every draw comes from the statistical model, the playbook tilt and this run's own
RNG. Nothing in this module reads an actual result. A run can be checkpointed as JSON and restored
to continue identically. A real event can be observed into a run; that returns a new run and leaves
the earlier one untouched, so a prediction made before the observation is never rewritten.

Output is a complete ordered play script in the shape of docs/GRIDIRON-CONTRACT-v1.md, labelled with
provenance. Use ``validate_script`` before serving or handing a script to a renderer.
"""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .events import Event
from .model import StatModel, clock_window, fg_bin, situation, weighted
from .playbook import CALLS, NeutralPlaybook, Playbook, checked_weights
from .rules import apply, initial_state
from .state import AWAY, GameState, HOME, OVERTIME_SECONDS, REGULATION_SECONDS, other, validate_state

MODEL_VERSION = "nfl-seq-v0.1"
RULES_VERSION = "nfl-2026-regular-season-approx-v0.1"
MAX_EVENTS = 1000
TIMEOUTS_HELD = 3
UNSUPPORTED_MECHANICS = (
    "penalties",
    "two_point_tries",
    "timeouts_and_challenges",
    "participants_and_rosters",
    "interception_and_fumble_return_yards",
    "regular_season_overtime_approximation",
    "clock_stops_beyond_the_empirical_runoff",
)


class SimulationError(RuntimeError):
    """The run cannot continue (for example it exceeds MAX_EVENTS). Raised, never padded."""


def derive_seed(game_key: str, snapshot_hash: str, model_version: str, trial: int) -> int:
    """Seed for one trial. The same inputs always give the same stream."""
    payload = json.dumps([game_key, snapshot_hash, model_version, trial], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def public_state(state: GameState, home_team: str, away_team: str) -> Dict[str, Any]:
    """The contract's canonical state, with team codes instead of sides."""
    team = {HOME: home_team, AWAY: away_team}
    offense = team.get(state.offense) if state.offense else None
    defense = team[other(state.offense)] if state.offense else None
    return {
        "quarter": state.period,
        "clock_seconds": state.clock,
        "phase": state.phase,
        "offense_team": offense,
        "defense_team": defense,
        "kicking_team": team.get(state.kicking) if state.kicking else None,
        "home_score": state.home_score,
        "away_score": state.away_score,
        "down": state.down,
        "yards_to_go": state.ydstogo,
        "yardline_100": state.yardline_100,
        "home_timeouts": TIMEOUTS_HELD,
        "away_timeouts": TIMEOUTS_HELD,
        "drive_index": state.drive_index,
        "result": state.result,
    }


def _choose(dist: Mapping[str, float], order: Sequence[str], rng: random.Random) -> str:
    """Pick a key with one uniform draw, scanning ``order`` so the result is platform-stable."""
    draw = rng.random()
    acc = 0.0
    last = None
    for key in order:
        prob = dist.get(key, 0.0)
        if prob <= 0:
            continue
        acc += prob
        last = key
        if draw < acc:
            return key
    if last is None:
        raise SimulationError("empty distribution")
    return last


def _game_seconds(state: Mapping[str, Any]) -> int:
    period = state["quarter"]
    if period <= 4:
        return (period - 1) * REGULATION_SECONDS + (REGULATION_SECONDS - state["clock_seconds"])
    return 4 * REGULATION_SECONDS + (period - 5) * OVERTIME_SECONDS + (OVERTIME_SECONDS - state["clock_seconds"])


class Simulator:
    """Binds a model, a playbook and the game's identity. Runs are started from it."""

    def __init__(
        self,
        model: StatModel,
        *,
        game_id: str,
        home_team: str,
        away_team: str,
        season: int,
        snapshot_hash: str,
        playbook: Optional[Playbook] = None,
        model_version: str = MODEL_VERSION,
    ):
        if home_team == away_team:
            raise ValueError("home and away teams must differ")
        self.model = model
        self.game_id = game_id
        self.home_team = home_team
        self.away_team = away_team
        self.season = season
        self.snapshot_hash = snapshot_hash
        self.playbook = playbook or NeutralPlaybook()
        self.model_version = model_version
        self.game_key = "%s|%s|%s" % (season, game_id, "%s@%s" % (away_team, home_team))
        self.simulation_id = self._simulation_id(0)

    def _simulation_id(self, seed: int) -> str:
        digest = hashlib.sha256(
            json.dumps(
                [self.game_key, self.snapshot_hash, self.model_version, self.model.variant, seed],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return "nfl-seq-%s-%d-%s" % (self.model.variant, seed, digest[:12])

    def start(self, seed: int) -> "Run":
        return Run.fresh(self, seed)

    def team(self, side: str) -> str:
        return self.home_team if side == HOME else self.away_team


class Run:
    """One game in progress. ``plays`` is the ordered script so far; ``state`` is its latest state."""

    def __init__(self, sim: Simulator, seed: int, state: GameState, rng: random.Random, plays: List[Dict[str, Any]]):
        self.sim = sim
        self.seed = seed
        self.state = state
        self.rng = rng
        self.plays = plays
        self.simulation_id = sim._simulation_id(seed)

    @classmethod
    def fresh(cls, sim: Simulator, seed: int) -> "Run":
        rng = random.Random(seed)
        opening = HOME if rng.random() < 0.5 else AWAY
        ot_kicker = HOME if rng.random() < 0.5 else AWAY
        return cls(sim, seed, initial_state(opening, ot_kicker), rng, [])

    @property
    def final(self) -> bool:
        return self.state.phase == "final"

    def advance(self) -> "Run":
        """Play events until the game is final. Returns self."""
        while not self.final:
            if len(self.plays) >= MAX_EVENTS:
                raise SimulationError("run %s exceeded %d events" % (self.simulation_id, MAX_EVENTS))
            event, call = self._draw_event()
            self._apply(event, call, provenance="simulated")
        return self

    def observe(self, event: Event) -> "Run":
        """Return a new run that has ``event`` applied as an observation. This run is unchanged."""
        if event.provenance != "observed":
            raise ValueError("observed events must carry provenance 'observed'")
        branch = self.copy()
        branch._apply(event, None, provenance="observed")
        return branch

    def copy(self) -> "Run":
        rng = random.Random()
        rng.setstate(self.rng.getstate())
        return Run(self.sim, self.seed, self.state, rng, [dict(play) for play in self.plays])

    def _apply(self, event: Event, call: Optional[str], provenance: str) -> None:
        before = self.state
        after, derived = apply(before, event)
        validate_state(after)
        self.state = after
        self.plays.append(self._record(event, call, before, after, derived, provenance))

    def _record(
        self,
        event: Event,
        call: Optional[str],
        before: GameState,
        after: GameState,
        derived: Sequence[Event],
        provenance: str,
    ) -> Dict[str, Any]:
        sequence = len(self.plays) + 1
        home, away = self.sim.home_team, self.sim.away_team
        return {
            "sequence": sequence,
            "id": "%s:%d" % (self.simulation_id, sequence),
            "event_type": event.kind,
            "provenance": provenance,
            "state_before": public_state(before, home, away),
            "decision": {"call": call, "playbook": self.sim.playbook.name, "playbook_version": self.sim.playbook.version},
            "outcome": {
                "yards": event.yards,
                "elapsed": min(event.elapsed, before.clock),
                "made": event.made,
                "touchback": event.touchback,
                "return_yards": event.return_yards,
                "fumble_lost": event.fumble_lost,
                "points_home": after.home_score - before.home_score,
                "points_away": after.away_score - before.away_score,
                "drive_ended": after.drive_index != before.drive_index,
            },
            "derived": [item.kind for item in derived],
            "state_after": public_state(after, home, away),
        }

    def _draw_event(self) -> Tuple[Event, Optional[str]]:
        state, model, rng = self.state, self.sim.model, self.rng
        if state.phase == "kickoff":
            elapsed = max(1, model["elapsed"].draw_int({"call": "kickoff", "sub": "normal"}, rng))
            if model["kickoff_touchback"].draw({}, rng) == "touchback":
                return Event("kickoff", offense=state.kicking, elapsed=elapsed, touchback=True), None
            ret = model["kickoff_implied_return"].draw_int({}, rng)
            return Event("kickoff", offense=state.kicking, elapsed=elapsed, return_yards=ret), None
        if state.phase == "try":
            made = model["xp"].draw({}, rng) == "make"
            elapsed = max(0, model["elapsed"].draw_int({"call": "extra_point", "sub": "normal"}, rng))
            return Event("extra_point", offense=state.offense, made=made, elapsed=elapsed), None
        return self._draw_scrimmage(state, model, rng)

    def _draw_scrimmage(self, state: GameState, model: StatModel, rng: random.Random) -> Tuple[Event, str]:
        team = self.sim.team(state.offense)
        diff = state.score(state.offense) - state.score(other(state.offense))
        ctx = situation(state.down, state.ydstogo, state.yardline_100, state.period, diff)
        base = model["call"].probabilities(dict(ctx, late=clock_window(state.period, state.clock)))
        weights = checked_weights(
            self.sim.playbook.call_weights(public_state(state, self.sim.home_team, self.sim.away_team), team)
        )
        dist = weighted(base, weights)
        if dist is None:
            raise SimulationError("playbook weights remove every call in state %r" % (ctx,))
        call = _choose(dist, CALLS, rng)
        if call == "run":
            yards = model["run_yards"].draw_int(ctx, rng)
            fumble = model["fumble"].draw({"call": "run"}, rng) == "yes"
            event = Event("run", offense=state.offense, yards=yards, fumble_lost=fumble, elapsed=self._time("run", model, rng))
            return event, call
        if call == "pass":
            return self._draw_pass(state, ctx, model, rng), call
        if call == "punt":
            gross = model["punt_gross"].draw_int({"field": ctx["field"]}, rng)
            ret = model["punt_return"].draw_int({}, rng)
            event = Event("punt", offense=state.offense, yards=gross, return_yards=ret, elapsed=self._time("punt", model, rng))
            return event, call
        if call == "field_goal":
            distance = state.yardline_100 + 17
            made = model["fg"].draw({"fg": fg_bin(distance)}, rng) == "make"
            event = Event("field_goal", offense=state.offense, made=made, elapsed=self._time("field_goal", model, rng))
            return event, call
        if call == "kneel":
            return Event("kneel", offense=state.offense, yards=-1, elapsed=self._time("kneel", model, rng)), call
        return Event("spike", offense=state.offense, yards=0, elapsed=self._time("spike", model, rng)), call

    def _draw_pass(self, state: GameState, ctx: Mapping[str, str], model: StatModel, rng: random.Random) -> Event:
        cls = model["pass_class"].draw(ctx, rng)
        if cls == "sack":
            yards = model["sack_yards"].draw_int({"field": ctx["field"]}, rng)
            fumble = model["fumble"].draw({"call": "pass"}, rng) == "yes"
            return Event("sack", offense=state.offense, yards=yards, fumble_lost=fumble, elapsed=self._time("pass", model, rng))
        if cls == "scramble":
            yards = model["scramble_yards"].draw_int({"field": ctx["field"]}, rng)
            fumble = model["fumble"].draw({"call": "pass"}, rng) == "yes"
            return Event("qb_scramble", offense=state.offense, yards=yards, fumble_lost=fumble, elapsed=self._time("pass", model, rng))
        if cls == "interception":
            return Event("interception", offense=state.offense, elapsed=self._time("pass", model, rng))
        if cls == "complete":
            yards = model["pass_yards"].draw_int({"dist": ctx["dist"], "field": ctx["field"]}, rng)
            fumble = model["fumble"].draw({"call": "pass"}, rng) == "yes"
            return Event("pass_complete", offense=state.offense, yards=yards, fumble_lost=fumble, elapsed=self._time("pass", model, rng))
        elapsed = max(1, model["elapsed"].draw_int({"call": "pass", "sub": "incomplete"}, rng))
        return Event("pass_incomplete", offense=state.offense, elapsed=elapsed)

    def _time(self, call: str, model: StatModel, rng: random.Random) -> int:
        return max(1, model["elapsed"].draw_int({"call": call, "sub": "normal"}, rng))


def script(run: Run) -> Dict[str, Any]:
    """The complete script for a finished run, with provenance, summary and validation."""
    if not run.final:
        raise SimulationError("the run is not final; advance it before exporting a script")
    sim, state = run.sim, run.state
    observed = sum(1 for play in run.plays if play["provenance"] == "observed")
    doc = {
        "schema_version": "1.0",
        "mode": "pregame_full_game",
        "simulation_id": run.simulation_id,
        "game_id": sim.game_id,
        "model_version": sim.model_version,
        "model_variant": sim.model.variant,
        "rules_version": RULES_VERSION,
        "seed": run.seed,
        "snapshot_hash": sim.snapshot_hash,
        "teams": {"home": sim.home_team, "away": sim.away_team},
        "playbook": {"name": sim.playbook.name, "version": sim.playbook.version},
        "provenance": {
            "outcomes": "sampled_statistical_baseline",
            "participants": "not_modeled",
            "motion": "not_produced",
            "observed_events": observed,
            "label": "HYPOTHETICAL MODEL SIMULATION",
        },
        "unsupported_mechanics": list(UNSUPPORTED_MECHANICS),
        "result": state.result,
        "final_score": {"home": state.home_score, "away": state.away_score},
        "plays": run.plays,
        "summary": summarise(run.plays),
    }
    doc["validation_problems"] = validate_script(doc)
    doc["valid_full_game"] = not doc["validation_problems"]
    return doc


def summarise(plays: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    calls: Dict[str, int] = {}
    points = {HOME: 0, AWAY: 0}
    counts = {"punts": 0, "field_goals_made": 0, "field_goals_attempted": 0, "sacks": 0, "interceptions": 0, "fumbles_lost": 0, "touchdowns": 0}
    for play in plays:
        call = play["decision"]["call"]
        if call:
            calls[call] = calls.get(call, 0) + 1
        out = play["outcome"]
        points[HOME] += out["points_home"]
        points[AWAY] += out["points_away"]
        kind = play["event_type"]
        if kind == "punt":
            counts["punts"] += 1
        elif kind == "field_goal":
            counts["field_goals_attempted"] += 1
            counts["field_goals_made"] += 1 if out["made"] else 0
        elif kind == "sack":
            counts["sacks"] += 1
        elif kind == "interception":
            counts["interceptions"] += 1
        if out["fumble_lost"]:
            counts["fumbles_lost"] += 1
        if out["points_home"] + out["points_away"] >= 6:
            counts["touchdowns"] += 1
    return {
        "plays": len(plays),
        "calls": dict(sorted(calls.items())),
        "points": {"home": points[HOME], "away": points[AWAY]},
        "drives": max((play["state_after"]["drive_index"] for play in plays), default=0),
        **counts,
    }


def validate_script(doc: Mapping[str, Any]) -> List[str]:
    """Return every contract problem found; an empty list means the script is internally consistent."""
    problems: List[str] = []
    plays = doc["plays"]
    if not plays:
        return ["script has no plays"]
    first = plays[0]["state_before"]
    if first["phase"] != "kickoff" or first["home_score"] or first["away_score"] or first["quarter"] != 1:
        problems.append("script does not start from the pregame kickoff")
    previous = None
    for index, play in enumerate(plays, start=1):
        if play["sequence"] != index:
            problems.append("sequence gap at %d" % index)
        before, after = play["state_before"], play["state_after"]
        if previous is not None and previous != before:
            problems.append("play %d does not start from the previous state_after" % index)
        if _game_seconds(after) < _game_seconds(before):
            problems.append("game time moved backwards at play %d" % index)
        if after["home_score"] < before["home_score"] or after["away_score"] < before["away_score"]:
            problems.append("score decreased at play %d" % index)
        previous = after
    last = plays[-1]["state_after"]
    if last["phase"] != "final":
        problems.append("script does not end in a final state")
    else:
        if (last["home_score"], last["away_score"]) != (doc["final_score"]["home"], doc["final_score"]["away"]):
            problems.append("final_score disagrees with the last state")
        if last["result"] != doc["result"]:
            problems.append("result disagrees with the last state")
    points_home = sum(play["outcome"]["points_home"] for play in plays)
    points_away = sum(play["outcome"]["points_away"] for play in plays)
    if (points_home, points_away) != (last["home_score"], last["away_score"]):
        problems.append("play points do not reconcile to the final score")
    return problems


def checkpoint(run: Run) -> Dict[str, Any]:
    """JSON-serialisable snapshot of a run, enough to resume it identically."""
    version, internal, gauss = run.rng.getstate()
    return {
        "simulation_id": run.simulation_id,
        "seed": run.seed,
        "state": run.state.to_dict(),
        "plays": run.plays,
        "rng": [version, list(internal), gauss],
    }


def restore(sim: Simulator, data: Mapping[str, Any]) -> Run:
    """Rebuild a run from ``checkpoint`` output for the same simulator inputs."""
    if data["simulation_id"] != sim._simulation_id(data["seed"]):
        raise ValueError("checkpoint belongs to a different simulator configuration")
    version, internal, gauss = data["rng"]
    rng = random.Random()
    rng.setstate((version, tuple(internal), gauss))
    state = GameState.from_dict(dict(data["state"]))
    validate_state(state)
    return Run(sim, data["seed"], state, rng, [dict(play) for play in data["plays"]])
