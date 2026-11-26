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
        if not isinstance(seed, int) or seed in rows:
            raise ValueError(f"invalid or duplicate seed at {path}:{line_number}")
        rows[seed] = row
    return rows


def compare(legacy_path, portable_path):
    legacy, portable = _read(legacy_path), _read(portable_path)
    mismatches = []
    if legacy.keys() != portable.keys():
        mismatches.append({"kind": "seed_set", "legacy_only": sorted(legacy.keys() - portable.keys()),
                           "portable_only": sorted(portable.keys() - legacy.keys())})
    for seed in sorted(legacy.keys() & portable.keys()):
        left_row, right_row = legacy[seed], portable[seed]
        left, right = left_row.get("record"), right_row.get("record")
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
    return {"schema": "lp-slc-exact-parity-1", "status": "pass" if not mismatches else "fail",
            "seeds_compared": len(legacy.keys() & portable.keys()), "mismatch_count": len(mismatches),
            "mismatches": mismatches}


def _digest(value):
    return __import__("hashlib").sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(args.legacy, args.portable)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{report['status']}: {report['seeds_compared']} seeds, {report['mismatch_count']} mismatches")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
