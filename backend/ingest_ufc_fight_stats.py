#!/usr/bin/env python3
"""
ingest_ufc_fight_stats.py — per-fight UFC player game logs from ESPN's
per-competitor statistics endpoint.

One row per completed fight per fighter into player_game_logs, sourced from
{competition_ref}/competitors/{competitor_id}/statistics?lang=en&region=us.

Usage: python3 ingest_ufc_fight_stats.py
  LP_DB_PATH=/path/to/picks.dev.db  (required env)
  --limit N   cap fights per fighter (default 5, matches ufc_fight_history)
  --dry-run   fetch and print but don't write
"""
import argparse
import json
import os
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_client import ufc_athlete, ufc_fight_history, _get, _SPORTS_CORE

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

# ESPN stats endpoint URL template.
_STATS_URL = (
    _SPORTS_CORE.format(sport="mma")
    + "/leagues/ufc/events/{event_id}/competitions/{fight_id}"
    + "/competitors/{competitor_id}/statistics?lang=en&region=us"
)


def ensure_table(con: sqlite3.Connection) -> None:
    """Create player_game_logs if not present (idempotent, same schema as NFL)."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS player_game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id         INTEGER,
            league            TEXT NOT NULL,
            season            INTEGER NOT NULL,
            game_no           TEXT,
            game_id           TEXT,
            game_date         TEXT,
            team              TEXT,
            opponent          TEXT,
            home_away         TEXT,
            stats             TEXT NOT NULL,
            source            TEXT,
            source_player_key TEXT,
            ingested_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(league, source_player_key, season, game_no)
        )""")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pgl_player "
        "ON player_game_logs(player_id, league, season, game_no)"
    )
    con.commit()


def fetch_stats(event_id: str, fight_id: str, competitor_id: str) -> dict:
    """Fetch per-fight statistics from ESPN, return the raw stats dict.
    Returns empty dict on any fetch failure (404, timeout, etc.)."""
    url = _STATS_URL.format(
        event_id=event_id, fight_id=fight_id, competitor_id=competitor_id
    )
    try:
        data = _get(url, ttl=21600)
    except Exception:
        return {}
    # Navigate: splits.categories[0].stats -> [{name, value}, ...]
    categories = (data.get("splits") or {}).get("categories") or []
    if not categories:
        return {}
    stats_list = categories[0].get("stats") or []
    return {item["name"]: item.get("value") for item in stats_list if "name" in item}


def resolve_fighter_id(name: str) -> Optional[str]:
    """Resolve a fighter name to ESPN athlete ID via ufc_athlete()."""
    result = ufc_athlete(name)
    return result["id"] if result else None


def ingest_fighter(
    con: sqlite3.Connection,
    player_id: int,
    name: str,
    espn_id: Optional[str],
    limit: int,
    dry_run: bool,
) -> int:
    """Ingest fight stats for one fighter. Returns number of new rows written."""
    if espn_id:
        athlete_id = espn_id
    else:
        athlete_id = resolve_fighter_id(name)
        if not athlete_id:
            print(f"  SKIP {name} (id={player_id}): could not resolve ESPN athlete ID")
            return 0
        print(f"  resolved {name} → ESPN {athlete_id}")

    try:
        fights = ufc_fight_history(athlete_id, limit=limit)
    except Exception:
        print(f"  {name}: ESPN API error fetching fight history for athlete {athlete_id}")
        return 0
    if not fights:
        print(f"  {name}: no completed fights in history")
        return 0

    written = 0
    for f in fights:
        stats = fetch_stats(f["event_id"], f["fight_id"], athlete_id)
        if not stats:
            print(f"  {name}: no stats for {f['date']} vs {f['opponent']} (fight_id={f['fight_id']})")
            continue

        # Add fight metadata into stats blob
        stats["result"] = f["result"]
        stats["method"] = f["method"]

        date_str = f["date"]
        season = int(date_str[:4]) if date_str and len(date_str) >= 4 else 0
        # game_no: use date as a stable sequence key
        game_no = date_str

        if dry_run:
            print(f"  DRY-RUN {name} vs {f['opponent']} ({date_str}): "
                  f"{len(stats)} stats, result={f['result']}, method={f['method']}")
            written += 1
            continue

        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date,
                team, opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                player_id,
                "ufc",
                season,
                game_no,
                f["fight_id"],
                date_str,
                None,               # team — N/A for UFC
                f["opponent"],
                None,               # home_away — N/A, result is in stats JSON
                json.dumps(stats),
                "espn_mma_stats",
                athlete_id,
            ),
        )
        written += 1

    if not dry_run:
        con.commit()
    return written


def main():
    parser = argparse.ArgumentParser(description="Ingest UFC per-fight stats into player_game_logs")
    parser.add_argument("--limit", type=int, default=5, help="Max fights per fighter (default 5)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, don't write")
    args = parser.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)

    rows = con.execute(
        "SELECT id, name, espn_id FROM players WHERE league='ufc' ORDER BY name"
    ).fetchall()

    print(f"Found {len(rows)} UFC fighters in players table")
    total = 0
    for r in rows:
        pid, name, espn_id = r["id"], r["name"], r["espn_id"]
        n = ingest_fighter(con, pid, name, espn_id, args.limit, args.dry_run)
        if n:
            print(f"  {name}: {n} fights {'(dry-run)' if args.dry_run else 'written'}")
        total += n

    suffix = " (dry-run, nothing written)" if args.dry_run else ""
    print(f"\nDone. {total} total fight rows{suffix}")

    if not args.dry_run:
        count = con.execute(
            "SELECT COUNT(*) FROM player_game_logs WHERE league='ufc'"
        ).fetchone()[0]
        print(f"player_game_logs WHERE league='ufc': {count} rows")

    con.close()


if __name__ == "__main__":
    main()
