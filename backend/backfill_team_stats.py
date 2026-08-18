#!/usr/bin/env python3
"""
backfill_team_stats.py — Pull NBA/NHL/NFL team boxscore stats from ESPN
and upsert into the team_game_stats table. Idempotent.

Usage: cd backend && venv/bin/python backfill_team_stats.py [--days N]
"""
import sys, os, sqlite3, datetime as dt, json

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
_SITE = "https://site.api.espn.com/apis/site/v2/sports/{path}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# The shared client keeps the raw call's headers and timeout; the module's own
# ttl-based _cache dict moves into the Fetcher's memory cache (json(url, ttl)).
_FETCH = paced_http.Fetcher(headers={"User-Agent": UA}, timeout=15, retry_waits=())

def _get(url, ttl=30):
    return _FETCH.json(url, ttl=ttl)


def _num(x):
    try: return float(x)
    except: return None


def backfill_nba(days=90):
    """Pull NBA boxscores for last N days."""
    path = "basketball/nba"
    con = sqlite3.connect(DB)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    inserted = 0

    for offset in range(days):
        d = (dt.date.today() - dt.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            sb = _get(_SITE.format(path=path) + f"/scoreboard?dates={d}", ttl=20)
        except Exception:
            continue

        for e in sb.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            st = comp.get("status", {}).get("type", {})
            if st.get("state") != "post":
                continue

            gid = str(e["id"])
            # Check if already exists
            existing = con.execute(
                "SELECT COUNT(*) FROM team_game_stats WHERE league='nba' AND game_id=?",
                (gid,)).fetchone()[0]
            if existing >= 2:
                continue

            try:
                summary = _get(_SITE.format(path=path) + f"/summary?event={gid}", ttl=20)
            except Exception:
                continue

            for t in summary.get("boxscore", {}).get("teams", []):
                team = t.get("team", {})
                abbrev = team.get("abbreviation", "?")
                home_away = "home" if t.get("homeAway") == "home" else "away"

                stats = {}
                for s in t.get("statistics", []):
                    name = s.get("name", "")
                    val = s.get("displayValue", "")
                    # Categorize
                    if name == "fieldGoalsMade-fieldGoalsAttempted":
                        stats["fgm_fga"] = val
                    elif name == "fieldGoalPct":
                        stats["fg_pct"] = _num(val)
                    elif name == "threePointFieldGoalsMade-threePointFieldGoalsAttempted":
                        stats["tpm_tpa"] = val
                    elif name == "threePointFieldGoalPct":
                        stats["tp_pct"] = _num(val)
                    elif name == "freeThrowsMade-freeThrowsAttempted":
                        stats["ftm_fta"] = val
                    elif name == "freeThrowPct":
                        stats["ft_pct"] = _num(val)
                    elif name == "totalRebounds":
                        stats["rebounds"] = int(float(val))
                    elif name == "offensiveRebounds":
                        stats["off_rebounds"] = int(float(val))
                    elif name == "defensiveRebounds":
                        stats["def_rebounds"] = int(float(val))
                    elif name == "assists":
                        stats["assists"] = int(float(val))
                    elif name == "steals":
                        stats["steals"] = int(float(val))
                    elif name == "blocks":
                        stats["blocks"] = int(float(val))
                    elif name == "totalTurnovers":
                        stats["turnovers"] = int(float(val))
                    elif name == "fouls":
                        stats["fouls"] = int(float(val))
                    elif name == "turnoverPoints":
                        stats["pts_off_to"] = int(float(val))
                    elif name == "fastBreakPoints":
                        stats["fast_break_pts"] = int(float(val))
                    elif name == "pointsInPaint":
                        stats["pts_in_paint"] = int(float(val))
                    elif name == "largestLead":
                        stats["largest_lead"] = int(float(val))
                    elif name == "leadChanges":
                        stats["lead_changes"] = int(float(val))
                    elif name == "leadPercentage":
                        stats["lead_pct"] = _num(val)

                if existing == 0:
                    # New row
                    cols = ["league", "game_id", "captured_at", "team_abbrev", "home_away"]
                    vals = ["nba", gid, now, abbrev, home_away]
                    for k, v in stats.items():
                        cols.append(k)
                        vals.append(v)
                    placeholders = ",".join(["?"] * len(vals))
                    sql = f"INSERT INTO team_game_stats({','.join(cols)}) VALUES({placeholders})"
                    con.execute(sql, vals)
                else:
                    # Update existing
                    sets = []
                    params = []
                    for k, v in stats.items():
                        sets.append(f"{k}=?")
                        params.append(v)
                    params.extend(["nba", gid, abbrev])
                    sql = f"UPDATE team_game_stats SET {','.join(sets)} WHERE league=? AND game_id=? AND team_abbrev=?"
                    con.execute(sql, params)

                inserted += 1

        con.commit()
        if offset % 5 == 0:
            print(f"  NBA: day {offset}/{days} date={d} — {inserted} total rows")
    con.close()
    return inserted


def backfill_nhl(days=90):
    """Pull NHL boxscores for last N days."""
    path = "hockey/nhl"
    con = sqlite3.connect(DB)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    inserted = 0

    for offset in range(days):
        d = (dt.date.today() - dt.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            sb = _get(_SITE.format(path=path) + f"/scoreboard?dates={d}", ttl=20)
        except Exception:
            continue

        for e in sb.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            st = comp.get("status", {}).get("type", {})
            if st.get("state") != "post":
                continue

            gid = str(e["id"])
            existing = con.execute(
                "SELECT COUNT(*) FROM team_game_stats WHERE league='nhl' AND game_id=?",
                (gid,)).fetchone()[0]
            if existing >= 2:
                continue

            try:
                summary = _get(_SITE.format(path=path) + f"/summary?event={gid}", ttl=20)
            except Exception:
                continue

            for t in summary.get("boxscore", {}).get("teams", []):
                team = t.get("team", {})
                abbrev = team.get("abbreviation", "?")
                home_away = "home" if t.get("homeAway") == "home" else "away"

                stats = {}
                for s in t.get("statistics", []):
                    name = s.get("name", "")
                    val = s.get("displayValue", "")
                    if name == "shotsTotal":
                        stats["shots"] = int(float(val))
                    elif name == "blockedShots":
                        stats["blocked_shots"] = int(float(val))
                    elif name == "hits":
                        stats["hits"] = int(float(val))
                    elif name == "takeaways":
                        stats["takeaways"] = int(float(val))
                    elif name == "giveaways":
                        stats["giveaways"] = int(float(val))
                    elif name == "faceoffsWon":
                        stats["faceoffs_won"] = int(float(val))
                    elif name == "faceoffPercent":
                        stats["faceoff_pct"] = _num(val)
                    elif name == "powerPlayGoals":
                        stats["powerplay_goals"] = int(float(val))
                    elif name == "powerPlayOpportunities":
                        stats["powerplay_opps"] = int(float(val))
                    elif name == "powerPlayPct":
                        stats["powerplay_pct"] = _num(val)
                    elif name == "shortHandedGoals":
                        stats["shorthanded_goals"] = int(float(val))
                    elif name == "penalties":
                        stats["penalties"] = int(float(val))
                    elif name == "penaltyMinutes":
                        stats["penalty_min"] = int(float(val))

                if existing == 0:
                    cols = ["league", "game_id", "captured_at", "team_abbrev", "home_away"]
                    vals = ["nhl", gid, now, abbrev, home_away]
                    for k, v in stats.items():
                        cols.append(k)
                        vals.append(v)
                    placeholders = ",".join(["?"] * len(vals))
                    sql = f"INSERT INTO team_game_stats({','.join(cols)}) VALUES({placeholders})"
                    con.execute(sql, vals)
                else:
                    sets = []
                    params = []
                    for k, v in stats.items():
                        sets.append(f"{k}=?")
                        params.append(v)
                    params.extend(["nhl", gid, abbrev])
                    sql = f"UPDATE team_game_stats SET {','.join(sets)} WHERE league=? AND game_id=? AND team_abbrev=?"
                    con.execute(sql, params)

                inserted += 1

        con.commit()
        if offset % 5 == 0:
            print(f"  NHL: day {offset}/{days} date={d} — {inserted} total rows")
    con.close()
    return inserted


def backfill_nfl(days=90):
    """Pull NFL boxscores. NFL is out of season — check if any games exist."""
    path = "football/nfl"
    con = sqlite3.connect(DB)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    inserted = 0
    # NFL is offseason. Check a few dates.
    # ESPN NFL boxscore stats differ from NBA/NHL
    for offset in range(min(days, 7)):  # Only check 7 days for NFL (offseason)
        d = (dt.date.today() - dt.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            sb = _get(_SITE.format(path=path) + f"/scoreboard?dates={d}", ttl=20)
        except Exception:
            continue

        for e in sb.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            st = comp.get("status", {}).get("type", {})
            if st.get("state") != "post":
                continue
            gid = str(e["id"])
            existing = con.execute(
                "SELECT COUNT(*) FROM team_game_stats WHERE league='nfl' AND game_id=?",
                (gid,)).fetchone()[0]
            if existing >= 2:
                continue
            try:
                summary = _get(_SITE.format(path=path) + f"/summary?event={gid}", ttl=20)
            except Exception:
                continue
            # NFL boxscore structure is deeply nested — skip for now (offseason)
            print(f"  NFL game {gid} found but NFL stat extraction not implemented (offseason)")
    con.close()
    return inserted


if __name__ == "__main__":
    days = 90
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])

    print(f"Backfilling last {days} days...")
    print("NBA:")
    nba = backfill_nba(days)
    print(f"  NBA: {nba} rows")
    print("NHL:")
    nhl = backfill_nhl(days)
    print(f"  NHL: {nhl} rows")
    print("NFL:")
    nfl = backfill_nfl(days)
    print(f"  NFL: {nfl} rows")
    print(f"\nTotal inserted: {nba + nhl + nfl}")
