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

Why this no longer classifies from `position` (2026-08-17)
----------------------------------------------------------
The first version read `players.position`, because on 2026-08-05 the constructs
still carried 'DEF'/'TQB'/'HC' there. They do not any more, and the reason is
this repo: `migrate_player_fantasy_positions.py` moved those labels out of
`players.position` into `nfl_adp.position`, and it selects the rows to blank
BY `entity_type`. So the two migrations were mutually destructive and
order-dependent -- run fantasy_positions, then re-run this one, and all 96
constructs are reclassified `unknown` because the column it reads is now empty
by design.

That is not hypothetical. It is what prod and dev were in this morning, and it
is why `ingest_nfl_adp.py` had been failing every run since ~04:10 with
`D/ST preflight: def_to_pid has 0 entries, expected 32`: that map is built
`WHERE entity_type='team_defense'`, which matched nothing.

So classify from the publisher's own encoding instead. ESPN's fantasy-football
constructs are `-BASE - proTeamId`, a fact the feed states rather than one we
derive, and no migration in this repo can empty it:

    -16001..-16034   team_defense   (defaultPositionId 16)
    -15001..-15034   team_qb        (15)
    -14001..-14034   coach          (14)

`position` remains a fallback for a database migrated in the other order, where
the labels are still in place and the ids may not be.

Second guard, independent of the first: this never downgrades a row that
already carries a known category to `unknown`. Losing a classification must
take an explicit decision, not a re-run.
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


# ESPN's fantasy-football construct ids are `-BASE - proTeamId`. The base is
# the category; only NFL has these, so `league` gates it -- two NCAAF team rows
# (-15591 CCU, -14550 FIU) sit inside the same numeric window and are not
# fantasy constructs.
ID_BASE_TO_ENTITY = {
    -16000: "team_defense",
    -15000: "team_qb",
    -14000: "coach",
}

# A category, once recorded, is not taken away by a re-run. Only these may be
# overwritten by a classification.
_UNSET = (None, "", "unknown")


def classify(position, espn_id, league=None) -> str:
    """A negative ESPN id is the publisher saying 'this is not an athlete'.

    Which construct it is comes from the id's base, not from `position` --
    see the module docstring for what reading `position` cost. `position`
    stays as the fallback for a database where the labels survive.
    """
    try:
        negative = espn_id is not None and int(espn_id) < 0
    except (TypeError, ValueError):
        negative = False
    if not negative:
        return "player"
    if (league or "").strip().lower() == "nfl":
        magnitude = -int(espn_id)
        base, offset = -(magnitude // 1000) * 1000, magnitude % 1000
        # offset 0 would be the bare base, which is no team at all.
        if offset and base in ID_BASE_TO_ENTITY:
            return ID_BASE_TO_ENTITY[base]
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
        kept = 0
        for row in con.execute(
                "SELECT id, position, espn_id, entity_type, league FROM players"):
            want = classify(row["position"], row["espn_id"], row["league"])
            if row["entity_type"] == want:
                continue
            if want == "unknown" and row["entity_type"] not in _UNSET:
                # Never downgrade. A row already classified stays classified;
                # this run simply has less to go on than the one that set it.
                kept += 1
                continue
            updates.append((want, row["id"]))
            changes[want] = changes.get(want, 0) + 1

        for value, count in sorted(changes.items(), key=lambda kv: -kv[1]):
            print(f"  {value:14s} {count}")
        print(f"rows to set: {len(updates)}")
        if kept:
            print(f"rows left alone: {kept} already classified, would have "
                  f"become 'unknown' (never downgrade)")

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
