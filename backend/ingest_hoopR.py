#!/usr/bin/env python3
"""
ingest_hoopR.py — download hoopR-data player_box parquets from GitHub and populate player_stats.

Usage: python3 ingest_hoopR.py [--season 2023]
Downloads from sportsdataverse/hoopR-data GitHub repo (free, no IP blocks).
"""
import sys, os, io, urllib.request, sqlite3
import pyarrow.parquet as pq
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
HOOPR_BASE = "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/player_box/parquet/player_box_{season}.parquet"

def ingest_season(season: int, con: sqlite3.Connection):
    url = HOOPR_BASE.format(season=season)
    print(f"Downloading {url}...")
    try:
        data = urllib.request.urlopen(url, timeout=60).read()
    except Exception as e:
        print(f"  FAIL: {e}")
        return 0

    table = pq.read_table(io.BytesIO(data))
    df = table.to_pandas()
    print(f"  {len(df)} rows, {len(df.columns)} columns")

    # Filter regular season only, drop All-Star/non-team rows
    df = df[df["team_abbreviation"].str.len() <= 3]  # 'BOS' not 'Team Giannis' -> 'GIA'
    # Aggregate per player per season (include athlete_id for spine resolution)
    grouped = df.groupby(["athlete_display_name", "athlete_id"]).agg(
        games=("game_id", "count"),
        pts=("points", "mean"),
        pts_total=("points", "sum"),
        reb=("rebounds", "mean"),
        ast=("assists", "mean"),
        stl=("steals", "mean"),
        blk=("blocks", "mean"),
        tov=("turnovers", "mean"),
        fgm=("field_goals_made", "sum"),
        fga=("field_goals_attempted", "sum"),
        fg3m=("three_point_field_goals_made", "sum"),
        fg3a=("three_point_field_goals_attempted", "sum"),
        ftm=("free_throws_made", "sum"),
        fta=("free_throws_attempted", "sum"),
        minutes=("minutes", "mean"),
    ).reset_index()

    # Compute TS%: points / (2 * (FGA + 0.44 * FTA))
    grouped["ts_pct"] = grouped.apply(
        lambda r: round(r["pts_total"] / (2 * (r["fga"] + 0.44 * r["fta"])) * 100, 1)
        if (r["fga"] + 0.44 * r["fta"]) > 0 else 0, axis=1
    )

    # Get dominant team per player
    teams = df.groupby("athlete_display_name")["team_abbreviation"].agg(
        lambda x: x.value_counts().index[0] if len(x) > 0 else "???"
    )

    # Pre-load player_id lookup: nba_id → players.id
    con.row_factory = sqlite3.Row
    nba_id_to_player = {}
    for r in con.execute("SELECT id, nba_id FROM players WHERE league='nba' AND nba_id IS NOT NULL"):
        nba_id_to_player[r["nba_id"]] = r["id"]

    ingested = 0
    for _, row in grouped.iterrows():
        name = row["athlete_display_name"]
        team = teams.get(name, "???")
        athlete_id = int(row["athlete_id"]) if row["athlete_id"] == row["athlete_id"] else None
        player_id = nba_id_to_player.get(athlete_id) if athlete_id else None
        con.execute(
            """INSERT OR REPLACE INTO player_stats
               (player_name, name_norm, league, team, stat_type, season, games,
                pts, reb, ast, stl, blk, tov,
                fgm, fga, fg3m, fg3a, ftm, fta, minutes, ts_pct, source, player_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, _normalize_name(name), "nba", team, "season", season,
             int(row["games"]),
             round(float(row["pts"]), 1), round(float(row["reb"]), 1),
             round(float(row["ast"]), 1), round(float(row["stl"]), 1),
             round(float(row["blk"]), 1), round(float(row["tov"]), 1),
             int(row["fgm"]), int(row["fga"]), int(row["fg3m"]), int(row["fg3a"]),
             int(row["ftm"]), int(row["fta"]), round(float(row["minutes"]), 1),
             float(row["ts_pct"]), "hoopR", player_id))
        ingested += 1

    con.commit()
    print(f"  Ingested {ingested} players")
    return ingested


def main():
    seasons = [2023]
    if "--season" in sys.argv:
        idx = sys.argv.index("--season")
        seasons = [int(sys.argv[idx + 1])]
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        seasons = [int(sys.argv[1])]

    con = sqlite3.connect(DB)
    total = 0
    for s in seasons:
        total += ingest_season(s, con)

    # Show sample
    row = con.execute("SELECT player_name, team, pts, reb, ast, ts_pct, games FROM player_stats WHERE league='nba' AND player_name LIKE '%Tatum%'").fetchone()
    if row:
        print(f"\nSample: {row[0]} ({row[1]}) — {row[2]} PPG, {row[3]} RPG, {row[4]} APG, TS% {row[5]}%, {row[6]} GP")
    con.close()
    print(f"\nTotal ingested: {total} players")


if __name__ == "__main__":
    main()
