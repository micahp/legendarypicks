#!/usr/bin/env python3
"""Freeze the pick record for lock rows that predate it.

The pick rule used to live only in the browser, so projections locked before the pick
record existed have no frozen recommendation and the record could not grade what the
cards showed. This fills that gap from the Bovada snapshot in force at each game's lock
timestamp, then verifies each frozen pick is stable.

Dry run by default (an in-memory copy is written); --apply writes immutable rows to the
standalone NHL model database. Never writes to a Legendary Picks database.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from nhl_model_store import (DEFAULT_DB, NHLModelError, backfill_picks, ensure_schema,
                             open_db)


def _assert_standalone(path: str) -> None:
    if os.path.basename(os.path.realpath(path)) in {"picks.db", "picks.dev.db"}:
        raise SystemExit("refusing Legendary Picks database path: %s" % path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("NHL_MODEL_DB_PATH", DEFAULT_DB))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--apply", action="store_true", help="write immutable pick rows")
    args = parser.parse_args(argv)
    _assert_standalone(args.db)
    if not os.path.exists(args.db):
        print("no NHL model database at %s" % args.db, file=sys.stderr)
        return 1
    try:
        if args.apply:
            con = open_db(args.db)
        else:
            source = open_db(args.db, readonly=True)
            con = open_db(":memory:")
            source.backup(con)
            source.close()
        try:
            ensure_schema(con)
            report = backfill_picks(con, args.season)
        finally:
            con.close()
    except (NHLModelError, sqlite3.Error) as exc:
        print("NHL pick backfill failed: %s" % exc, file=sys.stderr)
        return 1
    print("%s: %d games, %d pick rows frozen, %d already present, %d skipped" % (
        "applied" if args.apply else "dry-run", report["games"], report["pick_rows"],
        report["already_picked"], report["skipped"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
