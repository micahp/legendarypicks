#!/usr/bin/env python3
"""
ingest_statcast.py — pull Statcast data via pybaseball, persist to player_stats.

Usage: python3 ingest_statcast.py [--days 30]
Downloads last N days of Statcast data for all players in the players table
(MLB league only). Writes batting + pitching rows to player_stats.

pybaseball is ingest-time only — the request path reads from DB.
"""
import sys, os, sqlite3, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

def ingest_statcast(days: int = 30):
    from pybaseball import statcast_batter, statcast_pitcher, playerid_lookup
    import pandas as pd
    import numpy as np

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Get all MLB players from our DB
    players = con.execute("SELECT DISTINCT id, name FROM players WHERE league='mlb'").fetchall()
    print(f"MLB players to process: {len(players)}")

    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    batting_count = 0
    pitching_count = 0
    season = end.year

    for p in players:
        name = p["name"]
        # Resolve Statcast ID
        parts = name.strip().split(" ", 1)
        last = parts[-1]
        first = parts[0] if len(parts) > 1 else ""
        sid = None
        try:
            lookup = playerid_lookup(last, first)
            if lookup is not None and len(lookup) > 0:
                sid = int(lookup.iloc[0]["key_mlbam"])
        except Exception:
            pass

        if not sid:
            continue

        # ── Batting ──
        try:
            bat = statcast_batter(start_str, end_str, player_id=sid)
            if bat is not None and len(bat) > 0:
                bat = bat[bat["events"].notna() | bat["launch_speed"].notna()]
                bb = bat[bat["launch_speed"].notna()]
                events = bat["events"].dropna()

                avg_ev = float(bb["launch_speed"].mean()) if len(bb) > 0 else 0
                hard_hit = float((bb["launch_speed"] >= 95).mean() * 100) if len(bb) > 0 else 0
                barrel = float(((bb["launch_speed"] >= 98) & (bb["launch_angle"].between(26, 30))).mean() * 100) if len(bb) > 0 else 0
                avg_la = float(bb["launch_angle"].mean()) if len(bb) > 0 else 0
                woba = float(bat[bat["woba_value"].notna()]["woba_value"].mean())
                xwoba = float(bb["estimated_woba_using_speedangle"].mean()) if len(bb) > 0 else 0

                hits = int(events.isin(["single", "double", "triple", "home_run"]).sum())
                ab = len(events) - int((events == "walk").sum()) - int((events == "sac_fly").sum()) - int((events.isin(["sac_bunt", "sac_bunt_double_play"])).sum())
                avg = round(hits / ab, 3) if ab > 0 else 0
                hr = int((events == "home_run").sum())
                k_pct = round(float((events == "strikeout").mean() * 100), 1)
                bb_pct = round(float((events == "walk").mean() * 100), 1)
                games = len(bat["game_date"].unique()) if "game_date" in bat.columns else 0

                con.execute(
                    """INSERT OR REPLACE INTO player_stats
                       (player_name, league, team, stat_type, season, games,
                        avg, hr, k_pct, bb_pct, exit_velo, hard_hit_pct, barrel_pct, launch_angle,
                        woba, xwoba, source)
                       VALUES (?,?,?,'batting',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, "mlb", "", season, games, avg, hr, k_pct, bb_pct,
                     round(avg_ev, 1), round(hard_hit, 1), round(barrel, 1), round(avg_la, 1),
                     round(woba, 3), round(xwoba, 3), "statcast"))
                batting_count += 1
        except Exception as e:
            pass  # player may not have batted

        # ── Pitching ──
        try:
            pit = statcast_pitcher(start_str, end_str, player_id=sid)
            if pit is not None and len(pit) > 0:
                whiff = float(pit["description"].isin(["swinging_strike", "swinging_strike_blocked"]).mean() * 100)
                bb_a = pit[pit["launch_speed"].notna()]
                ev_against = float(bb_a["launch_speed"].mean()) if len(bb_a) > 0 else 0
                barrel_against = float(((bb_a["launch_speed"] >= 98) & (bb_a["launch_angle"].between(26, 30))).mean() * 100) if len(bb_a) > 0 else 0
                xwoba_against = float(bb_a["estimated_woba_using_speedangle"].mean()) if len(bb_a) > 0 else 0
                k_pct_p = float((pit["events"] == "strikeout").mean() * 100) if "events" in pit.columns else 0
                games_p = len(pit["game_date"].unique()) if "game_date" in pit.columns else 0

                con.execute(
                    """INSERT OR REPLACE INTO player_stats
                       (player_name, league, team, stat_type, season, games,
                        k_pct, whiff_pct, exit_velo_against, barrel_pct_against, xwoba_against, source)
                       VALUES (?,?,?,'pitching',?,?,?,?,?,?,?,?)""",
                    (name, "mlb", "", season, games_p, k_pct_p, round(whiff, 1),
                     round(ev_against, 1), round(barrel_against, 1), round(xwoba_against, 3), "statcast"))
                pitching_count += 1
        except Exception:
            pass

    con.commit()
    print(f"Ingested: {batting_count} batting, {pitching_count} pitching rows ({len(players)} players attempted)")
    con.close()


if __name__ == "__main__":
    days = 30
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
    ingest_statcast(days)
