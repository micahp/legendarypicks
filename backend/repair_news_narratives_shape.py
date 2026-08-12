#!/usr/bin/env python3
"""Bring a database's news_narratives to the conversation-keyed shape.

The additive migration framework cannot express this one. news_narratives was
redesigned from one row per LEAGUE (keyed `league`, carrying `points`) to one
row per CONVERSATION (keyed `conv_id`, carrying `title`/`fan_voice`/
`paragraph`), and a primary key cannot be reached by ALTER TABLE ADD COLUMN.
`news_league_summaries` belongs to the same superseded design and no longer
exists in the DDL at all.

Dev arrived at the new shape by being created after the redesign. Prod's table
predates it, so `CREATE TABLE IF NOT EXISTS` has been a no-op there ever since.

This drops and recreates rather than migrating rows, which is only defensible
because the tables are EMPTY. It refuses otherwise -- if a row ever appears,
whoever runs this needs to write a real backfill, not delete someone's data.

    python repair_news_narratives_shape.py            # dry run
    python repair_news_narratives_shape.py --apply
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

DB = os.environ.get("LP_DB_PATH", "data/picks.db")

# The canonical shape, identical to what _core.py creates on a fresh database.
NEWS_NARRATIVES_DDL = """
CREATE TABLE news_narratives(
  conv_id TEXT PRIMARY KEY,
  league TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  narrative TEXT NOT NULL,
  fan_voice TEXT NOT NULL DEFAULT '',
  paragraph TEXT NOT NULL DEFAULT '',
  sources TEXT NOT NULL DEFAULT '[]',
  source_count INTEGER NOT NULL DEFAULT 0,
  generated_at TEXT NOT NULL DEFAULT (datetime('now')))
"""

SUPERSEDED = ("news_league_summaries",)


def table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def columns(con, name):
    return [r[1] for r in con.execute(f"PRAGMA table_info({name})")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {DB}")

    work = []
    if table_exists(con, "news_narratives"):
        cols = columns(con, "news_narratives")
        if "conv_id" in cols:
            print("  news_narratives: already conversation-keyed, nothing to do")
        else:
            n = con.execute("SELECT COUNT(*) FROM news_narratives").fetchone()[0]
            print(f"  news_narratives: league-keyed old shape, {n} row(s) — {cols}")
            if n:
                print("  REFUSING: the table has rows. Write a backfill; do not drop data.")
                return 2
            work.append("news_narratives")

    for name in SUPERSEDED:
        if table_exists(con, name):
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"  {name}: superseded table present, {n} row(s)")
            if n:
                print("  REFUSING: the table has rows. Write a backfill; do not drop data.")
                return 2
            work.append(name)

    if not work:
        print("  nothing to do")
        return 0
    if not args.apply:
        print(f"  would drop and recreate: {', '.join(work)}")
        return 0

    backup = f"{DB}.pre-newsshape-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.bak"
    con.execute("VACUUM INTO ?", (backup,))
    ok = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={ok})")
    if ok != "ok":
        print("  REFUSING: backup failed its integrity check")
        return 3

    with con:
        if "news_narratives" in work:
            con.execute("DROP TABLE news_narratives")
            con.execute(NEWS_NARRATIVES_DDL)
            print("  news_narratives: dropped and recreated conversation-keyed")
        for name in SUPERSEDED:
            if name in work:
                con.execute(f"DROP TABLE {name}")
                print(f"  {name}: dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
