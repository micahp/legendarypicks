#!/usr/bin/env python3
"""migrate_nfl_model_tables.py -- create the NFL model tables defined by SPEC A, section 7.

Idempotent: every statement is CREATE ... IF NOT EXISTS. Running it twice changes nothing.
Columns are exactly those named in the spec; the test suite compares them to the spec's list.
Nothing is dropped and no existing table is altered.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python migrate_nfl_model_tables.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")

SEEDS = [1, 2, 3, 4, 5, 6, 7]
SEED_COLS = ", ".join("p_seed_%d REAL" % k for k in SEEDS)

STATEMENTS = [
    # One row per model run: tuning grid points, holdouts, weekly runs.
    """CREATE TABLE IF NOT EXISTS model_runs (
        run_id TEXT PRIMARY KEY,
        league TEXT NOT NULL,
        season INTEGER,
        week INTEGER,
        model TEXT NOT NULL,
        model_version TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        params_json TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT)""",
    """CREATE TABLE IF NOT EXISTS team_ratings (
        run_id TEXT NOT NULL,
        league TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        team TEXT NOT NULL,
        "off" REAL,
        "def" REAL,
        overall REAL,
        games INTEGER,
        as_of TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS idx_team_ratings_run ON team_ratings(run_id)""",
    # Game projections. A game has at most one locked row, enforced by the partial index.
    """CREATE TABLE IF NOT EXISTS game_projections (
        run_id TEXT NOT NULL,
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        home TEXT NOT NULL,
        away TEXT NOT NULL,
        proj_home REAL,
        proj_away REAL,
        proj_margin REAL NOT NULL,
        proj_total REAL NOT NULL,
        p_home_win REAL NOT NULL,
        market_spread REAL,
        market_total REAL,
        market_source TEXT,
        locked INTEGER NOT NULL,
        locked_at TEXT NOT NULL)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_game_projections_locked
        ON game_projections(league, game_id, locked) WHERE locked = 1""",
    """CREATE INDEX IF NOT EXISTS idx_game_projections_week
        ON game_projections(league, season, week)""",
    # Playoff odds per team per run.
    """CREATE TABLE IF NOT EXISTS playoff_odds (
        run_id TEXT NOT NULL,
        league TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        team TEXT NOT NULL,
        p_playoffs REAL,
        p_division REAL,
        p_bye REAL,
        %s,
        wins_mean REAL,
        wins_p10 REAL,
        wins_p90 REAL,
        d_playoffs REAL,
        as_of TEXT NOT NULL)""" % SEED_COLS,
    """CREATE INDEX IF NOT EXISTS idx_playoff_odds_run ON playoff_odds(run_id)""",
    # Public grading, one row per graded game per model version.
    """CREATE TABLE IF NOT EXISTS projection_grades (
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        actual_home REAL,
        actual_away REAL,
        brier REAL,
        logloss REAL,
        margin_err REAL,
        total_err REAL,
        ats_result TEXT,
        graded_at TEXT NOT NULL)""",
]

EXPECTED_COLUMNS = {
    "model_runs": ["run_id", "league", "season", "week", "model", "model_version", "started_at",
                   "finished_at", "params_json", "status", "error"],
    "team_ratings": ["run_id", "league", "season", "week", "team", "off", "def", "overall",
                     "games", "as_of"],
    "game_projections": ["run_id", "league", "game_id", "season", "week", "home", "away",
                         "proj_home", "proj_away", "proj_margin", "proj_total", "p_home_win",
                         "market_spread", "market_total", "market_source", "locked", "locked_at"],
    "playoff_odds": ["run_id", "league", "season", "week", "team", "p_playoffs", "p_division",
                     "p_bye"] + ["p_seed_%d" % k for k in SEEDS] +
                    ["wins_mean", "wins_p10", "wins_p90", "d_playoffs", "as_of"],
    "projection_grades": ["league", "game_id", "model_version", "actual_home", "actual_away",
                          "brier", "logloss", "margin_err", "total_err", "ats_result",
                          "graded_at"],
}


def migrate(con):
    for stmt in STATEMENTS:
        con.execute(stmt)
    con.commit()


def columns(con, table):
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % table).fetchall()]


def main(argv=None):
    con = sqlite3.connect(DB, timeout=30)
    try:
        migrate(con)
        for table, want in EXPECTED_COLUMNS.items():
            got = columns(con, table)
            if got != want:
                raise SystemExit("%s columns differ from spec: got %s" % (table, got))
        print("ok: %s" % DB)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
