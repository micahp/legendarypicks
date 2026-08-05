"""Give `players` a column that says whether the row is a person.

`players` has always held two different kinds of thing. Most rows are humans.
Ninety-seven NFL rows are **fantasy constructs** -- 32 team defences, 32 head
coaches, and 32 "TQB" entities (an ESPN format where you draft a team's whole
quarterback production) -- plus one unresolved row literally named `?`.

Nothing declared the difference, so every consumer had to infer it, and none
did. On 2026-08-04 `roster_sync` blanket-set `active=0` for league `nfl`; a
D/ST is on no roster, so all 32 stayed inactive, and `ingest_nfl_adp.py` builds
its team map from `position='DEF' AND active=1`. Its fail-closed D/ST preflight
then aborted **every subsequent run**, which stopped `injury_status` and
`last_news_date` for all 6,486 NFL players. The production draft board showed
nobody as injured, three weeks before draft season, with no error anywhere.

ESPN itself never confuses the two. Fantasy constructs exist only in
`lm-api-reads.fantasy.espn.com` -- never in `sports.core.api.espn.com` -- and
it signs their ids **negative**. Measured 2026-08-05 on prod, that marker is a
perfect discriminator and we were already storing it:

    DEF   32 rows   negative espn_id = 32       QB   710 rows   negative = 0
    TQB   32 rows   negative espn_id = 32       WR  2614 rows   negative = 0
    HC    32 rows   negative espn_id = 32

So this migration invents nothing. It reads the sign we already have and
records the category the publisher already drew, once, at the boundary --
rather than asking every reader to remember that `position='DEF'` is not a
position and `HC` is not something a human plays.

Values:
  player         a human. Everything with a non-negative espn_id, and every
                 row in a league that has no fantasy constructs.
  team_defense   an entire team's defence (ESPN defaultPositionId 16)
  team_qb        a team's combined QB production (id 15)
  coach          a head coach (id 14)
  unknown        a negative-id entity we could not classify

Usage:
  cd backend && venv/bin/python migrate_player_entity_type.py \\
      --db /abs/path/picks.db [--apply]

Dry run by default. Idempotent: ADD COLUMN is skipped when present, and the
backfill only writes rows whose value would change.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(HERE, "data", "picks.db")

# ESPN's fantasy `defaultPositionId` -> our category, for the ids that are not
# people. Everything else is a person.
POSITION_TO_ENTITY = {
    "DEF": "team_defense",
    "TQB": "team_qb",
    "HC": "coach",
}


def classify(position, espn_id) -> str:
    """A negative ESPN id is the publisher saying 'this is not an athlete'."""
    try:
        negative = espn_id is not None and int(espn_id) < 0
    except (TypeError, ValueError):
        negative = False
    if not negative:
        return "player"
    return POSITION_TO_ENTITY.get((position or "").strip().upper(), "unknown")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"migrate_player_entity_type: no such database: {args.db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        present = {r[1] for r in con.execute("PRAGMA table_info(players)")}
        added = False
        if "entity_type" not in present:
            print("  + entity_type TEXT")
            if args.apply:
                con.execute("ALTER TABLE players ADD COLUMN entity_type TEXT")
                added = True
        else:
            print("  entity_type already present")

        if "entity_type" not in present and not args.apply:
            print("\ndry run -- would add the column and backfill. re-run with --apply")
            return 0

        changes: dict[str, int] = {}
        updates = []
        for row in con.execute(
                "SELECT id, position, espn_id, entity_type FROM players"):
            want = classify(row["position"], row["espn_id"])
            if row["entity_type"] != want:
                updates.append((want, row["id"]))
                changes[want] = changes.get(want, 0) + 1

        for value, count in sorted(changes.items(), key=lambda kv: -kv[1]):
            print(f"  {value:14s} {count}")
        print(f"rows to set: {len(updates)}")

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        con.executemany("UPDATE players SET entity_type=? WHERE id=?", updates)
        con.commit()
        print(f"\nset entity_type on {len(updates)} rows"
              f"{' (column added)' if added else ''}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
