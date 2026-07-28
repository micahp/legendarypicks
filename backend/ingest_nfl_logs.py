#!/usr/bin/env python3
"""Shared ``player_game_logs`` schema.

The legacy NFL writer that used to live here is retired. It duplicated
``ingest_nfl_weekly_stats.py``, omitted the postseason, and replaced complete
rows with a legacy-keyed stats blob that erased snap-count and Next Gen
enrichment. This module remains because several league ingests import
``ensure_table``.

Executing this file is intentionally a no-op.
"""
import sqlite3


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
            game_type         TEXT,                -- 'REG' | 'POST' | NULL (populated from nfl_schedule)
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
