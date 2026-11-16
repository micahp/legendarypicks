#!/usr/bin/env python3
"""Rename players.nba_id to players.hoopr_id.

Why: the column holds hoopR athlete ids, which are ESPN athlete ids. It does not
hold official NBA.com ids. Those live in player_source_ids (source = 'nba.com').

What it does: ALTER TABLE players RENAME COLUMN. SQLite keeps every value, the
row order, and any index or view that used the column. Nothing is copied or
deleted. players.id is never touched.

Safe to re-run: if the column is already hoopr_id, it reports that and exits 0.
It refuses if both columns exist.

Usage (dry run is the default):
  python3 migrate_players_hoopr_id.py --db /abs/picks.dev.db
  python3 migrate_players_hoopr_id.py --db /abs/picks.dev.db --apply
  python3 migrate_players_hoopr_id.py --db /abs/picks.dev.db --rollback

Rollback is the same rename in reverse (--rollback). Do not apply to production
until the user approves it. Needs SQLite 3.25 or newer.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys

OLD, NEW = "nba_id", "hoopr_id"


def connect(path: str, read_only: bool) -> sqlite3.Connection:
    if not os.path.isabs(path) or not os.path.isfile(path):
        raise SystemExit("database must be an existing absolute file: " + path)
    mode = "ro" if read_only else "rw"
    con = sqlite3.connect("file:{}?mode={}".format(path, mode), uri=True,
                          timeout=120)
    con.execute("PRAGMA busy_timeout = 120000")
    return con


def columns(con):
    return {r[1] for r in con.execute("PRAGMA table_info(players)")}


def fingerprint(con, column):
    """Row count, non-empty id count, and a hash over (players.id, league, value)."""
    digest = hashlib.sha256()
    total = filled = 0
    for pid, league, value in con.execute(
            "SELECT id, league, {} FROM players ORDER BY id".format(column)):
        total += 1
        if value not in (None, ""):
            filled += 1
        digest.update("{}|{}|{}\n".format(pid, league, value).encode())
    return total, filled, digest.hexdigest()


def dependents(con, column):
    """Schema objects (other than the players table) whose SQL names the column."""
    return [r for r in con.execute(
        "SELECT type, name FROM sqlite_master WHERE sql LIKE ? "
        "AND NOT (type = 'table' AND name = 'players')", ("%" + column + "%",))]


def rename(con, src, dst):
    before = fingerprint(con, src)
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("ALTER TABLE players RENAME COLUMN {} TO {}".format(src, dst))
        after = fingerprint(con, dst)
        if before != after:
            raise RuntimeError("fingerprint changed: {} -> {}".format(before, after))
        if src in columns(con):
            raise RuntimeError("old column still present")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return before


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = parser.parse_args(argv)

    src, dst = (NEW, OLD) if args.rollback else (OLD, NEW)
    writing = args.apply or args.rollback
    con = connect(args.db, read_only=not writing)
    present = columns(con)
    if OLD in present and NEW in present:
        raise SystemExit("players has both {} and {}; resolve by hand".format(OLD, NEW))
    if dst in present:
        print("already {}: nothing to do".format(dst))
        return 0
    if src not in present:
        raise SystemExit("players has neither {} nor {}".format(OLD, NEW))

    total, filled, digest = fingerprint(con, src)
    deps = dependents(con, src)
    print("players rows: {} | {} filled: {} | hash {}".format(
        total, src, filled, digest[:16]))
    print("other schema objects naming {}: {}".format(src, deps or "none"))
    if not writing:
        print("dry run. Would rename {} to {}. Use --apply or --rollback.".format(src, dst))
        return 0
    before = rename(con, src, dst)
    print("renamed {} to {}. rows {}, filled {}, hash unchanged.".format(
        src, dst, before[0], before[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
