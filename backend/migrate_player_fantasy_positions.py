#!/usr/bin/env python3
"""Remove fantasy slots from `players.position`.

`players` holds two kinds of thing: humans and fantasy constructs (32 team
defences, 32 TQB entities, 32 head coaches). ESPN's fantasy API is the only
place constructs exist and it signs their ids negative, so `entity_type`
records the category at the ingest boundary (migrate_player_entity_type.py).

A team defence plays no position. `position` is a CURRENT ROSTER SPOT, and
'DEF' sitting in that column beside real defensive positions is how check C
read 'CB under DEF, DE under DEF, ...' as a vocabulary clash -- two levels of
one vocabulary that never join. The fantasy label already lives where it
belongs: `nfl_adp.position` holds 'DEF'/'TQB'/'HC' per player per season, and
the pool endpoint composes its contract from that table. This migration NULLs
`players.position` for the 96 construct rows; every reader that needs the
fantasy label reads `nfl_adp` or `entity_type`.

Values written: position -> NULL for league='nfl' rows whose entity_type is
team_defense / team_qb / coach. Rows are NOT deleted -- they are real
draftable entities with ids, names and teams.

Usage:
  cd backend && venv/bin/python migrate_player_fantasy_positions.py \\
      --db /abs/path/picks.db
  venv/bin/python migrate_player_fantasy_positions.py --db ... --apply

Dry run by default. Takes a VACUUM INTO backup before applying (never `cp` --
a plain copy of a live database races writers and produces a torn snapshot,
proved 2026-08-05). Idempotent: re-running finds nothing to NULL.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(HERE, "data", "picks.db")

# The three fantasy constructs, as migrate_player_entity_type.py classifies them.
FANTASY_TYPES = ("team_defense", "team_qb", "coach")
EXPECTED_TOTAL = 96  # 32 of each


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="apply even when the construct count differs from "
                         f"the expected {EXPECTED_TOTAL}")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"migrate_player_fantasy_positions: no such database: {args.db}",
              file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(players)")}
        if "entity_type" not in cols:
            print("migrate_player_fantasy_positions: players has no entity_type "
                  "column -- run migrate_player_entity_type.py first; without it "
                  "the classification is not trustworthy", file=sys.stderr)
            return 2

        counts = {
            r[0]: r[1] for r in con.execute(
                f"SELECT entity_type, COUNT(*) FROM players WHERE league='nfl' "
                f"AND entity_type IN ({','.join('?' for _ in FANTASY_TYPES)}) "
                "GROUP BY entity_type", FANTASY_TYPES)
        }
        total = sum(counts.values())
        print(f"NFL fantasy constructs: {total} rows {dict(counts)}")
        if not args.force and (
                total != EXPECTED_TOTAL
                or any(counts.get(t) != 32 for t in FANTASY_TYPES)):
            print(f"expected exactly 32 of each of {', '.join(FANTASY_TYPES)} "
                  f"({EXPECTED_TOTAL} rows), found {dict(counts)} -- the spine is "
                  "not in the shape this migration was written for; refusing "
                  "(--force to override)", file=sys.stderr)
            return 2

        affected = con.execute(
            f"SELECT id, name, position, entity_type FROM players "
            f"WHERE league='nfl' AND entity_type IN ({','.join('?' for _ in FANTASY_TYPES)}) "
            "AND position IS NOT NULL AND TRIM(position) != '' "
            "ORDER BY entity_type, name", FANTASY_TYPES).fetchall()
        print(f"{len(affected)} construct rows currently carry a position "
              "(would be NULLed):")
        for row_id, name, position, entity_type in affected[:10]:
            print(f"  id={row_id} {name!r} {position!r} ({entity_type})")
        if len(affected) > 10:
            print(f"  ... and {len(affected) - 10} more")

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        if not affected:
            print("nothing to change -- already migrated")
            return 0

        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup = f"{args.db}.pre-fantasy-null-{stamp}"
        con.execute(f"VACUUM INTO '{backup.replace(chr(39), chr(39) * 2)}'")
        print(f"backup: {backup}")

        con.execute(
            f"UPDATE players SET position=NULL WHERE league='nfl' "
            f"AND entity_type IN ({','.join('?' for _ in FANTASY_TYPES)}) "
            "AND position IS NOT NULL AND TRIM(position) != ''", FANTASY_TYPES)
        con.commit()

        remaining = con.execute(
            f"SELECT COUNT(*) FROM players WHERE league='nfl' "
            f"AND entity_type IN ({','.join('?' for _ in FANTASY_TYPES)}) "
            "AND position IS NOT NULL AND TRIM(position) != ''",
            FANTASY_TYPES).fetchone()[0]
        print(f"applied: {len(affected)} rows updated, {remaining} construct "
              "rows still carry a position")
        return 0 if remaining == 0 else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
