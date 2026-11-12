"""V1.7 research-only, team-first penalty occurrence/type model.

The model predicts whether an *opportunity* has a foul and, if so, one
classified committing side/type. It does NOT enforce penalties, decide whether
to accept/decline a foul, or generate team/player effects from box-score counts.
Data ingestion must supply every eligible no-foul opportunity as a negative.

No changes to V1.6 RNG, game transitions or the frozen baseline are made here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import random
import re
from typing import Iterable

SCHEMA = "lp.slc.penalty-occurrence.v1"
NO_FOUL = "none"
PHASES = ("pre_snap", "live_ball")
PLAY_CLASSES = ("run", "dropback", "kick")
CATEGORIES = {
    "pre_snap": {
        # Only dead-ball, before-snap fouls belong here. Formation, motion,
        # and ordinary offside flags generally belong with a snapped play.
        "offense": ("false_start", "delay_of_game"),
        "defense": ("encroachment", "neutral_zone_infraction"),
    },
    "live_ball": {
        "offense": ("offensive_holding", "offensive_pass_interference",
                    "illegal_block", "intentional_grounding",
                    "illegal_formation", "illegal_shift", "illegal_motion"),
        "defense": ("defensive_holding", "defensive_pass_interference",
                    "illegal_contact", "roughing_passer", "offside"),
    },
}
# Unknown or multiple-foul opportunities are outside this first gated model.
# They must never be relabeled as NO_FOUL or silently discarded.
CATALOG = {
    phase: (NO_FOUL,) + tuple(
        f"{side}:{foul}" for side in ("offense", "defense")
        for foul in CATEGORIES[phase][side])
    for phase in PHASES
}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: str) -> datetime:
    value = str(value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include its UTC offset")
    return parsed


def _bucket_distance(to_go: int) -> str:
    if to_go <= 2:
        return "1-2"
    if to_go <= 5:
        return "3-5"
    if to_go <= 9:
        return "6-9"
    return "10+"


def _bucket_field(yardline_100: int) -> str:
    if yardline_100 < 20:
        return "0-19"
    if yardline_100 < 50:
        return "20-49"
    if yardline_100 < 80:
        return "50-79"
    return "80-100"


@dataclass(frozen=True)
class Context:
    phase: str
    rule_era: int
    offense_team: str
    defense_team: str
    down: int
    to_go: int
    yardline_100: int
    play_class: str = "pre_snap"

    def __post_init__(self):
        if self.phase not in PHASES:
            raise ValueError(f"unsupported penalty phase: {self.phase}")
        if self.phase == "pre_snap" and self.play_class != "pre_snap":
            raise ValueError("pre-snap prediction must not know the intended play class")
        if self.phase == "live_ball" and self.play_class not in PLAY_CLASSES:
            raise ValueError("live-ball opportunities require a run/dropback/kick intent")
        if not 1 <= self.down <= 4 or self.to_go < 1 or not 0 <= self.yardline_100 <= 100:
            raise ValueError("invalid down, distance or field position")
        if not self.offense_team or not self.defense_team or self.offense_team == self.defense_team:
            raise ValueError("offense and defense teams must be distinct")
        if self.rule_era < 1999:
            raise ValueError("rule era must identify a supported year")

    def keys(self) -> tuple[str, ...]:
        root = [self.phase, str(self.rule_era), self.play_class, str(self.down),
                _bucket_distance(self.to_go), _bucket_field(self.yardline_100)]
        return tuple(json.dumps(root[:n], separators=(",", ":")) for n in (1, 2, 3, 4, 6))


@dataclass(frozen=True)
class Opportunity:
    context: Context
    opportunity_id: str
    game_kickoff_utc: str
    source_published_utc: str
    outcome: str
    label_verified: bool
    foul_count: int
    disposition: str = "none"

    def validate(self, train_before_utc: str):
        if not self.opportunity_id:
            raise ValueError("opportunity ID is required")
        if not self.label_verified:
            raise ValueError("unverified penalty disposition/opportunity cannot train")
        if self.foul_count not in (0, 1):
            raise ValueError("multiple fouls require a separate joint-event model")
        if self.outcome not in CATALOG[self.context.phase]:
            raise ValueError(f"unknown or unsupported foul label: {self.outcome}")
        if (self.outcome == NO_FOUL) != (self.foul_count == 0):
            raise ValueError("foul_count and outcome disagree")
        if self.disposition not in ("none", "accepted", "declined"):
            raise ValueError("ambiguous/offsetting/multiple rulings need separate modeling")
        if self.outcome == NO_FOUL and self.disposition != "none":
            raise ValueError("no-foul opportunity cannot have enforcement")
        if self.outcome != NO_FOUL and self.disposition == "none":
            raise ValueError("observed foul requires a verified disposition")
        cutoff = _utc(train_before_utc)
        if _utc(self.game_kickoff_utc) >= cutoff:
            raise ValueError("future/holdout game would leak into penalty model")
        if _utc(self.source_published_utc) > cutoff:
            raise ValueError("source evidence was not published before training cutoff")


class PenaltyModel:
    """Smoothed categorical stage model with separate committing-team shrinkage.

    Context priors are backoff-smoothed from phase -> rule era -> play class ->
    down -> exact distance/field bucket. Team propensities are shrunk toward
    historical league-side rates, estimated from the *same opportunity*
    denominator. No offense/defense effects are applied to the event-free mass.
    """

    def __init__(self, *, train_before_utc: str, source_sha256: str,
                 context_strength: float = 30., team_strength: float = 100.,
                 team_effects: bool = True):
        if not _SHA.fullmatch(source_sha256):
            raise ValueError("source_sha256 must be a 64-character SHA256 hex digest")
        _utc(train_before_utc)
        if context_strength <= 0 or team_strength <= 0:
            raise ValueError("shrinkage strengths must be positive")
        self.train_before_utc = train_before_utc
        self.source_sha256 = source_sha256
        self.context_strength = float(context_strength)
        self.team_strength = float(team_strength)
        self.team_effects = bool(team_effects)
        self.context_counts: dict[str, Counter] = defaultdict(Counter)
        self.team_exposures: Counter = Counter()
        self.team_fouls: Counter = Counter()
        self.stage_exposures: Counter = Counter()
        self.stage_fouls: Counter = Counter()
        self.opportunities = 0
        self.fitted = False

    def fit(self, rows: Iterable[Opportunity]) -> "PenaltyModel":
        if self.fitted:
            raise ValueError("model already fitted; create a new instance")
        seen = set()
        for obs in rows:
            obs.validate(self.train_before_utc)
            identifier = (obs.context.phase, obs.opportunity_id)
            if identifier in seen:
                raise ValueError(f"duplicate penalty opportunity: {identifier}")
            seen.add(identifier)
            self.opportunities += 1
            for key in obs.context.keys():
                self.context_counts[key][obs.outcome] += 1
            phase = obs.context.phase
            self.stage_exposures[phase] += 1
            for side, team in (("offense", obs.context.offense_team),
                               ("defense", obs.context.defense_team)):
                self.team_exposures[json.dumps([phase, side, team])] += 1
            if obs.outcome != NO_FOUL:
                side = obs.outcome.split(":", 1)[0]
                self.team_fouls[json.dumps([
                    phase, side,
                    obs.context.offense_team if side == "offense" else obs.context.defense_team])] += 1
                self.stage_fouls[json.dumps([phase, side])] += 1
        if not self.opportunities:
            raise ValueError("cannot fit penalty model on an empty opportunity dataset")
        self.fitted = True
        return self

    def predict(self, context: Context) -> dict[str, float]:
        if not self.fitted:
            raise ValueError("penalty model must be fitted before prediction")
        root = context.keys()[0]
        if root not in self.context_counts:
            raise ValueError(f"no training opportunities for phase {context.phase}")
        allowed = CATALOG[context.phase]
        root_counts = self.context_counts[root]
        denom = sum(root_counts.values()) + len(allowed)
        probs = {outcome: (root_counts[outcome] + 1.) / denom for outcome in allowed}
        for key in context.keys()[1:]:
            counts = self.context_counts.get(key)
            if counts:
                n = sum(counts.values())
                prior = self.context_strength
                probs = {event: (counts[event] + prior * probs[event]) / (n + prior)
                         for event in allowed}
        if self.team_effects:
            phase = context.phase
            for side, team in (("offense", context.offense_team),
                               ("defense", context.defense_team)):
                baseline = self.stage_fouls[json.dumps([phase, side])] / self.stage_exposures[phase]
                n = self.team_exposures[json.dumps([phase, side, team])]
                if n == 0 or baseline == 0:
                    continue
                hits = self.team_fouls[json.dumps([phase, side, team])]
                shrunk_rate = (hits + self.team_strength * baseline) / (n + self.team_strength)
                ratio = max(1 / 3, min(3., shrunk_rate / baseline))
                for event in allowed:
                    if event.startswith(side + ":"):
                        probs[event] *= ratio
            total = sum(probs.values())
            probs = {event: weight / total for event, weight in probs.items()}
        return probs

    def sample(self, context: Context, rng: random.Random) -> str:
        """Returns a foul event key or 'none'. NEVER changes game state.

        The caller must use a dedicated named RNG stream and a separate
        deterministic penalty-rules engine before any play is credited.
        """
        probs = self.predict(context)
        threshold = rng.random()
        cumulative = 0.
        for event, probability in probs.items():
            cumulative += probability
            if threshold < cumulative:
                return event
        return list(probs)[-1]  # floating point endpoint only

    def score(self, heldout: Iterable[Opportunity]) -> dict:
        """Offline categorical log loss and multiclass/Bernoulli Brier.

        Refuse training-period observations to prevent in-sample metrics from
        being incorrectly advertised as a held-out result.
        """
        n, loss, brier, any_foul_brier = 0, 0., 0., 0.
        for row in heldout:
            # Expected heldout rows require a verified label but need not precede fit cutoff.
            future = "9999-01-01T00:00:00+00:00"
            row.validate(future)
            if _utc(row.game_kickoff_utc) < _utc(self.train_before_utc):
                raise ValueError("heldout evaluation includes training-period opportunity")
            probs = self.predict(row.context)
            loss -= math.log(max(1e-15, probs[row.outcome]))
            brier += sum((p - float(event == row.outcome)) ** 2
                         for event, p in probs.items())
            predicted_any = 1. - probs[NO_FOUL]
            any_foul_brier += (predicted_any - float(row.outcome != NO_FOUL)) ** 2
            n += 1
        if n == 0:
            raise ValueError("heldout evaluation requires opportunities")
        return {"n": n, "log_loss": loss / n,
                "multiclass_brier": brier / n, "any_foul_brier": any_foul_brier / n}

    def to_json(self) -> str:
        if not self.fitted:
            raise ValueError("cannot serialize an unfitted model")
        payload = {
            "schema": SCHEMA, "train_before_utc": self.train_before_utc,
            "source_sha256": self.source_sha256, "opportunities": self.opportunities,
            "context_strength": self.context_strength, "team_strength": self.team_strength,
            "team_effects": self.team_effects,
            "context_counts": {k: dict(v) for k, v in sorted(self.context_counts.items())},
            "team_exposures": dict(self.team_exposures),
            "team_fouls": dict(self.team_fouls),
            "stage_exposures": dict(self.stage_exposures),
            "stage_fouls": dict(self.stage_fouls),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, content: str) -> "PenaltyModel":
        doc = json.loads(content)
        if doc.get("schema") != SCHEMA:
            raise ValueError("unsupported penalty model schema")
        model = cls(train_before_utc=doc["train_before_utc"],
                    source_sha256=doc["source_sha256"],
                    context_strength=doc["context_strength"],
                    team_strength=doc["team_strength"],
                    team_effects=doc["team_effects"])
        model.context_counts = defaultdict(Counter, {
            k: Counter(v) for k, v in doc["context_counts"].items()})
        for key in ("team_exposures", "team_fouls", "stage_exposures", "stage_fouls"):
            setattr(model, key, Counter(doc[key]))
        model.opportunities = int(doc["opportunities"])
        if not model.opportunities:
            raise ValueError("serialized model has no observations")
        model.fitted = True
        return model

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
