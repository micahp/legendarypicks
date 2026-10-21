#!/usr/bin/env python3
"""Add provider-separated RotoWire soccer logs and extend the appearance view."""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

from player_game_logs_view import ROTOWIRE_DDL_VIEW


TABLE = "player_game_logs_rotowire"
VIEW = "player_game_logs_all"

DDL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id             INTEGER,
    league                TEXT NOT NULL,
    season                INTEGER NOT NULL,
    game_no               TEXT,
    game_id               TEXT,
    game_date             TEXT,
    team                  TEXT,
    opponent              TEXT,
    home_away             TEXT,
    stats                 TEXT NOT NULL,
    source                TEXT NOT NULL DEFAULT 'rotowire',
    source_player_key     TEXT NOT NULL,
    ingested_at           TEXT NOT NULL DEFAULT (datetime('now')),
    game_type             TEXT,
    source_matchweek      INTEGER NOT NULL,
    source_position_filters TEXT NOT NULL,
    UNIQUE(league, source_player_key, season, game_no)
);
CREATE INDEX IF NOT EXISTS idx_pglr_player_date
    ON {TABLE}(player_id, game_date);
CREATE INDEX IF NOT EXISTS idx_pglr_league_date
    ON {TABLE}(league, game_date);
"""

DDL_VIEW = f"DROP VIEW IF EXISTS {VIEW};\n{ROTOWIRE_DDL_VIEW};"


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def status(con):
    columns = {row[1] for row in con.execute(f"PRAGMA table_info({VIEW})")}
    return {
        "table": _table_exists(con, TABLE),
        "view_has_rotowire": "rotowire_stats" in columns,
    }


def apply_schema(con):
    for required in (
        "player_game_logs", "player_game_logs_fotmob",
        "player_game_logs_sportsdataverse", "nba_sportsdataverse_releases",
    ):
        if not _table_exists(con, required):
            raise RuntimeError(
                f"required table {required!r} is missing; apply migrate_schema.py first"
            )
    con.executescript("BEGIN IMMEDIATE;\n" + DDL_TABLE + DDL_VIEW + "\nCOMMIT;")


def _backup(con, path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = f"{path}.pre-rotowire-soccer-{stamp}.bak"
    backup = sqlite3.connect(backup_path)
    try:
        con.backup(backup)
        check = backup.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        backup.close()
    if check != "ok":
        raise RuntimeError(f"backup failed quick_check: {check}")
    return backup_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isabs(args.db):
        parser.error("--db must be an absolute path")
    path = os.path.abspath(args.db)
    if not os.path.isfile(path):
        parser.error(f"database must already exist: {path}")
    con = sqlite3.connect(path)
    try:
        before = status(con)
        print(path)
        print(f"  {TABLE}: {'present' if before['table'] else 'missing'}")
        print("  player_game_logs_all.rotowire_stats: "
              f"{'present' if before['view_has_rotowire'] else 'missing'}")
        if args.check:
            print("  check only -- nothing written")
            return 0 if all(before.values()) else 1
        backup = _backup(con, path)
        print(f"  backup: {backup} (quick_check=ok)")
        apply_schema(con)
        after = status(con)
        check = con.execute("PRAGMA quick_check").fetchone()[0]
        if not all(after.values()) or check != "ok":
            raise RuntimeError(
                f"migration postcondition failed: status={after}, quick_check={check}")
        print("  applied; provider table and view column are present")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
