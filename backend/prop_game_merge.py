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


def shared_match_keys(con: sqlite3.Connection) -> List[dict]:
    """Rows that share `(league, date, home, away)`, classified.

    That tuple is the key both ingest paths match an existing fixture on, and it
    CANNOT DISTINGUISH A DOUBLEHEADER FROM A DUPLICATE. Two rows share it either
    because the same game was stored twice, or because the same two clubs really
    did play twice on one local day. Both look identical to the ingest, which
    picks one arbitrarily.

    Measured 2026-08-19, when re-dating every row onto the local slate day made
    five such pairs collide at once: four were one game stored twice and one was
    real. ESPN settled it -- the 07-27 Reds/Guardians game was Postponed and
    replayed as two games on 07-28.

    The published final score is what separates them, and it is the only thing
    that does. Two rows for one game carry the same final; a doubleheader's two
    games do not. So:

      duplicate     finals agree (or one side has not been settled yet)
      doubleheader  finals disagree, both settled

    Returns the classification rather than acting on it. Folding merges props
    and needs `dedupe_props.py` behind it, which is a decision, not a cleanup.
    """
    groups: dict = {}
    for row in con.execute(
            "SELECT id, league, date, home, away, start_time, final_home, final_away "
            "FROM prop_games ORDER BY id"):
        groups.setdefault(tuple(row[1:5]), []).append(row)

    out = []
    for key, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        finals = {(r["final_home"], r["final_away"]) for r in rows}
        settled = [f for f in finals if f[0] is not None and f[1] is not None]
        verdict = ("doubleheader" if len(settled) > 1 and len(finals) > 1
                   else "duplicate")
        out.append({
            "league": key[0], "date": key[1], "home": key[2], "away": key[3],
            "ids": [r["id"] for r in rows],
            "finals": sorted(finals, key=str),
            "starts": sorted(str(r["start_time"]) for r in rows),
            "verdict": verdict,
        })
    return out


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


if __name__ == "__main__":
    import os
    import sys

    db = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    shared = shared_match_keys(connection)
    dangling = dangling_source_mappings(connection)
    print("database: %s" % db)
    print("rows sharing (league, date, home, away): %d" % len(shared))
    for group in shared:
        print("  %-13s %-6s %s  %s @ %s  ids=%s finals=%s"
              % (group["verdict"], group["league"], group["date"],
                 group["away"], group["home"], group["ids"], group["finals"]))
    print("dangling source mappings: %d" % len(dangling))
    dupes = [g for g in shared if g["verdict"] == "duplicate"]
    # A doubleheader is not a defect. A duplicate is, and so is a mapping whose
    # game was deleted -- that one made the UFC timer fail every 30 minutes for
    # two hours reading a deleted row as a changed identity.
    sys.exit(1 if (dupes or dangling) else 0)
