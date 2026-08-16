#!/usr/bin/env python3
"""One spelling per NFL position: K -> PK, SAF -> S.

`K` (kicker) and `PK` are the same position from two writers, and so are `SAF`
(safety) and `S`. A draft board filtering `position='K'` misses every kicker
the ADP ingest wrote as `PK` -- silently. The published spelling is what
ingest_nfl_adp.py stores (`_ESPN_POSITION`: 5 -> "PK", 13 -> "S") and what
team_codes.POSITION_ALIASES already normalises to at the roster_sync boundary,
so the writers are aligned and only historical rows carry the old codes.

Migrate the league entire or not at all: a half-migration leaves both
spellings live, which is the current state and worse than either alone.

Values written: players.position K -> PK, SAF -> S for league='nfl'. Rows are
NOT deleted.

Usage:
  cd backend && venv/bin/python migrate_nfl_position_spellings.py \\
      --db /abs/path/picks.db
  venv/bin/python migrate_nfl_position_spellings.py --db ... --apply

Dry run by default. Takes a VACUUM INTO backup before applying. Idempotent.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(HERE, "data", "picks.db")

SPELLINGS = {"K": "PK", "SAF": "S"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"migrate_nfl_position_spellings: no such database: {args.db}",
              file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        counts = {
            r[0]: r[1] for r in con.execute(
                "SELECT position, COUNT(*) FROM players WHERE league='nfl' "
                "AND position IN ('K','PK','SAF','S') GROUP BY position")
        }
        print(f"NFL position spellings: {counts}")
        for old, new in SPELLINGS.items():
            if old in counts:
                print(f"  {old} -> {new}: {counts[old]} rows")

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        if not any(old in counts for old in SPELLINGS):
            print("nothing to change -- already one spelling per position")
            return 0

        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup = f"{args.db}.pre-position-spelling-{stamp}"
        con.execute(f"VACUUM INTO '{backup.replace(chr(39), chr(39) * 2)}'")
        print(f"backup: {backup}")

        for old, new in SPELLINGS.items():
            con.execute(
                "UPDATE players SET position=? WHERE league='nfl' AND position=?",
                (new, old))
        con.commit()

        remaining = con.execute(
            "SELECT COUNT(*) FROM players WHERE league='nfl' "
            "AND position IN ('K','SAF')").fetchone()[0]
        print(f"applied: {counts.get('K', 0) + counts.get('SAF', 0)} rows "
              f"renormalised, {remaining} old spellings remain")
        return 0 if remaining == 0 else 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
