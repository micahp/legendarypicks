#!/usr/bin/env python3
"""One-shot: give `players` the MLB position columns that carry one
publisher's vocabulary each.

`players.position` for MLB holds TWO publishers' vocabularies at once, split
by the `active` flag: roster_sync.py writes ESPN's SP/RP on the active rows,
ingest_mlb_spine_identity.py writes MLB's P on the rest, so
`WHERE position='P'` returns players who are all retired and
`WHERE position IN ('SP','RP')` returns players who are all current, and
nothing raises. Two levels of one vocabulary also sit in the column together:
MLB publishes `LF/CF/RF/OF -> Outfielder`, and `WHERE position='OF'` returns
1 of 129 outfielders.

The fix is three columns, each holding exactly one level from exactly one
publisher:

  position        MLB primaryPosition.abbreviation -- specific spots only
                  (P C 1B 2B 3B SS LF CF RF DH TWP; the group-level `OF`
                  is written as NULL, see ingest_mlb_spine_identity.py)
  position_group  MLB primaryPosition.type (Pitcher Catcher Infielder
                  Outfielder Hitter Two-Way Player)
  pitcher_role    ESPN roster position, active MLB rows only, SP or RP

This migration only ADDs the two new columns. The writers
(ingest_mlb_spine_identity.py and roster_sync.py) fill them; nothing here
reads or writes existing rows. Purely additive -- an existing column is never
touched.

Usage:
  cd backend && venv/bin/python migrate_mlb_position_vocabulary.py \
      --db /abs/path/picks.dev.db [--apply]

Dry run by default. Idempotent -- ADD COLUMN is skipped for any column already
present. Backup-first: before any write, a verified backup (quick_check=ok) is
taken via migrate_schema.create_verified_backup, so a failed migration can
never strand the database.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_schema import MigrationError, create_verified_backup  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

# Column -> why it exists, so the next person does not have to guess.
NEW_COLUMNS = {
    # MLB's group level. `position` holds the specific spot; this column
    # carries the group (Pitcher/Catcher/Infielder/Outfielder/Hitter/
    # Two-Way Player), which MLB publishes alongside the abbreviation.
    "position_group": "TEXT",
    # ESPN's starter/reliever split, active MLB rows only. SP or RP and
    # nothing else; never written into `position`.
    "pitcher_role": "TEXT",
}


def existing_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        row[1] for row in connection.execute("PRAGMA table_info(players)")
    }


def migrate(db_path: str, *, apply: bool) -> int:
    connection = sqlite3.connect(db_path)
    try:
        present = existing_columns(connection)
        missing = [name for name in NEW_COLUMNS if name not in present]
        if not missing:
            print("all columns already present -- nothing to do")
            return 0
        print("adding to players:")
        for name in missing:
            print(f"  + {name} {NEW_COLUMNS[name]}")
        if not apply:
            print("\ndry run -- pass --apply to add them")
            return 0
        try:
            backup = create_verified_backup(db_path)
        except MigrationError as exc:
            print(f"ERROR: backup failed, nothing written: {exc}",
                  file=sys.stderr)
            return 1
        print(f"backup: {backup} (quick_check=ok)")
        for name in missing:
            connection.execute(
                f"ALTER TABLE players ADD COLUMN {name} {NEW_COLUMNS[name]}"
            )
        connection.commit()
        added = existing_columns(connection) - present
        print(f"\nadded {len(added)} columns: {', '.join(sorted(added))}")
        return 0
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(f"database: {args.db}")
    return migrate(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
