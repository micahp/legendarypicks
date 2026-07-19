#!/usr/bin/env python3
"""Add the nullable prop_games.start_time column to production picks.db.

Idempotent and backs up prod before touching it, matching the migrate_*_to_prod.py pattern.
`start_time` is written by bovada_scraper.py and routers/props.py but was never in the canonical
_core.py CREATE TABLE (dev had it via an ad-hoc ALTER; prod predated it), so the prod props ingest
failed with `no such column: start_time`. This codifies it on the existing prod DB.
"""
import argparse
import datetime
import sqlite3
import sys

DEFAULT_PROD = "data/picks.db"


def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def migrate(prod_path: str = DEFAULT_PROD):
    with sqlite3.connect(prod_path) as prod:
        if not _has_table(prod, "prop_games"):
            raise RuntimeError(f"{prod_path} has no prop_games table")
        if _has_column(prod, "prop_games", "start_time"):
            print("prop_games.start_time already present — nothing to do")
            return None

        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = f"{prod_path}.bak-premigrate-propstart-{timestamp}"
        with sqlite3.connect(backup_path) as backup:
            prod.backup(backup)
        try:
            with prod:
                prod.execute("ALTER TABLE prop_games ADD COLUMN start_time TEXT")
                if not _has_column(prod, "prop_games", "start_time"):
                    raise RuntimeError("ALTER reported success but column is absent")
        except Exception:
            print(f"migration failed; untouched backup is at {backup_path}", file=sys.stderr)
            raise

    print(f"backed up prod -> {backup_path}")
    print("prop_games: added nullable start_time column")
    return backup_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod", default=DEFAULT_PROD)
    args = parser.parse_args()
    migrate(args.prod)


if __name__ == "__main__":
    main()
