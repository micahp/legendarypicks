"""One-shot: stamp provenance onto team_game_results rows written before it had a column.

`team_game_results` gained `source` and `run_id` on 2026-08-02 (see
`backfill_team_parity.ensure_schema`). Rows written before that carry NULL, and
`provenance.py` renders them honestly as "rows written without a source" — which
is correct, and also permanent unless something attributes them.

**This script does not guess.** It attributes only from evidence already in the
database: `team_game_stats.run_id`, which `backfill_team_parity` has written per
(league, game_id) since long before today. A run_id of the form
`<league>-parity-<timestamp>` names that script and therefore names its
publisher. Any row without such a run_id is left NULL, deliberately — an
unattributable row must keep saying so. "One script writes this table, so it's
obviously ESPN" is the reasoning that let two publishers share a schema
unremarked for nineteen days.

Measured 2026-08-02:
    nba  nba-parity-20260802T211716Z   2462 stat rows
    nhl  nhl-parity-20260802T211716Z   2624
    nfl  nfl-parity-20260714T212102Z    544
    mlb  (empty run_id)                  16   <- stays NULL

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db \\
      venv/bin/python stamp_team_result_source.py [--apply]
"""
from __future__ import annotations

import argparse
import os
import sqlite3

from backfill_team_parity import SOURCE

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# The run_id shape that identifies backfill_team_parity as the writer. Matched
# explicitly rather than "any non-empty run_id" — a future script writing this
# table under its own run_id must not be silently attributed to ESPN's site API.
PARITY_RUN = "%-parity-%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    try:
        print(f"stamp_team_result_source — db={DB}")
        plan = con.execute(
            "SELECT r.league, s.run_id, COUNT(*) FROM team_game_results r"
            " JOIN team_game_stats s ON s.league=r.league AND s.game_id=r.game_id"
            "   AND s.team_abbrev=r.team"
            " WHERE r.source IS NULL AND s.run_id LIKE ?"
            " GROUP BY r.league, s.run_id ORDER BY r.league",
            (PARITY_RUN,),
        ).fetchall()
        for lg, run_id, n in plan:
            print(f"  {lg}: {n} rows <- {run_id}  source={SOURCE}")

        unattributable = con.execute(
            "SELECT league, COUNT(*) FROM team_game_results r WHERE r.source IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM team_game_stats s"
            "   WHERE s.league=r.league AND s.game_id=r.game_id"
            "     AND s.team_abbrev=r.team AND s.run_id LIKE ?)"
            " GROUP BY league",
            (PARITY_RUN,),
        ).fetchall()
        for lg, n in unattributable:
            print(f"  {lg}: {n} rows have no parity run_id — LEFT NULL on purpose")

        total = sum(p[2] for p in plan)
        print(f"total rows to stamp: {total}")
        if not args.apply:
            print("dry run; nothing written. re-run with --apply")
            return

        cur = con.execute(
            "UPDATE team_game_results AS r SET source=?, run_id=("
            "  SELECT s.run_id FROM team_game_stats s"
            "   WHERE s.league=r.league AND s.game_id=r.game_id"
            "     AND s.team_abbrev=r.team AND s.run_id LIKE ?)"
            " WHERE r.source IS NULL AND EXISTS ("
            "  SELECT 1 FROM team_game_stats s"
            "   WHERE s.league=r.league AND s.game_id=r.game_id"
            "     AND s.team_abbrev=r.team AND s.run_id LIKE ?)",
            (SOURCE, PARITY_RUN, PARITY_RUN),
        )
        con.commit()
        print(f"stamped {cur.rowcount} rows")
    finally:
        con.close()


if __name__ == "__main__":
    main()
