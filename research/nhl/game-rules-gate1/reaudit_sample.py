#!/usr/bin/env python3
"""Re-audit frozen generated games without re-running or changing the simulator."""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path("/root/lp-data/nhl-game-rules-gate1-2026-10-26")
DEFAULT_OUTPUT = Path("/root/lp-data/nhl-game-rules-gate1-reaudit-2026-10-26")


def _load_validator():
    source = HERE / "validator.py"
    spec = importlib.util.spec_from_file_location("nhl_gate1_validator_reaudit", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load independent validator at {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE,
                        help="immutable original Monte Carlo sample directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="new directory for audit-only results")
    args = parser.parse_args()
    source_games = args.source_dir / "games.jsonl"
    source_summary_path = args.source_dir / "summary.json"
    if not source_games.is_file() or not source_summary_path.is_file():
        raise FileNotFoundError("source games.jsonl and summary.json are required")
    source_games_sha = _sha(source_games)
    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    if source_games_sha != source_summary.get("games_jsonl_sha256"):
        raise ValueError("frozen simulation sample hash does not match its original summary")
    if source_summary.get("generation_errors") != 0:
        raise ValueError("source sample has generation errors; inspect before re-auditing")
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    validator = _load_validator()
    check_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    finding_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    audited_rows: list[dict[str, Any]] = []
    seed_rows: list[dict[str, Any]] = []
    input_lines = 0
    started = time.monotonic()
    with source_games.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            input_lines += 1
            source = json.loads(line)
            game = source.get("simulation_record")
            if not isinstance(game, dict):
                raise ValueError(f"source row {input_lines} has no complete simulation_record")
            audit = validator.audit_game(game, ruleset=source_summary["ruleset"])
            original_hash = source.get("independent_audit", {}).get("input_sha256")
            if original_hash != audit["input_sha256"]:
                raise ValueError(f"simulation record changed at source row {input_lines}")
            row = {
                "target_index": source["target_index"],
                "game_id": source["game_id"],
                "game_date": source["game_date"],
                "draw_index": source["draw_index"],
                "seed": source["seed"],
                "pregame_snapshot_sha256": source["pregame_snapshot_sha256"],
                "simulation_record_sha256": audit["input_sha256"],
                "native_validation": source["native_validation"],
                "native_errors": source.get("native_errors", []),
                "independent_audit": audit,
            }
            audited_rows.append(row)
            seed_rows.append({
                key: row[key] for key in (
                    "target_index", "game_id", "game_date", "draw_index", "seed",
                    "pregame_snapshot_sha256", "simulation_record_sha256", "native_validation")
            } | {
                "structural_valid": audit["structural_valid"],
                "full_rule_assessed": audit["full_rule_assessed"],
                "failed_check_codes": [c["code"] for c in audit["checks"] if c["status"] == "FAIL"],
                "quarantined_check_codes": [c["code"] for c in audit["checks"]
                                             if c["status"] == "QUARANTINED"],
                "not_assessed_check_codes": [c["code"] for c in audit["checks"]
                                             if c["status"] == "NOT_ASSESSED"],
            })
            for check in audit["checks"]:
                check_counts[check["code"]][check["status"]] += 1
                for finding in check["findings"]:
                    finding_counts[check["code"]][finding["status"]] += 1

    if input_lines != source_summary["generated_games"]:
        raise ValueError(f"source game row count {input_lines} disagrees with summary")
    audit_path = args.output_dir / "reaudited-games.jsonl"
    seed_path = args.output_dir / "sample-index.json"
    _write_jsonl(audit_path, audited_rows)
    with seed_path.open("x", encoding="utf-8") as handle:
        json.dump(seed_rows, handle, indent=2, sort_keys=True)
        handle.write("\n")

    elapsed = time.monotonic() - started
    summary = {
        "report_kind": "validator-only re-audit; frozen simulation records are unchanged",
        "validator": validator.VALIDATOR_VERSION,
        "ruleset": source_summary["ruleset"],
        "database_used": False,
        "simulator_rerun": False,
        "source_output_dir": str(args.source_dir),
        "source_games_jsonl_sha256": source_games_sha,
        "source_generation_summary_sha256": _sha(source_summary_path),
        "source_generated_games": input_lines,
        "source_generation_errors": source_summary["generation_errors"],
        "audited_games": len(audited_rows),
        "native_validation_counts": dict(collections.Counter(r["native_validation"] for r in audited_rows)),
        "structural_valid_games": sum(r["independent_audit"]["structural_valid"] for r in audited_rows),
        "full_rule_assessed_games": sum(r["independent_audit"]["full_rule_assessed"] for r in audited_rows),
        "failed_seed_count": sum(
            r["native_validation"] == "FAIL" or not r["independent_audit"]["structural_valid"]
            for r in audited_rows),
        "check_status_counts": {code: dict(sorted(counts.items()))
                                for code, counts in sorted(check_counts.items())},
        "finding_status_counts": {code: dict(sorted(counts.items()))
                                  for code, counts in sorted(finding_counts.items())},
        "validator_sha256": _sha(HERE / "validator.py"),
        "reaudit_wall_seconds": round(elapsed, 3),
        "reaudited_games_jsonl_sha256": _sha(audit_path),
        "sample_index_sha256": _sha(seed_path),
    }
    summary_path = args.output_dir / "summary.json"
    with summary_path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    printed = dict(summary)
    printed["summary_file_sha256"] = _sha(summary_path)
    print(json.dumps(printed, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
