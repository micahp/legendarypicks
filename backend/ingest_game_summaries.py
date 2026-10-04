#!/usr/bin/env python3
"""Persist one completed ESPN summary for recently finished prop games."""
import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
from settlement.stored_summary import ensure_table


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
_SKIP_LEAGUES = ("atp", "wta", "wc", "mlb", "ufc")   # ufc: ESPN 404s every summary; settles from scoreboard rows


def _candidates(con: sqlite3.Connection):
    return con.execute("""
        SELECT pg.league, pg.espn_event_id
        FROM prop_games pg
        WHERE pg.espn_event_id IS NOT NULL
          AND trim(pg.espn_event_id) <> ''
          AND pg.league NOT IN (?,?,?,?)
          AND datetime(COALESCE(NULLIF(pg.start_time, ''), pg.date || 'T00:00:00Z'))
              BETWEEN datetime('now', '-72 hours') AND datetime('now')
          AND EXISTS (
              SELECT 1 FROM props p
              LEFT JOIN prop_results pr ON pr.prop_id=p.id
              WHERE p.game_id=pg.id AND pr.prop_id IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM game_summaries gs
              WHERE gs.league=pg.league
                AND gs.espn_event_id=pg.espn_event_id
          )
          AND 'post' = (
              SELECT ss.state
              FROM scoreboard_snapshots ss
              WHERE ss.league=pg.league
                AND ss.game_id=pg.espn_event_id
              ORDER BY ss.fetched_at DESC
              LIMIT 1
          )
        ORDER BY pg.league, pg.espn_event_id
    """, _SKIP_LEAGUES).fetchall()


def ingest(con: sqlite3.Connection) -> dict:
    ensure_table(con)
    candidates = _candidates(con)
    counts = {
        "candidates": len(candidates), "fetched": 0, "stored": 0,
        "not_final": 0, "failed": 0,
    }
    for league, event_id in candidates:
        try:
            payload = espn.summary(league, event_id)
            counts["fetched"] += 1
        except Exception as exc:
            counts["failed"] += 1
            print(f"game_summaries: FAILED {league} {event_id}: {exc}",
                  file=sys.stderr)
            continue
        competition = ((payload.get("header") or {}).get("competitions") or [{}])[0]
        status_type = ((competition.get("status") or {}).get("type") or {})
        state = status_type.get("state")
        completed = status_type.get("completed") is True
        if state != "post" or not completed:
            counts["not_final"] += 1
            continue
        con.execute(
            "INSERT OR IGNORE INTO game_summaries(league,espn_event_id,payload,"
            "state,completed,fetched_at,source) VALUES (?,?,?,?,?,?,?)",
            (league, str(event_id), json.dumps(payload), state, int(completed),
             dt.datetime.now(dt.timezone.utc).isoformat(), "espn_summary"),
        )
        con.commit()
        counts["stored"] += 1
    print("game_summaries: candidates={candidates} fetched={fetched} "
          "stored={stored} not_final={not_final} failed={failed}".format(**counts))
    return counts


def main():
    with espn.batch_pacing():
        con = sqlite3.connect(DB)
        try:
            return ingest(con)
        finally:
            con.close()


if __name__ == "__main__":
    main()
