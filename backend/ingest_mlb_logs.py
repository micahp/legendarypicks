#!/usr/bin/env python3
"""
ingest_mlb_logs.py — per-GAME MLB hitting logs derived from Statcast events.

The season-aggregate ingest (ingest_statcast.py) groups all pitches by batter.
This groups by (batter, game) instead, deriving a per-game box line from the
pitch-level `events` column: H, 2B, 3B, HR, BB, K, TB. These map directly to the
common MLB props (hits, total_bases, home_runs) and feed projections/form.

Usage: python3 ingest_mlb_logs.py [--days 60]
"""
import sys, os, json, sqlite3, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table  # reuse the shared schema

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

HIT_EVENTS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}  # event -> total bases


def ingest(days: int = 60) -> int:
    from pybaseball import statcast
    import pandas as pd

    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    print(f"Pulling Statcast {s}..{e} (per-game derive)...")
    data = statcast(s, e)
    if data is None or len(data) == 0:
        print("No Statcast data."); return 0

    bat = data[data["events"].notna()].copy()
    print(f"  {len(bat)} batted-ball/PA-ending events across {bat['game_pk'].nunique()} games")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    season = end.year

    mlbam_to_player = {
        r["mlbam_id"]: r["id"]
        for r in con.execute("SELECT mlbam_id, id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0")
    }

    ingested = 0
    for (batter, game_pk), g in bat.groupby(["batter", "game_pk"]):
        mlbam = int(batter)
        pid = mlbam_to_player.get(mlbam)
        ev = g["events"].value_counts().to_dict()
        h = sum(ev.get(k, 0) for k in HIT_EVENTS)
        tb = sum(ev.get(k, 0) * v for k, v in HIT_EVENTS.items())
        stats = {
            "H": int(h),
            "2B": int(ev.get("double", 0)),
            "3B": int(ev.get("triple", 0)),
            "HR": int(ev.get("home_run", 0)),
            "BB": int(ev.get("walk", 0)),
            "K": int(ev.get("strikeout", 0)),
            "TB": int(tb),
            "PA": int(len(g)),
        }
        gdate = str(g["game_date"].iloc[0])[:10]
        team = None
        opponent = None
        home_away = None
        # home/away team abbrevs exist as 'home_team'/'away_team'; batter's team = inferred via inning_topbot
        if "inning_topbot" in g.columns and "home_team" in g.columns and "away_team" in g.columns:
            top = (g["inning_topbot"].iloc[0] == "Top")  # away bats in top
            team = g["away_team"].iloc[0] if top else g["home_team"].iloc[0]
            opponent = g["home_team"].iloc[0] if top else g["away_team"].iloc[0]
            home_away = "away" if top else "home"
        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "mlb", season, gdate, str(int(game_pk)), gdate, team,
             opponent, home_away, json.dumps(stats), "statcast", str(mlbam)))
        ingested += 1

    con.commit()
    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='mlb' AND season=? AND player_id IS NOT NULL",
        (season,)).fetchone()[0]
    print(f"  Ingested {ingested} MLB game-logs ({resolved} spine-resolved)")
    con.close()
    return ingested


if __name__ == "__main__":
    days = 60
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    ingest(days)
