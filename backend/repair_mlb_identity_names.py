#!/usr/bin/env python3
"""repair_mlb_identity_names.py -- repair MLB player names from the published mlbam_id map.

Why this exists
---------------
Before commit b03b9c9, backend/ingest_statcast.py resolved batter names like this:

    name = pitcher_id_to_name.get(batter_id)
    if not name:
        name = group["player_name"].dropna()
        name = name.iloc[0] if len(name) > 0 else None   # <- the first PITCHER faced

Statcast's `player_name` column is the **pitcher's** name on every pitch row, so a
pure batter fell through and inherited the name of whoever threw their first pitch.
`player_id` still came from `batter_id`, so the players row kept the correct
mlbam_id and acquired a stranger's name. On prod 223 rows (and 167 on dev) carry an
mlbam_id whose published name is a different person.

The repair is **id-first**: take the name MLB publishes for that mlbam_id. Never
match on a name -- name matching is what produced this corruption.

What this script does
---------------------
* Selects `id, name, mlbam_id` from `players` where `league='mlb'` and mlbam_id set.
* For each row whose `str(mlbam_id)` is in the published map and whose normalized
  name differs from the published one, sets `players.name = published` (verbatim,
  accents included) and updates the descriptive copies on `player_stats`
  (`player_name`, `name_norm`) for that same `player_id`.

What it never does
------------------
* Never writes `mlbam_id`. Not once, not as a fallback.
* Never inserts, deletes, or merges a row. Renaming may create rows that look like
  duplicates; that is expected and is the dedupe's problem, not this script's.
* An mlbam_id absent from the published map is `unknown`, not a defect -- left alone.

Default is a **dry run**; `--apply` commits. `--db` takes an absolute path.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit_league_stats import _identity_name_key  # noqa: E402
from _core import _normalize_name  # noqa: E402

MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "published-identity-names.json")

SELECT_PLAYERS = (
    "SELECT id, name, mlbam_id FROM players "
    "WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"
)


def load_published_names():
    with open(MAP_PATH) as f:
        artifact = json.load(f)
    return artifact["leagues"]["mlb"]["names"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True,
                    help="absolute path to the database (picks.db or picks.dev.db)")
    ap.add_argument("--apply", action="store_true",
                    help="commit the repair; default is a dry run")
    args = ap.parse_args()

    names = load_published_names()

    con = sqlite3.connect(args.db)
    try:
        rows = con.execute(SELECT_PLAYERS).fetchall()

        examined = 0
        not_in_map = 0
        already_correct = 0
        repairs = []  # (id, old_name, new_name, mlbam_id)

        for row_id, name, mlbam_id in rows:
            examined += 1
            published = names.get(str(mlbam_id))
            if published is None:
                not_in_map += 1
                continue
            if _identity_name_key(name) == _identity_name_key(published):
                already_correct += 1
                continue
            repairs.append((row_id, name, published, mlbam_id))

        print(f"rows examined           : {examined}")
        print(f"mlbam_id not in map     : {not_in_map} (left alone)")
        print(f"rows already correct    : {already_correct}")
        print(f"rows repaired           : {len(repairs)}")
        print("first 10 repairs (id / old name / new name / mlbam_id):")
        for row_id, old, new, mlbam_id in repairs[:10]:
            print(f"  {row_id} / {old} / {new} / {mlbam_id}")

        if repairs and args.apply:
            con.execute("BEGIN")
            for row_id, _old, published, _mlbam_id in repairs:
                con.execute("UPDATE players SET name=? WHERE id=?", (published, row_id))
                con.execute(
                    "UPDATE player_stats SET player_name=?, name_norm=? WHERE player_id=?",
                    (published, _normalize_name(published), row_id))
            con.commit()
            print(f"applied {len(repairs)} renames to players + player_stats")
        else:
            con.rollback()  # dry run: discard anything (nothing) staged
            if repairs:
                print("dry run -- nothing committed (use --apply to commit)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
