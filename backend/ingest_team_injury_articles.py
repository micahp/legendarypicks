#!/usr/bin/env python3
"""Ingest injury-report and inactives articles from each team's own HTML article sitemap.

One sitemap per team per month: https://<team site>/sitemap/html/articles/YYYY/MM. Each row of that page is a date cell
and a link to /news/<slug>. An article is kept when its slug or title says injury, inactive or practice. Titles are
copied as published. Nothing here reads injury status: nflverse's published designations are in injury_reports.

Fails loudly. A sitemap that cannot be fetched, or that parses to zero rows, is listed and makes the run exit 1. Every
team prints its count, zeros included.

Usage: python3 backend/ingest_team_injury_articles.py --db PATH --months 2026-09 2026-10 2026-11
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

import paced_http

TEAM_SITES = {
    'ARI': 'https://www.azcardinals.com', 'ATL': 'https://www.atlantafalcons.com',
    'BAL': 'https://www.baltimoreravens.com', 'BUF': 'https://www.buffalobills.com',
    'CAR': 'https://www.panthers.com', 'CHI': 'https://www.chicagobears.com',
    'CIN': 'https://www.bengals.com', 'CLE': 'https://www.clevelandbrowns.com',
    'DAL': 'https://www.dallascowboys.com', 'DEN': 'https://www.denverbroncos.com',
    'DET': 'https://www.detroitlions.com', 'GB': 'https://www.packers.com',
    'HOU': 'https://www.houstontexans.com', 'IND': 'https://www.colts.com',
    'JAX': 'https://www.jaguars.com', 'KC': 'https://www.chiefs.com',
    'LA': 'https://www.therams.com', 'LAC': 'https://www.chargers.com',
    'LV': 'https://www.raiders.com', 'MIA': 'https://www.miamidolphins.com',
    'MIN': 'https://www.vikings.com', 'NE': 'https://www.patriots.com',
    'NO': 'https://www.neworleanssaints.com', 'NYG': 'https://www.giants.com',
    'NYJ': 'https://www.newyorkjets.com', 'PHI': 'https://www.philadelphiaeagles.com',
    'PIT': 'https://www.steelers.com', 'SEA': 'https://www.seahawks.com',
    'SF': 'https://www.49ers.com', 'TB': 'https://www.buccaneers.com',
    'TEN': 'https://www.tennesseetitans.com', 'WAS': 'https://www.commanders.com',
}

ROW = re.compile(r'<tr><td[^>]*>(\d{4}-\d{2}-\d{2})</td><td><a href="(/news/[^"]+)"[^>]*>(.*?)</a>', re.S)
SCHEMA = """
CREATE TABLE IF NOT EXISTS team_injury_articles (
    url TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    published_date TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    sitemap_month TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL
)
"""


def parse_sitemap(page, base):
    """[(published date, absolute url, title)] for every article row on one team sitemap page."""
    rows = []
    for date, href, raw_title in ROW.findall(page):
        title = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw_title))).strip()
        rows.append((date, base + href, title))
    return rows


def classify(url, title):
    """'inactives', 'injury_report' or 'practice' for a kept article, None for everything else.

    'injured reserve' on its own is not an injury report, so it is removed before the injury test."""
    text = (url.rsplit('/', 1)[-1] + ' ' + title).lower()
    if 'inactive' in text:
        return 'inactives'
    if 'injur' in text.replace('injured reserve', ''):
        return 'injury_report'
    if 'practice' in text:
        return 'practice'
    return None


def fetch_month(fetch, base, month):
    """Rows of one team's sitemap for one month, kept to articles dated in that month."""
    year, mm = month.split('-')
    page = fetch.text(f'{base}/sitemap/html/articles/{year}/{mm}')
    rows = parse_sitemap(page, base)
    if not rows:
        raise ValueError('sitemap parsed to 0 article rows; the page format may have changed')
    return [row for row in rows if row[0].startswith(month)], len(rows)


def ingest(db, months, fetch, now=None):
    """Store kept articles for each team and month. Returns (lines to print, failures)."""
    now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    con = sqlite3.connect(db, timeout=30)
    con.execute(SCHEMA)
    lines, failures = [], []
    for team, base in sorted(TEAM_SITES.items()):
        for month in months:
            try:
                rows, parsed = fetch_month(fetch, base, month)
            except Exception as exc:  # recorded and reported below; the run still exits non-zero
                failures.append(f'{team} {month}: {exc}')
                lines.append(f'{team} {month}: FAILED {exc}')
                continue
            kept = [(url, team, date, title, classify(url, title), month, now) for date, url, title in rows]
            kept = [row for row in kept if row[4] is not None]
            before = con.total_changes
            con.executemany('INSERT OR IGNORE INTO team_injury_articles VALUES (?,?,?,?,?,?,?)', kept)
            new = con.total_changes - before
            lines.append(f'{team} {month}: {parsed} rows on the sitemap, {len(kept)} injury or inactive articles, '
                         f'{new} new, {len(kept) - new} already held')
    con.commit()
    con.close()
    return lines, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=os.environ.get('LP_DB_PATH'), required=not os.environ.get('LP_DB_PATH'))
    ap.add_argument('--months', nargs='+', required=True, metavar='YYYY-MM')
    a = ap.parse_args(argv)
    fetch = paced_http.Fetcher(min_interval=1.0, host_budget=20, on_exhausted='refuse')
    lines, failures = ingest(a.db, a.months, fetch)
    print('\n'.join(lines))
    print(f'teams {len(TEAM_SITES)}, months {len(a.months)}, failures {len(failures)}')
    for failure in failures:
        print('FAILURE', failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
