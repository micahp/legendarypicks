#!/usr/bin/env python3
"""Promote the MLB 2026 Team Stats population from dev into a target database.

Distinct from `migrate_team_stats_from_dev.py`, which replaces whole leagues
wholesale into a disposable clone and refuses a target named picks.db. This one
is additive and MLB-only: it copies `team_game_results` rows dev already holds,
adds the `checked_through` column when the target predates it, and writes
nothing else. It never touches player logs (migrate_logs_to_prod.py owns those),
never deletes, and never writes a coverage row -- that row has to be EARNED by
running reconcile_totals against the target afterwards, which is the whole point
of the coverage contract. A copied verdict would vouch for data nobody checked.

Ordering matters and is not enforceable from here, so it is stated:
    1. migrate_logs_to_prod.py --league mlb --apply     (the missing logs)
    2. backfill_mlb_game_types.py --apply               (the phase they need)
    3. this script                                       (the team results)
    4. reconcile_totals.py --league mlb --write-coverage (earn the row)

    venv/bin/python promote_mlb_to_prod.py --target data/picks.db --dry-run
    venv/bin/python promote_mlb_to_prod.py --target data/picks.db --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

LEAGUE = "mlb"
SEASON = 2026
DEFAULT_SOURCE = "/root/legendarypicks/backend/data/picks.dev.db"


def _rows(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", default=os.environ.get("LP_SOURCE_DB_PATH", DEFAULT_SOURCE))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    if os.path.abspath(args.target) == os.path.abspath(args.source):
        print("ERROR: --target must differ from --source", file=sys.stderr)
        return 2

    src = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(args.target)
    dst.row_factory = sqlite3.Row
    try:
        # ---- measure the source BEFORE opening any write ----------------------
        want = _rows(src, "SELECT * FROM team_game_results WHERE league=? AND season=?",
                     (LEAGUE, SEASON))
        games = len({r["game_id"] for r in want})
        teams = len({r["team"] for r in want})
        horizon = _rows(src, "SELECT MAX(game_date) FROM team_game_results"
                             " WHERE league=? AND season=?", (LEAGUE, SEASON))[0][0]
        print(f"source: {len(want)} rows, {games} games, {teams} teams, through {horizon}")
        # 30 teams and two rows per game are properties of baseball, not of this
        # run. A source that fails them is not a population worth promoting.
        if teams != 30 or len(want) != games * 2 or not games:
            print(f"ERROR: source population is not well formed "
                  f"(rows={len(want)} games={games} teams={teams}) -- aborting",
                  file=sys.stderr)
            return 1

        have = _rows(dst, "SELECT COUNT(*), COUNT(DISTINCT game_id) FROM team_game_results"
                          " WHERE league=? AND season=?", (LEAGUE, SEASON))[0]
        print(f"target holds: {have[0]} rows, {have[1]} games")

        cols = [r[1] for r in dst.execute("PRAGMA table_info(team_stats_coverage)")]
        needs_column = "checked_through" not in cols
        print(f"target team_stats_coverage.checked_through: "
              f"{'MISSING -- will add' if needs_column else 'present'}")

        if args.dry_run:
            print("dry-run: nothing written")
            return 0

        # ---- one transaction, additive only -----------------------------------
        shared = [c for c in want[0].keys()
                  if c in {r[1] for r in dst.execute("PRAGMA table_info(team_game_results)")}]
        try:
            dst.execute("BEGIN")
            if needs_column:
                # Additive DDL: existing rows read NULL, which is what a row written
                # before the column existed honestly means.
                dst.execute("ALTER TABLE team_stats_coverage ADD COLUMN checked_through TEXT")
            placeholders = ", ".join("?" for _ in shared)
            dst.executemany(
                f"INSERT OR REPLACE INTO team_game_results ({', '.join(shared)})"
                f" VALUES ({placeholders})",
                [tuple(r[c] for c in shared) for r in want],
            )
            after = _rows(dst, "SELECT COUNT(*), COUNT(DISTINCT game_id), MAX(game_date)"
                               " FROM team_game_results WHERE league=? AND season=?",
                          (LEAGUE, SEASON))[0]
            if after[0] != len(want) or after[1] != games:
                raise RuntimeError(f"post-copy verification failed: {tuple(after)}")
            dst.execute("COMMIT")
        except Exception as exc:  # noqa: BLE001
            dst.execute("ROLLBACK")
            print(f"FAILED -- rolled back: {exc}", file=sys.stderr)
            return 1

        print(f"wrote {after[0]} rows, {after[1]} games, through {after[2]}")
        print(f"target quick_check: {dst.execute('PRAGMA quick_check').fetchone()[0]}")
        print("NOTE: no coverage row was written. Run reconcile_totals against this "
              "database to earn one.")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
