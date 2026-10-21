#!/usr/bin/env python3
"""Give each provider its own table, and one row per appearance back to `player_game_logs`.

WHY. FotMob was first MERGED into the ESPN row, which put FotMob-sourced tackles on a
row stamped `source='espn'` -- the column named the row's creator, not each field's
origin. That was reverted. The replacement kept both providers in ONE table as one row
each, which duplicated every shared appearance (2,609 on dev, 2,045 on prod) and forced
a `ROW_NUMBER() PARTITION BY game_date` in the reader to hide it. A duplication the
reader has to ignore is still a duplication, and every one of the 20+ other consumers of
this table would have to learn the same rule.

WHAT. `player_game_logs` returns to ESPN-only: one row per appearance, the shape every
existing reader already assumes. FotMob's rows move to `player_game_logs_fotmob`, keyed
the same way, including the rows whose player never resolved. A view joins them, so a
value's origin is the COLUMN it came from -- no stamp to maintain, nothing to drift.

Adding a third provider is a third table, not a migration of this one.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

from player_game_logs_view import (
    DDL_VIEW as NBA_PROVIDER_DDL_VIEW,
    ROTOWIRE_DDL_VIEW,
)

FOTMOB = "player_game_logs_fotmob"
VIEW = "player_game_logs_all"

DDL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FOTMOB} (
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
    game_type         TEXT,
    UNIQUE(league, source_player_key, season, game_no)
);
CREATE INDEX IF NOT EXISTS idx_pglf_player_date ON {FOTMOB}(player_id, game_date);
CREATE INDEX IF NOT EXISTS idx_pglf_league_date ON {FOTMOB}(league, game_date);
"""

# One row per appearance. ESPN's line and FotMob's line sit in SEPARATE columns, so a
# field's provenance is the column it was read from. The second leg carries appearances
# only FotMob saw -- a LEFT JOIN alone would silently drop them, and SQLite has no FULL
# OUTER JOIN.
DDL_VIEW = f"DROP VIEW IF EXISTS {VIEW};\n{NBA_PROVIDER_DDL_VIEW};"


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# The production columns of `player_game_logs`. Tests import this so a fixture
# cannot declare a NARROWER table than the one that ships: a fixture is a claim
# about the schema, and a fixture missing `source` already described a world
# where the reader could not tell two providers apart.
ESPN_COLUMNS = (
    ("player_id", "INTEGER"), ("league", "TEXT"), ("season", "INTEGER"),
    ("game_no", "TEXT"), ("game_id", "TEXT"), ("game_date", "TEXT"),
    ("team", "TEXT"), ("opponent", "TEXT"), ("home_away", "TEXT"),
    ("stats", "TEXT"), ("source", "TEXT"), ("source_player_key", "TEXT"),
    ("ingested_at", "TEXT"), ("game_type", "TEXT"),
)


def ensure_espn_columns(con):
    """Add any production column `player_game_logs` is missing. Never drops."""
    have = {r[1] for r in con.execute("PRAGMA table_info(player_game_logs)")}
    for name, kind in ESPN_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE player_game_logs ADD COLUMN {name} {kind}")

COLS = ("player_id", "league", "season", "game_no", "game_id", "game_date", "team",
        "opponent", "home_away", "stats", "source", "source_player_key",
        "ingested_at", "game_type")


def report(con):
    q = con.execute
    return {
        "pgl rows": q("SELECT COUNT(*) FROM player_game_logs").fetchone()[0],
        "pgl fotmob rows": q("SELECT COUNT(*) FROM player_game_logs WHERE source='fotmob'").fetchone()[0],
        "doubled appearances": q(
            "SELECT COUNT(*) FROM (SELECT player_id, game_date FROM player_game_logs"
            " WHERE player_id IS NOT NULL GROUP BY 1,2 HAVING COUNT(DISTINCT source)>1)").fetchone()[0],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    before = report(con)
    print(f"{args.db}")
    for k, v in before.items():
        print(f"  {k:22s} {v}")

    if args.check:
        print("  check only -- nothing written")
        return 0

    for required in ("player_game_logs_sportsdataverse", "nba_sportsdataverse_releases"):
        if not _table_exists(con, required):
            raise SystemExit(
                "required schema is missing; apply migrate_schema.py first: " + required
            )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{args.db}.pre-provider-split-{stamp}.bak"
    con.execute("VACUUM INTO ?", (backup,))
    ok = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={ok})")
    if ok != "ok":
        raise SystemExit("backup failed quick_check; nothing moved")

    con.executescript(DDL_TABLE)
    cols = ", ".join(COLS)
    con.execute("BEGIN IMMEDIATE")
    moved = con.execute(
        f"INSERT OR IGNORE INTO {FOTMOB} ({cols}) SELECT {cols} FROM player_game_logs"
        " WHERE source='fotmob'").rowcount
    # Only delete what is now provably held in the new table, keyed on the row's own
    # identity rather than on a count. A row that failed to copy stays where it is.
    deleted = con.execute(
        f"DELETE FROM player_game_logs WHERE source='fotmob' AND EXISTS ("
        f" SELECT 1 FROM {FOTMOB} f WHERE f.league=player_game_logs.league"
        "  AND f.source_player_key IS player_game_logs.source_player_key"
        "  AND f.season=player_game_logs.season"
        "  AND f.game_no IS player_game_logs.game_no)").rowcount
    con.commit()
    view_ddl = DDL_VIEW
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='player_game_logs_rotowire'"
    ).fetchone():
        view_ddl = f"DROP VIEW IF EXISTS {VIEW};\n{ROTOWIRE_DDL_VIEW};"
    con.executescript(view_ddl)
    con.commit()

    after = report(con)
    left = con.execute(f"SELECT COUNT(*) FROM {FOTMOB}").fetchone()[0]
    print(f"  moved={moved}  deleted={deleted}  {FOTMOB} now holds {left}")
    for k, v in after.items():
        print(f"  after {k:16s} {v}")
    if after["pgl fotmob rows"]:
        print(f"  WARNING: {after['pgl fotmob rows']} fotmob rows could NOT be moved and were left in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
