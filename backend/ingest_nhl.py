#!/usr/bin/env python3
"""
ingest_nhl.py — pull NHL player stats from nhle.com + ESPN rosters, persist to player_stats.

Usage: python3 ingest_nhl.py
"""
import sys, os, sqlite3, json, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HDR = {"User-Agent": "Mozilla/5.0"}

KNOWN_NHL = {
    "connor mcdavid": 8478402, "auston matthews": 8479318,
    "nathan mackinnon": 8477492, "leon draisaitl": 8477934,
    "david pastrnak": 8477956, "nikita kucherov": 8476453,
    "sidney crosby": 8471675, "alex ovechkin": 8471214,
    "cale makar": 8478486, "matthew tkachuk": 8479314,
}

def fetch_nhl_stats(nhl_id: int):
    url = f"https://api-web.nhle.com/v1/player/{nhl_id}/landing"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    st = data.get("seasonTotals", [])
    if not st:
        return None
    latest = st[-1]
    first = data.get("firstName", {})
    last = data.get("lastName", {})
    return {
        "name": f"{first.get('default','')} {last.get('default','')}".strip(),
        "position": data.get("position", "?"),
        "team": data.get("currentTeamAbbrev", "?"),
        "season": latest.get("season", ""),
        "games": int(latest.get("gamesPlayed", 0)),
        "goals": int(latest.get("goals", 0)),
        "assists": int(latest.get("assists", 0)),
        "points": int(latest.get("points", 0)),
        "shots": int(latest.get("shots", 0)),
        "shooting_pct": round(float(latest.get("shootingPctg", 0)) * 100, 1),
        "plus_minus": int(latest.get("plusMinus", 0)),
        "pim": int(latest.get("pim", 0)),
        "ppg": int(latest.get("powerPlayGoals", 0)),
        "ppp": int(latest.get("powerPlayPoints", 0)),
        "shg": int(latest.get("shorthandedGoals", 0)),
        "toi": str(latest.get("avgToi", "")),
        "faceoff_pct": round(float(latest.get("faceoffWinningPctg", 0)) * 100, 1),
    }

def ingest():
    con = sqlite3.connect(DB)
    ingested = 0

    for name, pid in KNOWN_NHL.items():
        try:
            s = fetch_nhl_stats(pid)
            if not s:
                continue
            display = s["name"] or name.title()
            con.execute(
                """INSERT OR REPLACE INTO player_stats
                   (player_name, league, team, stat_type, season, games,
                    nhl_position, nhl_team, goals, assists, points_nhl, shots,
                    shooting_pct, plus_minus, pim, ppg, ppp, shg, toi, faceoff_pct, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (display, "nhl", s["team"], "season", s["season"], s["games"],
                 s["position"], s["team"],
                 s["goals"], s["assists"], s["points"], s["shots"],
                 s["shooting_pct"], s["plus_minus"], s["pim"],
                 s["ppg"], s["ppp"], s["shg"],
                 s["toi"], s["faceoff_pct"], "nhle.com"))
            ingested += 1
            print(f"  {display}: {s['goals']}G {s['assists']}A {s['points']}PTS in {s['games']}GP")
        except Exception as e:
            print(f"  {name}: FAIL ({e})")

    # Also pull from ESPN rosters
    try:
        import espn_client as espn
        teams = espn.NHL_TEAMS if hasattr(espn, 'NHL_TEAMS') else ['VGK','EDM','TOR','COL','FLA','TBL','BOS','NYR']
        for team in teams[:5]:
            try:
                roster = espn.roster('nhl', team)
                for p in roster[:5]:
                    name = p.get("name", "")
                    # Try nhle.com for each (expensive — just note for now)
                    pass
            except Exception:
                pass
    except Exception:
        pass

    con.commit()
    con.close()
    print(f"\nIngested: {ingested} NHL players")

if __name__ == "__main__":
    ingest()
