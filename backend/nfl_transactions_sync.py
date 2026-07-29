#!/usr/bin/env python3
"""
nfl_transactions_sync.py — ingest the NFL offseason transaction ticker (waives,
signings, IR moves, releases, retirements, front-office moves) from ESPN's public
site API, for the "Offseason Movers" card on the NFL league page.

Source verified 2026-07-22: site.web.api.espn.com/apis/site/v2/sports/football/nfl/transactions
is free, unauthenticated, reachable from this host (unlike www.espn.com itself, which
CloudFront 403s our datacenter IP). Returns 25 transactions/page, sorted newest-first,
each a plain-English description with a date and team — no stable per-row id, so
(date, team, description) is the dedup key.

Usage: python3 nfl_transactions_sync.py [--full] [--pages N]
  (default: first 3 pages / ~75 most recent — enough for a daily incremental job;
  --full walks every page for a one-time historical backfill)
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
_URL = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/transactions"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def ensure_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS nfl_transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txn_date TEXT NOT NULL,
        team_id TEXT,
        team_abbr TEXT,
        team_name TEXT,
        description TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        UNIQUE(txn_date, team_id, description))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_txn_date ON nfl_transactions(txn_date)")


def _fetch_page(page: int) -> dict:
    url = f"{_URL}?page={page}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HDRS), timeout=15) as r:
        return json.loads(r.read().decode())


def sync(con, pages: int = 3, full: bool = False) -> dict:
    if pages < 1:
        return {
            "status": "error",
            "reason": "pages must be at least 1",
            "pages_fetched": 0,
            "inserted": 0,
        }
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    seen_pages = 0
    page_count = None
    page = 1
    fetched_rows = []
    while True:
        try:
            body = _fetch_page(page)
        except (urllib.error.URLError, TimeoutError) as e:
            return {
                "status": "error",
                "reason": str(e),
                "pages_fetched": seen_pages,
                "inserted": 0,
            }
        page_count = body.get("pageCount") or page_count
        rows = body.get("transactions") or []
        for transaction in rows:
            if not transaction.get("date") or not transaction.get(
                "description"
            ):
                return {
                    "status": "error",
                    "reason": (
                        f"page {page} has a transaction without "
                        "date/description"
                    ),
                    "pages_fetched": seen_pages,
                    "inserted": 0,
                }
        fetched_rows.extend(rows)
        seen_pages += 1
        page += 1
        if not full and seen_pages >= pages:
            break
        if page_count and page > page_count:
            break
        if not rows:
            break

    inserted = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_tables(con)
        for transaction in fetched_rows:
            team = transaction.get("team") or {}
            cur = con.execute(
                """INSERT OR IGNORE INTO nfl_transactions
                   (txn_date, team_id, team_abbr, team_name, description, ingested_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    transaction["date"],
                    team.get("id"),
                    team.get("abbreviation"),
                    team.get("displayName"),
                    transaction["description"],
                    now,
                ),
            )
            inserted += cur.rowcount
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    total = con.execute("SELECT COUNT(*) FROM nfl_transactions").fetchone()[0]
    return {
        "status": "ok",
        "pages_fetched": seen_pages,
        "page_count": page_count,
        "inserted": inserted,
        "total_rows": total,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="walk every page (one-time backfill)")
    ap.add_argument("--pages", type=int, default=3, help="pages to fetch when not --full")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    result = sync(con, pages=args.pages, full=args.full)
    con.close()
    print(f"nfl_transactions_sync: {result}")


if __name__ == "__main__":
    main()
