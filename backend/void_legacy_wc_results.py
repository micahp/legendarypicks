#!/usr/bin/env python3
"""Convert legacy null-result World Cup rows into explicit, auditable voids.

The legacy writer put ``settled_at`` on a prop_results row even when it had no
actual or hit.  A result row is terminal everywhere else, so this script moves
only that impossible World Cup shape into ``prop_voids`` and removes the false
result rows.  It is backup-first and requires an explicit existing absolute DB.
"""
from __future__ import annotations

import argparse
import os
import sqlite3

import migrate_schema


VOID_REASON = "legacy_world_cup_ungraded"
VOID_SCHEMA = """
CREATE TABLE IF NOT EXISTS prop_voids(
  prop_id INTEGER PRIMARY KEY REFERENCES props(id),
  reason TEXT NOT NULL,
  voided_at TEXT NOT NULL
);
"""


def _path(path: str) -> str:
    if not os.path.isabs(path) or not os.path.isfile(path):
        raise ValueError("--db must be an existing absolute database path")
    return path


def candidates(con: sqlite3.Connection) -> list[tuple[int, str]]:
    return con.execute("""
        SELECT r.prop_id, r.settled_at
        FROM prop_results r
        JOIN props p ON p.id=r.prop_id
        JOIN prop_games g ON g.id=p.game_id
        WHERE g.league='wc' AND r.actual_value IS NULL AND r.hit IS NULL
        ORDER BY r.prop_id
    """).fetchall()


def plan(path: str) -> dict:
    with sqlite3.connect("file:{}?mode=ro".format(_path(path)), uri=True) as con:
        rows = candidates(con)
    return {"candidates": len(rows), "first_prop_id": rows[0][0] if rows else None}


def apply(path: str) -> dict:
    path = _path(path)
    before = plan(path)
    backup = migrate_schema.create_verified_backup(path)
    with sqlite3.connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.executescript(VOID_SCHEMA)
            rows = candidates(con)
            for prop_id, settled_at in rows:
                con.execute(
                    "INSERT OR IGNORE INTO prop_voids(prop_id,reason,voided_at) VALUES(?,?,?)",
                    (prop_id, VOID_REASON, settled_at),
                )
            ids = [row[0] for row in rows]
            if ids:
                con.execute("DELETE FROM prop_results WHERE prop_id IN ({})".format(
                    ",".join("?" for _ in ids)), ids)
            con.commit()
        except Exception:
            con.rollback()
            raise
        voids = con.execute("SELECT count(*) FROM prop_voids WHERE reason=?", (VOID_REASON,)).fetchone()[0]
        left = len(candidates(con))
        integrity = con.execute("PRAGMA quick_check").fetchone()[0]
    if integrity != "ok" or left:
        raise RuntimeError("post-apply verification failed: quick_check={} candidates={}".format(integrity, left))
    return {**before, "backup": backup, "voids": voids, "quick_check": integrity}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(plan(args.db) if args.check else apply(args.db))
    except (ValueError, RuntimeError, sqlite3.Error) as exc:
        print("ERROR: {}".format(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
