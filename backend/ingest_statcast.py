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

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _ensure_identity_queue_schema(con) -> None:
    """Keep standalone ingest runs compatible with older unresolved queues."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(unresolved_players)")}
    for column in ("source_player_key", "reason"):
        if column not in columns:
            con.execute(f"ALTER TABLE unresolved_players ADD COLUMN {column} TEXT")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key "
        "ON unresolved_players(source, league, source_player_key)"
    )


def _load_mlb_spine(con):
    """Return unique MLBAM resolutions and IDs that are ambiguous in the spine."""
    resolved = {}
    ambiguous = set()
    rows = con.execute(
        "SELECT mlbam_id, name, id FROM players WHERE league='mlb' "
        "AND mlbam_id IS NOT NULL AND mlbam_id != 0 ORDER BY id"
    )
    for row in rows:
        mlbam_id = int(row["mlbam_id"])
        if mlbam_id in resolved:
            ambiguous.add(mlbam_id)
        else:
            resolved[mlbam_id] = (row["name"], row["id"])
    return resolved, ambiguous


def _queue_unresolved_statcast(con, mlbam_id: int, fallback_name: str, reason: str) -> None:
    """Queue a stable Statcast identity for review without creating a player."""
    source_key = str(int(mlbam_id))
    existing = con.execute(
        "SELECT id FROM unresolved_players "
        "WHERE source='statcast' AND league='mlb' AND source_player_key=?",
        (source_key,),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE unresolved_players SET count=count+1, raw_name=?, reason=? WHERE id=?",
            (str(fallback_name), reason, existing["id"]),
        )
        return
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute(
        "INSERT INTO unresolved_players"
        "(source,raw_name,league,team,first_seen,count,source_player_key,reason) "
        "VALUES ('statcast',?,'mlb',NULL,?,1,?,?)",
        (str(fallback_name), now, source_key, reason),
    )


def _resolve_or_queue_statcast(
    con, mlbam_info, ambiguous_mlbam_ids, queued_mlbam_ids,
    mlbam_id: int, fallback_name: str,
):
    """Resolve by stable MLBAM ID or queue once per ingest run; never insert."""
    mlbam_id = int(mlbam_id)
    if mlbam_id not in ambiguous_mlbam_ids:
        info = mlbam_info.get(mlbam_id)
        if info:
            return info
    if mlbam_id not in queued_mlbam_ids:
        reason = (
            "duplicate_spine_mlbam_id"
            if mlbam_id in ambiguous_mlbam_ids
            else "mlbam_id_not_in_spine"
        )
        _queue_unresolved_statcast(con, mlbam_id, fallback_name, reason)
        queued_mlbam_ids.add(mlbam_id)
    return None

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
    unresolved_batting = 0
    unresolved_pitching = 0

    _ensure_identity_queue_schema(con)
    # Pre-load the Chadwick-backed spine. Duplicate MLBAM IDs fail closed.
    mlbam_info, ambiguous_mlbam_ids = _load_mlb_spine(con)
    queued_mlbam_ids = set()
    print(f"  Loaded {len(mlbam_info)} mlbam_id→(name, player_id) from spine")
    if ambiguous_mlbam_ids:
        print(f"  WARNING: {len(ambiguous_mlbam_ids)} duplicate MLBAM IDs will be queued")

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
            resolved = _resolve_or_queue_statcast(
                con, mlbam_info, ambiguous_mlbam_ids, queued_mlbam_ids,
                mlbam, f"mlbam_{mlbam}",
            )
            if resolved is None:
                unresolved_batting += 1
                continue
            name, player_id = resolved

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
        resolved = _resolve_or_queue_statcast(
            con, mlbam_info, ambiguous_mlbam_ids, queued_mlbam_ids,
            mlbam, fallback,
        )
        if resolved is None:
            unresolved_pitching += 1
            continue
        name, player_id = resolved
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
    if queued_mlbam_ids:
        print(
            f"  Resolve-or-queue: {len(queued_mlbam_ids)} MLBAM IDs queued; "
            f"skipped {unresolved_batting} batting and {unresolved_pitching} pitching rows"
        )


if __name__ == "__main__":
    days = 200
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
    ingest(days)
