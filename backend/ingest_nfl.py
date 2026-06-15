#!/usr/bin/env python3
"""
ingest_nfl.py — pull nfl_data_py weekly data, persist to player_stats.

Usage: python3 ingest_nfl.py [--year 2024]
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

def ingest_nfl(season: int = 2024):
    import nfl_data_py as nfl

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Pre-load player_id lookup: nfl_gsis_id → players.id
    gsis_to_player = {}
    for r in con.execute("SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''"):
        gsis_to_player[r["nfl_gsis_id"]] = r["id"]
    print(f"Loaded {len(gsis_to_player)} gsis_id→player_id mappings")

    print(f"Loading NFL weekly data for {season}...")
    weekly = nfl.import_weekly_data([season])
    print(f"  {len(weekly)} player-weeks")

    # Aggregate per player (include player_id=gsis_id for spine resolution)
    group_cols = ["player_display_name", "position", "recent_team"]
    has_player_id = "player_id" in weekly.columns
    if has_player_id:
        group_cols.append("player_id")
    grouped = weekly.groupby(group_cols).agg(
        games=("week", "count"),
        pass_yds_g=("passing_yards", "mean"),
        pass_td=("passing_tds", "sum"),
        interceptions=("interceptions", "sum"),
        cmp_g=("completions", "mean"),
        pass_epa=("passing_epa", "sum"),
        carries_g=("carries", "mean"),
        rush_yds_g=("rushing_yards", "mean"),
        receptions=("receptions", "sum"),
        rec_yds_g=("receiving_yards", "mean"),
        targets=("targets", "sum"),
        fantasy_pts_g=("fantasy_points", "mean"),
        fantasy_ppr_g=("fantasy_points_ppr", "mean"),
    ).reset_index()

    ingested = 0
    for _, row in grouped.iterrows():
        # Resolve player_id from gsis_id (spine), fall back to None
        gsis_id = str(row.get("player_id", "")) if has_player_id else ""
        player_id = gsis_to_player.get(gsis_id) if gsis_id else None

        con.execute(
            """INSERT OR REPLACE INTO player_stats
               (player_name, name_norm, league, team, stat_type, season, games,
                nfl_position, nfl_team,
                pass_yds_g, pass_td, interceptions, cmp_g, pass_epa,
                carries_g, rush_yds_g, receptions, rec_yds_g, targets,
                fantasy_pts_g, fantasy_ppr_g, source, player_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["player_display_name"], _normalize_name(row["player_display_name"]),
             "nfl", row["recent_team"], "weekly",
             season, int(row["games"]),
             row["position"], row["recent_team"],
             round(float(row["pass_yds_g"]), 1) if row["pass_yds_g"] == row["pass_yds_g"] else 0,
             int(row["pass_td"]) if row["pass_td"] == row["pass_td"] else 0,
             int(row["interceptions"]) if row["interceptions"] == row["interceptions"] else 0,
             round(float(row["cmp_g"]), 1) if row["cmp_g"] == row["cmp_g"] else 0,
             round(float(row["pass_epa"]), 1) if row["pass_epa"] == row["pass_epa"] else 0,
             round(float(row["carries_g"]), 1) if row["carries_g"] == row["carries_g"] else 0,
             round(float(row["rush_yds_g"]), 1) if row["rush_yds_g"] == row["rush_yds_g"] else 0,
             int(row["receptions"]) if row["receptions"] == row["receptions"] else 0,
             round(float(row["rec_yds_g"]), 1) if row["rec_yds_g"] == row["rec_yds_g"] else 0,
             int(row["targets"]) if row["targets"] == row["targets"] else 0,
             round(float(row["fantasy_pts_g"]), 1) if row["fantasy_pts_g"] == row["fantasy_pts_g"] else 0,
             round(float(row["fantasy_ppr_g"]), 1) if row["fantasy_ppr_g"] == row["fantasy_ppr_g"] else 0,
             "nflverse", player_id))
        ingested += 1

    con.commit()
    # Sample
    r = con.execute("SELECT player_name, nfl_position, pass_yds_g, rush_yds_g, pass_epa, games FROM player_stats WHERE league='nfl' AND player_name LIKE '%Mahomes%'").fetchone()
    if r:
        print(f"  Sample: {r[0]} ({r[1]}) — {r[2]} pass yds/g, {r[4]} EPA, {r[5]} GP")
    con.close()
    print(f"Ingested: {ingested} NFL players")


if __name__ == "__main__":
    year = 2024
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        year = int(sys.argv[1])
    ingest_nfl(year)
