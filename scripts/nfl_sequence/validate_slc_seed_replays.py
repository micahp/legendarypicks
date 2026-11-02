#!/usr/bin/env python3
"""Validate exact pinned-source replays against archived MIN-DET boxscore sidecars."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from slc_realism_ranker import (DEFAULT_WEIGHTS, hard_gate, replay_equivalence,
                                select_marketing_scenarios, write_outputs)


def _load_scored_seed_features(seed_features_path: Path, rankings_path: Path) -> list[dict]:
    """Join Stage A scores back to the normalized per-seed records before replay validation."""
    with seed_features_path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    with rankings_path.open(newline="", encoding="utf-8") as handle:
        parsed_scores = list(csv.DictReader(handle))
    score_rows = {int(item["seed"]): item for item in parsed_scores}
    if len(score_rows) != len(parsed_scores):
        raise ValueError("duplicate seed in Stage A ranking CSV")
    seed_ids = [int(row["seed"]) for row in rows]
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("duplicate seed in normalized feature records")
    missing = set(seed_ids) - set(score_rows)
    extra = set(score_rows) - set(seed_ids)
    if missing or extra:
        raise ValueError(f"Stage A ranking seed coverage mismatch: missing={len(missing)} extra={len(extra)}")

    def number(value: str, seed: int, field: str, *, required: bool = True) -> float | None:
        if value == "":
            if required:
                raise ValueError(f"missing Stage A {field} for seed {seed}")
            return None
        return float(value)

    for row in rows:
        seed = int(row["seed"])
        score = score_rows[seed]
        row["realism_score"] = number(score["realism_score"], seed, "realism score")
        row["score_contributions"] = {
            group: number(score[f"score_{group}"], seed, f"{group} contribution")
            for group in DEFAULT_WEIGHTS
        }
        row["component_scores"] = {
            group: row["score_contributions"][group] / weight
            for group, weight in DEFAULT_WEIGHTS.items()
        }
        row["group_distances"] = {
            group: number(score[f"distance_{group}"], seed, f"{group} distance", required=False)
            for group in DEFAULT_WEIGHTS
        }
        row["replay_status"] = score.get("replay_status") or "not_tested"
        row["gate"] = hard_gate(row)
    return sorted(rows, key=lambda row: (-float(row["realism_score"]), int(row["seed"])))


def _canonical_hash(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _score_side(record: dict, boxscore: dict, home: bool) -> int | None:
    team_name = boxscore.get("home_team" if home else "away_team")
    team = next((item for item in boxscore.get("teams", []) if item.get("team") == team_name), None)
    if team is None:
        return None
    return (record.get("points") or {}).get(team.get("side"))


def _replay_evidence_mismatches(original: dict, replay: dict, record: dict) -> list[str]:
    """Compare replay scores and the archived team, player, drive, and quarter evidence."""
    def totals_by_team(boxscore: dict) -> dict:
        result = {}
        for team, periods in (boxscore.get("points_by_period") or {}).items():
            result[team] = sum(value for value in periods.values()
                               if isinstance(value, int) and not isinstance(value, bool))
        return result

    replay_scores = {}
    for team in replay.get("teams") or []:
        side = team.get("side")
        team_name = team.get("team")
        if side in {"A", "B"} and team_name:
            replay_scores[team_name] = (record.get("points") or {}).get(side)

    def valid_full_game(boxscore: dict, result_record: dict | None = None) -> bool:
        reconciled = (boxscore.get("reconciliation") or {}).get("status") == "passed"
        quarter_complete = boxscore.get("quarter_scoring_complete") is True
        record_valid = result_record is None or result_record.get("valid_full_game") is True
        return reconciled and quarter_complete and record_valid

    original_quarters = original.get("quarter_by_quarter") or {}
    replay_quarters = replay.get("quarter_by_quarter") or {}
    original_surface = {
        "score": totals_by_team(original),
        "teams": original.get("teams"),
        "players": original.get("players"),
        "drives": original_quarters.get("drive_summaries"),
        "quarters": original_quarters,
        "status": original.get("status"),
        "valid_full_game": valid_full_game(original),
    }
    replay_surface = {
        "score": replay_scores,
        "teams": replay.get("teams"),
        "players": replay.get("players"),
        "drives": replay_quarters.get("drive_summaries"),
        "quarters": replay_quarters,
        "status": replay.get("status"),
        "valid_full_game": valid_full_game(replay, record),
    }
    return replay_equivalence(original_surface, replay_surface)


def _trace_audit(trace: dict) -> list[str]:
    record = trace.get("result") or {}
    findings = []
    if trace.get("seed") != record.get("seed"):
        findings.append("trace_record_seed_mismatch")
    drives = record.get("drives") or []
    if not drives:
        findings.append("missing_drive_sequence")
        return findings
    sequence = 1
    for drive_index, drive in enumerate(drives, 1):
        plays = drive.get("plays") or []
        if drive.get("index") != drive_index:
            findings.append(f"drive_index_mismatch:{drive_index}")
        if not plays:
            findings.append(f"empty_drive_sequence:{drive_index}")
            continue
        if plays[0].get("state_before", {}).get("drive_index") != drive_index:
            findings.append(f"drive_state_index_mismatch:{drive_index}")
        for play in plays:
            if play.get("sequence") != sequence:
                findings.append(f"play_sequence_gap:{sequence}")
            if play.get("id") != f"{record.get('simulation_id')}:{sequence}":
                findings.append(f"play_id_mismatch:{sequence}")
            sequence += 1
            before, after = play.get("state_before") or {}, play.get("state_after") or {}
            if before.get("offense_team") != drive.get("offense_team"):
                findings.append(f"drive_possession_mismatch:{drive_index}:{play.get('sequence')}")
            for state in (before, after):
                spot = state.get("yardline_100")
                if spot is not None and (not isinstance(spot, int) or spot < 0 or spot > 100):
                    findings.append(f"illegal_yardline:{drive_index}:{play.get('sequence')}")
            if not isinstance(play.get("outcome"), dict):
                findings.append(f"missing_play_outcome:{drive_index}:{play.get('sequence')}")
    return sorted(set(findings))


def _participants_available(boxscore: dict) -> bool:
    for player in boxscore.get("players", []):
        has_opportunity = any(
            isinstance(value, (int, float)) and value != 0
            for category, stats in player.items()
            if category not in {"identity_namespace", "stable_player_id", "lp_player_id", "name", "team",
                                "position", "side", "roster_eligible", "starter", "starter_basis",
                                "attribution"}
            and isinstance(stats, dict)
            for value in stats.values()
        )
        if has_opportunity and (player.get("roster_eligible") is not True
                                or not player.get("stable_player_id")
                                or player.get("identity_namespace") != "nfl_gsis_id"):
            return False
    return True


def _load_archived_boxscores(paths: list[Path], selected: set[int]) -> dict[int, dict]:
    result = {}
    for path in sorted(paths):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") == "manifest":
                    continue
                seed = row.get("seed")
                if seed not in selected:
                    continue
                if seed in result:
                    raise ValueError(f"duplicate archived boxscore for seed {seed}")
                result[seed] = {key: value for key, value in row.items() if key != "type"}
    missing = selected - set(result)
    if missing:
        raise ValueError(f"missing archived boxscores for selected seeds: {sorted(missing)[:10]}")
    return result


def _load_traces(trace_dir: Path, selected: set[int]) -> dict[int, tuple[Path, dict]]:
    result = {}
    for seed in sorted(selected):
        path = trace_dir / f"seed-{seed}.json"
        if not path.exists():
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        if int(trace.get("seed", -1)) != seed:
            raise ValueError(f"replay trace identity mismatch in {path}")
        record = trace.get("result") or {}
        if record and int(record.get("seed", -1)) != seed:
            raise ValueError(f"replay record seed identity mismatch in {path}")
        result[seed] = (path, trace)
    return result


def validate_replays(*, top_path: Path, seed_features_path: Path, rankings_path: Path,
                     sidecar_dir: Path,
                     trace_dir: Path, contract_audit_path: Path, input_provenance_path: Path,
                     run_header_path: Path, out_dir: Path, top_n: int = 150,
                     marketing_n: int = 15) -> dict:
    ranked_all = _load_scored_seed_features(seed_features_path, rankings_path)
    stage_a_top = json.loads(top_path.read_text(encoding="utf-8"))
    selected = {int(row["seed"]) for row in stage_a_top[:top_n]}
    archived = _load_archived_boxscores(list(sidecar_dir.glob("worker-*.boxscores.jsonl")), selected)
    traces = _load_traces(trace_dir, selected)
    contract_audit = json.loads(contract_audit_path.read_text(encoding="utf-8"))
    audit_by_seed = {int(row["seed"]): row for row in contract_audit.get("seeds", [])}
    provenance = json.loads(input_provenance_path.read_text(encoding="utf-8"))
    run_header = json.loads(run_header_path.read_text(encoding="utf-8"))
    candidate_by_seed = {int(row["seed"]): row for row in ranked_all}
    replay_outcomes = {}
    for seed in selected:
        candidate = candidate_by_seed[seed]
        trace_entry = traces.get(seed)
        if trace_entry is None:
            candidate.update({"replay_status": "missing_replay", "complete_sequence": False,
                              "unsupported_sequence": True, "contract_compatible": False})
            candidate["gate"] = hard_gate(candidate)
            missing_result = {"seed": seed, "status": "missing_replay", "findings": ["missing_replay_file"]}
            replay_outcomes[seed] = missing_result
            manifest_dir = out_dir / "replay-manifests"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            missing_manifest = {
                "schema": "lp.nfl.slc-seed-replay-manifest.v1",
                "run_id": run_header.get("run_id"), "seed": seed,
                "source_commit": run_header.get("source_commit"), "source_worktree_dirty": False,
                "configuration_hash": None,
                "pinned_inputs": {
                    "database_sha256": run_header.get("database_sha256"),
                    "snapshot_sha256": run_header.get("snapshot_sha256"),
                    "playcall_artifact_sha256": run_header.get("playcall_artifact_sha256"),
                    "streak_file_sha256": run_header.get("streak_file_sha256"),
                    "archived_boxscore_sha256": _canonical_hash(archived[seed]),
                },
                "reproduction_command": _reproduction_command(seed, run_header),
                "replay_output_sha256": None, "replay_boxscore_sha256": None,
                "validation": missing_result,
            }
            (manifest_dir / f"seed-{seed}.json").write_text(
                json.dumps(missing_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue
        trace_path, trace = trace_entry
        record = trace.get("result") or {}
        replay_source_commit = (trace.get("source") or {}).get("base_commit") or (trace.get("source") or {}).get("commit")
        replay_boxscore = trace.get("replay_boxscore")
        original_boxscore = archived[seed]
        boxscore_equal = isinstance(replay_boxscore, dict) and replay_boxscore == original_boxscore
        participants_available = _participants_available(replay_boxscore or {})
        equivalence_mismatches = (_replay_evidence_mismatches(original_boxscore, replay_boxscore, record)
                                  if isinstance(replay_boxscore, dict) else ["missing_replay_boxscore"])
        status_equal = record.get("status") == candidate.get("source_status", candidate.get("status"))
        full_game_flag_equal = record.get("valid_full_game") is candidate.get("valid_full_game")
        expected_home = _score_side(record, original_boxscore, True)
        expected_away = _score_side(record, original_boxscore, False)
        score_equal = (expected_home == record.get("points", {}).get("A")
                       and expected_away == record.get("points", {}).get("B"))
        trace_findings = _trace_audit(trace)
        audit = audit_by_seed.get(seed, {})
        adapter_passed = audit.get("passed") is True and audit.get("validation_passed") is True
        sequence_complete = bool(
            record.get("valid_full_game") is True and record.get("complete_regulation")
            and record.get("final_quarter") == 4
            and record.get("final_clock_seconds") == 0 and record.get("complete_game")
            and not record.get("unmodelled_transitions") and not record.get("unsupported_rules")
            and not trace_findings
        )
        exact = bool(boxscore_equal and score_equal and not equivalence_mismatches and status_equal
                     and full_game_flag_equal and participants_available
                     and trace.get("playcall", {}).get("summary")
                     and replay_source_commit == run_header.get("source_commit"))
        # The archived boxscore is the exact comparison surface for score, team/player stats, drives and quarters.
        reasons = []
        if not boxscore_equal:
            reasons.append("archived_boxscore_mismatch")
        if not score_equal:
            reasons.append("score_mismatch")
        if not status_equal:
            reasons.append("replay_status_mismatch")
        if not full_game_flag_equal:
            reasons.append("replay_full_game_flag_mismatch")
        reasons.extend(f"replay_equivalence_mismatch:{field}" for field in equivalence_mismatches)
        if not participants_available:
            reasons.append("essential_participant_unavailable_or_unidentified")
        if replay_source_commit != run_header.get("source_commit"):
            reasons.append("replay_source_commit_mismatch")
        if not sequence_complete:
            reasons.extend(trace_findings or ["incomplete_or_unsupported_full_game_sequence"])
        if not adapter_passed:
            reasons.extend(audit.get("findings") or ["gridiron_e2_adapter_rejected_record"])
        candidate.update({
            "replay_status": "passed" if exact and sequence_complete and adapter_passed else "rejected",
            "complete_sequence": sequence_complete,
            "unsupported_sequence": not sequence_complete,
            "contract_compatible": adapter_passed,
            "essential_participants_available": participants_available,
            "replay_boxscore_equal": boxscore_equal,
            "replay_score_equal": score_equal,
            "replay_status_equal": status_equal,
            "replay_full_game_flag_equal": full_game_flag_equal,
            "replay_equivalence_mismatches": equivalence_mismatches,
            "replay_trace_play_count": sum(len(drive.get("plays", [])) for drive in record.get("drives", [])),
        })
        candidate["gate"] = hard_gate(candidate)
        if not candidate["gate"]["renderable"]:
            reasons.extend(candidate["gate"]["render_reasons"])
        replay_outcomes[seed] = {
            "seed": seed,
            "status": candidate["replay_status"],
            "archived_boxscore_equal": boxscore_equal,
            "score_equal": score_equal,
            "status_equal": status_equal,
            "full_game_flag_equal": full_game_flag_equal,
            "replay_equivalence_mismatches": equivalence_mismatches,
            "trace_play_count": candidate["replay_trace_play_count"],
            "trace_drive_count": len(record.get("drives", [])),
            "gridiron_adapter_passed": adapter_passed,
            "essential_participants_available": participants_available,
            "findings": sorted(set(reasons)),
        }
        replay_manifest = {
            "schema": "lp.nfl.slc-seed-replay-manifest.v1",
            "run_id": run_header.get("run_id"),
            "seed": seed,
            "source_commit": run_header.get("source_commit"),
            "source_worktree_dirty": False,
            "configuration_hash": (replay_boxscore or {}).get("configuration_hash"),
            "pinned_inputs": {
                "database_sha256": run_header.get("database_sha256"),
                "snapshot_sha256": run_header.get("snapshot_sha256"),
                "playcall_artifact_sha256": run_header.get("playcall_artifact_sha256"),
                "streak_file_sha256": run_header.get("streak_file_sha256"),
                "archived_boxscore_sha256": _canonical_hash(original_boxscore),
            },
            "reproduction_command": _reproduction_command(seed, run_header),
            "replay_output_sha256": _file_hash(trace_path),
            "replay_boxscore_sha256": _canonical_hash(replay_boxscore) if replay_boxscore else None,
            "validation": replay_outcomes[seed],
            "trace": {
                "drive_count": len(record.get("drives", [])),
                "play_count": candidate["replay_trace_play_count"],
                "complete_regulation": record.get("complete_regulation"),
                "valid_full_game": record.get("valid_full_game"),
                "unsupported_rules": record.get("unsupported_rules", []),
            },
        }
        manifest_dir = out_dir / "replay-manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"seed-{seed}.json").write_text(
            json.dumps(replay_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(ranked_all, out_dir, top_n=top_n, marketing_n=marketing_n)
    results = list(replay_outcomes.values())
    validation_summary = {
        "schema": "lp.nfl.slc-seed-replay-validation.v1",
        "attempted": len(selected),
        "replayed": len(traces),
        "passed": sum(item["status"] == "passed" for item in results),
        "rejected": sum(item["status"] == "rejected" for item in results),
        "missing": sum(item["status"] == "missing_replay" for item in results),
        "results": sorted(results, key=lambda item: item["seed"]),
    }
    (out_dir / "replay-validation.json").write_text(
        json.dumps(validation_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    marketing_document = json.loads((out_dir / "marketing-seeds.json").read_text(encoding="utf-8"))
    marketing_document["run_id"] = run_header.get("run_id")
    marketing_document["source_commit"] = run_header.get("source_commit")
    marketing_document["source_input_hashes"] = provenance.get("run_configuration", {})
    (out_dir / "marketing-seeds.json").write_text(
        json.dumps(marketing_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    marketing = marketing_document.get("seeds", [])
    report_path = out_dir / "research-report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else "# MIN–DET Realism Based Seed Ranking\n"
    report += "\n## Stage B replay and GridIron adapter validation\n\n"
    report += (f"- Pinned-source replays attempted: {validation_summary['attempted']}\n"
               f"- Exact boxscore and score matches with a supported full sequence and passing E2 adapter: {validation_summary['passed']}\n"
               f"- Rejected: {validation_summary['rejected']}\n"
               f"- Missing replay outputs: {validation_summary['missing']}\n\n")
    report += "Marketing shortlist (interest is separate from realism):\n\n"
    report += "| Scenario | Seed | Realism | Visual interest | Replay |\n|---|---:|---:|---:|---|\n"
    for row in marketing:
        report += (f"| {row.get('selection')} | {row.get('seed')} | {row.get('realism_score', 0):.2f} | "
                   f"{row.get('visual_interest_score')} | {row.get('replay_status')} |\n")
    report += ("\nE2 compatibility means the pinned statistical event record passes the GridIron viewer adapter. "
               "It does not provide measured player trajectories or establish shared-v1 physical replay conformance.\n")
    report_path.write_text(report, encoding="utf-8")
    return validation_summary


def _reproduction_command(seed: int, header: dict) -> str:
    blockers = header.get("blocker_fixes", [])
    parts = [
        "python3 /tmp/min-det-stageb/replay_slc_seed_batch.py",
        "--source-root /root/legendarypicks-slc-research-24d8b301",
        "--run-header /tmp/min-det-stageb/run-header.json",
        f"--seed-list /tmp/slc-replay-traces/reproduction-selections/seed-{seed}.json",
        f"--out-dir /tmp/slc-replay-traces/reproduction-{seed}",
    ]
    return " ".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-seeds", type=Path, required=True)
    parser.add_argument("--seed-features", type=Path, required=True)
    parser.add_argument("--rankings-csv", type=Path)
    parser.add_argument("--boxscore-dir", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--contract-audit", type=Path, required=True)
    parser.add_argument("--input-provenance", type=Path, required=True)
    parser.add_argument("--run-header", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--marketing-n", type=int, default=15)
    args = parser.parse_args(argv)
    rankings_path = args.rankings_csv or args.seed_features.parent.parent / "seed-realism-rankings.csv"
    summary = validate_replays(
        top_path=args.top_seeds, seed_features_path=args.seed_features,
        rankings_path=rankings_path,
        sidecar_dir=args.boxscore_dir, trace_dir=args.trace_dir,
        contract_audit_path=args.contract_audit,
        input_provenance_path=args.input_provenance,
        run_header_path=args.run_header, out_dir=args.out_dir,
        top_n=args.top_n, marketing_n=args.marketing_n,
    )
    print(json.dumps({key: summary[key] for key in ("attempted", "replayed", "passed", "rejected", "missing")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
