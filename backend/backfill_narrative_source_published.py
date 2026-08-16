#!/usr/bin/env python3
"""backfill_narrative_source_published.py — put the publisher's date on the
receipts of already-served narrative cards.

`_cited_sources` now stores `published` on every receipt so a card can be dated
by when its STORY last moved rather than by when the writer last ran (see
routers/news._story_time). Rows written before that change have receipts with
no `published`, so every one of them falls back to `generated_at` — which is
the exact value the fix exists to stop using. The fix is inert on existing data
until this runs.

The date is recovered from `news_items.published` by URL: the same row the
receipt was built from, so this is a lookup of a published value, not a guess.
A receipt whose URL is no longer in news_items is left alone and keeps falling
back.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 backfill_narrative_source_published.py [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys


def backfill(con, dry_run=False):
    """Returns (rows_touched, receipts_filled, receipts_unresolved)."""
    rows = con.execute("SELECT conv_id, sources FROM news_narratives").fetchall()
    touched = filled = unresolved = 0
    for r in rows:
        sources = json.loads(r["sources"] or "[]")
        changed = False
        for s in sources:
            if s.get("published"):
                continue
            got = con.execute(
                "SELECT published FROM news_items "
                "WHERE url=? AND published IS NOT NULL AND published!='' LIMIT 1",
                (s.get("url"),)).fetchone()
            if got:
                s["published"] = got["published"]
                filled += 1
                changed = True
            else:
                unresolved += 1
        if changed:
            touched += 1
            if not dry_run:
                con.execute("UPDATE news_narratives SET sources=? WHERE conv_id=?",
                            (json.dumps(sources), r["conv_id"]))
    return touched, filled, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    if not os.path.exists(db_path):
        sys.exit("No DB at %s" % db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    touched, filled, unresolved = backfill(con, args.dry_run)
    if not args.dry_run:
        con.commit()
    print("%s%d cards updated, %d receipts dated, %d unresolved (left falling back)"
          % ("[dry-run] " if args.dry_run else "", touched, filled, unresolved))


if __name__ == "__main__":
    main()
