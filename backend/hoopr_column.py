"""Name of the players column that holds the legacy hoopR athlete id.

The column was `players.nba_id`. It never held an official NBA.com id. It holds
hoopR's athlete_id, which is ESPN's athlete id. `migrate_players_hoopr_id.py`
renames it to `hoopr_id`. Production keeps the old name until that migration
is approved there, so code that must run on both databases asks this module
for the name instead of hard-coding either one.

Official NBA.com ids live in `player_source_ids` (source = 'nba.com').
"""
from __future__ import annotations

import sqlite3
from typing import Optional

NEW_NAME = "hoopr_id"
OLD_NAME = "nba_id"


def hoopr_column(con: sqlite3.Connection) -> Optional[str]:
    """Return 'hoopr_id', 'nba_id', or None if players has neither."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    if NEW_NAME in columns and OLD_NAME in columns:
        raise RuntimeError("players has both hoopr_id and nba_id; "
                           "run migrate_players_hoopr_id.py to resolve it")
    if NEW_NAME in columns:
        return NEW_NAME
    if OLD_NAME in columns:
        return OLD_NAME
    return None
