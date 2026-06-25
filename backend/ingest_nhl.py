#!/usr/bin/env python3
"""
ingest_nhl.py — pull full NHL rosters + stats from api-web.nhle.com, persist to player_stats.

Roster source: api-web.nhle.com/v1/roster/{TEAM}/current (all 32 teams)
Stats source: api-web.nhle.com/v1/player/{id}/landing
Target: >=95% of rostered NHL players resolve to a stats row.

Usage: python3 ingest_nhl.py
"""
import sys, os, sqlite3, json, urllib.request, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HDR = {"User-Agent": "Mozilla/5.0"}

# All 32 NHL team abbreviations (nhle.com format — 3 letters for most, some differ from ESPN)
NHL_TEAMS = [
    "CAR","BUF","TBL","MTL","BOS","OTT","PIT","PHI","WSH","DET","CBJ","NYI","NJD","FLA","TOR","NYR",
    "VGK","DAL","MIN","EDM","UTA","ANA","LAK","STL","NSH","SJS","WPG","SEA","CGY","CHI","VAN","COL",
]


def fetch_roster(team: str) -> list:
    """Pull current roster from nhle.com. Returns list of {name, id, position, team}."""
    url = f"https://api-web.nhle.com/v1/roster/{team}/current"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print(f"    {team}: roster FAIL ({e})")
        return []

    players = []
    for pos_group in ["forwards", "defensemen", "goalies"]:
        for p in data.get(pos_group, []):
            pid = p.get("id")
            fn = p.get("firstName", {}).get("default", "")
            ln = p.get("lastName", {}).get("default", "")
            name = f"{fn} {ln}".strip()
            pos = p.get("positionCode", "?")
            if pid and name:
                players.append({"name": name, "id": pid, "position": pos, "team": team})
    return players


def fetch_stats(nhl_id: int) -> dict:
    """Pull season stats from nhle.com landing endpoint."""
    url = f"https://api-web.nhle.com/v1/player/{nhl_id}/landing"
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
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
    con.row_factory = sqlite3.Row

    # Pre-load player_id lookup: nhl_id → players.id
    nhl_id_to_player = {}
    for r in con.execute("SELECT id, nhl_id FROM players WHERE league='nhl' AND nhl_id IS NOT NULL"):
        nhl_id_to_player[r["nhl_id"]] = r["id"]
    print(f"Loaded {len(nhl_id_to_player)} nhl_id→player_id mappings")

    total_players = 0
    total_stats = 0
    per_team = {}

    for team in NHL_TEAMS:
        print(f"{team}:", end=" ", flush=True)
        roster = fetch_roster(team)
        if not roster:
            per_team[team] = (0, 0, 0)
            continue

        size = len(roster)
        stats_count = 0
        for p in roster:
            total_players += 1
            # Check if already ingested this season
            existing = con.execute(
                "SELECT COUNT(*) FROM player_stats WHERE league='nhl' AND name_norm=? AND season >= 2025",
                (_normalize_name(p["name"]),)
            ).fetchone()
            if existing[0] > 0:
                stats_count += 1
                continue

            s = fetch_stats(p["id"])
            if s:
                display = s["name"] or p["name"]
                player_id = nhl_id_to_player.get(p["id"])
                try:
                    con.execute(
                        """INSERT OR REPLACE INTO player_stats
                           (player_name, name_norm, league, team, stat_type, season, games,
                            nhl_position, nhl_team, goals, assists, points_nhl, shots,
                            shooting_pct, plus_minus, pim, ppg, ppp, shg, toi, faceoff_pct, source, player_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (display, _normalize_name(display), "nhl", s["team"], "season",
                         s["season"], s["games"],
                         s["position"], s["team"],
                         s["goals"], s["assists"], s["points"], s["shots"],
                         s["shooting_pct"], s["plus_minus"], s["pim"],
                         s["ppg"], s["ppp"], s["shg"],
                         s["toi"], s["faceoff_pct"], "nhle.com", player_id))
                    stats_count += 1
                except Exception:
                    pass
                time.sleep(0.15)  # gentle rate limit

        pct = round(stats_count / size * 100) if size > 0 else 0
        flag = "✅" if pct >= 95 else ("⚠️" if pct < 50 else "  ")
        print(f"{flag} {stats_count}/{size} ({pct}%)")
        per_team[team] = (stats_count, size, pct)

    con.commit()
    con.close()

    total_resolved = sum(c for c, _, _ in per_team.values())
    total_roster = sum(s for _, s, _ in per_team.values())
    print(f"\nTotal: {total_resolved}/{total_roster} ({round(total_resolved/max(total_roster,1)*100)}%)")


if __name__ == "__main__":
    ingest()
