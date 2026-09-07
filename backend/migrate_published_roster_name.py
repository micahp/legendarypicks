"""One-shot: bring a database up to the `published_roster` schema v0.9.3 reads.

Three additive changes, all of them `published_roster.ensure()`'s own:

    published_roster_name           new table, every spelling a publisher prints
    published_roster.team_code      new column
    published_roster.player_id      new column, the canonical identity binding

`published_roster.lookup_player` reads the names table to find every spelling a publisher
prints for one of its own people, and `player_id` is where roster publication records the
canonical person, which is what lets the request path resolve without minting anything. mlssoccer.com displays "Jake Davis" and files him at
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

Additive and idempotent: a `CREATE TABLE IF NOT EXISTS` and two `ADD COLUMN`s, no
existing row read or written. Safe to re-run, and it must be run on BOTH databases: the
first version of this returned early when the names table was already present, which
skipped the column check and left dev behind prod.

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

        # Every check runs every time. Reporting "present" for one of the three and
        # returning is how the first run of this left dev two columns behind prod.
        missing = []
        if not has_table(connection, TABLE):
            missing.append("table " + TABLE)
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(published_roster)")}
        missing.extend("published_roster." + c
                       for c in ("team_code", "player_id") if c not in columns)
        print("{}: {}".format(args.db,
                              "missing " + ", ".join(missing) if missing
                              else "already at the v0.9.3 schema"))
        if not missing:
            return 0
        if not args.apply:
            print("  would add the above (dry run)")
            return 0

        # The DDL comes from the module that reads it, so the two cannot drift.
        published_roster.ensure(connection)
        connection.commit()
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(published_roster)")}
        still = ([] if has_table(connection, TABLE) else ["table " + TABLE])
        still += ["published_roster." + c
                  for c in ("team_code", "player_id") if c not in columns]
        if still:
            print("  FAILED: still missing {}".format(", ".join(still)))
            return 1
        print("  added {}".format(", ".join(missing)))
        print("  {} is EMPTY by design; ingest_published_rosters.py fills it".format(TABLE))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
