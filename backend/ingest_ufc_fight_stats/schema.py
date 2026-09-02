"""SQLite schema and connection helpers for the UFC fight-stat ingest."""
from __future__ import annotations

import os
import sqlite3
from urllib.parse import quote

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)

def ensure_table(con: sqlite3.Connection) -> None:
    """Create the shared log table/indexes inside the caller's transaction."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS player_game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id         INTEGER,
            league            TEXT NOT NULL,
            season            INTEGER NOT NULL,
            game_no           TEXT,
            game_id           TEXT,
            game_date         TEXT,
            team              TEXT,
            opponent          TEXT,
            home_away         TEXT,
            stats             TEXT NOT NULL,
            source            TEXT,
            source_player_key TEXT,
            ingested_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(league, source_player_key, season, game_no)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pgl_player "
        "ON player_game_logs(player_id, league, season, game_no)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pgl_league_date "
        "ON player_game_logs(league, game_date)"
    )

def _read_only_connection(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    uri = "file:{}?mode=ro".format(quote(absolute, safe="/"))
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con
