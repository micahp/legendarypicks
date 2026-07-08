#!/usr/bin/env python3
"""
ingest_team_results.py — season-to-date team game results via ESPN team schedules.

One schedule call per team (~30 for MLB) yields every completed game with final
scores — the team-level series (runs for/against, result) that the momentum
engine needs and that no existing table holds (team_game_stats is box-stat
snapshots, prop_games has no finals).

Usage: python3 ingest_team_results.py [--league mlb]
"""
import sys, os, json, sqlite3, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_client import LEAGUES, _get

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS team_game_results(
        league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
        game_date TEXT, opponent TEXT, home_away TEXT,
        score_for REAL, score_against REAL, win INTEGER,
        ingested_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY(league, game_id, team))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tgr_team ON team_game_results(league, team, game_date)")


def ingest(league: str = "mlb") -> int:
    path = LEAGUES[league][0]
    teams_doc = _get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams", ttl=3600)
    abbrevs = [t["team"]["abbreviation"].lower()
               for t in teams_doc["sports"][0]["leagues"][0]["teams"]]
    con = sqlite3.connect(DB)
    ensure_table(con)
    wrote = 0
    for ab in abbrevs:
        try:
            sched = _get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{ab}/schedule", ttl=600)
        except Exception as e:
            print(f"  {ab}: schedule fetch failed ({e})"); continue
        for ev in sched.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            comps = comp.get("competitors", [])
            if len(comps) != 2:
                continue
            mine = next((c for c in comps if c["team"]["abbreviation"].lower() == ab), None)
            theirs = next((c for c in comps if c is not mine), None)
            if not mine or not theirs:
                continue
            sf = (mine.get("score") or {}).get("value")
            sa = (theirs.get("score") or {}).get("value")
            if sf is None or sa is None:
                continue
            win = mine.get("winner")
            con.execute("""INSERT OR REPLACE INTO team_game_results
                (league, game_id, team, game_date, opponent, home_away, score_for, score_against, win)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (league, str(ev.get("id")), mine["team"]["abbreviation"],
                 (ev.get("date") or "")[:10], theirs["team"]["abbreviation"],
                 mine.get("homeAway"), float(sf), float(sa),
                 1 if win is True else 0 if win is False else None))
            wrote += 1
        con.commit()
    con.close()
    print(f"{league}: wrote {wrote} team-game rows across {len(abbrevs)} teams")
    return wrote


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    args = ap.parse_args()
    ingest(args.league)
