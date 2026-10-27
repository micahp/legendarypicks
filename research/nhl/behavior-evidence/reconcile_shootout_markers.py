#!/usr/bin/env python3
"""Reconcile 2021 eligible NHL shootout games with PBP completion markers.

Reads only the verified local PBP and box-score archives. Every processed PBP
body is checked against the pinned manifest's compressed size and SHA-256.
The generated JSON and Markdown contain aggregate results plus marker-only
event metadata for any per-game count anomaly; they do not copy raw PBP.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
BOXSCORE_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
OUT_JSON = AUDIT_DIR / "results/shootout-marker-reconciliation-2026-10-27.json"
OUT_REPORT = ROOT / "docs/research/NHL-SHOOTOUT-MARKER-RECONCILIATION-2026-10-27.md"
SO_ATTEMPT_TYPES = {"goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"}


def _load_audit_module():
    path = AUDIT_DIR / "audit_behavior.py"
    spec = importlib.util.spec_from_file_location("nhl_shootout_reconciliation_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verified archive helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _event_row(event: dict[str, Any]) -> dict[str, Any]:
    descriptor = event.get("periodDescriptor") or {}
    return {
        "event_id": event.get("eventId"),
        "sort_order": event.get("sortOrder"),
        "event_type": event.get("typeDescKey"),
        "period_type": descriptor.get("periodType"),
        "period_number": descriptor.get("number"),
        "time_in_period": event.get("timeInPeriod"),
        "details_present": isinstance(event.get("details"), dict),
    }


def analyze(data_root: Path, boxscore_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    audit = _load_audit_module()
    _, corpus = audit._load_v01(data_root, boxscore_root)
    eligible = {
        game_id: summary
        for game_id, summary in corpus.games.items()
        if summary.start_season == 2021 and summary.eligible
    }
    if len(eligible) != 1292:
        raise ValueError(f"2021 eligible-game population changed: {len(eligible)} != 1292")

    manifest_path = data_root / "manifests/hardened-v1/pbp_verified_manifest.csv"
    manifest = audit._read_manifest(manifest_path, audit.PBP_MANIFEST_SHA256)
    rows = {
        str(row["game_id"]): row
        for row in manifest
        if row.get("kind") == "pbp" and row.get("http_status") == "200"
    }
    if len(rows) != 4876:
        raise ValueError(f"PBP manifest population changed: {len(rows)} != 4876")

    marker_counts: dict[str, int] = {}
    marker_details: dict[str, list[dict[str, Any]]] = {}
    marker_context: dict[str, dict[str, Any]] = {}
    attempts_by_game: dict[str, int] = {}
    goals_by_game: dict[str, int] = {}
    period_so_ids: set[str] = set()
    attempt_count = 0
    goal_count = 0
    for game_id in sorted(eligible):
        row = rows.get(game_id)
        if row is None:
            raise ValueError(f"eligible game {game_id} is absent from the verified PBP manifest")
        body = audit._read_verified_body(data_root / "raw/pbp" / f"{game_id}.json.gz", row)
        if str(body.get("id")) != game_id:
            raise ValueError(f"{game_id}: PBP body ID mismatch")
        ordered = sorted(
            enumerate(body.get("plays") or []),
            key=lambda pair: (int(pair[1].get("sortOrder", pair[0])), pair[0]),
        )
        markers = []
        so_events = []
        game_attempts = 0
        game_goals = 0
        for _, event in ordered:
            descriptor = event.get("periodDescriptor") or {}
            event_type = str(event.get("typeDescKey") or "")
            if descriptor.get("periodType") == "SO":
                period_so_ids.add(game_id)
                so_events.append(event)
                if event_type in SO_ATTEMPT_TYPES:
                    attempt_count += 1
                    game_attempts += 1
                    is_goal = int(event_type == "goal")
                    goal_count += is_goal
                    game_goals += is_goal
            if event_type == "shootout-complete":
                markers.append(_event_row(event))
        if markers:
            marker_counts[game_id] = len(markers)
            marker_details[game_id] = markers
            attempts_by_game[game_id] = game_attempts
            goals_by_game[game_id] = game_goals
            marker_positions = [i for i, event in enumerate(so_events)
                                if event.get("typeDescKey") == "shootout-complete"]
            first_marker = marker_positions[0]
            last_marker = marker_positions[-1]
            marker_context[game_id] = {
                "previous_event_before_first_marker": (
                    _event_row(so_events[first_marker - 1]) if first_marker > 0 else None),
                "next_event_after_last_marker": (
                    _event_row(so_events[last_marker + 1])
                    if last_marker + 1 < len(so_events) else None),
            }

    summary_so_ids = {
        game_id for game_id, summary in eligible.items()
        if summary.source_last_period_type == "SO"
    }
    marker_game_ids = set(marker_counts)
    duplicate_ids = sorted(game_id for game_id, count in marker_counts.items() if count > 1)
    missing_marker_ids = sorted(summary_so_ids - marker_game_ids)
    marker_without_so_ids = sorted(marker_game_ids - summary_so_ids)
    period_summary_mismatch = sorted(period_so_ids.symmetric_difference(summary_so_ids))

    anomalies = []
    for game_id in sorted(set(duplicate_ids) | set(missing_marker_ids)
                          | set(marker_without_so_ids) | set(period_summary_mismatch)):
        row = rows[game_id]
        anomalies.append({
            "game_id": game_id,
            "source_last_period_type": eligible[game_id].source_last_period_type,
            "pbp_has_shootout_period": game_id in period_so_ids,
            "marker_count": marker_counts.get(game_id, 0),
            "marker_events": marker_details.get(game_id, []),
            "shootout_attempt_events": attempts_by_game.get(game_id, 0),
            "shootout_goal_events": goals_by_game.get(game_id, 0),
            "marker_sequence_context": marker_context.get(game_id, {}),
            "pbp_compressed_bytes": int(row["bytes_gz"]),
            "pbp_compressed_sha256": row["sha256_gz"],
        })

    result = {
        "report_kind": "nhl_2021_shootout_completion_marker_reconciliation",
        "date": "2026-10-27",
        "source": {
            "pbp_manifest_sha256": audit.PBP_MANIFEST_SHA256,
            "boxscore_manifest_sha256": corpus.boxscore_manifest_sha256,
            "verified_eligible_pbp_bodies": len(eligible),
            "archive_pbp_games": 4876,
            "access": "local verified archive only; no network or database access",
        },
        "population": {
            "eligible_2021_games": len(eligible),
            "games_reaching_shootout_by_independent_game_summary": len(summary_so_ids),
            "games_with_a_pbp_shootout_period": len(period_so_ids),
            "games_with_at_least_one_shootout_complete_marker": len(marker_game_ids),
            "shootout_complete_marker_event_rows": sum(marker_counts.values()),
            "shootout_attempt_events": attempt_count,
            "shootout_goal_events": goal_count,
        },
        "reconciliation": {
            "summary_and_pbp_shootout_game_sets_match": summary_so_ids == period_so_ids,
            "summary_and_marker_game_sets_match": summary_so_ids == marker_game_ids,
            "games_missing_completion_marker": missing_marker_ids,
            "marker_games_not_ending_in_shootout": marker_without_so_ids,
            "period_vs_game_summary_mismatch_ids": period_summary_mismatch,
            "duplicate_marker_game_ids": duplicate_ids,
            "anomaly_records": anomalies,
            "denominator_guidance": "Use distinct eligible game IDs (95) for shootout game frequency. The marker event-row count is 96 because one game has two marker records.",
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if (summary_so_ids != period_so_ids or summary_so_ids != marker_game_ids
            or duplicate_ids != ["2021020336"] or attempt_count != 702 or goal_count != 210):
        raise ValueError("shootout marker reconciliation did not match expected verified archive evidence")
    return result


def render_report(result: dict[str, Any]) -> str:
    pop = result["population"]
    rec = result["reconciliation"]
    anomaly = rec["anomaly_records"][0]
    markers = anomaly["marker_events"]
    return "\n".join([
        "# NHL shootout completion-marker reconciliation",
        "",
        "Date: 2026-10-27  ",
        "Scope: explain the 2021 difference between shootout games and `shootout-complete` event rows using the verified PBP and box-score archive. Diagnostic only; no simulator, rule gate, or historical result is changed.",
        "",
        "## Result",
        "",
        f"The eligible 2021 population has {pop['eligible_2021_games']:,} games. {pop['games_reaching_shootout_by_independent_game_summary']} distinct games end in a shootout according to the independently reconciled game summary; the same {pop['games_with_a_pbp_shootout_period']} games have a PBP shootout period and {pop['games_with_at_least_one_shootout_complete_marker']} games have at least one completion marker. The archive contains {pop['shootout_complete_marker_event_rows']} marker event rows because game `{anomaly['game_id']}` has two consecutive `shootout-complete` records.",
        "",
        f"The two records are event IDs {markers[0]['event_id']} and {markers[1]['event_id']}, sort orders {markers[0]['sort_order']} and {markers[1]['sort_order']}, both in SO period {markers[0]['period_number']} at {markers[0]['time_in_period']}. Both have no event details. The preceding event is `{anomaly['marker_sequence_context']['previous_event_before_first_marker']['event_type']}` (ID {anomaly['marker_sequence_context']['previous_event_before_first_marker']['event_id']}); the following event is `{anomaly['marker_sequence_context']['next_event_after_last_marker']['event_type']}` (ID {anomaly['marker_sequence_context']['next_event_after_last_marker']['event_id']}). The flagged game has {anomaly['shootout_attempt_events']} attempt events and {anomaly['shootout_goal_events']} goals in its SO period. This establishes a duplicate marker record in the archived event stream, not a second shootout game or additional play.",
        "",
        f"Across all 95 shootout games, the archive contains {pop['shootout_attempt_events']} attempt events and {pop['shootout_goal_events']} goals. Use **95 distinct games** as the shootout-game denominator; retain **96** only when reporting completion-marker event rows.",
        "",
        "## Reconciliation checks",
        "",
        f"- Eligible 2021 PBP bodies checked against pinned compressed size and SHA-256: {result['source']['verified_eligible_pbp_bodies']:,}.",
        f"- Independent game-summary SO set equals the PBP SO-period set: **{rec['summary_and_pbp_shootout_game_sets_match']}**.",
        f"- Independent game-summary SO set equals the distinct marker-game set: **{rec['summary_and_marker_game_sets_match']}**.",
        f"- Games missing a marker: {rec['games_missing_completion_marker']}.",
        f"- Marker games not ending in SO: {rec['marker_games_not_ending_in_shootout']}.",
        f"- Duplicate-marker game IDs: {rec['duplicate_marker_game_ids']}.",
        "",
        "The marker's duplication does not invalidate the 95-game denominator. The event count of 96 is a valid count of records as stored, but must not be reported as 96 shootout games.",
        "",
        "## Provenance",
        "",
        f"PBP manifest SHA-256: `{result['source']['pbp_manifest_sha256']}`  ",
        f"Box-score manifest SHA-256: `{result['source']['boxscore_manifest_sha256']}`  ",
        f"Game `{anomaly['game_id']}` compressed PBP SHA-256: `{anomaly['pbp_compressed_sha256']}`  ",
        f"Audit script SHA-256: `{result['analysis_script_sha256']}`",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--boxscore-root", type=Path, default=BOXSCORE_ROOT)
    parser.add_argument("--output", type=Path, default=OUT_JSON)
    parser.add_argument("--report", type=Path, default=OUT_REPORT)
    args = parser.parse_args()
    result = analyze(args.data_root, args.boxscore_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"json": str(args.output), "report": str(args.report),
                      "eligible_games": result["population"]["eligible_2021_games"],
                      "shootout_games": result["population"]["games_reaching_shootout_by_independent_game_summary"],
                      "marker_rows": result["population"]["shootout_complete_marker_event_rows"],
                      "duplicate_marker_games": result["reconciliation"]["duplicate_marker_game_ids"],
                      "elapsed_seconds": result["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
