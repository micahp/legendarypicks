#!/usr/bin/env python3
"""Independently audit frozen NHL v0.2 distribution artifacts with stdlib only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ATTEMPT_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
SOG_EVENTS = {"goal", "shot-on-goal"}


def audit(path: Path) -> dict[str, Any]:
    distribution = json.loads(path.read_text(encoding="utf-8"))
    if distribution.get("schema_version") != "nhl-statistical-full-game-distribution-v0.2-alpha2":
        raise ValueError(f"{path}: unexpected distribution schema")
    if distribution.get("model_version") != "nhl-team-conditioned-shift-player-v0.2-alpha2":
        raise ValueError(f"{path}: unexpected model version")
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
