#!/usr/bin/env python3
"""Repair the stored player-game rows damaged by the zero-target receiving gate.

Every 2026 regular-season player-week where nflverse publishes receiving yards or
a receiving touchdown with zero targets is a post-catch lateral: the NFL credits
the yards (and the score) to the player who ends the play, not the player who
caught the forward pass. The weekly ingester used to gate the whole receiving key
group on target volume, so those rows were written without rec_yds / rec_td.

This script re-reads the published artifact, finds every affected player-week in
the requested seasons, backs up the current stats JSON, and patches only the
receiving keys on those rows. It writes nothing else: no other key, row, season,
or table is touched, and it refuses to run if the artifact disagrees with the
count it expects.

Usage:
    python repair_lateral_receiving_rows.py --dry-run
    python repair_lateral_receiving_rows.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

import ingest_nfl_weekly_stats as ingester

SEASONS = (2025, 2026)
EXPECTED = {2025: 1, 2026: 2}
REC_KEYS = ("targets", "rec", "rec_yds", "rec_td", "rec_air_yds")


def find_cases(cache_dir):
    cases = []
    for season in SEASONS:
        path = ingester.fetch(season, cache_dir)
        rows = ingester.build_rows(path)
        by_key = {(r["gsis"], r["week"]): r for r in rows}
        import pandas as pd

        frame = pd.read_parquet(path)
        frame = frame[frame["season_type"] == "REG"] if "season_type" in frame else frame
        hits = frame[(frame["receiving_yards"].fillna(0) > 0) & (frame["targets"].fillna(0) == 0)]
        for row in hits.itertuples():
            key = (str(row.player_id), int(row.week))
            built = by_key.get(key)
            if built is None:
                raise SystemExit("published row missing from build: %r" % (key,))
            cases.append({
                "season": season, "gsis": key[0], "week": key[1],
                "name": row.player_display_name, "team": built["team"],
                "game_id": built["game_id"],
                "rec_yds": float(row.receiving_yards), "rec_td": float(row.receiving_tds),
                "built_stats": built["stats"],
            })
    got = {s: sum(1 for c in cases if c["season"] == s) for s in SEASONS}
    if got != EXPECTED:
        raise SystemExit("affected-case count changed: %r != %r (artifact updated?)" % (got, EXPECTED))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("/root/legendarypicks/backend/data/picks.dev.db"))
    ap.add_argument("--cache-dir", default="/root/.hermes/cache/scratch")
    ap.add_argument("--backup", type=Path, default=HERE / "lateral-row-repair-backup.json")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cases = find_cases(args.cache_dir)
    for case in cases:
        if not all(k in case["built_stats"] for k in ("rec_yds", "rec_td")):
            raise SystemExit("ingester still drops receiving keys for %r — patch the gate first"
                             % ((case["season"], case["name"], case["week"]),))

    con = sqlite3.connect(str(args.db))
    con.execute("BEGIN")
    backup, changes = [], []
    try:
        for case in cases:
            row = con.execute(
                "SELECT id, stats FROM player_game_logs WHERE league='nfl' AND season=? "
                "AND source_player_key=? AND game_no=? AND source=?",
                (case["season"], case["gsis"], str(case["week"]), ingester.SOURCE)).fetchone()
            if row is None:
                raise SystemExit("target row not found: %r" % ((case["season"], case["gsis"], case["week"]),))
            row_id, raw = row
            before = json.loads(raw)
            after = dict(before)
            after.update({k: case["built_stats"][k] for k in REC_KEYS if k in case["built_stats"]})
            backup.append({"id": row_id, "season": case["season"], "gsis": case["gsis"],
                           "week": case["week"], "name": case["name"], "stats_before": before})
            changes.append({
                "id": row_id, "name": case["name"], "season": case["season"], "week": case["week"],
                "before": {k: before.get(k) for k in ("targets", "rec", "rec_yds", "rec_td")},
                "after": {k: after.get(k) for k in ("targets", "rec", "rec_yds", "rec_td")},
                "other_keys_changed": sorted(set(after) ^ set(before)),
            })
            if args.apply:
                con.execute("UPDATE player_game_logs SET stats=? WHERE id=?", (json.dumps(after), row_id))
        print(json.dumps(changes, indent=2, sort_keys=True))
        if args.apply:
            con.commit()
            args.backup.write_text(json.dumps(backup, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("applied; backup written to %s" % args.backup)
        else:
            con.rollback()
            print("dry run: nothing written")
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
