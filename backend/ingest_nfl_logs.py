#!/usr/bin/env python3
"""
ingest_nfl_logs.py — per-GAME NFL player logs from nflverse weekly data.

Unlike ingest_nfl.py (which collapses weekly rows to season averages in
player_stats), this stores one row PER PLAYER PER GAME in player_game_logs.
Per-game logs are the foundation projections / form / matchup splits need —
season averages can't express recent form or game-to-game variance.

Usage: python3 ingest_nfl_logs.py [--year 2024] [--all]
  --all   ingest every season nflverse exposes (slower)
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Per-game stat columns to capture into the JSON stats blob (only those present).
STAT_COLS = [
    "passing_yards", "passing_tds", "interceptions", "completions", "attempts",
    "carries", "rushing_yards", "rushing_tds",
    "receptions", "targets", "receiving_yards", "receiving_tds",
    "fantasy_points", "fantasy_points_ppr",
]


def ensure_table(con: sqlite3.Connection) -> None:
    """Create player_game_logs (additive, idempotent). Sport-agnostic: per-game
    context columns + a JSON stats line so each league keeps its own metrics
    without a 60-column table."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS player_game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id         INTEGER,             -- FK players.id (spine); NULL if unresolved
            league            TEXT NOT NULL,
            season            INTEGER NOT NULL,
            game_no           TEXT,                -- week (NFL) / game seq within season
            game_id           TEXT,               -- source game id when available
            game_date         TEXT,               -- ISO date when available
            team              TEXT,
            opponent          TEXT,
            home_away         TEXT,                -- 'home' | 'away' | NULL
            stats             TEXT NOT NULL,       -- JSON per-game stat line
            source            TEXT,
            source_player_key TEXT,                -- gsis/athlete/mlbam/nhl id for re-resolution
            ingested_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(league, source_player_key, season, game_no)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pgl_player ON player_game_logs(player_id, league, season, game_no)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pgl_league_date ON player_game_logs(league, game_date)")
    # Team-wide stat sums (target share, carry share) look rows up by team+game,
    # never by player. Without these the usage endpoint scans every NFL row twice
    # per request — 70-100ms each, ~140x slower than the indexed lookup. Two
    # indexes because the 2024 rows carry no game_id and fall back to season+week.
    con.execute("CREATE INDEX IF NOT EXISTS idx_pgl_team_game ON player_game_logs(league, game_id, team)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pgl_team_season_game ON player_game_logs(league, season, game_no, team)")
    con.commit()


def ingest_nfl_logs(season: int) -> int:
    import warnings; warnings.filterwarnings("ignore")
    import nfl_data_py as nfl

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)

    # spine: gsis_id -> players.id
    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }

    print(f"Loading nflverse weekly {season}...")
    weekly = nfl.import_weekly_data([season])
    if "season_type" in weekly.columns:
        weekly = weekly[weekly["season_type"] == "REG"]  # regular season only
    cols = [c for c in STAT_COLS if c in weekly.columns]
    print(f"  {len(weekly)} regular-season player-weeks; {len(cols)} stat cols")

    ingested = 0
    for _, row in weekly.iterrows():
        gsis = str(row.get("player_id") or "")
        pid = gsis_to_player.get(gsis)
        stats = {}
        for c in cols:
            v = row[c]
            if v != v:  # NaN
                continue
            fv = float(v)
            stats[c] = int(fv) if fv.is_integer() else round(fv, 2)
        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "nfl", season, str(int(row["week"])), None, None,
             row.get("recent_team"), row.get("opponent_team"), None,
             json.dumps(stats), "nflverse", gsis))
        ingested += 1

    con.commit()
    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nfl' AND season=? AND player_id IS NOT NULL",
        (season,)).fetchone()[0]
    print(f"  Ingested {ingested} game-logs ({resolved} spine-resolved)")
    con.close()
    return ingested


if __name__ == "__main__":
    if "--all" in sys.argv:
        seasons = list(range(1999, 2025))
    else:
        year = 2024
        if "--year" in sys.argv:
            year = int(sys.argv[sys.argv.index("--year") + 1])
        elif len(sys.argv) > 1 and sys.argv[1].isdigit():
            year = int(sys.argv[1])
        seasons = [year]
    total = sum(ingest_nfl_logs(s) for s in seasons)
    print(f"Done. {total} total game-logs.")
