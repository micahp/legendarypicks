#!/usr/bin/env python3
"""migrate_cbs_projection_table.py -- create external_projections, the table for third-party weekly projections.

One row per (source, season, week, scoring, position, player, team, stat, fetched_at): a published projection as it
was fetched. value_text keeps the cell as published; value is the number when the cell is one.

Idempotent: CREATE ... IF NOT EXISTS. Nothing is dropped and no existing table is altered.
The production database (a path ending in picks.db) needs --allow-prod, as lock_nfl_models.py does.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python migrate_cbs_projection_table.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS external_projections (
        source TEXT NOT NULL,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        scoring TEXT NOT NULL,
        position TEXT NOT NULL,
        player TEXT NOT NULL,
        team TEXT NOT NULL,
        stat TEXT NOT NULL,
        value_text TEXT,
        value REAL,
        fetched_at_utc TEXT NOT NULL,
        url TEXT NOT NULL,
        PRIMARY KEY (source, season, week, scoring, position, player, team, stat, fetched_at_utc)
    )""",
    """CREATE INDEX IF NOT EXISTS external_projections_lookup
        ON external_projections (source, season, week, position, player)""",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--allow-prod", action="store_true",
                    help="required to write the production database (LP_DB_PATH ending in picks.db)")
    a = ap.parse_args(argv)
    if os.path.basename(os.path.normpath(DB)) == "picks.db" and not a.allow_prod:
        raise SystemExit("refusing the production database %s without --allow-prod" % DB)
    con = sqlite3.connect(DB, timeout=60)
    try:
        for stmt in STATEMENTS:
            con.execute(stmt)
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM external_projections").fetchone()[0]
        print("external_projections ready in %s (%d rows)" % (DB, n))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
