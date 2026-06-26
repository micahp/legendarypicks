#!/usr/bin/env python3
"""
ingest_nba_logs.py — per-GAME NBA logs from ESPN box scores.

hoopR-data's parquet mirror dead-ends at season 2023, so current NBA per-game
data comes from ESPN (same source as espn_client elsewhere). Iterates a date
range, pulls each final game's box score, parses player lines into
player_game_logs. Maps ESPN athlete id -> players.espn_id (spine).

Usage: python3 ingest_nba_logs.py --start 2026-04-01 --end 2026-04-12
"""
import sys, os, json, sqlite3, time, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from ingest_nfl_logs import ensure_table

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _madeatt(s):
    """'3-5' -> (3,5). Returns (made, att)."""
    try:
        m, a = s.split("-"); return int(m), int(a)
    except Exception:
        return None, None


def _parse_line(names, stats):
    d = dict(zip(names, stats))
    def num(k):
        try: return int(d.get(k, "")) if d.get(k, "").lstrip("-+").isdigit() else None
        except Exception: return None
    fg3m, _ = _madeatt(d.get("3PT", ""))
    fgm, fga = _madeatt(d.get("FG", ""))
    ftm, fta = _madeatt(d.get("FT", ""))
    pts, reb, ast = num("PTS"), num("REB"), num("AST")
    line = {"PTS": pts, "REB": reb, "AST": ast, "STL": num("STL"), "BLK": num("BLK"),
            "TO": num("TO"), "MIN": num("MIN"), "3PM": fg3m,
            "FGM": fgm, "FGA": fga, "FTM": ftm, "FTA": fta}
    if None not in (pts, reb, ast):
        line["PRA"] = pts + reb + ast
    return {k: v for k, v in line.items() if v is not None}


def ingest(start: str, end: str, season: int = 2026) -> int:
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    espn_to_player = {
        str(r["espn_id"]): r["id"]
        for r in con.execute("SELECT id, espn_id FROM players WHERE league='nba' AND espn_id IS NOT NULL")
    }

    d0 = dt.datetime.strptime(start, "%Y-%m-%d").date()
    d1 = dt.datetime.strptime(end, "%Y-%m-%d").date()
    ingested = 0; resolved = 0; added = 0
    day = d0
    while day <= d1:
        ds = day.strftime("%Y-%m-%d")
        try:
            games = [g for g in espn.games("nba", ds) if g.get("state") == "post"]
        except Exception:
            games = []
        for g in games:
            gid = g["game_id"]
            try:
                bx = espn.boxscore("nba", gid)
            except Exception:
                continue
            for blk in bx.get("players", []):
                team = (blk.get("team") or {}).get("abbreviation")
                for st in blk.get("statistics", []):
                    names = st.get("names", [])
                    for a in st.get("athletes", []):
                        ath = a.get("athlete", {})
                        eid = str(ath.get("id"))
                        stats = _parse_line(names, a.get("stats", []))
                        if not stats:
                            continue
                        pid = espn_to_player.get(eid)
                        if pid is None and not ath.get("displayName"):
                            continue  # malformed box-score row (no name, not in spine) — skip
                        if pid is None:
                            cur = con.execute(
                                "INSERT INTO players(name, league, espn_id, active) VALUES (?,?,?,1)",
                                (ath.get("displayName"), "nba", eid))
                            pid = cur.lastrowid
                            espn_to_player[eid] = pid; added += 1
                        else:
                            resolved += 1
                        con.execute(
                            """INSERT OR REPLACE INTO player_game_logs
                               (player_id, league, season, game_no, game_id, game_date, team,
                                opponent, home_away, stats, source, source_player_key)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (pid, "nba", season, ds, str(gid), ds, team, None, None,
                             json.dumps(stats), "espn", eid))
                        ingested += 1
            time.sleep(0.05)
        con.commit()
        print(f"  {ds}: {len(games)} final games, running total {ingested} logs")
        day += dt.timedelta(days=1)

    print(f"Done. {ingested} NBA game-logs ({resolved} matched existing spine, {added} new players added)")
    con.close()
    return ingested


if __name__ == "__main__":
    args = sys.argv
    start = args[args.index("--start") + 1] if "--start" in args else "2026-04-01"
    end = args[args.index("--end") + 1] if "--end" in args else "2026-04-07"
    ingest(start, end)
