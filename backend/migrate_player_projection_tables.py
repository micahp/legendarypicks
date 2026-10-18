#!/usr/bin/env python3
"""migrate_player_projection_tables.py -- tables for Spec B section 6 (player projections and grades).

Idempotent: CREATE ... IF NOT EXISTS only. Creates `player_projections` and `player_projection_grades`.
`model_runs` belongs to SPEC A's migration (migrate_nfl_model_tables.py); this one only reads it and
refuses to run without it, so the two migrations never create it twice.

player_projections: one row per (run, game, player, stat, scenario, model_version).
  scenario       'base' (blended over the report), 'if_plays' (every Questionable teammate plays),
                 'if_out' (every Questionable teammate is out)
  model_version  'v2' (this engine), 'marcel-lite', or 'espn-weekly' (ESPN's published projection)
  source         'lp' or 'espn'
  p_plays        P(this player plays): 1.0 listed healthy, the fitted rate if Questionable
  The mean is conditional on playing, as are the quantiles; p_plays is how to weight the game.

player_projection_grades: one row per graded projection. `played` = 0 rows carry no error: a projection
conditional on playing is not wrong when the player does not play.

Usage: LP_DB_PATH=/abs/path/picks.dev.db python3 migrate_player_projection_tables.py
"""
import os
import sqlite3
import sys

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS player_projections (
        run_id TEXT NOT NULL,
        league TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        game_id TEXT NOT NULL,
        player_id INTEGER NOT NULL,
        team TEXT NOT NULL,
        stat TEXT NOT NULL,
        mean REAL NOT NULL,
        median REAL,
        p10 REAL,
        p90 REAL,
        scenario TEXT NOT NULL CHECK (scenario IN ('base', 'if_plays', 'if_out')),
        model_version TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'lp',
        p_plays REAL,
        as_of TEXT NOT NULL,
        PRIMARY KEY (run_id, game_id, player_id, stat, scenario, model_version))""",
    "CREATE INDEX IF NOT EXISTS idx_pp_game ON player_projections(league, season, week, game_id)",
    "CREATE INDEX IF NOT EXISTS idx_pp_player ON player_projections(league, player_id, season, week)",
    """CREATE TABLE IF NOT EXISTS player_projection_grades (
        run_id TEXT NOT NULL,
        league TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        game_id TEXT NOT NULL,
        player_id INTEGER NOT NULL,
        stat TEXT NOT NULL,
        scenario TEXT NOT NULL,
        model_version TEXT NOT NULL,
        mean REAL NOT NULL,
        actual REAL,
        error REAL,
        abs_error REAL,
        played INTEGER NOT NULL CHECK (played IN (0, 1)),
        in_band INTEGER,
        graded_at TEXT NOT NULL,
        PRIMARY KEY (run_id, game_id, player_id, stat, scenario, model_version))""",
    "CREATE INDEX IF NOT EXISTS idx_ppg_week ON player_projection_grades(league, season, week, model_version)",
]


def migrate(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_runs'").fetchone() is None:
        raise RuntimeError("model_runs is missing: run migrate_nfl_model_tables.py first (SPEC A owns it)")
    for sql in STATEMENTS:
        con.execute(sql)
    con.commit()


def main():
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect(path)
    try:
        migrate(con)
    finally:
        con.close()
    print("OK migrated player_projections, player_projection_grades")


if __name__ == "__main__":
    sys.exit(main())
