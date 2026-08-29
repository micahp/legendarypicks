#!/usr/bin/env python3
"""Backfill the current UFC prop population's last five fights from UFCStats."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import quote

from ingest_ufc_fight_stats.names import _parse_date
from ingest_ufc_fight_stats.ufcstats_pipeline import (
    apply_ufcstats_plan,
    build_ufcstats_plan,
    load_ufcstats_state,
)
from ingest_ufc_fight_stats.ufcstats_source import UfcStatsClient


DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
DEFAULT_ARCHIVE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "ufcstats-archive"
)


def _non_negative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 5:
        raise argparse.ArgumentTypeError("must be between 1 and 5")
    return parsed


def _absolute_file(path: str, label: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.stat().st_size <= 0:
        raise ValueError("{} must be an absolute existing non-empty file: {}".format(label, path))
    return str(candidate)


def _quick_check(path: str) -> str:
    con = sqlite3.connect("file:{}?mode=ro".format(quote(path, safe="/")), uri=True)
    try:
        return str(con.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        con.close()


def _print_plan(plan, dry_run: bool) -> None:
    print("\nUFCStats summary")
    print("  publisher completed events: {}".format(plan.published_event_count))
    print("  scoped published card fights: {}".format(plan.scoped_card_fight_count))
    print("  fighters targeted: {}".format(plan.target_count))
    print("  fighters resolved by native id + card pair: {}".format(plan.resolved_count))
    print("  fighter profiles fetched: {}".format(plan.profile_count))
    print("  published fight rows (last-five bounded): {}".format(plan.candidate_count))
    print("  existing rows unchanged: {}".format(plan.existing_count))
    print("  {} inserts: {}".format("would" if dry_run else "planned", len(plan.inserts)))
    print("  {} updates: {}".format("would" if dry_run else "planned", len(plan.updates)))
    print("  fighters with no completed history: {}".format(len(plan.no_history)))
    print("  unresolved fighters: {}".format(len(plan.unresolved)))
    print("  source errors: {}".format(len(plan.source_errors)))
    print("  conflicts: {}".format(len(plan.conflicts)))
    for label, values in (
        ("NO HISTORY", plan.no_history),
        ("UNRESOLVED", plan.unresolved),
        ("SOURCE ERROR", plan.source_errors),
        ("CONFLICT", plan.conflicts),
    ):
        for value in values:
            print("  {} {}".format(label, value))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    parser.add_argument("--archive-dir", default=DEFAULT_ARCHIVE)
    parser.add_argument("--from-archive", action="store_true")
    parser.add_argument("--as-of")
    parser.add_argument("--lookback-days", type=_non_negative, default=0)
    parser.add_argument("--lookahead-days", type=_non_negative, default=0)
    parser.add_argument("--limit", type=_limit, default=5)
    parser.add_argument("--min-interval", type=float, default=0.75)
    parser.add_argument("--expect-targets", type=_non_negative)
    parser.add_argument("--expect-inserts", type=_non_negative)
    parser.add_argument("--expect-updates", type=_non_negative)
    parser.add_argument("--expect-unresolved", type=_non_negative)
    parser.add_argument("--expect-no-history", type=_non_negative)
    args = parser.parse_args(argv)
    try:
        db_path = _absolute_file(args.db, "database")
        if _quick_check(db_path) != "ok":
            raise ValueError("database quick_check failed")
        as_of = _parse_date(args.as_of) if args.as_of else dt.date.today()
        if as_of is None:
            raise ValueError("--as-of must be YYYY-MM-DD")
        if args.apply:
            if not args.backup:
                raise ValueError("--apply requires --backup")
            backup = _absolute_file(args.backup, "backup")
            if os.path.samefile(db_path, backup):
                raise ValueError("backup must differ from database")
            if _quick_check(backup) != "ok":
                raise ValueError("backup quick_check failed")

        targets, accepted, stored, owners, existing = load_ufcstats_state(
            db_path,
            as_of,
            lookback_days=args.lookback_days,
            lookahead_days=args.lookahead_days,
        )
        print("database: {}".format(db_path))
        print("archive: {} ({})".format(
            os.path.abspath(args.archive_dir),
            "required" if args.from_archive else "write-through",
        ))
        client = UfcStatsClient(
            args.archive_dir,
            from_archive=args.from_archive,
            min_interval=args.min_interval,
        )
        plan = build_ufcstats_plan(
            targets, accepted, stored, owners, existing, client,
            limit=args.limit,
        )
        _print_plan(plan, dry_run=args.dry_run)
        if plan.source_errors or plan.conflicts or plan.unresolved:
            print("\nABORTED: incomplete source/identity plan; no database writes attempted")
            return 2
        if args.dry_run:
            print("\nDone (dry-run, database opened read-only)")
            return 0

        expected = {
            "--expect-targets": args.expect_targets,
            "--expect-inserts": args.expect_inserts,
            "--expect-updates": args.expect_updates,
            "--expect-unresolved": args.expect_unresolved,
            "--expect-no-history": args.expect_no_history,
        }
        missing = [name for name, value in expected.items() if value is None]
        if missing:
            raise ValueError("--apply requires {}".format(", ".join(missing)))
        actual = {
            "--expect-targets": plan.target_count,
            "--expect-inserts": len(plan.inserts),
            "--expect-updates": len(plan.updates),
            "--expect-unresolved": len(plan.unresolved),
            "--expect-no-history": len(plan.no_history),
        }
        mismatches = [
            "{} expected {}, got {}".format(name, expected[name], actual[name])
            for name in expected if expected[name] != actual[name]
        ]
        if mismatches:
            print("\nABORTED: source plan changed; no database writes attempted")
            for mismatch in mismatches:
                print("  - {}".format(mismatch))
            return 2
        result = apply_ufcstats_plan(db_path, plan)
        print(
            "\nApplied: {mappings_inserted} source mappings inserted, "
            "{mappings_refreshed} refreshed, {inserted_logs} logs inserted, "
            "{updated_logs} updated".format(**result)
        )
        return 0
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
