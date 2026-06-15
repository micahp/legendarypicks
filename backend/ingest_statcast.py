#!/usr/bin/env python3
"""
ingest_statcast.py — bulk Statcast league-wide pull, persist all MLB players to player_stats.

EFFICIENCY: one pybaseball statcast(start,end) call covers the entire league.
Groups by batter (batting stats) and pitcher (pitching stats), writes ALL players
found — no per-player API calls. Two-way players get both rows.

Usage: python3 ingest_statcast.py [--days 30]
"""
import sys, os, sqlite3, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

def _flip_name(name: str) -> str:
    """Convert 'Last, First' → 'First Last' for ESPN compatibility."""
    if ',' in name:
        parts = name.split(',', 1)
        return f'{parts[1].strip()} {parts[0].strip()}'
    return name

def ingest(days: int = 30):
    from pybaseball import statcast
    import pandas as pd
    import numpy as np

    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    print(f"Pulling Statcast {start_str} to {end_str} (this may take a minute)...")
    data = statcast(start_str, end_str)
    if data is None or len(data) == 0:
        print("No Statcast data returned.")
        return

    print(f"  {len(data)} pitches, {data['batter'].nunique()} batters, {data['pitcher'].nunique()} pitchers")
    season = end.year

    con = sqlite3.connect(DB)
    batting_count = 0
    pitching_count = 0

    # ── Batting: group by batter ID ──
    # IMPORTANT: player_name is the PITCHER in Statcast data.
    # For batters, we need to resolve batter ID → name from a known-good source.
    # Build a mapping: batter_id → name from rows where that player PITCHED
    # (player_name is correct when they're the pitcher), then use that.
    pitcher_id_to_name = {}
    for pid, name in data.groupby("pitcher")["player_name"].first().items():
        if name and name != "NaN":
            pitcher_id_to_name[pid] = name

    bat_mask = data["events"].notna() | data["launch_speed"].notna()
    bat_data = data[bat_mask]
    if len(bat_data) == 0:
        print("  No batting data")
    else:
        for batter_id, group in bat_data.groupby("batter"):
            # Resolve name: prefer pitcher-name map (two-way players), else use first non-NaN
            name = pitcher_id_to_name.get(batter_id)
            if not name:
                name = group["player_name"].dropna()
                name = name.iloc[0] if len(name) > 0 else None
            if not name or name == "NaN":
                continue
            name = _flip_name(str(name))

            events = group["events"].dropna()
            bb = group[group["launch_speed"].notna()]  # batted balls

            avg_ev = float(bb["launch_speed"].mean()) if len(bb) > 0 else 0
            hard_hit = float((bb["launch_speed"] >= 95).mean() * 100) if len(bb) > 0 else 0
            barrel = float(((bb["launch_speed"] >= 98) & (bb["launch_angle"].between(26, 30))).mean() * 100) if len(bb) > 0 else 0
            avg_la = float(bb["launch_angle"].mean()) if len(bb) > 0 else 0
            woba_vals = group[group["woba_value"].notna()]["woba_value"]
            woba = float(woba_vals.mean()) if len(woba_vals) > 0 else 0
            xwoba_vals = bb["estimated_woba_using_speedangle"].dropna()
            xwoba = float(xwoba_vals.mean()) if len(xwoba_vals) > 0 else 0

            hits = int(events.isin(["single", "double", "triple", "home_run"]).sum())
            ab = len(events) - int((events == "walk").sum()) - int((events.isin(["sac_fly", "sac_bunt", "sac_bunt_double_play"])).sum())
            avg = round(hits / ab, 3) if ab > 0 else 0
            hr = int((events == "home_run").sum())
            k_pct = round(float((events == "strikeout").mean() * 100), 1)
            bb_pct = round(float((events == "walk").mean() * 100), 1)
            games = group["game_date"].nunique()

            try:
                con.execute(
                    """INSERT OR REPLACE INTO player_stats
                       (player_name, name_norm, league, team, stat_type, season, games,
                        avg, hr, k_pct, bb_pct, exit_velo, hard_hit_pct, barrel_pct, launch_angle,
                        woba, xwoba, source)
                       VALUES (?,?,?,?,'batting',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(name), _normalize_name(str(name)), "mlb", "", season, games,
                     avg, hr, k_pct, bb_pct,
                     round(avg_ev, 1), round(hard_hit, 1), round(barrel, 1), round(avg_la, 1),
                     round(woba, 3), round(xwoba, 3), "statcast"))
                batting_count += 1
            except Exception as e:
                if batting_count == 0:
                    print(f"  Batting INSERT error (first): {e}")
                    print(f"    name={str(name)[:30]} season={season} games={games}")

    # ── Pitching: group by pitcher ID ──
    pitcher_names = data.groupby("pitcher")["player_name"].first()
    for pitcher_id, group in data.groupby("pitcher"):
        name = pitcher_names.get(pitcher_id, f"pitcher_{pitcher_id}")
        if not name or name == "NaN":
            continue
        name = _flip_name(str(name))

        whiff = float(group["description"].isin(["swinging_strike", "swinging_strike_blocked"]).mean() * 100)
        bb_a = group[group["launch_speed"].notna()]
        ev_against = float(bb_a["launch_speed"].mean()) if len(bb_a) > 0 else 0
        barrel_against = float(((bb_a["launch_speed"] >= 98) & (bb_a["launch_angle"].between(26, 30))).mean() * 100) if len(bb_a) > 0 else 0
        xwoba_against_vals = bb_a["estimated_woba_using_speedangle"].dropna()
        xwoba_against = float(xwoba_against_vals.mean()) if len(xwoba_against_vals) > 0 else 0
        k_pct_p = float((group["events"] == "strikeout").mean() * 100) if "events" in group.columns else 0
        games_p = group["game_date"].nunique()

        try:
            con.execute(
                """INSERT OR REPLACE INTO player_stats
                   (player_name, name_norm, league, team, stat_type, season, games,
                    k_pct, whiff_pct, exit_velo_against, barrel_pct_against, xwoba_against, source)
                   VALUES (?,?,?,?,'pitching',?,?,?,?,?,?,?,?)""",
                (str(name), _normalize_name(str(name)), "mlb", "", season, games_p,
                 round(k_pct_p, 1), round(whiff, 1),
                 round(ev_against, 1), round(barrel_against, 1), round(xwoba_against, 3), "statcast"))
            pitching_count += 1
        except Exception:
            pass

    con.commit()
    con.close()
    print(f"  Ingested: {batting_count} batting, {pitching_count} pitching")


if __name__ == "__main__":
    days = 30
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
    ingest(days)
