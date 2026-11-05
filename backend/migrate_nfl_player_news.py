#!/usr/bin/env python3
"""Additive migration for the NFL player news, claim, poll and identity-decision tables.

Creates only what is missing (CREATE TABLE/INDEX IF NOT EXISTS). It never alters or drops an existing table, and it never
touches projection tables or simulation inputs. Run it once against each database before its first ingest.

Usage: migrate_nfl_player_news.py --db PATH
"""
import argparse
import sqlite3
import sys

import backfill_nfl_rotowire_ids
import ingest_nfl_player_news

NEW_TABLES = ('nfl_player_news_updates', 'nfl_player_news_claims', 'nfl_player_news_polls', 'nfl_rotowire_id_decisions')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    a = ap.parse_args(argv)
    con = sqlite3.connect(a.db, timeout=30)
    try:
        before = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with con:
            ingest_nfl_player_news.ensure_schema(con)
            con.execute(backfill_nfl_rotowire_ids.DECISIONS_DDL)
        after = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        created = [name for name in NEW_TABLES if name in after and name not in before]
        present = [name for name in NEW_TABLES if name in after]
        print(f"NFL player news migration: created {created or 'nothing'}; tables present {present}")
        return 0
    except sqlite3.Error as exc:
        print(f'NFL player news migration failed, rolled back: {exc}', file=sys.stderr)
        return 1
    finally:
        con.close()


if __name__ == '__main__':
    sys.exit(main())
