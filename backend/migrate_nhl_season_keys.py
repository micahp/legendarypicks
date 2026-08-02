"""One-shot: move every NHL season key in the database to ESPN vocabulary.

The database has been speaking two languages about the same season. nhle.com
publishes an 8-digit span (`20252026`); ESPN keys that season `2026`, the year it
ends. `ingest_nhl_logs.py` and `ingest_nhl.py` both stored nhle's value verbatim,
so `player_game_logs` and `player_stats` said `20252026` while
`team_game_results` and `team_stats_coverage` said `2026`.

A wrong season key does not raise. It misses — exactly like the LAR/LA join key
that silently lost 178 players. `reconcile_totals` asked
`WHERE league='nhl' AND season=2026` and got **0**, over a season whose 1,312
games were all present, and reported it as a shortfall of 1,312 games. NHL sat
at coverage `partial` — unofferable — on the strength of a misspelled question.

ESPN is the spine of this backend, so ESPN wins and the data moves once. The
boundary that keeps it moved is `season_keys.normalize_season()`, now called by
both nhle ingests; this script is only the historical rows.

Why the whole league and not just the current season
----------------------------------------------------
`league_stats.py` resolves the live season with `MAX(season)`. Translate
`20252026 -> 2026` and stop there, and `MAX` picks `20242025` — a two-year-old
season served as current, from a migration that looked successful. Partial is
worse than none here. All three NHL spans move together or the script refuses.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db \\
      venv/bin/python migrate_nhl_season_keys.py [--apply]

Dry run by default: prints exact per-table counts and touches nothing.
Idempotent — a second --apply run reports zero rows, because an already-4-digit
key is a no-op through the same boundary function.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from season_keys import normalize_season

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# (table, league column, the UNIQUE tuple the rewrite could collide on).
# The unique tuples are read from the schema, not guessed:
#   player_game_logs  UNIQUE(league, source_player_key, season, game_no)
#   player_stats      UNIQUE(name_norm, league, season, stat_type)
TABLES = (
    ("player_game_logs", "league", ("league", "source_player_key", "game_no")),
    ("player_stats", "league", ("name_norm", "league", "stat_type")),
)

LEAGUE = "nhl"
SOURCE = "nhle.com"


def spans(con: sqlite3.Connection, table: str, league_col: str):
    """The 8-digit season keys this table holds for NHL, and their row counts."""
    return [
        (str(row[0]), row[1])
        for row in con.execute(
            f"SELECT season, COUNT(*) FROM {table}"
            f" WHERE {league_col}=? AND LENGTH(CAST(season AS TEXT))=8"
            f" GROUP BY season ORDER BY season",
            (LEAGUE,),
        )
    ]


def collisions(con: sqlite3.Connection, table: str, league_col: str, keys, old: str, new: int) -> int:
    """Rows that already exist at the destination key on the UNIQUE tuple.

    Zero today, checked anyway: this script may be re-pointed at prod, where the
    row history is not the one measured here, and a UNIQUE violation mid-UPDATE
    would leave the table half-translated — the exact state the docstring above
    argues is worse than not running at all.
    """
    cols = ", ".join(keys)
    return con.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT {cols} FROM {table} WHERE {league_col}=? AND CAST(season AS TEXT)=?"
        f"  INTERSECT"
        f"  SELECT {cols} FROM {table} WHERE {league_col}=? AND season=?)",
        (LEAGUE, old, LEAGUE, new),
    ).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    try:
        print(f"migrate_nhl_season_keys — db={DB}")
        plan = []
        blocked = []
        for table, league_col, unique_keys in TABLES:
            found = spans(con, table, league_col)
            if not found:
                print(f"  {table}: clean (no 8-digit NHL season keys)")
                continue
            for old, n in found:
                new = normalize_season(SOURCE, LEAGUE, old)
                clash = collisions(con, table, league_col, unique_keys, old, new)
                flag = "" if not clash else f"  <-- {clash} UNIQUE collisions"
                print(f"  {table}: {old} -> {new}   {n} rows{flag}")
                if clash:
                    blocked.append(f"{table} {old}->{new} ({clash} collisions)")
                plan.append((table, league_col, old, new, n))

        total = sum(p[4] for p in plan)
        print(f"total rows to rewrite: {total}")

        if blocked:
            print("REFUSING — destination keys already occupied:")
            for b in blocked:
                print(f"  {b}")
            sys.exit(1)

        if not plan:
            print("nothing to do")
            return

        if not args.apply:
            print("dry run; nothing written. re-run with --apply")
            return

        changed = 0
        for table, league_col, old, new, _n in plan:
            cur = con.execute(
                f"UPDATE {table} SET season=? WHERE {league_col}=? AND CAST(season AS TEXT)=?",
                (new, LEAGUE, old),
            )
            changed += cur.rowcount
        con.commit()
        print(f"rewrote {changed} rows")

        leftover = []
        for table, league_col, _keys in TABLES:
            for old, n in spans(con, table, league_col):
                leftover.append(f"{table}.{old} = {n} rows")
        if leftover:
            print("VERIFY FAILED — 8-digit NHL season keys remain:")
            for row in leftover:
                print(f"  {row}")
            sys.exit(1)
        print("verify: every NHL season key is a plain ESPN year")
    finally:
        con.close()


if __name__ == "__main__":
    main()
