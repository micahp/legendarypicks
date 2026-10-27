#!/usr/bin/env python3
"""Independently compare Gate 1 samples and audit projected-roster accounting.

The source game records remain immutable and outside Git. This script reads
their JSONL wrappers, recomputes event-to-team/player/goalie/shift totals, and
checks that quarantine telemetry adds no gameplay changes to the paired-seed
projected-roster run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OLD_RUN = Path("/root/lp-data/nhl-game-rules-gate1-2026-10-26-post-da62d47b")
PROJECTED_RUN = Path(
    "/root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-v1-final-120")
TELEMETRY_RUN = Path(
    "/root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-v1-penalty-audit-120")
PRIOR_BEHAVIOR_AUDIT = ROOT / "research/nhl/behavior-evidence/results/nhl-behavior-evidence-2026-10-26.json"
CORRECTED_BEHAVIOR_AUDIT = ROOT / "research/nhl/behavior-evidence/results/nhl-behavior-evidence-event-state-v3-2026-10-27.json"
ATTEMPTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
SOG_EVENTS = {"goal", "shot-on-goal"}
SIDES = ("home", "away")


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _read_run(run_dir: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    summary = _read_json(run_dir / "summary.json")
    records: dict[int, dict[str, Any]] = {}
    with (run_dir / "games.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            wrapper = json.loads(line)
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("simulation_record"), dict):
                raise ValueError(f"{run_dir}/games.jsonl:{line_number}: missing simulation_record")
            seed = int(wrapper["seed"])
            if seed in records:
                raise ValueError(f"{run_dir}: duplicate seed {seed}")
            records[seed] = wrapper
    if len(records) != int(summary.get("generated_games", -1)):
        raise ValueError(f"{run_dir}: generated-game count disagrees with games.jsonl")
    if int(summary.get("generation_errors", -1)) != 0:
        raise ValueError(f"{run_dir}: generation errors present; retain them in report")
    return summary, records


def _strip_quarantine_telemetry(record: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    normalized["schema_version"] = "nhl-statistical-pbp-v0.2b-projected-roster-v1"
    for event in normalized.get("events", []):
        omission = (event.get("details") or {}).get("unsupported_penalty_omitted")
        if isinstance(omission, dict):
            omission.pop("candidate_coincidental", None)
            omission.pop("candidate_team_side", None)
            omission.pop("active_manpower_units_by_side", None)
            omission.pop("active_penalty_state_before", None)
    return normalized


def _record_roster_audit(wrapper: dict[str, Any]) -> dict[str, Any]:
    game = wrapper["simulation_record"]
    findings: list[dict[str, Any]] = []
    snapshot = game.get("pregame_snapshot") or {}
    projection = snapshot.get("projected_game_roster") or {}
    rows_by_side = projection.get("players_by_side") or {}
    players = game.get("summary", {}).get("player_totals") or {}
    rosters: dict[str, dict[str, str]] = {}
    all_ids: set[str] = set()

    for side in SIDES:
        rows = rows_by_side.get(side)
        if not isinstance(rows, list):
            findings.append({"type": "roster_rows_missing", "side": side})
            rosters[side] = {}
            continue
        roster: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("player_id") is None:
                findings.append({"type": "malformed_roster_row", "side": side})
                continue
            player_id = str(row["player_id"])
            if player_id in roster:
                findings.append({"type": "duplicate_roster_player", "side": side,
                                 "player_id": player_id})
            roster[player_id] = str(row.get("position", ""))
        overlap = all_ids.intersection(roster)
        if overlap:
            findings.append({"type": "cross_team_roster_identity", "player_ids": sorted(overlap)})
        all_ids.update(roster)
        rosters[side] = roster

    if set(map(str, players)) != all_ids:
        findings.append({"type": "projected_roster_player_totals_set_mismatch",
                         "roster_only": sorted(all_ids - set(map(str, players))),
                         "totals_only": sorted(set(map(str, players)) - all_ids)})
    for player_id, player in players.items():
        pid = str(player_id)
        side = player.get("team_side")
        if side not in SIDES or rosters.get(side, {}).get(pid) != player.get("position"):
            findings.append({"type": "player_totals_roster_identity_mismatch",
                             "player_id": pid, "team_side": side,
                             "position": player.get("position")})

    expected_player = defaultdict(Counter)
    expected_team = {side: Counter() for side in SIDES}
    expected_goalie = defaultdict(Counter)
    goal_events = 0
    shootout_attempts = 0
    goalie_transitions = 0
    shootout_team_roster_mismatches = 0
    events = game.get("events") or []
    for event in events:
        side = event.get("team_side")
        kind = event.get("event_type")
        participants = event.get("participants") or {}
        on_ice = event.get("on_ice") or {}
        for ice_side in SIDES:
            ids = [str(pid) for pid in on_ice.get(ice_side, [])]
            if len(ids) != len(set(ids)):
                findings.append({"type": "duplicate_on_ice_player", "sequence": event.get("sequence"),
                                 "team_side": ice_side})
            for pid in ids:
                if pid not in rosters.get(ice_side, {}):
                    findings.append({"type": "on_ice_outside_projected_roster",
                                     "sequence": event.get("sequence"),
                                     "team_side": ice_side, "player_id": pid})
        for key, value in participants.items():
            if key.endswith("_id") and value is not None and str(value) not in all_ids:
                findings.append({"type": "participant_outside_projected_roster",
                                 "sequence": event.get("sequence"), "field": key,
                                 "player_id": str(value)})
            elif key.endswith("_ids") and isinstance(value, list):
                for value_id in value:
                    if str(value_id) not in all_ids:
                        findings.append({"type": "participant_outside_projected_roster",
                                         "sequence": event.get("sequence"), "field": key,
                                         "player_id": str(value_id)})

        if side in SIDES and kind in ATTEMPTS and event.get("period_type") != "SO":
            expected_team[side]["shot_attempts"] += 1
            shooter = participants.get("shooter_id")
            if shooter is not None:
                expected_player[str(shooter)]["shot_attempts"] += 1
        if side in SIDES and kind in SOG_EVENTS and event.get("period_type") != "SO":
            expected_team[side]["shots_on_goal"] += 1
            shooter = participants.get("shooter_id")
            if shooter is not None:
                expected_player[str(shooter)]["shots_on_goal"] += 1
            defending = "away" if side == "home" else "home"
            goalie_id = participants.get("goalie_id")
            defending_goalies = [str(pid) for pid in on_ice.get(defending, [])
                                 if rosters.get(defending, {}).get(str(pid)) == "G"]
            if goalie_id is None:
                if not participants.get("empty_net") or defending_goalies:
                    findings.append({"type": "goalie_empty_net_state_mismatch",
                                     "sequence": event.get("sequence"),
                                     "defending_goalies_on_ice": defending_goalies})
            else:
                goalie_id = str(goalie_id)
                if (rosters.get(defending, {}).get(goalie_id) != "G"
                        or goalie_id not in defending_goalies
                        or participants.get("empty_net")):
                    findings.append({"type": "shot_goalie_not_projected_defending_goalie_on_ice",
                                     "sequence": event.get("sequence"),
                                     "goalie_id": goalie_id, "defending_side": defending,
                                     "goalies_on_ice": defending_goalies})
                expected_goalie[goalie_id]["shots_against"] += 1
                expected_goalie[goalie_id]["goals_against"] += int(kind == "goal")
                expected_goalie[goalie_id]["saves"] += int(kind == "shot-on-goal")

        if kind == "goal" and event.get("period_type") != "SO":
            goal_events += 1
            if side in SIDES:
                expected_team[side]["goals"] += 1
            shooter = participants.get("shooter_id")
            if shooter is not None:
                expected_player[str(shooter)]["goals"] += 1
            for assist_id in participants.get("assist_player_ids", []):
                expected_player[str(assist_id)]["assists"] += 1
        elif kind == "faceoff" and side in SIDES:
            expected_team[side]["faceoffs_won"] += 1
            winner = participants.get("faceoff_winner_id")
            loser = participants.get("faceoff_loser_id")
            if winner is not None:
                expected_player[str(winner)]["faceoffs_taken"] += 1
                expected_player[str(winner)]["faceoffs_won"] += 1
            if loser is not None:
                expected_player[str(loser)]["faceoffs_taken"] += 1
                expected_player[str(loser)]["faceoffs_lost"] += 1
        elif kind == "penalty" and side in SIDES:
            expected_team[side]["penalties"] += 1
            penalized = participants.get("penalized_player_id")
            if penalized is not None:
                expected_player[str(penalized)]["penalties"] += 1
                if (str(penalized) not in rosters.get(side, {})
                        or rosters[side].get(str(penalized)) == "G"):
                    findings.append({"type": "penalty_player_not_eligible_projected_skater",
                                     "sequence": event.get("sequence"),
                                     "team_side": side, "player_id": str(penalized)})
            server = participants.get("serving_player_id")
            if server is not None and (str(server) not in rosters.get(side, {})
                                       or rosters[side].get(str(server)) == "G"):
                findings.append({"type": "penalty_server_not_projected_skater",
                                 "sequence": event.get("sequence"),
                                 "team_side": side, "player_id": str(server)})
        elif kind == "hit" and side in SIDES:
            expected_team[side]["hits"] += 1
            hitter = participants.get("hitter_id")
            if hitter is not None:
                expected_player[str(hitter)]["hits"] += 1

        if kind == "blocked-shot":
            blocker = participants.get("blocker_id")
            if blocker is not None:
                expected_player[str(blocker)]["blocks"] += 1
        if kind == "shootout-attempt":
            shootout_attempts += 1
            shooter = participants.get("shooter_id")
            if side not in SIDES or shooter is None or str(shooter) not in rosters.get(side, {}):
                shootout_team_roster_mismatches += 1
                findings.append({"type": "shootout_shooter_outside_projected_team_roster",
                                 "sequence": event.get("sequence"),
                                 "team_side": side,
                                 "player_id": None if shooter is None else str(shooter)})
            if shooter is not None:
                expected_player[str(shooter)]["shootout_attempts"] += 1
                if (participants.get("attempt_result") == "goal"
                        or (event.get("details") or {}).get("attempt_result") == "goal"):
                    expected_player[str(shooter)]["shootout_goals"] += 1
        if kind == "goalie-substitution":
            goalie_transitions += 1
            for field in ("goalie_leaving_id", "goalie_entering_id"):
                pid = participants.get(field)
                if pid is not None and (str(pid) not in rosters.get(side, {})
                                        or rosters.get(side, {}).get(str(pid)) != "G"):
                    findings.append({"type": "goalie_transition_identity_not_on_projected_team_roster",
                                     "sequence": event.get("sequence"), "field": field,
                                     "team_side": side, "player_id": str(pid)})
            entering = participants.get("goalie_entering_id")
            leaving = participants.get("goalie_leaving_id")
            side_ice = {str(pid) for pid in on_ice.get(side, [])}
            if entering is not None and str(entering) not in side_ice:
                findings.append({"type": "goalie_transition_entering_goalie_not_on_ice",
                                 "sequence": event.get("sequence"), "player_id": str(entering)})
            if leaving is not None and str(leaving) in side_ice:
                findings.append({"type": "goalie_transition_leaving_goalie_still_on_ice",
                                 "sequence": event.get("sequence"), "player_id": str(leaving)})

    summary = game.get("summary") or {}
    team_totals = summary.get("team_totals") or {}
    players_as_strings = {str(pid): row for pid, row in players.items()}
    for side in SIDES:
        for field in ("goals", "shot_attempts", "shots_on_goal", "faceoffs_won", "penalties", "hits"):
            actual = int(team_totals.get(side, {}).get(field, -1))
            expected = int(expected_team[side][field])
            if actual != expected:
                findings.append({"type": "team_event_total_mismatch", "team_side": side,
                                 "field": field, "expected": expected, "actual": actual})
        if int((summary.get("regulation_overtime_score") or {}).get(side, -1)) != int(expected_team[side]["goals"]):
            findings.append({"type": "regulation_overtime_score_event_mismatch", "team_side": side})
    for pid, player in players_as_strings.items():
        for field in ("goals", "assists", "shot_attempts", "shots_on_goal", "faceoffs_taken",
                      "faceoffs_won", "faceoffs_lost", "penalties", "hits", "blocks",
                      "shootout_attempts", "shootout_goals"):
            actual = int(player.get(field, 0))
            expected = int(expected_player[pid][field])
            if actual != expected:
                findings.append({"type": "player_event_total_mismatch", "player_id": pid,
                                 "field": field, "expected": expected, "actual": actual})

    toi_by_player = Counter()
    for shift in game.get("shift_ledger") or []:
        pid = str(shift.get("player_id", ""))
        side = shift.get("team_side")
        start = int(shift.get("start_seconds", -1))
        end = int(shift.get("end_seconds", -1))
        duration = int(shift.get("duration_seconds", -1))
        period = int(shift.get("period_number", -1))
        period_type = shift.get("period_type")
        limit = 1200 if period_type == "REG" else 300 if period_type == "OT" else -1
        if (side not in SIDES or pid not in rosters.get(side, {}) or start < 0
                or end < start or end > limit or duration != end - start):
            findings.append({"type": "invalid_or_ineligible_shift_interval", "player_id": pid,
                             "team_side": side, "period_number": period})
        toi_by_player[pid] += duration
    for pid, player in players_as_strings.items():
        actual_toi = int(player.get("time_on_ice_seconds", -1))
        if actual_toi != toi_by_player[pid]:
            findings.append({"type": "player_toi_shift_ledger_mismatch", "player_id": pid,
                             "shift_seconds": toi_by_player[pid], "player_total_seconds": actual_toi})

    goalie_totals = summary.get("goalie_totals") or {}
    for goalie_id, stats in goalie_totals.items():
        gid = str(goalie_id)
        side = stats.get("team_side")
        if side not in SIDES or rosters.get(side, {}).get(gid) != "G":
            findings.append({"type": "goalie_total_outside_projected_goalie_roster",
                             "goalie_id": gid, "team_side": side})
        for field in ("shots_against", "goals_against", "saves"):
            actual = int(stats.get(field, 0))
            expected = int(expected_goalie[gid][field])
            if actual != expected:
                findings.append({"type": "goalie_event_total_mismatch", "goalie_id": gid,
                                 "field": field, "expected": expected, "actual": actual})

    omission_events = []
    for event in events:
        omission = (event.get("details") or {}).get("unsupported_penalty_omitted")
        if not isinstance(omission, dict):
            continue
        omission_events.append({
            "sequence": event.get("sequence"), "period_type": event.get("period_type"),
            "period_number": event.get("period_number"),
            "time_in_period": event.get("time_in_period"),
            "reason": omission.get("reason"),
            "penalty_kind": omission.get("penalty_kind"),
            "candidate_coincidental": omission.get("candidate_coincidental"),
            "candidate_team_side": omission.get("candidate_team_side"),
            "active_manpower_units_by_side": omission.get("active_manpower_units_by_side"),
            "active_penalty_state_before": omission.get("active_penalty_state_before"),
        })
        for penalty in omission.get("active_penalty_state_before") or []:
            penalty_side = penalty.get("team_side")
            penalty_player = str(penalty.get("player_id", ""))
            if (penalty_side not in SIDES or penalty_player not in rosters.get(penalty_side, {})
                    or rosters[penalty_side].get(penalty_player) == "G"):
                findings.append({"type": "quarantine_active_penalty_not_projected_skater",
                                 "sequence": event.get("sequence"),
                                 "team_side": penalty_side, "player_id": penalty_player})

    return {
        "seed": int(wrapper["seed"]), "game_id": str(wrapper["game_id"]),
        "target_index": int(wrapper["target_index"]),
        "pregame_snapshot_sha256": wrapper.get("pregame_snapshot_sha256"),
        "model_version": game.get("model_version"), "schema_version": game.get("schema_version"),
        "projected_roster_player_count": len(all_ids),
        "independent_event_accounting_findings": findings,
        "independent_event_accounting_pass": not findings,
        "shootout_attempts": shootout_attempts,
        "shootout_attempts_outside_projected_team_roster": shootout_team_roster_mismatches,
        "shootout_projected_team_roster_membership_pass": shootout_team_roster_mismatches == 0,
        "goalie_substitution_events": goalie_transitions,
        "goalie_transition_legal_timing_status": "NOT_ASSESSED: stoppage and bench-window semantics are absent",
        "omitted_penalty_transitions": omission_events,
        "independent_validator_structural_valid": (wrapper.get("independent_audit") or {}).get("structural_valid"),
        "independent_validator_penalty_status": next((check.get("status") for check in
            (wrapper.get("independent_audit") or {}).get("checks", [])
            if check.get("code") == "penalty_and_manpower"), None),
    }


def _conditional_rate_rows(path: Path) -> dict[str, Any]:
    audit = _read_json(path)
    rows: dict[str, Any] = {}
    for population in ("training_2019_2020", "development_2021"):
        rates = audit["event_rate_diagnostics"][population]
        rows[population] = {}
        for family in ("attempt", "sog", "goal", "penalty"):
            by_context = {row["context"]: row for row in rates[family]}
            rows[population][family] = {
                context: by_context.get(f"strength={context}")
                for context in ("5v5", "5v4", "4v5")
            }
    training = audit["behavior"]["training_2019_2020"]
    # The preserved prior audit predates the attribution table. Keep its
    # legacy counts as the before-state instead of fabricating a comparison.
    attribution = {row["key"]: int(row["count"])
                   for row in training.get("event_state_attribution", [])}
    penalty_fit_counts = {
        row["context"].removeprefix("strength="): int(
            row.get("events", row.get("observed_events", 0)))
        for row in audit["event_rate_diagnostics"]["training_2019_2020"]["penalty"]
        if row.get("context", "").startswith("strength=")
    }
    legacy_penalty_counts = {
        row["key"].removeprefix("penalty:"): int(row["count"])
        for row in training["event_counts_by_strength"]
        if row["key"].startswith("penalty:")
    }
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "analysis_version": audit.get("metadata", {}).get("analysis_version"),
        "training_seasons": audit.get("metadata", {}).get("training_seasons"),
        "development_seasons": audit.get("metadata", {}).get("development_seasons"),
        "source_attribution_counts": attribution,
        "training_penalty_event_counts_by_strength": penalty_fit_counts,
        "legacy_event_counts_by_reported_strength": legacy_penalty_counts,
        "overtime_shootout_evidence": {
            population: {
                "overtime": {row["key"]: int(row["count"])
                             for row in audit["behavior"][population]["overtime"]},
                "shootout": {row["key"]: int(row["count"])
                             for row in audit["behavior"][population]["shootout"]},
            }
            for population in ("training_2019_2020", "development_2021")
        },
        "conditional_event_rates": rows,
    }


def _seeds_with_check_status(rows: dict[int, dict[str, Any]], code: str,
                            status: str) -> set[int]:
    result = set()
    for seed, wrapper in rows.items():
        checks = (wrapper.get("independent_audit") or {}).get("checks", [])
        if any(check.get("code") == code and check.get("status") == status
               for check in checks):
            result.add(seed)
    return result


def run_audit(old_dir: Path, projected_dir: Path, telemetry_dir: Path,
              prior_behavior_path: Path = PRIOR_BEHAVIOR_AUDIT,
              corrected_behavior_path: Path = CORRECTED_BEHAVIOR_AUDIT) -> dict[str, Any]:
    old_summary, old_rows = _read_run(old_dir)
    projected_summary, projected_rows = _read_run(projected_dir)
    telemetry_summary, telemetry_rows = _read_run(telemetry_dir)
    prior_behavior = _conditional_rate_rows(prior_behavior_path)
    corrected_behavior = _conditional_rate_rows(corrected_behavior_path)
    old_seeds, projected_seeds, telemetry_seeds = set(old_rows), set(projected_rows), set(telemetry_rows)
    if old_seeds != projected_seeds or projected_seeds != telemetry_seeds:
        raise ValueError("paired-run seed populations do not match")

    stable_run_fields = (
        "training_start_seasons", "development_target_season", "eligible_2021_target_games",
        "selected_target_games", "draws_requested_per_game", "seed_mapping", "input_sources",
    )
    paired_fields_match = {
        field: old_summary.get(field) == projected_summary.get(field)
        for field in stable_run_fields
    }
    telemetry_fields_match = {
        field: projected_summary.get(field) == telemetry_summary.get(field)
        for field in stable_run_fields
    }

    telemetry_behavior_mismatch_seeds = []
    snapshot_mismatch_seeds = []
    for seed in sorted(projected_seeds):
        before = projected_rows[seed]
        after = telemetry_rows[seed]
        if before.get("pregame_snapshot_sha256") != after.get("pregame_snapshot_sha256"):
            snapshot_mismatch_seeds.append(seed)
        if _strip_quarantine_telemetry(before["simulation_record"]) != _strip_quarantine_telemetry(
                after["simulation_record"]):
            telemetry_behavior_mismatch_seeds.append(seed)

    old_nonpassing_seeds = {seed for seed, row in old_rows.items()
        if (row.get("independent_audit") or {}).get("structural_valid") is False}
    projected_nonpassing_seeds = {seed for seed, row in projected_rows.items()
        if (row.get("independent_audit") or {}).get("structural_valid") is False}
    telemetry_nonpassing_seeds = {seed for seed, row in telemetry_rows.items()
        if (row.get("independent_audit") or {}).get("structural_valid") is False}
    old_penalty_quarantine_seeds = _seeds_with_check_status(
        old_rows, "penalty_and_manpower", "QUARANTINED")
    projected_penalty_quarantine_seeds = _seeds_with_check_status(
        projected_rows, "penalty_and_manpower", "QUARANTINED")
    telemetry_penalty_quarantine_seeds = _seeds_with_check_status(
        telemetry_rows, "penalty_and_manpower", "QUARANTINED")
    old_shootout_not_assessed_seeds = _seeds_with_check_status(
        old_rows, "overtime_and_shootout", "NOT_ASSESSED")
    projected_shootout_not_assessed_seeds = _seeds_with_check_status(
        projected_rows, "overtime_and_shootout", "NOT_ASSESSED")
    telemetry_shootout_not_assessed_seeds = _seeds_with_check_status(
        telemetry_rows, "overtime_and_shootout", "NOT_ASSESSED")

    if not all(paired_fields_match.values()):
        raise ValueError(f"pre-roster and projected-roster run populations differ: {paired_fields_match}")
    if not all(telemetry_fields_match.values()):
        raise ValueError(f"projected-roster telemetry rerun population differs: {telemetry_fields_match}")
    if snapshot_mismatch_seeds:
        raise ValueError(f"telemetry-only rerun changed pregame snapshots: {snapshot_mismatch_seeds[:10]}")
    if telemetry_behavior_mismatch_seeds:
        raise ValueError(f"quarantine metadata changed gameplay records: {telemetry_behavior_mismatch_seeds[:10]}")

    run_accounts = []
    for seed in sorted(telemetry_seeds):
        result = _record_roster_audit(telemetry_rows[seed])
        if not result["independent_event_accounting_pass"]:
            run_accounts.append(result)

    all_telemetry_quarantines = []
    for seed in sorted(telemetry_seeds):
        wrapper = telemetry_rows[seed]
        for omission in _record_roster_audit(wrapper)["omitted_penalty_transitions"]:
            all_telemetry_quarantines.append({
                "seed": seed, "game_id": str(wrapper["game_id"]), **omission})
    reason_counts = Counter(row.get("reason") for row in all_telemetry_quarantines)
    candidate_side_counts = Counter(row.get("candidate_team_side") for row in all_telemetry_quarantines)

    return {
        "report_kind": "nhl_projected_roster_paired_run_and_behavior_audit",
        "runs": {
            "pre_roster": {"directory": str(old_dir), "summary_sha256": _canonical_hash(old_summary),
                           "games_jsonl_sha256": old_summary.get("games_jsonl_sha256"),
                           "games": len(old_rows), "structurally_valid": old_summary.get("independent_structural_valid_games"),
                           "structurally_nonpassing_seeds": sorted(old_nonpassing_seeds),
                           "penalty_quarantined_seeds": sorted(old_penalty_quarantine_seeds),
                           "overtime_shootout_not_assessed_seeds": sorted(old_shootout_not_assessed_seeds),
                           "model_versions": sorted({r["simulation_record"].get("model_version") for r in old_rows.values()}),
                           "schema_versions": sorted({r["simulation_record"].get("schema_version") for r in old_rows.values()})},
            "projected_roster_v1": {"directory": str(projected_dir), "summary_sha256": _canonical_hash(projected_summary),
                           "games_jsonl_sha256": projected_summary.get("games_jsonl_sha256"),
                           "games": len(projected_rows), "structurally_valid": projected_summary.get("independent_structural_valid_games"),
                           "structurally_nonpassing_seeds": sorted(projected_nonpassing_seeds),
                           "penalty_quarantined_seeds": sorted(projected_penalty_quarantine_seeds),
                           "overtime_shootout_not_assessed_seeds": sorted(projected_shootout_not_assessed_seeds),
                           "model_versions": sorted({r["simulation_record"].get("model_version") for r in projected_rows.values()}),
                           "schema_versions": sorted({r["simulation_record"].get("schema_version") for r in projected_rows.values()})},
            "projected_roster_quarantine_telemetry": {"directory": str(telemetry_dir), "summary_sha256": _canonical_hash(telemetry_summary),
                           "games_jsonl_sha256": telemetry_summary.get("games_jsonl_sha256"),
                           "games": len(telemetry_rows), "structurally_valid": telemetry_summary.get("independent_structural_valid_games"),
                           "structurally_nonpassing_seeds": sorted(telemetry_nonpassing_seeds),
                           "penalty_quarantined_seeds": sorted(telemetry_penalty_quarantine_seeds),
                           "overtime_shootout_not_assessed_seeds": sorted(telemetry_shootout_not_assessed_seeds),
                           "model_versions": sorted({r["simulation_record"].get("model_version") for r in telemetry_rows.values()}),
                           "schema_versions": sorted({r["simulation_record"].get("schema_version") for r in telemetry_rows.values()})},
        },
        "comparability": {
            "same_exact_seed_set_all_three_runs": old_seeds == projected_seeds == telemetry_seeds,
            "pre_roster_vs_projected_stable_fields_match": paired_fields_match,
            "projected_v1_vs_telemetry_stable_fields_match": telemetry_fields_match,
            "paired_seed_population_comparison_only": True,
            "pregame_snapshots_same_pre_roster_vs_projected": all(
                old_rows[s].get("pregame_snapshot_sha256") == projected_rows[s].get("pregame_snapshot_sha256")
                for s in old_seeds),
            "pregame_snapshots_same_projected_v1_vs_telemetry": not snapshot_mismatch_seeds,
            "snapshot_mismatch_seed_examples": snapshot_mismatch_seeds[:20],
            "telemetry_rerun_gameplay_unchanged_after_metadata_removal": not telemetry_behavior_mismatch_seeds,
            "telemetry_gameplay_mismatch_seeds": telemetry_behavior_mismatch_seeds[:50],
        },
        "structural_delta_pre_roster_to_projected": {
            "valid_before": old_summary.get("independent_structural_valid_games"),
            "valid_after": projected_summary.get("independent_structural_valid_games"),
            "valid_delta": int(projected_summary.get("independent_structural_valid_games", 0))
                          - int(old_summary.get("independent_structural_valid_games", 0)),
            "old_only_structurally_nonpassing_seeds": sorted(old_nonpassing_seeds - projected_nonpassing_seeds),
            "old_only_shootout_not_assessed_seeds": sorted(old_shootout_not_assessed_seeds - projected_shootout_not_assessed_seeds),
            "old_only_penalty_quarantine_seeds": sorted(old_penalty_quarantine_seeds - projected_penalty_quarantine_seeds),
            "shared_penalty_quarantine_seeds": sorted(old_penalty_quarantine_seeds & projected_penalty_quarantine_seeds),
            "new_only_penalty_quarantine_seeds": sorted(projected_penalty_quarantine_seeds - old_penalty_quarantine_seeds),
            "interpretation": "The eight old-only structural nonpasses are all overtime/shootout NOT_ASSESSED outcomes from the missing projected-roster eligibility evidence, not quarantines. The projected-roster run moves those checks to PASS within its projected-roster and active-ten-minute-misconduct scope; complete Rule 84.4 exclusions remain NOT_ASSESSED. It also has two new penalty quarantines. Thus the net structural-pass increase is 8 formerly NOT_ASSESSED outcomes minus 2 newly exposed unsupported penalty transitions. Snapshots and generated gameplay differ, so this is a paired-seed population comparison, not an identical-input counterfactual.",
        },
        "quarantine_audit": {
            "total_omitted_penalty_transitions": len(all_telemetry_quarantines),
            "pre_roster_penalty_quarantined_seeds": sorted(old_penalty_quarantine_seeds),
            "projected_roster_penalty_quarantined_seeds": sorted(projected_penalty_quarantine_seeds),
            "projected_roster_overtime_shootout_not_assessed_seeds": sorted(projected_shootout_not_assessed_seeds),
            "reason_counts": dict(sorted(reason_counts.items())),
            "candidate_team_side_counts": dict(sorted(candidate_side_counts.items())),
            "events": all_telemetry_quarantines,
        },
        "conditional_behavior_rate_correction": {
            "prior_audit": prior_behavior,
            "corrected_audit": corrected_behavior,
            "interpretation": "The prior single-state event-rate labels placed many penalty events in the wrong manpower context. The corrected rates reconcile the source situation code against shift left/right limits and exclude conflicts or missing labels. Counts do not represent a one-for-one move because ambiguous boundary events are excluded.",
        },
        "projected_roster_event_accounting": {
            "games_checked": len(telemetry_rows),
            "games_with_any_independent_accounting_findings": len(run_accounts),
            "failing_game_examples": run_accounts[:20],
            "goalie_substitution_events": sum(
                row["goalie_substitution_events"]
                for seed in telemetry_seeds for row in [_record_roster_audit(telemetry_rows[seed])]),
            "shootout_attempts": sum(
                row["shootout_attempts"]
                for seed in telemetry_seeds for row in [_record_roster_audit(telemetry_rows[seed])]),
            "shootout_attempts_outside_projected_team_roster": sum(
                row["shootout_attempts_outside_projected_team_roster"]
                for seed in telemetry_seeds for row in [_record_roster_audit(telemetry_rows[seed])]),
            "shootout_projected_team_roster_membership": "PASS" if not any(
                _record_roster_audit(telemetry_rows[seed])["shootout_attempts_outside_projected_team_roster"]
                for seed in telemetry_seeds) else "FAIL",
            "shootout_rule_84_4_full_exclusion_audit": "NOT_ASSESSED: the generator and independent validator exclude active ten-minute misconduct only; game-misconduct, match-penalty and designated-server exclusions are not represented as a complete checked set.",
            "goalie_transition_legality": "Identity/on-ice consistency is audited; legal stoppage and bench windows remain NOT_ASSESSED.",
            "official_target_lineup_match": "NOT_ASSESSED: the snapshots are prospective projections, not the submitted dressed lineups.",
        },
    }


def render_report(result: dict[str, Any]) -> str:
    runs = result["runs"]
    compare = result["comparability"]
    delta = result["structural_delta_pre_roster_to_projected"]
    q = result["quarantine_audit"]
    roster = result["projected_roster_event_accounting"]
    rate_correction = result["conditional_behavior_rate_correction"]
    historical_shootout = rate_correction["corrected_audit"][
        "overtime_shootout_evidence"]["development_2021"]
    lines = [
        "# NHL projected-roster and behavior evidence audit",
        "",
        "Date: 2026-10-27  ",
        "Scope: reconcile the 120-seed Gate 1 runs, audit projected-roster accounting and goalie transitions, and preserve unsupported penalty states. The Gate 1 acceptance threshold is unchanged.",
        "",
        "## Paired-run comparison",
        "",
        "| Run | Games | Structural PASS | Penalty quarantines (seeds) | OT/SO NOT_ASSESSED (seeds) | Model | Schema |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for key, label in (("pre_roster", "Pre-roster"),
                       ("projected_roster_v1", "Projected roster v1"),
                       ("projected_roster_quarantine_telemetry", "Telemetry rerun")):
        run = runs[key]
        penalty_seeds = ', '.join(map(str, run['penalty_quarantined_seeds'])) or 'none'
        shootout_na_seeds = ', '.join(map(str, run['overtime_shootout_not_assessed_seeds'])) or 'none'
        lines.append(f"| {label} | {run['games']} | {run['structurally_valid']} | {penalty_seeds} | {shootout_na_seeds} | {'; '.join(run['model_versions'])} | {'; '.join(run['schema_versions'])} |")
    lines += [
        "",
        f"The seed sets match across all three runs: **{compare['same_exact_seed_set_all_three_runs']}**. PBP, box-score and shift-manifest hashes match for the pre-roster and projected-roster runs: **{all(compare['pre_roster_vs_projected_stable_fields_match'].get(k, False) for k in ('input_sources', 'selected_target_games', 'seed_mapping', 'training_start_seasons', 'development_target_season'))}**. The roster change intentionally changes every pregame snapshot; this is a paired-seed population comparison, not an identical-input counterfactual. The telemetry rerun has unchanged projected snapshots: **{compare['pregame_snapshots_same_projected_v1_vs_telemetry']}**.",
        "",
        f"After removing only the three added quarantine metadata fields and normalizing the schema-version bump, simulator records are gameplay-identical to the projected-roster v1 run for every seed: **{compare['telemetry_rerun_gameplay_unchanged_after_metadata_removal']}**.",
        "",
        f"Structural PASS rises from {delta['valid_before']}/120 to {delta['valid_after']}/120 (+{delta['valid_delta']}). The pre-roster run's 11 non-PASS records comprise 3 penalty quarantines and 8 overtime/shootout `NOT_ASSESSED` records because no projected game roster was supplied. In projected-roster v1 those eight checks become PASS within the validator's modeled scope, and no OT/SO check remains `NOT_ASSESSED`; full Rule 84.4 exclusions are still not covered. The original three penalty-quarantine seeds remain; two additional penalty-quarantine seeds appear: {', '.join(map(str, delta['new_only_penalty_quarantine_seeds']))}. The net +6 reflects eight former `NOT_ASSESSED` statuses becoming scoped PASS minus two new penalty quarantines. Since roster snapshots and generated gameplay differ, this is a paired-seed population comparison, not an identical-snapshot causal effect.",
        "",
        "## Five penalty quarantines",
        "",
        f"The telemetry rerun preserves {q['total_omitted_penalty_transitions']} omitted penalty transitions: `{q['reason_counts']}`. Candidate team-side counts are `{q['candidate_team_side_counts']}`. Each event below remains an explicit `stoppage` with its unsupported-penalty marker; none is converted into a guessed penalty or manpower update.",
        "",
        "| Seed | Game | Event | Clock | Candidate side | Reason | Active units before |",
        "|---:|---:|---|---|---|---|---|",
    ]
    for event in q["events"]:
        lines.append(f"| {event['seed']} | {event['game_id']} | {event['sequence']} P{event['period_number']} | {event['time_in_period']} | {event.get('candidate_team_side')} | `{event.get('reason')}` | `{event.get('active_manpower_units_by_side')}` |")
    lines += [
        "",
        "## Overtime and shootout evidence",
        "",
        f"The 2021 development archive contains {historical_shootout['overtime'].get('games', 0):,} eligible games, {historical_shootout['overtime'].get('games_reaching_ot', 0):,} reaching overtime, {historical_shootout['overtime'].get('last_period:OT', 0):,} ending in overtime, and {historical_shootout['overtime'].get('games_reaching_shootout', 0):,} reaching a shootout. It records {historical_shootout['shootout'].get('attempts', 0):,} shootout attempts and {historical_shootout['shootout'].get('goals', 0):,} shootout goals. Historical OT/SO data were present; the prior gap was the lack of a game-specific projected-roster input for generated shooter membership checks.",
        "",
        f"Across the 120 telemetry games, the independent record audit checked {roster['shootout_attempts']:,} generated shootout attempts; projected-team-roster membership is **{roster['shootout_projected_team_roster_membership']}** with {roster['shootout_attempts_outside_projected_team_roster']} mismatches. This is an internal consistency result, not proof of the actual dressed lineup or complete Rule 84.4 eligibility. {roster['shootout_rule_84_4_full_exclusion_audit']}",
        "",
        "## Corrected conditional event rates",
        "",
        "The prior report's 2019–20 training event-rate fit labeled 26,596 attempts and 227 goals as 5v4, 4,587 attempts and 325 goals as 4v5, and 10,154 penalties as 4v5. The v3 extractor reconciles each PBP situation code against both shift limits, excludes boundary conflicts and missing labels from conditional fitting, and uses the matching source state. These remain descriptive event-state rates, not uniformly pre-decision probabilities when a code matches only the right limit.",
        "",
        "| Population | Event | Strength | Events | Exposure (team-min) | Rate / 60 (95% game-cluster CI) |",
        "|---|---|---|---:|---:|---:|",
    ]
    for population, label in (("training_2019_2020", "2019/20 train"),
                              ("development_2021", "2021 development")):
        for family in ("attempt", "sog", "goal", "penalty"):
            for strength in ("5v4", "4v5"):
                row = rate_correction["corrected_audit"]["conditional_event_rates"][population][family][strength]
                ci = row.get("cluster_95_ci_observed_per_60")
                ci_text = "—" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"
                events = row.get("events", row.get("observed_events"))
                lines.append(f"| {label} | {family} | {strength} | {events} | {row['team_exposure_minutes']:.1f} | {row['observed_per_60_team_minutes']:.3f} ({ci_text}) |")
    attr = rate_correction["corrected_audit"]["source_attribution_counts"]
    penalty_fit_counts = rate_correction["corrected_audit"]["conditional_event_rates"][
        "training_2019_2020"]["penalty"]
    lines += [
        "",
        f"Training penalty events at shift boundaries: {attr.get('penalty:at_shift_boundary', 0):,}; source codes matched the left limit: {attr.get('penalty:source_matches_left_limit', 0):,}, right limit: {attr.get('penalty:source_matches_right_limit', 0):,}, both: {attr.get('penalty:source_matches_both_boundary_states', 0):,}; excluded due to conflicts/missing state: {attr.get('penalty:excluded_from_conditional_fit', 0):,}. After exclusions, penalty event counts include {penalty_fit_counts['5v5'].get('events', 0):,} at 5v5, {penalty_fit_counts['5v4'].get('events', 0):,} at 5v4 and {penalty_fit_counts['4v5'].get('events', 0):,} at 4v5. The reported previous 10,154 at 4v5 was not a valid conditional label; the corrected extraction retains the evidence boundary and excludes ambiguous events rather than forcing all rows into a manpower bin.",
        "",
        "### Rules and evidence interpretation",
        "",
        "The pinned [2021–22 NHL Official Rules, Rule 26.1](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf) says a third player penalized while two teammates are serving does not begin serving until one earlier penalty expires; the third offender goes to the penalty bench, and a substitute may keep the team at no fewer than three skaters. Rule 26.2 also governs when the penalized players may return. The current model does not represent that queued service and substitution state, so the third-concurrent cases remain quarantined. It does not have evidence to pair a second penalty sampled at the same game-clock second with an existing penalty; that case remains quarantined as well. The actual synthetic candidate is not an observed penalty from the target game and has no one-to-one historical PBP event ID.",
        "",
        "The corrected historical behavior audit is produced separately from this run comparison. It reports source `situationCode` against shift left-limit and right-limit states, excludes unresolved boundary labels from conditional-rate fitting, and retains source game/event identifiers for historical examples. Do not use the projected target-game outcomes as pregame inputs.",
        "",
        "## Projected-roster, player-stat and goalie audit",
        "",
        f"Games checked: {roster['games_checked']}. Games with independently recomputed roster/event/TOI accounting findings: {roster['games_with_any_independent_accounting_findings']}. Goalie-substitution event count: {roster['goalie_substitution_events']}.",
        "",
        f"The audit reconciles event participants and on-ice IDs to projected rosters, team and player goals/shots/faceoffs/penalties/hits/blocks/shootout totals to emitted events, goalie saves/shots/goals to shot events, and player TOI to shift-ledger durations. Goalie identities and active on-ice presence are checked at shot and substitution events. Generated shootout shooter membership is {roster['shootout_projected_team_roster_membership']}; complete Rule 84.4 exclusion handling remains NOT_ASSESSED. Legal goalie pull/return timing also remains `NOT_ASSESSED`: the records do not encode a validated stoppage or bench-window decision. The projected roster is not proof of the actual dressed target-game lineup.",
        "",
        "## Full-population historical behavior audit",
        "",
        "The corrected 2019–20 training / 2021 development behavior audit is in `NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md`, with its machine-readable counts in the sibling `results/nhl-behavior-evidence-event-state-v3-2026-10-27.json`. It separates event-state attribution, boundary uncertainty, and the matched shot cohorts; event-rate confidence intervals are now reported in the same per-60 units as their point estimates. 2021 is development-only diagnostic evidence, not fresh model-selection data.",
        "",
        "## Decision",
        "",
        "Roster membership and accounting are supported for the projected roster in this 120-record sample. The two new penalty quarantines are explained by unsupported queued service; all five remain quarantined pending an explicit queue/penalty pairing model and independent transition fixtures. Goalie identity/presence checks are possible, but legal pull/return timing remains unassessed. Gate 1 is **not passed**; no acceptance gate is changed.",
        "",
        "### Frozen run provenance",
        "",
        f"Pre-roster games SHA-256: `{runs['pre_roster']['games_jsonl_sha256']}`  ",
        f"Projected-roster v1 games SHA-256: `{runs['projected_roster_v1']['games_jsonl_sha256']}`  ",
        f"Telemetry rerun games SHA-256: `{runs['projected_roster_quarantine_telemetry']['games_jsonl_sha256']}`  ",
        f"Telemetry rerun summary SHA-256: `{runs['projected_roster_quarantine_telemetry']['summary_sha256']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-roster", type=Path, default=OLD_RUN)
    parser.add_argument("--projected-roster", type=Path, default=PROJECTED_RUN)
    parser.add_argument("--telemetry-rerun", type=Path, default=TELEMETRY_RUN)
    parser.add_argument("--json-output", type=Path,
                        default=ROOT / "research/nhl/game-rules-gate1/results/roster-behavior-audit-2026-10-27.json")
    parser.add_argument("--report-output", type=Path,
                        default=ROOT / "docs/research/NHL-PROJECTED-ROSTER-BEHAVIOR-AUDIT-2026-10-27.md")
    args = parser.parse_args()
    result = run_audit(args.pre_roster, args.projected_roster, args.telemetry_rerun)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report_output.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"json": str(args.json_output), "report": str(args.report_output),
                      "json_sha256": hashlib.sha256(args.json_output.read_bytes()).hexdigest(),
                      "report_sha256": hashlib.sha256(args.report_output.read_bytes()).hexdigest(),
                      "quarantines": result["quarantine_audit"]["total_omitted_penalty_transitions"],
                      "roster_accounting_failures": result["projected_roster_event_accounting"][
                          "games_with_any_independent_accounting_findings"]}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
