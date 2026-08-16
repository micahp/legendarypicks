"""One-shot: add the NCAAF season-stat columns CFBD publishes.

The ncaaf gate (``audit_league_stats.py`` MANIFEST) declares the ``season``
stat_type's required columns as the exact CFBD keys the logs carry: ``att,
pass_yds, pass_td, intc, rush_yds, rush_td, rec, rec_yds, rec_td``. Of those,
``player_stats`` already holds ``pass_td, rush_td, rec_td`` (added by the NFL
touchdown migration); the other six are missing, so ``A/required-stats[season]``
reads "no such column: att, pass_yds, intc, rush_yds, rec, rec_yds".

Nothing new is fetched to fill them. The numbers are the same CFBD per-game
values ``ingest_cfbd_logs.py`` already writes into ``player_game_logs.stats``;
``ingest_ncaaf_season_stats.py`` sums them per player. Purely additive and
idempotent, same shape as ``migrate_nfl_td_columns.py``.

Usage:
  cd backend && python3 migrate_ncaaf_season_columns.py \\
      --db /root/legendarypicks/backend/data/picks.dev.db [--apply]

Dry run by default.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# CFBD key -> column type. The three touchdown columns already exist; the
# six below are the only ones added here.
NEW_COLUMNS = {
    "att": "INTEGER",
    "pass_yds": "INTEGER",
    "intc": "INTEGER",
    "rush_yds": "INTEGER",
    "rec": "INTEGER",
    "rec_yds": "INTEGER",
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
            print("all ncaaf season columns already present -- nothing to do")
            return 0
        if not apply:
            for name in missing:
                print(f"  would add {name} {NEW_COLUMNS[name]}")
            print("dry run -- pass --apply to add them")
            return 0
        for name in missing:
            connection.execute(
                f"ALTER TABLE player_stats ADD COLUMN {name} {NEW_COLUMNS[name]}"
            )
        connection.commit()
        print(f"added {len(missing)} columns: {', '.join(sorted(missing))}")
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
