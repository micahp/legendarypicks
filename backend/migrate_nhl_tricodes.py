#!/usr/bin/env python3
"""migrate_nhl_tricodes.py — move NHL club codes onto the league's own tricodes.

WHY.

`players.team` and `player_game_logs.team` disagreed with the committed club map, and the
map was right. `_TEAM_MAPS['nhl']` says LAK, SJS, TBL and UTA; the database said LA, SJ, TB
and UTAH on 129 players and 6,450 log rows against 5 player rows following the map. Verified
against the publisher on 2026-09-07 — `api.nhle.com/stats/rest/en/team` publishes:

    LAK  Los Angeles Kings      TBL  Tampa Bay Lightning
    SJS  San Jose Sharks        UTA  Utah Hockey Club / Utah Mammoth

So anything resolving a club through `_norm_team` produced a code the data did not contain,
and silently matched nothing. The publisher decides; the data moves.

THE DANGEROUS PART, AND WHY EVERY STATEMENT IS LEAGUE-SCOPED.

`LA`, `SJ` and `TB` are live codes in OTHER leagues. Unscoped, these four renames would hit
26 nfl_transactions rows, 641 nfl_snap_counts, 34 nfl_schedule and more. Counted per table
with an NHL scope first, every other hit is another league's data and is not touched. There
is no table here without either a `league` column or a `player_id` to reach one; a table
with neither would have to be left alone rather than guessed at.

Scoped counts on prod 2026-09-07 (13,864 values across 7 tables):

    player_game_logs.team 6450   player_game_logs.opponent 6319
    team_game_stats 246          team_game_results.team 246, .opponent 246
    players 129                  roster_memberships 129    player_stats 99

Usage:
  cd backend && python3 migrate_nhl_tricodes.py --db data/picks.db [--apply]

Dry run by default. Idempotent: the codes are their own targets on a second run.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# The publisher's own tricodes. Verified against api.nhle.com, not inferred.
TRICODES = {"LA": "LAK", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}

# (table, column, how to reach the league). Every entry is scoped; see the docstring.
TARGETS = [
    ("player_game_logs", "team", "league"),
    ("player_game_logs", "opponent", "league"),
    ("team_game_stats", "team_abbrev", "league"),
    ("team_game_results", "team", "league"),
    ("team_game_results", "opponent", "league"),
    ("players", "team", "league"),
    ("player_stats", "team", "league"),
    ("roster_memberships", "team", "player_id"),
]
OLD = tuple(TRICODES)
_IN = ",".join("?" * len(OLD))


def _where(scope):
    if scope == "league":
        return "LOWER(league)='nhl'"
    return "player_id IN (SELECT id FROM players WHERE league='nhl')"


def _count(con, table, column, scope):
    return con.execute(
        "SELECT COUNT(*) FROM {} WHERE {} AND UPPER(TRIM({})) IN ({})".format(
            table, _where(scope), column, _IN), OLD).fetchone()[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        print("no such database: {}".format(args.db))
        return 2

    con = sqlite3.connect(args.db, timeout=30)
    try:
        print("{}:".format(args.db))
        planned = 0
        for table, column, scope in TARGETS:
            try:
                n = _count(con, table, column, scope)
            except sqlite3.Error as exc:
                print("  {}.{}: {}; skipped".format(table, column, exc))
                continue
            if n:
                print("  {:<22} {:<12} {:>6}".format(table, column, n))
            planned += n
            if n and args.apply:
                for old, new in TRICODES.items():
                    con.execute(
                        "UPDATE {} SET {}=? WHERE {} AND UPPER(TRIM({}))=?".format(
                            table, column, _where(scope), column), (new, old))
        if not planned:
            print("  nothing to do")
            return 0
        if not args.apply:
            print("  {} values would change (dry run)".format(planned))
            return 0
        con.commit()

        # Verify against the goal: no NHL row anywhere still holds an old code.
        left = 0
        for table, column, scope in TARGETS:
            try:
                left += _count(con, table, column, scope)
            except sqlite3.Error:
                pass
        print("  applied {} values; {} old NHL codes remain".format(planned, left))
        print("  PRAGMA quick_check: {}".format(
            con.execute("PRAGMA quick_check").fetchone()[0]))
        return 1 if left else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
