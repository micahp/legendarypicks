#!/usr/bin/env python3
"""Guarded UFCStats-only history ingest for fighters on the published props board."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
from contextlib import closing
from typing import Dict, Optional

import history_refresh_common as common
from ingest_ufc_fight_stats.ufcstats_pipeline import (
    SUPPORTED_PROP_MARKETS,
    apply_ufcstats_plan,
    build_ufcstats_plan,
    load_ufcstats_state,
)
from ingest_ufc_fight_stats.ufcstats_source import UfcStatsClient
from migrate_ufcstats_history import inspect as inspect_migration


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "picks.dev.db")


def _backup_to(db_path: str, backup_path: str) -> None:
    target = os.path.abspath(backup_path)
    if target == os.path.abspath(db_path) or os.path.exists(target):
        raise RuntimeError("backup path must be new and differ from the database")
    with closing(common.read_only_connection(db_path)) as source:
        source.execute("PRAGMA busy_timeout=60000")
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    if common.integrity_check(target) != "ok":
        raise RuntimeError("backup integrity check failed: {}".format(target))


def run(
    db_path: str,
    as_of: dt.date,
    archive_dir: str,
    lookback_days: int = 0,
    lookahead_days: int = 2,
    limit: int = 5,
    apply: bool = False,
    backup_path: Optional[str] = None,
    expected: Optional[Dict[str, int]] = None,
    client=None,
    emit=print,
) -> dict:
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path) or os.path.getsize(db_path) <= 0:
        raise RuntimeError("database is missing or empty: {}".format(db_path))
    migration = inspect_migration(db_path)
    if migration["state"] != "applied":
        raise RuntimeError("UFCStats history migration is {}".format(migration["state"]))

    targets, accepted, stored, owners, existing = load_ufcstats_state(
        db_path,
        as_of,
        lookback_days=lookback_days,
        lookahead_days=lookahead_days,
        markets=SUPPORTED_PROP_MARKETS,
    )
    plan = build_ufcstats_plan(
        targets, accepted, stored, owners, existing,
        client or UfcStatsClient(archive_dir),
        limit=limit,
        emit=emit,
        include_upcoming_events=True,
        allow_pair_alias=True,
    )
    counts = {
        "targets": len(targets),
        "active_targets": plan.active_target_count,
        "inserts": len(plan.inserts),
        "updates": len(plan.updates),
        "mappings": len(plan.mappings),
        "identity_merges": len(plan.identity_merges),
        "existing": plan.existing_count,
        "no_history": len(plan.no_history),
        "inactive": len(plan.inactive),
        "unresolved": len(plan.unresolved),
        "source_errors": len(plan.source_errors),
        "conflicts": len(plan.conflicts),
    }
    emit("UFCStats plan: " + ", ".join("{}={}".format(k, v) for k, v in counts.items()))
    for label, values in (
        ("UNRESOLVED", plan.unresolved),
        ("SOURCE ERROR", plan.source_errors),
        ("CONFLICT", plan.conflicts),
        ("NO HISTORY", plan.no_history),
        ("INACTIVE", plan.inactive),
    ):
        for value in values:
            emit("{} {}".format(label, value))
    if plan.unresolved or plan.source_errors or plan.conflicts:
        raise RuntimeError("UFCStats plan failed closed")
    if not apply:
        return {"status": "dry_run", **counts}

    if backup_path is None or expected is None:
        raise RuntimeError("apply requires a new backup path and expected plan counts")
    mismatches = [
        "{} expected {}, got {}".format(key, expected.get(key), counts[key])
        for key in (
            "targets",
            "active_targets",
            "inserts",
            "updates",
            "mappings",
            "identity_merges",
            "no_history",
            "inactive",
        )
        if expected.get(key) != counts[key]
    ]
    if mismatches:
        raise RuntimeError("plan changed: " + "; ".join(mismatches))
    _backup_to(db_path, backup_path)
    result = apply_ufcstats_plan(db_path, plan)
    if common.integrity_check(db_path) != "ok":
        raise RuntimeError("database integrity check failed after apply")
    return {"status": "applied", "backup": os.path.abspath(backup_path), **counts, **result}


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH") or DEFAULT_DB)
    parser.add_argument("--as-of", default=dt.date.today().isoformat())
    parser.add_argument("--archive-dir", default=os.path.join(HERE, "data", "ufcstats-archive"))
    parser.add_argument(
        "--from-archive",
        action="store_true",
        help="replay the exact archived source snapshot without network requests",
    )
    parser.add_argument("--lookback-days", type=_nonnegative, default=0)
    parser.add_argument("--lookahead-days", type=_nonnegative, default=2)
    parser.add_argument("--limit", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    for name in (
        "targets",
        "active-targets",
        "inserts",
        "updates",
        "mappings",
        "identity-merges",
        "no-history",
        "inactive",
    ):
        parser.add_argument("--expect-" + name, type=_nonnegative)
    args = parser.parse_args(argv)
    try:
        as_of = dt.date.fromisoformat(args.as_of)
    except ValueError:
        parser.error("--as-of must be YYYY-MM-DD")
    expected = None
    if args.apply:
        values = {
            "targets": args.expect_targets,
            "active_targets": args.expect_active_targets,
            "inserts": args.expect_inserts,
            "updates": args.expect_updates,
            "mappings": args.expect_mappings,
            "identity_merges": args.expect_identity_merges,
            "no_history": args.expect_no_history,
            "inactive": args.expect_inactive,
        }
        missing = [key for key, value in values.items() if value is None]
        if not args.backup or missing:
            parser.error("--apply requires --backup and every --expect-* count")
        expected = values
    try:
        result = run(
            args.db, as_of, args.archive_dir,
            lookback_days=args.lookback_days,
            lookahead_days=args.lookahead_days,
            limit=args.limit, apply=args.apply, backup_path=args.backup,
            expected=expected,
            client=UfcStatsClient(args.archive_dir, from_archive=args.from_archive),
        )
    except Exception as exc:
        print("ERROR: {}: {}".format(type(exc).__name__, exc))
        return 2
    print("Result: " + ", ".join("{}={}".format(k, v) for k, v in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
