"""One-shot: add the MLS season-stat column the manifest declares.

The mls gate (``audit_league_stats.py`` MANIFEST) declares the ``season``
stat_type's required columns as the exact keys ``ingest_soccer_logs`` writes:
``goals, assists, shots, sot``. Of those, ``player_stats`` already holds
``goals, assists, shots`` (and ``shooting_pct``); only ``sot`` (shots on
target) is missing, so ``A/required-stats[season]`` reads "no such column:
sot".

Nothing new is fetched to fill it. The numbers are the same ESPN per-game
values ``ingest_soccer_logs.py`` already writes into ``player_game_logs.stats``
(zero-filled for every line); ``ingest_mls_season_stats.py`` sums them per
player. Purely additive and idempotent, same shape as
``migrate_ncaaf_season_columns.py``.

Usage:
  cd backend && python3 migrate_mls_season_columns.py \
      --db /root/lp-league-mls-ncaaf/backend/data/picks.dev.db [--apply]

Dry run by default.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# stat key -> column type. goals/assists/shots already exist; sot is the
# only one added here.
NEW_COLUMNS = {
    "sot": "INTEGER",
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
            print("all mls season columns already present -- nothing to do")
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
