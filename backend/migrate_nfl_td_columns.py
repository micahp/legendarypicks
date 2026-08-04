"""One-shot: add the NFL touchdown and attempt columns nflverse already publishes.

`A/required-stats[season]` has failed for NFL on "no such column: rush_td,
rec_td", and `E/qualifier[season]` on "there is no `attempts` column to measure
it with" -- the published rule being *passer rating 14 att x team games*. Both
read as missing data. Neither is.

All three are in `stats_player_reg_YEAR.parquet`, the artifact
`ingest_nfl_season_stats.py` already downloads and already reads 143 columns
from: `rushing_tds`, `receiving_tds`, `attempts`. Nothing new is fetched to fill
these; the numbers have been arriving and being dropped on the floor.

This is the fourth league where the headline gap was published data nobody read
-- see `.claude/skills/published-first/SKILL.md` §2b. It is also the reason the
NFL board cannot be sorted by touchdowns, which for a fantasy-football product
is the column people actually want.

Usage:
  cd backend && venv/bin/python migrate_nfl_td_columns.py \\
      --db data/picks.dev.db [--apply]

Dry run by default. Purely additive and idempotent.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

NEW_COLUMNS = {
    "rush_td": "INTEGER",
    "rec_td": "INTEGER",
    # The published qualifier's own unit. Without the column there is no way to
    # ask the published question at all.
    "attempts": "INTEGER",
}


def existing_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        row[1] for row in connection.execute("PRAGMA table_info(player_stats)")
    }


def migrate(db_path: str, *, apply: bool) -> int:
    connection = sqlite3.connect(db_path)
    try:
        present = existing_columns(connection)
        missing = [name for name in NEW_COLUMNS if name not in present]
        if not missing:
            print("all columns already present -- nothing to do")
            return 0

        waiting = connection.execute(
            """SELECT COUNT(*) FROM player_stats
               WHERE lower(league)='nfl' AND stat_type='season'"""
        ).fetchone()[0]
        print(f"{waiting} nfl season rows waiting on these columns")
        for name in missing:
            print(f"  + {name} {NEW_COLUMNS[name]}")
        if not apply:
            print("\ndry run -- pass --apply to add them")
            return 0

        for name in missing:
            connection.execute(
                f"ALTER TABLE player_stats ADD COLUMN {name} {NEW_COLUMNS[name]}"
            )
        connection.commit()
        print(f"\nadded {len(missing)} columns: {', '.join(sorted(missing))}")
        print("now re-run ingest_nfl_season_stats.py to fill them")
        return 0
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("LP_DB_PATH")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "picks.db"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(f"database: {args.db}")
    return migrate(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
