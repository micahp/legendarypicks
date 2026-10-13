#!/usr/bin/env python3
"""Undo the FotMob merge: an ESPN row must contain only ESPN's own fields.

`ingest_fotmob_soccer_logs` originally merged its stats INTO the existing ESPN
row, one row per appearance. That leaves a row stamped `source='espn'` carrying
FotMob-sourced tackles, so the column names the row's creator rather than each
field's origin -- and anyone auditing it later concludes ESPN publishes tackles,
which is the exact false belief this work existed to correct.

Providers now keep separate rows. This strips the merged-in keys back out.
Reversible in the sense that re-running the FotMob ingest rewrites them as its
own rows; nothing ESPN published is touched.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import time

# Everything ingest_soccer_logs writes. A key outside this set on an
# `espn` row did not come from ESPN.
ESPN_KEYS = {
    "goals", "assists", "shots", "sot", "yellow_cards", "red_cards",
    "fouls_committed", "fouls_suffered", "offsides", "own_goals", "saves",
    "shots_faced", "goals_conceded", "appearances", "sub_ins", "first_goal",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    # SOCCER ONLY. ESPN_KEYS is the soccer vocabulary, and `source='espn'`
    # spans every league we ingest: an unscoped run would have stripped PTS,
    # REB, AST and FGM from 28,731 NBA rows, because none of those are soccer
    # keys. Measured before applying, which is the only reason it did not.
    LEAGUES = ("ligamx", "lcup", "mls")
    rows = con.execute(
        "SELECT id, stats FROM player_game_logs WHERE source='espn'"
        " AND league IN ({})".format(",".join("?" * len(LEAGUES))),
        LEAGUES).fetchall()

    dirty = []
    stripped_keys = {}
    for row_id, raw in rows:
        try:
            stats = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        extra = [k for k in stats if k not in ESPN_KEYS]
        if not extra:
            continue
        for key in extra:
            stripped_keys[key] = stripped_keys.get(key, 0) + 1
        dirty.append((row_id, {k: v for k, v in stats.items() if k in ESPN_KEYS}))

    print(f"{args.db}")
    print(f"  espn SOCCER rows: {len(rows)}   carrying non-ESPN keys: {len(dirty)}")
    for key, n in sorted(stripped_keys.items(), key=lambda kv: -kv[1]):
        print(f"    {key:18s} {n}")

    if not args.apply:
        print("  check only -- nothing written.")
        return 0
    if not dirty:
        print("  nothing to do.")
        return 0

    backup = f"{args.db}.pre-unmerge-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.bak"
    shutil.copy2(args.db, backup)
    check = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={check})")
    if check != "ok":
        raise SystemExit("backup failed its integrity check; refusing to write")

    con.executemany("UPDATE player_game_logs SET stats=? WHERE id=?",
                    [(json.dumps(s), i) for i, s in dirty])
    con.commit()
    left = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE source='espn'"
        " AND league IN ('ligamx','lcup','mls')"
        " AND (json_extract(stats,'$.tackles') IS NOT NULL"
        "   OR json_extract(stats,'$.passes') IS NOT NULL"
        "   OR json_extract(stats,'$.dribbles') IS NOT NULL)").fetchone()[0]
    print(f"  cleaned {len(dirty)} rows; espn rows still carrying fotmob keys: {left}")
    if left:
        raise SystemExit("rows remain dirty; investigate before continuing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
