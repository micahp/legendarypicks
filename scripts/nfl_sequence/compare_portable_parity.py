#!/usr/bin/env python3
"""Compare legacy and packaged records exactly for every requested seed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


PARITY_FIELDS = (
    "ledger", "drives", "kickoffs", "boundaries", "points", "stats", "status", "blocker",
    "complete_game", "valid_full_game", "regulation_end_reached", "tied", "overtime",
    "game_id", "snapshot_hash", "rules_version", "model_version", "unsupported_rules",
)


def _read(path):
    rows = {}
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        seed = row.get("seed")
        if type(seed) is not int or seed < 0 or seed in rows:
            raise ValueError(f"invalid or duplicate seed at {path}:{line_number}")
        rows[seed] = row
    return rows


def compare(legacy_path, portable_path, *, expected_seeds=None, seed_start=None, allow_invalid_research=False):
    legacy, portable = _read(legacy_path), _read(portable_path)
    mismatches = []
    acceptance = []
    if not legacy or not portable:
        acceptance.append({"kind": "empty_cohort"})
    if (expected_seeds is None) != (seed_start is None):
        raise ValueError("expected_seeds and seed_start must be supplied together")
    if expected_seeds is not None:
        if expected_seeds < 1 or seed_start < 0:
            raise ValueError("positive expected_seeds and nonnegative seed_start required")
        planned = set(range(seed_start, seed_start + expected_seeds))
        if legacy.keys() != planned or portable.keys() != planned:
            acceptance.append({"kind": "requested_seed_census_mismatch"})
    if legacy.keys() != portable.keys():
        mismatches.append({"kind": "seed_set", "legacy_only": sorted(legacy.keys() - portable.keys()),
                           "portable_only": sorted(portable.keys() - legacy.keys())})
    for seed in sorted(legacy.keys() & portable.keys()):
        left_row, right_row = legacy[seed], portable[seed]
        left, right = left_row.get("record"), right_row.get("record")
        for label, row, record in (("legacy", left_row, left), ("portable", right_row, right)):
            if (not isinstance(record, dict) or row.get("error") is not None
                    or record.get("valid_full_game") is not True or record.get("complete_game") is not True
                    or record.get("blocker") is not None or record.get("unsupported_rules")
                    or not isinstance(record.get("points"), dict)
                    or any(type(record["points"].get(side)) is not int or record["points"][side] < 0
                           for side in ("A", "B"))
                    or not isinstance(record.get("stats"), dict)
                    or not isinstance(record.get("ledger"), list)):
                if not allow_invalid_research:
                    acceptance.append({"kind": "invalid_game", "side": label, "seed": seed})
        if left is not None and not isinstance(left, dict) or right is not None and not isinstance(right, dict):
            mismatches.append({"kind": "malformed_record", "seed": seed})
            continue
        if left is None or right is None:
            if left is not right or left_row.get("error") != right_row.get("error"):
                mismatches.append({"kind": "record_presence_or_error", "seed": seed,
                                   "legacy_error": left_row.get("error"),
                                   "portable_error": right_row.get("error")})
            continue
        for field in PARITY_FIELDS:
            if left.get(field) != right.get(field):
                mismatches.append({"kind": "field", "seed": seed, "field": field,
                                   "legacy_sha256": _digest(left.get(field)),
                                   "portable_sha256": _digest(right.get(field))})
    return {"schema": "lp-slc-exact-parity-1", "status": "pass" if not mismatches and not acceptance else "fail",
            "comparison_class": "diagnostic_only" if allow_invalid_research else "valid_game_parity",
            "requested_cohort_verified": (expected_seeds is not None and not acceptance and not mismatches
                                          and not allow_invalid_research),
            "expected_seeds": expected_seeds, "seed_start": seed_start,
            "seeds_compared": len(legacy.keys() & portable.keys()), "mismatch_count": len(mismatches),
            "mismatches": mismatches, "acceptance_failures": acceptance}


def _digest(value):
    return __import__("hashlib").sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-seeds", type=int)
    parser.add_argument("--seed-start", type=int)
    parser.add_argument("--allow-invalid-research", action="store_true",
                        help="compare failed records for diagnostics, never acceptance")
    args = parser.parse_args(argv)
    report = compare(args.legacy, args.portable, expected_seeds=args.expected_seeds,
                     seed_start=args.seed_start, allow_invalid_research=args.allow_invalid_research)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{report['status']}: {report['seeds_compared']} seeds, {report['mismatch_count']} mismatches")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
