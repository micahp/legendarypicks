"""One-shot: move every NFL team code in the database to ESPN vocabulary.

The database has been speaking two languages. `players` held ESPN codes on
active rows and nflverse codes on the 1,724 inactive ones; `player_game_logs`,
`nfl_pbp`, `nfl_depth_chart` and the 2024 rows of `nfl_schedule` and
`team_game_results` were nflverse throughout. Readers coped by normalising at
the point of display (`nfl_offseason._normalize_team`), which made the board
look clean over dirty data and hid the split from everything that joined.

ESPN is the spine of this backend, so ESPN wins and the data moves once.

Why every statement is league-scoped
------------------------------------
This is the trap, and it is not hypothetical. `STL` is the St. Louis Blues,
`SD` is the San Diego Padres, `LA` is the LA Kings, `AZ` is the Arizona
Diamondbacks -- all current, correct codes in their own leagues, all sitting in
the same shared tables as the NFL rows. A league-blind `STL -> LAR` would
silently rewrite 1,459 MLB and 1,500 NHL game logs into Rams games. So every
statement below either filters on a league column or runs against a table that
is NFL by definition, and the ones without a league column are listed
explicitly rather than inferred from the name.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db \\
      venv/bin/python migrate_nfl_team_vocabulary.py [--apply]

Dry run by default: prints the exact per-column counts it would change and
touches nothing. Idempotent -- a second --apply run reports zero rows.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# NOT RUNNABLE YET -- team_codes.py has not been written. See
# CONTEXT-2026-07-27-HANDOFF-9.md §2. The scoping below (which tables, which
# columns, which league filter) is measured and correct; only the module import
# is pending.
from team_codes import ALIASES as _ALL_ALIASES, CANONICAL

ALIASES = _ALL_ALIASES["nfl"]
ESPN_TEAMS = CANONICAL["nfl"]

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# (table, column, league_filter). league_filter None means the table is NFL by
# definition -- verified by reading its writer, not by trusting the name:
#   nfl_schedule      <- ingest_nfl_schedule.py
#   nfl_pbp           <- ingest_nfl_pbp_logs.py
#   nfl_depth_chart   <- ingest_nfl_depth_charts.py
TARGETS = (
    ("players", "team", "nfl"),
    ("player_stats", "team", "nfl"),
    ("player_stats", "nfl_team", "nfl"),
    ("player_game_logs", "team", "nfl"),
    ("player_game_logs", "opponent", "nfl"),
    ("team_game_results", "team", "nfl"),
    ("team_game_results", "opponent", "nfl"),
    ("nfl_schedule", "home_team", None),
    ("nfl_schedule", "away_team", None),
    ("nfl_depth_chart", "team", None),
    ("nfl_pbp", "posteam", None),
    ("nfl_pbp", "defteam", None),
    ("nfl_pbp", "home_team", None),
    ("nfl_pbp", "away_team", None),
)


def _exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    return bool(cols) and column in cols


def survey(con: sqlite3.Connection):
    """Per-target counts of rows that would change, keyed by alias."""
    out = []
    for table, column, league in TARGETS:
        if not _exists(con, table, column):
            out.append((table, column, league, None))
            continue
        counts = {}
        for bad, good in ALIASES.items():
            sql = f"SELECT COUNT(*) FROM {table} WHERE {column} = ?"
            params = [bad]
            if league:
                sql += " AND league = ?"
                params.append(league)
            n = con.execute(sql, params).fetchone()[0]
            if n:
                counts[(bad, good)] = n
        out.append((table, column, league, counts))
    return out


def apply(con: sqlite3.Connection) -> int:
    total = 0
    for table, column, league in TARGETS:
        if not _exists(con, table, column):
            continue
        for bad, good in ALIASES.items():
            sql = f"UPDATE {table} SET {column} = ? WHERE {column} = ?"
            params = [good, bad]
            if league:
                sql += " AND league = ?"
                params.append(league)
            cur = con.execute(sql, params)
            total += cur.rowcount
    return total


def verify(con: sqlite3.Connection) -> list:
    """Every NFL team code left in the database that is not one of the 32."""
    bad = []
    for table, column, league in TARGETS:
        if not _exists(con, table, column):
            continue
        sql = f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL"
        params = []
        if league:
            sql += " AND league = ?"
            params.append(league)
        for (value,) in con.execute(sql, params):
            if value and value not in ESPN_TEAMS:
                bad.append((table, column, value))
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes; omit for a dry run")
    args = ap.parse_args()

    print(f"db: {DB}")
    con = sqlite3.connect(DB)
    try:
        grand = 0
        for table, column, league, counts in survey(con):
            scope = f" [league={league}]" if league else ""
            if counts is None:
                print(f"  {table}.{column}{scope}: absent, skipped")
                continue
            if not counts:
                print(f"  {table}.{column}{scope}: clean")
                continue
            detail = ", ".join(f"{b}->{g}={n}" for (b, g), n in sorted(counts.items()))
            n = sum(counts.values())
            grand += n
            print(f"  {table}.{column}{scope}: {n}  ({detail})")
        print(f"total rows to rewrite: {grand}")

        if not args.apply:
            print("dry run; nothing written. re-run with --apply")
            return

        changed = apply(con)
        con.commit()
        print(f"rewrote {changed} rows")

        leftover = verify(con)
        if leftover:
            print("VERIFY FAILED -- non-canonical codes remain:")
            for row in leftover:
                print(f"  {row[0]}.{row[1]} = {row[2]!r}")
            sys.exit(1)
        print("verify: every NFL team code is one of the 32")
    finally:
        con.close()


if __name__ == "__main__":
    main()
