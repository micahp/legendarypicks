#!/usr/bin/env python3
"""
ingest_nfl_adp.py — fetch real ESPN fantasy ADP for the 2026 draft season.

Source: ESPN's public fantasy API (same unauthenticated family as roster_sync).
Join: players.espn_id = feed.id (already populated by roster_sync.py for NFL).
Writes one row per (player_id, season) into nfl_adp — refreshable snapshot.

Usage: python3 ingest_nfl_adp.py
"""
import json
import os
import sqlite3
import sys
import urllib.request

URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players"
       "?scoringPeriodId=0&view=kona_player_info")
HEADERS = {
    "x-fantasy-filter": json.dumps({
        "players": {
            "filterSlotIds": {"value": [0]},
            "limit": 3000,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"},
        }
    }),
}
SEASON = 2026

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def _fetch_page(offset: int) -> list:
    """Fetch one page of players from ESPN's ADP API."""
    hdrs = dict(HEADERS)
    hdrs["x-fantasy-filter"] = json.dumps({
        "players": {
            "filterSlotIds": {"value": [0]},
            "limit": 3000,
            "offset": offset,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"},
        }
    })
    req = urllib.request.Request(URL, headers=hdrs)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8")
    return json.loads(body)


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Build espn_id → player_id lookup from players table (NFL only, with espn_id)
    eid_to_pid = {}
    for r in con.execute(
        "SELECT id, espn_id FROM players WHERE league='nfl' AND espn_id IS NOT NULL AND espn_id != 0"
    ):
        eid_to_pid[str(r["espn_id"])] = r["id"]
    print(f"NFL players with espn_id: {len(eid_to_pid)}")

    # Create table
    con.execute(
        """CREATE TABLE IF NOT EXISTS nfl_adp (
            player_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            espn_player_id INTEGER NOT NULL,
            adp REAL,
            percent_owned REAL,
            percent_started REAL,
            espn_ppr_rank INTEGER,
            espn_standard_rank INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (player_id, season)
        )"""
    )
    con.commit()

    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    total_fetched = 0
    total_matched = 0
    total_unmatched = 0
    non_null_adp = 0
    unmatched_samples = []
    offset = 0
    page_num = 1
    seen_espn_ids = set()

    while True:
        print(f"  Fetching page {page_num} (offset {offset})...")
        page = _fetch_page(offset)
        if not page:
            break
        total_fetched += len(page)

        page_ids = {str(p.get("id", "")) for p in page}
        if page_ids and page_ids <= seen_espn_ids:
            # ESPN's API ignores `limit`/`offset` on this endpoint and just
            # returns the whole player pool every call — no new ids means
            # pagination isn't actually advancing, so stop instead of
            # looping forever re-fetching the same set.
            print("    no new espn ids vs previous page(s) — pagination isn't advancing, stopping")
            break
        seen_espn_ids |= page_ids

        for p in page:
            eid = str(p.get("id", ""))
            pid = eid_to_pid.get(eid)
            if pid is None:
                total_unmatched += 1
                if len(unmatched_samples) < 5:
                    unmatched_samples.append(f"{p.get('fullName','?')} (espn_id={eid})")
                continue

            ownership = p.get("ownership", {}) or {}
            adp = ownership.get("averageDraftPosition")
            pct_owned = ownership.get("percentOwned")
            pct_started = ownership.get("percentStarted")

            ranks = p.get("draftRanksByRankType", {}) or {}
            ppr = ranks.get("PPR", {}) or {}
            std = ranks.get("STANDARD", {}) or {}
            ppr_rank = ppr.get("rank")
            std_rank = std.get("rank")

            if adp is not None:
                non_null_adp += 1

            con.execute(
                """INSERT OR REPLACE INTO nfl_adp
                   (player_id, season, espn_player_id, adp, percent_owned,
                    percent_started, espn_ppr_rank, espn_standard_rank, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pid, SEASON, int(eid), adp, pct_owned, pct_started,
                 ppr_rank, std_rank, now),
            )
            total_matched += 1

        con.commit()
        print(f"    page {page_num}: {len(page)} fetched, {total_matched} matched so far")

        if len(page) < 3000:
            break
        offset += 3000
        page_num += 1

    # Verify
    row = con.execute(
        "SELECT COUNT(*) as n, COUNT(adp) as with_adp FROM nfl_adp WHERE season=?",
        (SEASON,),
    ).fetchone()
    print(f"\nIngested: {row['n']} rows ({row['with_adp']} with non-null ADP)")
    print(f"Matched (by espn_id): {total_matched}")
    print(f"Unmatched (no matching espn_id): {total_unmatched}")
    if unmatched_samples:
        print(f"  Sample unmatched: {unmatched_samples}")

    # Show top 10 by ADP
    top = con.execute(
        """SELECT na.adp, na.percent_owned, p.name, p.team, p.position
           FROM nfl_adp na JOIN players p ON p.id=na.player_id
           WHERE na.season=? AND na.adp IS NOT NULL
           ORDER BY na.adp ASC LIMIT 10""",
        (SEASON,),
    ).fetchall()
    print("\nTop 10 by ADP:")
    for t in top:
        print(f"  {t['adp']:7.1f}  {t['name']:25s} {t['position']:3s} {t['team']:4s}  owned {t['percent_owned']:.1f}%")

    con.close()


if __name__ == "__main__":
    main()
