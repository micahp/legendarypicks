#!/usr/bin/env python3
"""
ingest_nhl_logs.py — per-GAME NHL logs from api-web.nhle.com game-log endpoint.

The season-aggregate ingest (ingest_nhl.py) uses the /landing seasonTotals
endpoint. This uses /v1/player/{id}/game-log/{season}/2 which returns one row
per game — goals, assists, points, shots, PP points, TOI, opponent.

Usage: python3 ingest_nhl_logs.py [--season 20252026] [--limit N]
"""
import sys, os, json, sqlite3, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HDR = {"User-Agent": "Mozilla/5.0 (legendarypicks ingest)"}
STAT_KEYS = ["goals", "assists", "points", "shots", "plusMinus", "powerPlayGoals",
             "powerPlayPoints", "shorthandedPoints", "pim", "toi"]


def fetch_game_log(nhl_id: int, season: str):
    url = f"https://api-web.nhle.com/v1/player/{nhl_id}/game-log/{season}/2"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=12) as r:
            return json.loads(r.read()).get("gameLog", [])
    except Exception:
        return []


def ingest(season: str = "20252026", limit: int = 0) -> int:
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)

    players = con.execute(
        "SELECT id, name, nhl_id FROM players WHERE league='nhl' AND nhl_id IS NOT NULL ORDER BY id").fetchall()
    if limit:
        players = players[:limit]
    print(f"NHL game-logs {season}: {len(players)} players to pull")

    season_int = int(season)
    ingested = 0
    for i, p in enumerate(players):
        log = fetch_game_log(p["nhl_id"], season)
        for g in log:
            stats = {}
            for k in STAT_KEYS:
                v = g.get(k)
                if v is not None:
                    stats[k] = v
            con.execute(
                """INSERT OR REPLACE INTO player_game_logs
                   (player_id, league, season, game_no, game_id, game_date, team,
                    opponent, home_away, stats, source, source_player_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (p["id"], "nhl", season_int, str(g.get("gameId")), str(g.get("gameId")),
                 g.get("gameDate"), g.get("teamAbbrev"), g.get("opponentAbbrev"),
                 "home" if g.get("homeRoadFlag") == "H" else "away",
                 json.dumps(stats), "nhle.com", str(p["nhl_id"])))
            ingested += 1
        if (i + 1) % 50 == 0:
            con.commit(); print(f"  {i+1}/{len(players)} players, {ingested} logs")
        time.sleep(0.05)

    con.commit()
    print(f"  Ingested {ingested} NHL game-logs")
    con.close()
    return ingested


if __name__ == "__main__":
    season = "20252026"
    if "--season" in sys.argv:
        season = sys.argv[sys.argv.index("--season") + 1]
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    ingest(season, limit)
