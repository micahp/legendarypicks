"""One-shot: create the `published_roster_name` table PROD is missing.

`published_roster.lookup_player` reads this table to find every spelling a publisher
prints for one of its own people. mlssoccer.com displays "Jake Davis" and files him at
`/players/jacob-davis/`; storing only the first is what forced six hand-written aliases
into `REVIEWED_ALIASES` on 2026-09-06, five of which the second publisher retired.

WHY A MIGRATION AND NOT A REBUILD. `scripts/release.sh` blocks on prod/dev schema
divergence (line 142), and it is right to: v0.9.3's resolver reads a table prod does not
have. Prod gets the DB change; the image is rebuilt by the release, not by this.

WHAT IT DOES NOT DO. Fill the table. It is created empty and
`ingest_published_rosters.py` populates it on its next registry run, from the publishers
each league declares. Copying dev's 2,180 rows would be the wrong move twice over:
`published_roster` is keyed on the publisher's own id, so the rows are portable, but a
migration that carries data is a migration that can carry a bad row, and the ingest that
owns this table is scheduled and idempotent.

Additive and idempotent: `CREATE TABLE IF NOT EXISTS` plus its index, no existing row
read or written. Safe to re-run.

Usage:
  cd backend && python3 migrate_published_roster_name.py \
      --db data/picks.db [--apply]

Dry run by default.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster

TABLE = "published_roster_name"


def has_table(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.db):
        print("no such database: {}".format(args.db))
        return 2

    connection = sqlite3.connect(args.db, timeout=30)
    try:
        # `published_roster` must already exist. If it does not, this database has never
        # run the roster ingest and creating only the names table would leave a half
        # schema that reads as migrated.
        if not has_table(connection, "published_roster"):
            print("{}: published_roster is absent; run ingest_published_rosters.py "
                  "first, then re-run this".format(args.db))
            return 1

        before = has_table(connection, TABLE)
        print("{}: {} is {}".format(args.db, TABLE, "PRESENT" if before else "MISSING"))
        if before:
            rows = connection.execute("SELECT COUNT(*) FROM {}".format(TABLE)).fetchone()[0]
            print("  nothing to do; it holds {} rows".format(rows))
            return 0
        if not args.apply:
            print("  would create the table and its lookup index (dry run)")
            return 0

        # The DDL comes from the module that reads the table, so the two cannot drift.
        published_roster.ensure(connection)
        connection.commit()
        if not has_table(connection, TABLE):
            print("  FAILED: table still absent after ensure()")
            return 1
        indexes = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (TABLE,))]
        print("  created {}, indexes: {}".format(TABLE, ", ".join(indexes) or "none"))
        print("  it is EMPTY by design; ingest_published_rosters.py fills it")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
