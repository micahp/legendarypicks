#!/usr/bin/env python3
"""Compare fresh V1.7 replay of exactly the 47 saved failures with original IDs.

The source 1000-seed run is immutable; this validator reads a NEW batch run and
will not certify fixes without all 47 truly completed and verified simulations.
Research-only penalty probabilities still cannot be forecast-release approved.
"""
import argparse
import json
from pathlib import Path


def verify(failure_seed_list, replay_payload):
    expected = failure_seed_list["seeds"]
    if len(expected) != 47 or len(set(expected)) != 47:
        raise ValueError("source failure list must contain exactly 47 distinct seeds")
    if replay_payload.get("game_id") != failure_seed_list["game_id"]:
        raise ValueError("replay belongs to the wrong matchup")
    simulation = replay_payload.get("simulation") or {}
    if simulation.get("slc_profile") != "v1_7_candidate":
        raise ValueError("replay must use the v1_7_candidate profile")
    if simulation.get("requested_games") != 47:
        raise ValueError("replay did not request exactly 47 games")
    rows = (replay_payload.get("summary") or {}).get("outcomes") or []
    got = [row.get("seed") for row in rows]
    if len(got) != 47 or len(set(got)) != 47 or set(got) != set(expected):
        raise ValueError("replay does not contain exactly the pinned 47 seed IDs")
    failures = []
    for outcome in sorted(rows, key=lambda row: row["seed"]):
        reasons = []
        if not outcome.get("complete_game"):
            reasons.append("not_complete")
        if not outcome.get("mechanically_complete_game"):
            reasons.append("not_mechanically_complete")
        if not outcome.get("valid_full_game"):
            reasons.append("valid_full_game_false")
        if outcome.get("status") not in ("complete_regulation", "complete_overtime"):
            reasons.append("wrong_terminal_status")
        if outcome.get("error") or outcome.get("blocker"):
            reasons.append("error_or_blocker")
        if outcome.get("forecast_release_validated"):
            reasons.append("research_falsely_release_validated")
        if not outcome.get("research_only_penalty_model"):
            reasons.append("missing_research_penalty_scope")
        if reasons:
            failures.append({"seed": outcome["seed"], "reasons": reasons,
                             "status": outcome.get("status"),
                             "error": outcome.get("error"),
                             "blocker": outcome.get("blocker")})
    return {
        "replay_completed_successfully": not failures,
        "requested_original_failed_seeds": 47,
        "mechanically_verified_full_games": 47 - len(failures),
        "still_failing": len(failures),
        "failed_seeds": failures,
        "new_configuration_hash": simulation.get("configuration_hash"),
        "new_profile_model_id": simulation.get("resolved_model_id"),
        "new_source_snapshot_sha256": (replay_payload.get("data_sources") or {}).get(
            "source_snapshot_sha256"),
        "new_pregame_snapshot_sha256": (replay_payload.get("pregame_snapshot") or {}).get(
            "snapshot_sha256"),
        "research_release_approval": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-seeds", type=Path, required=True)
    parser.add_argument("--replay-report", type=Path, required=True)
    parser.add_argument("--audit-out", type=Path, required=True)
    args = parser.parse_args()
    failures = json.loads(args.failed_seeds.read_text())
    replay = json.loads(args.replay_report.read_text())
    audit = verify(failures, replay)
    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps(audit, indent=2, sort_keys=True))
    if audit["still_failing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
