#!/usr/bin/env python3
"""Explicit migration for provider-separated UFCStats fight logs."""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import quote


MIGRATION_ID = "20260829_001_ufcstats_game_logs"
TABLE = "player_game_logs_ufcstats"
TABLE_SQL = """
CREATE TABLE player_game_logs_ufcstats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id         INTEGER NOT NULL REFERENCES players(id),
    league            TEXT NOT NULL CHECK(league='ufc'),
    season            INTEGER NOT NULL,
    game_no           TEXT NOT NULL,
    game_id           TEXT NOT NULL,
    game_date         TEXT NOT NULL,
    opponent          TEXT NOT NULL,
    stats             TEXT NOT NULL,
    source            TEXT NOT NULL CHECK(source='ufcstats'),
    source_player_key TEXT NOT NULL,
    source_event_key  TEXT NOT NULL,
    ingested_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_player_key, game_id)
)
""".strip()
INDEX_SQL = (
    "CREATE INDEX idx_pgl_ufcstats_player_date "
    "ON player_game_logs_ufcstats(player_id, game_date)",
    "CREATE INDEX idx_pgl_ufcstats_fight "
    "ON player_game_logs_ufcstats(game_id)",
)
CHECKSUM = hashlib.sha256(
    (TABLE_SQL + "\n" + "\n".join(INDEX_SQL)).encode("utf-8")
).hexdigest()
EXPECTED_COLUMNS = (
    "id", "player_id", "league", "season", "game_no", "game_id",
    "game_date", "opponent", "stats", "source", "source_player_key",
    "source_event_key", "ingested_at",
)


class MigrationError(RuntimeError):
    pass


def _absolute_database(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.stat().st_size <= 0:
        raise MigrationError("database must be an absolute existing non-empty file: {}".format(path))
    return str(candidate)


def _read_only(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(
        "file:{}?mode=ro".format(quote(path, safe="/")), uri=True
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def inspect(path: str) -> dict:
    absolute = _absolute_database(path)
    with closing(_read_only(absolute)) as con:
        quick_check = con.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            return {"path": absolute, "state": "error", "detail": "quick_check={}".format(quick_check)}
        if not _table_exists(con, TABLE):
            return {"path": absolute, "state": "pending", "detail": "{} is missing".format(TABLE)}
        columns = tuple(row["name"] for row in con.execute("PRAGMA table_info({})".format(TABLE)))
        if columns != EXPECTED_COLUMNS:
            return {
                "path": absolute,
                "state": "error",
                "detail": "wrong columns: {}".format(",".join(columns)),
            }
        index_names = {
            row["name"] for row in con.execute("PRAGMA index_list({})".format(TABLE))
        }
        missing_indexes = {
            "idx_pgl_ufcstats_player_date", "idx_pgl_ufcstats_fight"
        } - index_names
        if missing_indexes:
            return {
                "path": absolute,
                "state": "error",
                "detail": "missing indexes: {}".format(",".join(sorted(missing_indexes))),
            }
        if not _table_exists(con, "app_schema_migrations"):
            return {"path": absolute, "state": "error", "detail": "migration registry is missing"}
        row = con.execute(
            "SELECT checksum FROM app_schema_migrations WHERE migration_id=?",
            (MIGRATION_ID,),
        ).fetchone()
        if row is None:
            return {"path": absolute, "state": "adopt", "detail": "schema exists without registry row"}
        if row["checksum"] != CHECKSUM:
            return {"path": absolute, "state": "error", "detail": "migration checksum mismatch"}
        return {"path": absolute, "state": "applied", "detail": "checksum={}".format(CHECKSUM)}


def _verify_backup(source: str, backup: str) -> str:
    candidate = Path(backup)
    if not candidate.is_absolute() or not candidate.is_file() or candidate.stat().st_size <= 0:
        raise MigrationError("backup must be an absolute existing non-empty file")
    if os.path.samefile(source, str(candidate)):
        raise MigrationError("backup must differ from the target database")
    with closing(_read_only(str(candidate))) as con:
        check = con.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise MigrationError("backup quick_check={}".format(check))
    return str(candidate)


def apply(path: str, backup: str) -> dict:
    absolute = _absolute_database(path)
    backup_path = _verify_backup(absolute, backup)
    before = inspect(absolute)
    if before["state"] == "error":
        raise MigrationError(before["detail"])
    con = sqlite3.connect(absolute, timeout=60)
    try:
        con.execute("BEGIN IMMEDIATE")
        if not _table_exists(con, "player_source_ids"):
            raise MigrationError("player_source_ids is required before UFCStats migration")
        if not _table_exists(con, "app_schema_migrations"):
            raise MigrationError("app_schema_migrations is required")
        if not _table_exists(con, TABLE):
            con.execute(TABLE_SQL)
            for statement in INDEX_SQL:
                con.execute(statement)
        con.execute(
            """INSERT INTO app_schema_migrations(migration_id,checksum,status,note)
               VALUES(?,?,'applied','provider-separated UFCStats fight history')
               ON CONFLICT(migration_id) DO UPDATE SET checksum=excluded.checksum,
                   status='applied',note=excluded.note""",
            (MIGRATION_ID, CHECKSUM),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    after = inspect(absolute)
    if after["state"] != "applied":
        raise MigrationError("post-migration verification failed: {}".format(after["detail"]))
    after["backup"] = backup_path
    return after


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args(argv)
    try:
        if args.check:
            result = inspect(args.db)
            print("database: {}".format(result["path"]))
            print("{} {}: {}".format(result["state"].upper(), MIGRATION_ID, result["detail"]))
            return 0 if result["state"] == "applied" else 1
        if not args.backup:
            parser.error("--apply requires --backup")
        result = apply(args.db, args.backup)
        print("database: {}".format(result["path"]))
        print("backup: {} (quick_check=ok)".format(result["backup"]))
        print("APPLIED {}: {}".format(MIGRATION_ID, result["detail"]))
        return 0
    except (MigrationError, sqlite3.Error) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
