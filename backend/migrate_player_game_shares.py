#!/usr/bin/env python3
"""Create the per-game share tables (idempotent).

``nfl_team_game_totals`` holds nflverse's published team totals, the denominator
for every share. ``player_game_shares`` holds one row per (game, player, metric).
Shares are copied from the publisher where it publishes them; the carry share is
derived from published carries and is labelled as such in ``source``.
"""

import os
import sqlite3


def migrate(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS nfl_team_game_totals (
            league      TEXT NOT NULL,
            season      INTEGER NOT NULL,
            week        INTEGER NOT NULL,
            game_id     TEXT NOT NULL,
            team        TEXT NOT NULL,           -- ESPN vocabulary (LAR, WSH)
            carries     REAL,
            targets     REAL,
            air_yards   REAL,               -- team PASSING air yards (published as receiving_air_yards)
            air_yards_unassigned REAL,      -- air_yards minus the air yards assigned to logged players
            source      TEXT NOT NULL,
            sha256      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (league, game_id, team)
        )""")
    if "air_yards_unassigned" not in {r[1] for r in con.execute("PRAGMA table_info(nfl_team_game_totals)")}:
        con.execute("ALTER TABLE nfl_team_game_totals ADD COLUMN air_yards_unassigned REAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS player_game_shares (
            league       TEXT NOT NULL,
            season       INTEGER NOT NULL,
            week         INTEGER NOT NULL,
            game_id      TEXT NOT NULL,
            team         TEXT NOT NULL,
            player_id    INTEGER NOT NULL,
            metric       TEXT NOT NULL,          -- 'targets' | 'air_yards' | 'carries'
            share        REAL,                   -- NULL when the team total is 0
            player_value REAL NOT NULL,
            team_value   REAL,
            source       TEXT NOT NULL,          -- 'nflverse_weekly' (copied) | 'derived_carries'
            built_at     TEXT NOT NULL,
            PRIMARY KEY (league, game_id, team, player_id, metric)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pgs_player "
                "ON player_game_shares(league, player_id, season)")
    con.commit()


if __name__ == "__main__":
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        raise SystemExit("LP_DB_PATH is required")
    connection = sqlite3.connect(db_path)
    migrate(connection)
    connection.close()
    print("player_game_shares and nfl_team_game_totals ready")
