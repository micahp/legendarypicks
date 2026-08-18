"""Command-line entry point for the UFC fight-stat ingest."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from contextlib import closing
from typing import Optional, Sequence

from .apply import apply_plan
from .names import _parse_date
from .plan import IngestPlan, build_current_card_plan, build_plan
from .schema import DB, _read_only_connection
from .targets import load_targets

def _positive_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number

def _fight_limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 5:
        raise argparse.ArgumentTypeError("must be between 1 and 5")
    return number

def _print_summary(plan: IngestPlan, dry_run: bool) -> None:
    print("\nSummary")
    print("  fighters targeted: {}".format(plan.target_count))
    print("  ESPN identities to persist: {}".format(len(plan.identity_updates)))
    print("  UFC prop games to link: {}".format(len(plan.game_links)))
    print("  fight rows with stats: {}".format(plan.candidate_count))
    print("  existing rows preserved: {}".format(plan.existing_count))
    label = "would insert" if dry_run else "planned inserts"
    print("  {}: {}".format(label, len(plan.logs)))
    print("  missing-stat fight references: {}".format(len(plan.missing_stats)))
    print("  unresolved fighters: {}".format(len(plan.unresolved)))
    print("  source errors: {}".format(len(plan.source_errors)))
    print("  conflicts: {}".format(len(plan.conflicts)))
    if plan.unresolved:
        print("  unresolved detail:")
        for item in plan.unresolved:
            print("    - {}".format(item))
    if plan.source_errors:
        print("  source error detail:")
        for item in plan.source_errors:
            print("    - {}".format(item))
    if plan.conflicts:
        print("  conflict detail:")
        for item in plan.conflicts:
            print("    - {}".format(item))

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest UFC per-fight stats into player_game_logs"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="fetch and plan; never write")
    mode.add_argument("--apply", action="store_true", help="apply a fully fetched additive plan")
    parser.add_argument("--limit", type=_fight_limit, default=5)
    parser.add_argument("--lookback-days", type=_positive_int, default=7)
    parser.add_argument("--lookahead-days", type=_positive_int, default=21)
    parser.add_argument(
        "--all-fighters",
        action="store_true",
        help="include every durable UFC fighter, not just the current card window",
    )
    parser.add_argument(
        "--current-card-only",
        action="store_true",
        help="ingest only completed scoped-card fights; do not call athlete history",
    )
    parser.add_argument(
        "--as-of",
        help="YYYY-MM-DD target date for reproducible planning (default: today)",
    )
    parser.add_argument(
        "--backup",
        help="required integrity-checked pre-write backup path with --apply",
    )
    parser.add_argument("--expect-inserts", type=_positive_int)
    parser.add_argument("--expect-identity-updates", type=_positive_int)
    parser.add_argument("--expect-game-links", type=_positive_int)
    parser.add_argument("--expect-unresolved", type=_positive_int)
    parser.add_argument("--expect-missing-stats", type=_positive_int)
    args = parser.parse_args(argv)
    if not os.path.isfile(DB) or os.path.getsize(DB) <= 0:
        parser.error("database is missing or empty: {}".format(DB))
    as_of = _parse_date(args.as_of) if args.as_of else dt.date.today()
    if as_of is None:
        parser.error("--as-of must be YYYY-MM-DD")
    if args.apply:
        required = {
            "--backup": args.backup,
            "--expect-inserts": args.expect_inserts,
            "--expect-identity-updates": args.expect_identity_updates,
            "--expect-game-links": args.expect_game_links,
            "--expect-unresolved": args.expect_unresolved,
            "--expect-missing-stats": args.expect_missing_stats,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            parser.error("--apply requires {}".format(", ".join(missing)))
        backup_path = os.path.abspath(args.backup)
        if backup_path == os.path.abspath(DB):
            parser.error("--backup must differ from the production database")
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) <= 0:
            parser.error("backup is missing or empty: {}".format(backup_path))
        with closing(_read_only_connection(backup_path)) as backup_con:
            backup_integrity = backup_con.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
        if backup_integrity != "ok":
            parser.error(
                "backup integrity_check returned {}".format(backup_integrity)
            )
    targets, existing_keys, owner_by_espn = load_targets(
        DB,
        as_of,
        lookback_days=args.lookback_days,
        lookahead_days=args.lookahead_days,
        all_fighters=args.all_fighters,
    )
    print(
        "Found {} UFC fighters in the {} work set".format(
            len(targets), "all-fighter" if args.all_fighters else "card-window"
        )
    )
    if not targets:
        print("ERROR: no UFC fighters are linked to the selected card window")
        return 2
    if args.current_card_only:
        plan = build_current_card_plan(
            targets, existing_keys, owner_by_espn
        )
    else:
        plan = build_plan(targets, existing_keys, owner_by_espn, args.limit)
    _print_summary(plan, dry_run=args.dry_run)
    if plan.source_errors or plan.conflicts:
        print("\nABORTED: no database writes were attempted")
        return 2
    if args.dry_run:
        print("\nDone (dry-run, database opened read-only)")
        return 0
    actual = {
        "--expect-inserts": len(plan.logs),
        "--expect-identity-updates": len(plan.identity_updates),
        "--expect-game-links": len(plan.game_links),
        "--expect-unresolved": len(plan.unresolved),
        "--expect-missing-stats": len(plan.missing_stats),
    }
    expected = {
        "--expect-inserts": args.expect_inserts,
        "--expect-identity-updates": args.expect_identity_updates,
        "--expect-game-links": args.expect_game_links,
        "--expect-unresolved": args.expect_unresolved,
        "--expect-missing-stats": args.expect_missing_stats,
    }
    mismatches = [
        "{} expected {}, got {}".format(name, expected[name], actual[name])
        for name in expected
        if expected[name] != actual[name]
    ]
    if mismatches:
        print("\nABORTED: plan changed; no database writes were attempted")
        for mismatch in mismatches:
            print("  - {}".format(mismatch))
        return 2
    result = apply_plan(DB, plan)
    print(
        "\nApplied: {identity_updates} identities, {game_links} game links, "
        "{inserted_logs} new fight rows".format(**result)
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
