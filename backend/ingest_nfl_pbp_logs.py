#!/usr/bin/env python3
"""
ingest_nfl_pbp_logs.py — per-GAME NFL logs derived from nflverse play-by-play.

nflverse's pre-built weekly summary 404s for 2025, but the raw play-by-play IS
published (richer: per-play EPA, CPOE, air yards). This aggregates pbp into
per-player-per-game lines (passing / rushing / receiving + EPA) and writes them
to player_game_logs — the richest free option for the latest NFL season.

Usage: python3 ingest_nfl_pbp_logs.py [--year 2025]
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def ingest(year: int = 2025) -> int:
    import warnings; warnings.filterwarnings("ignore")
    import nfl_data_py as nfl
    import pandas as pd

    print(f"Loading nflverse pbp {year}...")
    df = nfl.import_pbp_data([year])
    df = df[df["season_type"] == "REG"] if "season_type" in df.columns else df
    print(f"  {len(df)} plays")

    keys = ["game_id", "week", "posteam", "defteam"]

    # Passing — group by passer per game
    pa = df[df["passer_player_id"].notna()].groupby(["passer_player_id"] + keys).agg(
        att=("pass_attempt", "sum"), cmp=("complete_pass", "sum"),
        pass_yds=("passing_yards", "sum"), pass_td=("pass_touchdown", "sum"),
        intc=("interception", "sum"), air_yds=("air_yards", "sum"),
        pass_epa=("qb_epa", "sum"), cpoe=("cpoe", "mean"),
        name=("passer_player_name", "first")).reset_index().rename(columns={"passer_player_id": "pid"})

    # Rushing
    ru = df[df["rusher_player_id"].notna()].groupby(["rusher_player_id"] + keys).agg(
        carries=("rush_attempt", "sum"), rush_yds=("rushing_yards", "sum"),
        rush_td=("rush_touchdown", "sum"),
        name=("rusher_player_name", "first")).reset_index().rename(columns={"rusher_player_id": "pid"})

    # Receiving — each play with a receiver = a target
    re = df[df["receiver_player_id"].notna()].groupby(["receiver_player_id"] + keys).agg(
        targets=("play_id", "count"), rec=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"), rec_td=("pass_touchdown", "sum"),
        name=("receiver_player_name", "first")).reset_index().rename(columns={"receiver_player_id": "pid"})

    merged = pa.merge(ru, on=["pid"] + keys, how="outer", suffixes=("", "_r")) \
               .merge(re, on=["pid"] + keys, how="outer", suffixes=("", "_e"))
    merged["name"] = merged["name"].fillna(merged.get("name_r")).fillna(merged.get("name_e"))
    print(f"  {len(merged)} player-game lines")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute("SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }

    # standard / PPR fantasy from the projected line
    def fpts(s, ppr=0.0):
        return round(
            s.get("pass_yds", 0) * 0.04 + s.get("pass_td", 0) * 4 - s.get("intc", 0) * 2
            + s.get("rush_yds", 0) * 0.1 + s.get("rush_td", 0) * 6
            + s.get("rec_yds", 0) * 0.1 + s.get("rec_td", 0) * 6 + s.get("rec", 0) * ppr, 2)

    STAT_FIELDS = ["att", "cmp", "pass_yds", "pass_td", "intc", "air_yds", "pass_epa", "cpoe",
                   "carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td"]
    ingested = 0
    for _, row in merged.iterrows():
        gsis = str(row["pid"])
        pid = gsis_to_player.get(gsis)
        s = {}
        for f in STAT_FIELDS:
            v = row.get(f)
            if v is None or v != v:  # NaN
                continue
            fv = float(v)
            s[f] = int(fv) if fv.is_integer() else round(fv, 2)
        s["fpts"] = fpts(s); s["fpts_ppr"] = fpts(s, 1.0)
        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "nfl", year, str(int(row["week"])), row["game_id"], None,
             row["posteam"], row["defteam"], None, json.dumps(s), "nflverse_pbp", gsis))
        ingested += 1

    con.commit()
    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nfl' AND season=? AND source='nflverse_pbp' AND player_id IS NOT NULL",
        (year,)).fetchone()[0]
    print(f"  Ingested {ingested} NFL pbp game-logs ({resolved} spine-resolved)")
    con.close()
    return ingested


if __name__ == "__main__":
    year = 2025
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(year)
