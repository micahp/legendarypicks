#!/usr/bin/env python3
"""Independently audit frozen NHL v0.2 distribution artifacts with stdlib only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ATTEMPT_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
SOG_EVENTS = {"goal", "shot-on-goal"}


def _audit_live_state(events: list[dict[str, Any]], players: dict[str, Any]) -> dict[str, int]:
    """Check penalties and personnel independently of the simulator module."""
    active: list[dict[str, Any]] = []
    pending: set[tuple[str, str]] = set()
    pending_second: int | None = None
    penalty_count = 0
    expiry_count = 0

    def absolute(event: dict[str, Any]) -> int:
        period = int(event["period_number"])
        elapsed = int(event["clock_elapsed_seconds"])
        return (period - 1) * 1200 + elapsed if period <= 3 else 3600 + elapsed

    def expected_manpower(period_type: str, pulled: dict[str, bool]) -> dict[str, int]:
        base = 3 if period_type == "OT" else 5
        penalties = {side: sum(p["side"] == side and p["kind"] in {"MIN", "MAJ"}
                               and not p["coincidental"] for p in active)
                     for side in ("home", "away")}
        counts = {"home": base, "away": base}
        diff = penalties["home"] - penalties["away"]
        if diff:
            short = "home" if diff > 0 else "away"
            units = min(2, abs(diff))
            counts[short] = max(3, base - units)
            if period_type == "OT":
                other = "away" if short == "home" else "home"
                counts[other] = min(5, base + units)
        for side, is_pulled in pulled.items():
            if is_pulled:
                counts[side] = min(6, counts[side] + 1)
        return counts

    for event in events:
        event_type = event["event_type"]
        if event["period_type"] == "SO":
            continue
        now = absolute(event)
        participants = event.get("participants") or {}
        side = event.get("team_side")
        player_id = str(participants.get("player_id") or "")

        if pending:
            key = (str(side or ""), player_id)
            if event_type != "penalty-expiration" or now != pending_second or key not in pending:
                raise ValueError("simultaneous penalty expiration records do not reconcile")
            pending.remove(key)
            expiry_count += 1
        elif event_type == "penalty-expiration":
            due = [p for p in active if p["end"] <= now]
            due_keys = {(p["side"], p["player_id"]) for p in due}
            key = (str(side or ""), player_id)
            if not due or key not in due_keys or any(p["end"] != now for p in due):
                raise ValueError("penalty expiration is missing, late, or unmatched")
            pending = due_keys - {key}
            pending_second = now if pending else None
            active = [p for p in active if (p["side"], p["player_id"]) not in due_keys]
            expiry_count += 1
        elif any(p["end"] <= now for p in active):
            raise ValueError("an active penalty passed its expiration without an event")

        on_ice = event.get("on_ice") or {}
        for ice_side, ids in on_ice.items():
            for pid in ids:
                if players[str(pid)]["team_side"] != ice_side:
                    raise ValueError(f"player {pid} appears on the wrong team at event {event['sequence']}")
                if any(p["side"] == ice_side and p["player_id"] == str(pid) and p["end"] > now
                       for p in active):
                    raise ValueError(f"penalized player {pid} remains on ice at event {event['sequence']}")

        details = event.get("details") or {}
        pulled = details.get("goalie_pulled")
        if (event_type not in {"period-start", "period-end", "game-end", "goalie-substitution"}
                and isinstance(pulled, dict)):
            expected = expected_manpower(event["period_type"], pulled)
            actual: dict[str, int] = {}
            for ice_side in ("home", "away"):
                ids = on_ice.get(ice_side, [])
                goalie_count = sum(players[str(pid)]["position"] == "G" for pid in ids)
                if goalie_count != (0 if pulled.get(ice_side, False) else 1):
                    raise ValueError(f"goalie presence disagrees with pull state at event {event['sequence']}")
                actual[ice_side] = len(ids) - goalie_count
            if actual != expected or event.get("strength") != f"{actual['home']}v{actual['away']}":
                raise ValueError(f"penalty manpower or strength does not reconcile at event {event['sequence']}")

        if event_type == "penalty":
            actor = str(participants.get("penalized_player_id") or "")
            server = str(participants.get("serving_player_id") or "")
            kind = str(details.get("penalty_kind") or "")
            duration = int(details.get("penalty_duration_seconds") or 0)
            coincidental = bool(details.get("coincidental", False))
            if (side not in {"home", "away"} or not actor or actor != server
                    or actor not in on_ice.get(side, []) or players[actor]["team_side"] != side
                    or players[actor]["position"] == "G"):
                raise ValueError(f"penalty actor/server is ineligible at event {event['sequence']}")
            valid_durations = {"MIN": {120, 240}, "MAJ": {300}, "MIS": {600}}
            if kind not in valid_durations or duration not in valid_durations[kind]:
                raise ValueError(f"unsupported penalty state at event {event['sequence']}")
            for prior in active:
                if prior["start"] == now and prior["side"] != side and \
                        (prior["kind"], prior["duration"], prior["coincidental"]) != (kind, duration, coincidental):
                    raise ValueError("coincident penalties disagree on kind, duration, or status")
            active.append({"side": side, "player_id": actor, "kind": kind, "duration": duration,
                           "start": now, "end": now + duration, "coincidental": coincidental})
            penalty_count += 1
        elif event_type in {"penalty-release", "penalty-segment-end"}:
            matches = [p for p in active if p["side"] == side and p["player_id"] == player_id]
            if not matches:
                raise ValueError(f"penalty resolution has no active penalty at event {event['sequence']}")
            penalty = matches[0]
            if event_type == "penalty-release":
                active.remove(penalty)
            else:
                if penalty["kind"] != "MIN" or penalty["duration"] != 240:
                    raise ValueError("only a double-minor segment can end early")
                penalty["end"] = now + 120

    if pending:
        raise ValueError("simultaneous penalties lack all expiration events")
    return {"penalty_events": penalty_count, "penalty_expiration_events": expiry_count}


def _audit_shootout(events: list[dict[str, Any]], summary: dict[str, Any],
                    players: dict[str, Any]) -> int:
    attempts = {"home": 0, "away": 0}
    goals = {"home": 0, "away": 0}
    decided: str | None = None
    decisions: list[str | None] = []

    def clinched() -> str | None:
        if attempts["home"] == attempts["away"] and min(attempts.values()) >= 3:
            if goals["home"] != goals["away"]:
                return "home" if goals["home"] > goals["away"] else "away"
        if max(attempts.values()) <= 3:
            for side in ("home", "away"):
                other = "away" if side == "home" else "home"
                if goals[side] > goals[other] + max(0, 3 - attempts[other]):
                    return side
        return None

    for event in events:
        if event["event_type"] == "shootout-attempt":
            if decided is not None:
                raise ValueError("shootout continued after its first decisive attempt")
            side = event.get("team_side")
            result = (event.get("details") or {}).get("attempt_result")
            participants = event.get("participants") or {}
            shooter = str(participants.get("shooter_id") or "")
            goalie = str(participants.get("goalie_id") or "")
            defending = "away" if side == "home" else "home"
            if (side not in attempts or result not in {"goal", "saved", "missed"}
                    or players[shooter]["team_side"] != side
                    or players[goalie]["team_side"] != defending
                    or players[goalie]["position"] != "G"):
                raise ValueError("shootout attempt has invalid participants or result")
            attempts[side] += 1
            goals[side] += int(result == "goal")
            decided = clinched()
        elif event["event_type"] == "shootout-decision":
            decisions.append(event.get("team_side"))
    expected = summary.get("shootout_winner")
    if expected is None:
        if sum(attempts.values()) or decisions:
            raise ValueError("shootout activity exists without a winner")
    elif decided != expected or decisions != [expected]:
        raise ValueError("shootout decision does not match the earliest clinching attempt")
    return sum(attempts.values())


def audit(path: Path) -> dict[str, Any]:
    distribution = json.loads(path.read_text(encoding="utf-8"))
    expected_model = {
        "nhl-statistical-full-game-distribution-v0.2-alpha2":
            "nhl-team-conditioned-shift-player-v0.2-alpha2",
        "nhl-statistical-full-game-distribution-v0.2b": {
            "nhl-game-state-v0.2b-b1", "nhl-game-state-v0.2b-b2"},
    }.get(distribution.get("schema_version"))
    if expected_model is None:
        raise ValueError(f"{path}: unexpected distribution schema")
    observed_model = distribution.get("model_version")
    if observed_model not in (expected_model if isinstance(expected_model, set) else {expected_model}):
        raise ValueError(f"{path}: unexpected model version")
    if distribution.get("candidate_block") != ("B2" if observed_model.endswith("-b2") else "B1") \
            and distribution.get("schema_version", "").endswith("v0.2b"):
        raise ValueError(f"{path}: candidate label and model version disagree")
    if not distribution.get("reproducibility_verified"):
        raise ValueError(f"{path}: fixed-seed reproduction was not verified")
    if distribution.get("simulation_count", 0) < 1:
        raise ValueError(f"{path}: empty simulation distribution")

    snapshot = distribution["pregame_snapshot"]
    schedule = distribution["schedule"]
    if schedule["frozen_as_of_utc"] >= schedule["scheduled_start_utc"]:
        raise ValueError(f"{path}: cutoff is not before scheduled puck drop")
    if snapshot.get("actual_target_game_stats_or_lineups_used") is not False:
        raise ValueError(f"{path}: target-game input boundary is not explicitly false")
    cutoff = schedule["frozen_as_of_utc"]
    for side in ("home", "away"):
        as_of = snapshot["team_model"][f"{side}_elo"]["as_of_utc"]
        if as_of > cutoff:
            raise ValueError(f"{path}: {side} team input is after frozen cutoff")

    game = distribution["example_game"]
    events = game["events"]
    summary = game["summary"]
    if game.get("record_complete") is not True or not events:
        raise ValueError(f"{path}: example game is incomplete")
    if game.get("seed") != distribution.get("base_seed"):
        raise ValueError(f"{path}: example seed differs from distribution base seed")
    if events[-1]["event_type"] != "game-end":
        raise ValueError(f"{path}: final event is not game-end")
    if [event["sequence"] for event in events] != list(range(1, len(events) + 1)):
        raise ValueError(f"{path}: event sequence is not contiguous")

    player_totals = summary["player_totals"]
    player_ids = set(player_totals)
    live_state_counts = _audit_live_state(events, player_totals)
    shootout_attempts = _audit_shootout(events, summary, player_totals)
    score = {"home": 0, "away": 0}
    sog = {"home": 0, "away": 0}
    attempts = {"home": 0, "away": 0}
    regulation_ot_goals = {"home": 0, "away": 0}
    last_period = 0
    last_elapsed: dict[int, int] = {}

    for event in events:
        period = int(event["period_number"])
        period_type = event["period_type"]
        elapsed = int(event["clock_elapsed_seconds"])
        event_type = event["event_type"]
        side = event["team_side"]
        if period < last_period or period < 1 or period > 5:
            raise ValueError(f"{path}: invalid event period ordering")
        if elapsed < last_elapsed.get(period, -1):
            raise ValueError(f"{path}: period clock moves backwards")
        last_period = period
        last_elapsed[period] = elapsed

        expected_type = "REG" if period <= 3 else "OT" if period == 4 else "SO"
        if period_type != expected_type:
            raise ValueError(f"{path}: period number/type mismatch")
        duration = 1200 if period_type == "REG" else 300 if period_type == "OT" else 0
        if not 0 <= elapsed <= duration:
            raise ValueError(f"{path}: event clock outside period bounds")
        if event["clock_remaining_seconds"] != duration - elapsed:
            raise ValueError(f"{path}: event remaining clock does not reconcile")

        expected_before = {"score": score.copy(), "sog_event_count": sog.copy()}
        if event["state_before"] != expected_before:
            raise ValueError(f"{path}: event {event['sequence']} before-state mismatch")

        if period_type != "SO" and side in score:
            if event_type in ATTEMPT_EVENTS:
                attempts[side] += 1
            if event_type in SOG_EVENTS:
                sog[side] += 1
            if event_type == "goal":
                score[side] += 1
                regulation_ot_goals[side] += 1
        elif event_type == "shootout-decision" and side in score:
            score[side] += 1

        expected_after = {"score": score.copy(), "sog_event_count": sog.copy()}
        if event["state_after"] != expected_after:
            raise ValueError(f"{path}: event {event['sequence']} after-state mismatch")

        for side_name, ids in event.get("on_ice", {}).items():
            if len(ids) != len(set(ids)) or any(str(pid) not in player_ids for pid in ids):
                raise ValueError(f"{path}: invalid on-ice player identity")
            if event_type not in {"period-start", "period-end", "game-end",
                                  "shootout-attempt", "shootout-decision"}:
                goalie_count = sum(player_totals[str(pid)]["position"] == "G" for pid in ids)
                skater_count = len(ids) - goalie_count
                if goalie_count > 1 or not 3 <= skater_count <= 6:
                    raise ValueError(
                        f"{path}: invalid {side_name} on-ice personnel at event {event['sequence']}"
                    )
        for key, value in event.get("participants", {}).items():
            ids = value if key.endswith("_ids") else [value] if key.endswith("_id") else []
            if any(pid is not None and str(pid) not in player_ids for pid in ids):
                raise ValueError(f"{path}: invalid participant identity")
        if period_type != "SO" and event_type in ATTEMPT_EVENTS:
            shooter = event.get("participants", {}).get("shooter_id")
            if shooter is None or str(shooter) not in player_ids:
                raise ValueError(f"{path}: shot attempt lacks eligible simulated shooter")

    for period in (1, 2, 3):
        period_events = [event for event in events if event["period_number"] == period]
        if not period_events or period_events[0]["event_type"] != "period-start":
            raise ValueError(f"{path}: regulation period {period} lacks start")
        if sum(event["event_type"] == "period-end" for event in period_events) != 1:
            raise ValueError(f"{path}: regulation period {period} lacks exactly one end")
        if period_events[0]["clock_elapsed_seconds"] != 0:
            raise ValueError(f"{path}: regulation period {period} starts off-clock")
        period_end = next(event for event in period_events if event["event_type"] == "period-end")
        if period_end["clock_elapsed_seconds"] != 1200:
            raise ValueError(f"{path}: regulation period {period} ends off-clock")
    if sum(event["event_type"] == "game-end" for event in events) != 1:
        raise ValueError(f"{path}: game does not have exactly one terminal event")

    if score != summary["official_final_score"] or sog != summary["sog_event_counts"]:
        raise ValueError(f"{path}: score or SOG does not reconcile with event stream")
    if regulation_ot_goals != summary["regulation_overtime_score"]:
        raise ValueError(f"{path}: regulation/OT goals do not reconcile")
    if score["home"] == score["away"]:
        raise ValueError(f"{path}: official final result is tied")
    shootout_winner = summary["shootout_winner"]
    expected_final = regulation_ot_goals.copy()
    shootout_decisions = [event for event in events if event["event_type"] == "shootout-decision"]
    if shootout_winner is None:
        if shootout_decisions or score != expected_final:
            raise ValueError(f"{path}: shootout accounting exists without a shootout winner")
    else:
        if shootout_winner not in {"home", "away"} or len(shootout_decisions) != 1:
            raise ValueError(f"{path}: shootout winner/decision accounting is invalid")
        expected_final[shootout_winner] += 1
        if shootout_decisions[0]["team_side"] != shootout_winner or score != expected_final:
            raise ValueError(f"{path}: shootout bonus goal does not reconcile")
    expected_winner = "home" if score["home"] > score["away"] else "away"
    if summary["winner"] != expected_winner:
        raise ValueError(f"{path}: winner does not match official final score")

    for side in ("home", "away"):
        team = summary["team_totals"][side]
        if team["shot_attempts"] != attempts[side] or team["shots_on_goal"] != sog[side]:
            raise ValueError(f"{path}: {side} attempt/SOG totals do not reconcile")
        if team["goals"] != regulation_ot_goals[side]:
            raise ValueError(f"{path}: {side} goal total does not reconcile")
        if sum(player["goals"] for player in player_totals.values()
               if player["team_side"] == side) != team["goals"]:
            raise ValueError(f"{path}: {side} player goals do not reconcile")

    if sum(player["shot_attempts"] for player in player_totals.values()) != sum(attempts.values()):
        raise ValueError(f"{path}: player attempts do not reconcile")
    if sum(player["shots_on_goal"] for player in player_totals.values()) != sum(sog.values()):
        raise ValueError(f"{path}: player SOG does not reconcile")
    player_goals = sum(player["goals"] for player in player_totals.values())
    assists = sum(player["assists"] for player in player_totals.values())
    if player_goals != sum(regulation_ot_goals.values()) or assists > 2 * player_goals:
        raise ValueError(f"{path}: player goal/assist accounting does not reconcile")
    for goalie in summary["goalie_totals"].values():
        if goalie["saves"] + goalie["goals_against"] != goalie["shots_against"]:
            raise ValueError(f"{path}: goalie saves and goals against do not reconcile")

    toi = {player_id: 0 for player_id in player_ids}
    for shift in game["shift_ledger"]:
        player_id = str(shift["player_id"])
        if player_id not in toi:
            raise ValueError(f"{path}: shift ledger has an ineligible player")
        toi[player_id] += int(shift["duration_seconds"])
    if any(player_totals[player_id]["time_on_ice_seconds"] != seconds
           for player_id, seconds in toi.items()):
        raise ValueError(f"{path}: player TOI does not reconcile to shift ledger")

    return {
        "path": str(path),
        "status": "PASS",
        "simulations": distribution["simulation_count"],
        "sample_game_events": len(events),
        "official_final_score": summary["official_final_score"],
        "team_totals": summary["team_totals"],
        "shift_rows": len(game["shift_ledger"]),
        **live_state_counts,
        "shootout_attempts": shootout_attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.artifacts:
        print(json.dumps(audit(path), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
