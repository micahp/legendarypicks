#!/usr/bin/env python3
"""One-shot: make `player_game_logs.team` agree with the vocabulary everything joins on.

Found 2026-09-07 by comparing `players.team` against `player_game_logs.team` per league.
Most leagues agree exactly. Two do not, in two different ways.

FIX 1 - MLB carries both spellings of two clubs.

    AZ    1832 rows   2026-03-15 .. 2026-09-05      ARI    214 rows   from 2026-07-26
    CWS   1885 rows   2026-03-15 .. 2026-09-05      CHW    246 rows   from 2026-07-26

`refresh_mlb_player_teams.py` already names this boundary: "statsapi says AZ and CWS; this
repo says ARI and CHW. Converted once, at ingest, never by a reader." The conversion began
working on 2026-07-26 and nothing went back for what came before, so 3,717 rows still carry
the publisher's spelling while `players.team` and `_TEAM_MAPS['mlb']` both say ARI and CHW.
Any join on team silently drops those rows, for those two clubs only.

FIX 2 - the NBA All-Star game is indistinguishable from the season.

24 rows on 2026-02-15 have teams STARS, STRIPES and WORLD playing one another. Those team
names are CORRECT; that is what the 2026 All-Star teams were called. The defect is that
`game_type` is NULL for all 23,749 NBA rows, so an exhibition is shaped exactly like a
regular-season game and lands in season aggregates. NHL already uses REG and POST, so the
column and the vocabulary both exist; NBA just never populated it.

The team names are deliberately NOT rewritten. Renaming them would destroy a true fact to
work around a missing one.

NOT INCLUDED: NHL. `players.team` and the static map disagree there too, but the shape is
different and it is a decision rather than a repair. The committed map says LAK, SJS, TBL
and UTA, which are the NHL's own tricodes, while the database says LA, SJ, TB and UTAH on
129 players and 6,450 log rows against 5 player rows following the map. Picking a side
moves thousands of rows either way and belongs in its own change with its own argument.

Usage:
  cd backend && python3 migrate_log_team_vocabulary.py --db data/picks.db [--apply]

Dry run by default. Idempotent: a second run reports nothing to do.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# statsapi spelling -> the spelling players.team and _TEAM_MAPS['mlb'] already use.
MLB_RESPELL = {"AZ": "ARI", "CWS": "CHW"}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_types import ALLSTAR as ALLSTAR_GAME_TYPE

# The 2026 All-Star teams. Marked, never renamed. The marker itself comes from
# `game_types`, which owns the PRE/REG/POST/PLAYIN/ALLSTAR vocabulary, so this cannot
# drift from what every reader already checks. picks.dev.db already carries it on these
# rows; prod is the one that never got it.
NBA_ALLSTAR_TEAMS = ("STARS", "STRIPES", "WORLD")


def _count(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


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
        planned = 0

        print("{}:".format(args.db))
        for wrong, right in sorted(MLB_RESPELL.items()):
            n = _count(con,
                       "SELECT COUNT(*) FROM player_game_logs WHERE player_id IN "
                       "(SELECT id FROM players WHERE league='mlb') "
                       "AND UPPER(TRIM(team))=?", (wrong,))
            print("  mlb  {:>5} rows spelled {} -> {}".format(n, wrong, right))
            planned += n
            if n and args.apply:
                con.execute(
                    "UPDATE player_game_logs SET team=? WHERE player_id IN "
                    "(SELECT id FROM players WHERE league='mlb') "
                    "AND UPPER(TRIM(team))=?", (right, wrong))

        placeholders = ",".join("?" * len(NBA_ALLSTAR_TEAMS))
        n = _count(con,
                   "SELECT COUNT(*) FROM player_game_logs WHERE player_id IN "
                   "(SELECT id FROM players WHERE league='nba') "
                   "AND UPPER(TRIM(team)) IN ({}) "
                   "AND COALESCE(game_type,'')<>?".format(placeholders),
                   list(NBA_ALLSTAR_TEAMS) + [ALLSTAR_GAME_TYPE])
        print("  nba  {:>5} All-Star rows to mark game_type={} (names unchanged)".format(
            n, ALLSTAR_GAME_TYPE))
        planned += n
        if n and args.apply:
            con.execute(
                "UPDATE player_game_logs SET game_type=? WHERE player_id IN "
                "(SELECT id FROM players WHERE league='nba') "
                "AND UPPER(TRIM(team)) IN ({})".format(placeholders),
                [ALLSTAR_GAME_TYPE] + list(NBA_ALLSTAR_TEAMS))

        if not planned:
            print("  nothing to do")
            return 0
        if not args.apply:
            print("  {} rows would change (dry run)".format(planned))
            return 0
        con.commit()

        # Verify against the goal, not against the statement having run.
        left = sum(_count(con,
                          "SELECT COUNT(*) FROM player_game_logs WHERE player_id IN "
                          "(SELECT id FROM players WHERE league='mlb') "
                          "AND UPPER(TRIM(team))=?", (wrong,))
                   for wrong in MLB_RESPELL)
        unmarked = _count(con,
                          "SELECT COUNT(*) FROM player_game_logs WHERE player_id IN "
                          "(SELECT id FROM players WHERE league='nba') "
                          "AND UPPER(TRIM(team)) IN ({}) "
                          "AND COALESCE(game_type,'')<>?".format(placeholders),
                          list(NBA_ALLSTAR_TEAMS) + [ALLSTAR_GAME_TYPE])
        print("  applied {} rows; {} mlb misspellings and {} unmarked All-Star rows remain"
              .format(planned, left, unmarked))
        print("  PRAGMA quick_check: {}".format(
            con.execute("PRAGMA quick_check").fetchone()[0]))
        return 1 if (left or unmarked) else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
