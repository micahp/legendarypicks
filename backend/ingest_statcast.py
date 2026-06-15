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

def ingest(days: int = 200):
    from pybaseball import statcast
    import pandas as pd
    import numpy as np

    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    print(f"Pulling Statcast {start_str} to {end_str} (full-season window, this may take a minute)...")
    data = statcast(start_str, end_str)
    if data is None or len(data) == 0:
        print("No Statcast data returned.")
        return

    print(f"  {len(data)} pitches, {data['batter'].nunique()} batters, {data['pitcher'].nunique()} pitchers")
    season = end.year

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    batting_count = 0
    pitching_count = 0
    unresolved_count = 0

    # Pre-load spine: mlbam_id → (name, player_id) — Chadwick-backed, the source of truth
    mlbam_info = {}   # mlbam_id → (name, player_id)
    mlbam_to_player = {}  # mlbam_id → player_id (for quick lookup)
    for r in con.execute("SELECT mlbam_id, name, id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"):
        mlbam_info[r["mlbam_id"]] = (r["name"], r["id"])
        mlbam_to_player[r["mlbam_id"]] = r["id"]
    print(f"  Loaded {len(mlbam_info)} mlbam_id→(name, player_id) from spine")
    spine_added = 0

    def _resolve_or_add(mlbam_id: int, fallback_name: str) -> tuple:
        """Return (name, player_id) — from spine if known, else upsert with fallback name.
        The fallback_name is a placeholder for batters (mlbam_XXXXX) or a real name
        for pitchers (from Statcast's player_name, which IS the pitcher's name)."""
        nonlocal spine_added
        info = mlbam_info.get(mlbam_id)
        if info:
            return info  # (name, player_id) from Chadwick-backed spine
        # Not in spine — add them
        pid = mlbam_to_player.get(mlbam_id)
        if pid is None:
            cur = con.execute(
                "INSERT INTO players(name, league, mlbam_id, active) VALUES (?,?,?,1)",
                (str(fallback_name), "mlb", mlbam_id))
            pid = cur.lastrowid
            mlbam_to_player[mlbam_id] = pid
            mlbam_info[mlbam_id] = (str(fallback_name), pid)
            spine_added += 1
        else:
            # Already resolved in this session
            pass
        return (str(fallback_name), pid)

    # ── Batting: group by batter ID ──
    # KEY FIX: batter_id IS the mlbam_id. Resolve name + player_id from the spine
    # (Chadwick-backed players table), NOT from Statcast's player_name (which is
    # the PITCHER's name, useless for pure batters).
    bat_mask = data["events"].notna() | data["launch_speed"].notna()
    bat_data = data[bat_mask]
    if len(bat_data) == 0:
        print("  No batting data")
    else:
        for batter_id, group in bat_data.groupby("batter"):
            mlbam = int(batter_id)
            name, player_id = _resolve_or_add(mlbam, f"mlbam_{mlbam}")

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
                        woba, xwoba, source, player_id)
                       VALUES (?,?,?,?,'batting',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(name), _normalize_name(str(name)), "mlb", "", season, games,
                     avg, hr, k_pct, bb_pct,
                     round(avg_ev, 1), round(hard_hit, 1), round(barrel, 1), round(avg_la, 1),
                     round(woba, 3), round(xwoba, 3), "statcast", player_id))
                batting_count += 1
            except Exception as e:
                if batting_count <= 3:
                    print(f"  Batting INSERT error: {e}")
                    print(f"    batter={mlbam} name={str(name)[:40]} season={season}")

    # ── Pitching: group by pitcher ID ──
    # For pitchers, Statcast's player_name IS correct (it's the pitcher's name).
    # We prefer the spine name when available (Chadwick-backed), falling back to
    # the Statcast name for players not yet in the spine.
    pitcher_names = data.groupby("pitcher")["player_name"].first()
    for pitcher_id, group in data.groupby("pitcher"):
        mlbam = int(pitcher_id)
        statcast_name = pitcher_names.get(pitcher_id)
        if statcast_name and statcast_name != "NaN":
            statcast_name = _flip_name(str(statcast_name))
        else:
            statcast_name = None

        # Resolve: spine name preferred, fallback to Statcast name, then placeholder
        fallback = statcast_name if statcast_name else f"mlbam_{mlbam}"
        name, player_id = _resolve_or_add(mlbam, fallback)
        # If spine returned a placeholder but we have a real Statcast name, use that
        if name.startswith("mlbam_") and statcast_name:
            name = statcast_name

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
                    k_pct, whiff_pct, exit_velo_against, barrel_pct_against, xwoba_against, source, player_id)
                   VALUES (?,?,?,?,'pitching',?,?,?,?,?,?,?,?,?)""",
                (str(name), _normalize_name(str(name)), "mlb", "", season, games_p,
                 round(k_pct_p, 1), round(whiff, 1),
                 round(ev_against, 1), round(barrel_against, 1), round(xwoba_against, 3), "statcast", player_id))
            pitching_count += 1
        except Exception:
            pass

    con.commit()
    con.close()
    print(f"  Ingested: {batting_count} batting, {pitching_count} pitching")
    if spine_added:
        print(f"  Spine: added {spine_added} new players (with mlbam_id)")
    unresolved_count = sum(1 for v in mlbam_info.values() if v[0].startswith("mlbam_"))
    if unresolved_count:
        print(f"  Placeholder names in spine: {unresolved_count} (needs name repair pass)")


if __name__ == "__main__":
    days = 200
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
    ingest(days)
