#!/usr/bin/env python3
"""
ingest_mlb_pitcher_logs.py — per-GAME MLB pitching logs derived from Statcast events.

Groups Statcast by (pitcher, game_pk), computing per-game pitching lines:
K, outs, hits_allowed, BB, batters_faced. Writes to player_game_logs with
source='statcast_pitcher'.

Identity: resolve pitcher mlbam_id → players.id via mlbam_to_player lookup.
RESOLVE-OR-QUEUE per AGENTS.md §7: if mlbam_id is not spine-resolved, skip the row
(do NOT create a dup players row, do NOT write a null-player-id log).

Usage: python3 ingest_mlb_pitcher_logs.py [--days 60]
"""
import sys, os, json, sqlite3, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table  # reuse the shared schema

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Events that result in outs (value = outs recorded on the play)
OUT_EVENTS = {
    "strikeout": 1,
    "field_out": 1,
    "force_out": 1,
    "grounded_into_double_play": 2,
    "double_play": 2,
    "sac_fly": 1,
    "sac_bunt": 1,
    "fielders_choice_out": 1,
    "caught_stealing_2b": 1,
    "caught_stealing_3b": 1,
    "caught_stealing_home": 1,
    "pickoff_1b": 1,
    "pickoff_2b": 1,
    "pickoff_3b": 1,
    "other_out": 1,
    "sac_fly_double_play": 2,
    "sac_bunt_double_play": 2,
}

HIT_EVENTS = {"single", "double", "triple", "home_run"}


def ingest(days: int = 60) -> int:
    from pybaseball import statcast
    import pandas as pd

    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    print(f"Pulling Statcast {s}..{e} (per-game pitcher derive)...")
    data = statcast(s, e)
    if data is None or len(data) == 0:
        print("No Statcast data."); return 0

    pit = data[data["events"].notna()].copy()
    n_events = len(pit)
    n_pitchers = pit["pitcher"].nunique()
    n_games = pit["game_pk"].nunique()
    print(f"  {n_events} PA-ending events, {n_pitchers} pitchers, {n_games} games")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    season = end.year

    # Build mlbam → player.id lookup (spine-resolved pitchers only)
    mlbam_to_player = {
        r["mlbam_id"]: r["id"]
        for r in con.execute(
            "SELECT mlbam_id, id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"
        )
    }
    print(f"  {len(mlbam_to_player)} spine-resolved mlbam ids")

    # Track what already exists (idempotent)
    existing = set(
        (r["player_id"], r["game_id"], r["source"])
        for r in con.execute(
            "SELECT player_id, game_id, source FROM player_game_logs WHERE league='mlb' AND source='statcast_pitcher'"
        )
    )

    ingested = 0
    skipped_no_pid = 0
    for (pitcher_mlbam, game_pk), g in pit.groupby(["pitcher", "game_pk"]):
        mlbam = int(pitcher_mlbam)
        pid = mlbam_to_player.get(mlbam)
        if pid is None:
            skipped_no_pid += 1
            continue  # resolve-or-queue — never create a dup

        game_pk_str = str(int(game_pk))
        if (pid, game_pk_str, "statcast_pitcher") in existing:
            continue  # idempotent

        ev_counts = g["events"].value_counts().to_dict()

        ks = int(ev_counts.get("strikeout", 0))
        hits = sum(int(ev_counts.get(e, 0)) for e in HIT_EVENTS)
        outs = sum(int(ev_counts.get(ev, 0)) * out_val for ev, out_val in OUT_EVENTS.items())
        bb = int(ev_counts.get("walk", 0))
        bf = int(len(g))

        stats = {
            "K": ks,
            "outs": outs,
            "hits_allowed": hits,
            "BB": bb,
            "batters_faced": bf,
        }

        gdate = str(g["game_date"].iloc[0])[:10]
        team = None
        if "inning_topbot" in g.columns and "home_team" in g.columns and "away_team" in g.columns:
            top = (g["inning_topbot"].iloc[0] == "Top")
            team = g["home_team"].iloc[0] if not top else g["away_team"].iloc[0]

        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "mlb", season, gdate, game_pk_str, gdate, team,
             None, None, json.dumps(stats), "statcast_pitcher", str(mlbam)))
        ingested += 1

    con.commit()
    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='mlb' AND source='statcast_pitcher' AND player_id IS NOT NULL"
    ).fetchone()[0]
    print(f"  Ingested {ingested} pitcher game-logs ({resolved} spine-resolved)")
    if skipped_no_pid:
        print(f"  Skipped {skipped_no_pid} pitcher-games (mlbam_id not spine-resolved — resolve-or-queue)")
    con.close()
    return ingested


if __name__ == "__main__":
    days = 60
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    ingest(days)
