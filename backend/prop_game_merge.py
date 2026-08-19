#!/usr/bin/env python3
"""Folding one prop_games row into another, with everything that pointed at it.

Why this exists: on 2026-08-19 the Underdog UFC timer failed every 30 minutes for
two hours with `SourceIdentityConflict: source game key 291703 conflicts with
canonical fighters`. The fighters were fine. Game 1235 (Anthony Wint vs Terrance
Chatman) had been folded into game 1234, and the fold repointed `props` but left
`prop_game_source_ids` pointing at a row that no longer existed. The guard read a
deleted game as a changed identity and refused, correctly by its own logic and
wrongly in fact.

Three call sites did the same two statements by hand (`link_prop_games`,
`dedupe_prop_games`, `routers/props.py`), and each one knew about `props` only,
because `props` is the table you think of. A fold has to move every reference, so
it lives in one function and the list of tables lives with it.

Add to `_REFERENCING_TABLES` when a new table keys on `prop_games.id`.
"""
import sqlite3
from typing import List, Tuple


# (table, column) pairs whose value is a prop_games.id. Verified 2026-08-19
# against both DBs: no other table references prop_games, and the many other
# `game_id` columns hold ESPN event ids, not our row ids.
_REFERENCING_TABLES: List[Tuple[str, str]] = [
    ("props", "game_id"),
    ("prop_game_source_ids", "game_id"),
]


def fold_prop_game(con: sqlite3.Connection, loser_id: int, winner_id: int) -> int:
    """Repoint every reference from ``loser_id`` to ``winner_id``, drop the loser.

    Returns the surviving id so callers can use it directly. A no-op when the two
    ids are the same, so it is safe to call defensively.
    """
    if loser_id == winner_id:
        return winner_id
    for table, column in _REFERENCING_TABLES:
        if not _table_exists(con, table):
            continue
        con.execute(
            "UPDATE {t} SET {c}=? WHERE {c}=?".format(t=table, c=column),
            (winner_id, loser_id),
        )
    con.execute("DELETE FROM prop_games WHERE id=?", (loser_id,))
    return winner_id


def dangling_source_mappings(con: sqlite3.Connection) -> List[sqlite3.Row]:
    """Source-key mappings whose game row is gone. Should always be empty."""
    if not _table_exists(con, "prop_game_source_ids"):
        return []
    return con.execute(
        "SELECT s.id, s.source, s.league, s.source_game_key, s.game_id "
        "FROM prop_game_source_ids s "
        "LEFT JOIN prop_games g ON g.id=s.game_id "
        "WHERE g.id IS NULL"
    ).fetchall()


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None
