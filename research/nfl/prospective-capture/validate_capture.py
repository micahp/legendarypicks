#!/usr/bin/env python3
"""Validate captured NFL prop observations and demonstrate fail-closed behavior."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from capture_validation import validate_row


def rows_from(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_no}: {exc}") from exc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("artifact", type=Path)
    ap.add_argument("--demonstrate-broken-row", action="store_true")
    args = ap.parse_args(argv)

    count = 0
    seen = set()
    first = None
    failures = []
    for line_no, row in rows_from(args.artifact):
        count += 1
        first = first or row
        errors = validate_row(row)
        if row.get("observation_id") in seen:
            errors.append("duplicate observation_id")
        seen.add(row.get("observation_id"))
        if errors:
            failures.append((line_no, errors))
            if len(failures) >= 20:
                break
    if failures:
        for line_no, errors in failures:
            print(f"invalid row {line_no}: " + "; ".join(errors))
        print(f"validation failed: {len(failures)} invalid row(s), scanned {count}")
        return 1
    print(f"validation passed: {count} observations; unique observation_id; all required fields present")

    if args.demonstrate_broken_row:
        if first is None:
            print("cannot demonstrate rejection on an empty artifact", file=sys.stderr)
            return 2
        broken = dict(first)
        for key in ("pmf", "information_cutoff", "pre_kickoff_assertion", "outcome_state"):
            broken.pop(key, None)
        errors = validate_row(broken)
        required_failures = {"missing pmf", "missing information_cutoff", "missing pre_kickoff_assertion", "missing outcome_state"}
        if not required_failures.issubset(set(errors)):
            print("validator self-check failed: broken row was not rejected for every removed field", file=sys.stderr)
            return 3
        print("deliberately broken row rejected: missing PMF, information cutoff, pre-kickoff proof, and outcome state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
