#!/usr/bin/env python3
"""Backfill scoring events for explicitly named MLS/NCAAF games.

The game-id list is required so an operator must size the ESPN request count.
Dry-run is the default; ``--apply`` writes only play identities not already in
``scoring_plays``.
"""
import argparse
import datetime as dt
import os
import sqlite3

import espn_client as espn
from core_snapshots import _extract_scoring_plays


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def backfill(con: sqlite3.Connection, league: str, game_id: str,
             summary: dict, apply: bool = False) -> dict:
    plays = _extract_scoring_plays(league, game_id, summary)
    existing = {
        row[0] for row in con.execute(
            "SELECT play_id FROM scoring_plays WHERE league=? AND game_id=?",
            (league, str(game_id)),
        )
    }
    new = [play for play in plays if play["play_id"] not in existing]
    if apply and new:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.executemany(
            "INSERT INTO scoring_plays(league,game_id,play_id,captured_at,period,"
            "period_disp,clock,away_score,home_score,team_abbrev,scorer_name,"
            "play_text,play_type) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(league, str(game_id), play["play_id"], now, play["period"],
              play["period_disp"], play["clock"], play["away_score"],
              play["home_score"], play["team_abbrev"], play["scorer_name"],
              play["play_text"], play["play_type"]) for play in new],
        )
        con.commit()
    return {"published": len(plays), "existing": len(existing),
            "new": len(new), "written": len(new) if apply else 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", required=True, choices=("mls", "ncaaf"))
    parser.add_argument("--game-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    game_ids = list(dict.fromkeys(args.game_id))
    print(f"Scoring-play backfill [{args.league}] — {len(game_ids)} summary requests")
    if len(game_ids) > 50:
        print("REFUSED: scope the run to at most 50 explicit game ids")
        return 2
    con = sqlite3.connect(DB)
    total = 0
    with espn.batch_pacing():
        for game_id in game_ids:
            summary = espn.summary(args.league, game_id)
            result = backfill(con, args.league, game_id, summary, apply=args.apply)
            total += result["written"]
            print(f"  {game_id}: {result}")
    con.close()
    print(f"  total_written: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
