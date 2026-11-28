#!/usr/bin/env python3
"""Collect team injury-related sitemap links as observed discovery evidence.

A sitemap provides dates, titles and URLs, not verified player designations or
exact publication timestamps. A row is visible only at/after actual retrieval;
never use this catalog to set a player's availability. Legacy title/date rows
from the old research collector are not promoted to cutoff-safe observations.
Explicit CLI only; no scheduler or live ingest is enabled by installing this file.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import paced_http
import team_codes

TEAM_SITES = {
    'ARI': 'https://www.azcardinals.com', 'ATL': 'https://www.atlantafalcons.com',
    'BAL': 'https://www.baltimoreravens.com', 'BUF': 'https://www.buffalobills.com',
    'CAR': 'https://www.panthers.com', 'CHI': 'https://www.chicagobears.com',
    'CIN': 'https://www.bengals.com', 'CLE': 'https://www.clevelandbrowns.com',
    'DAL': 'https://www.dallascowboys.com', 'DEN': 'https://www.denverbroncos.com',
    'DET': 'https://www.detroitlions.com', 'GB': 'https://www.packers.com',
    'HOU': 'https://www.houstontexans.com', 'IND': 'https://www.colts.com',
    'JAX': 'https://www.jaguars.com', 'KC': 'https://www.chiefs.com',
    'LAR': 'https://www.therams.com', 'LAC': 'https://www.chargers.com',
    'LV': 'https://www.raiders.com', 'MIA': 'https://www.miamidolphins.com',
    'MIN': 'https://www.vikings.com', 'NE': 'https://www.patriots.com',
    'NO': 'https://www.neworleanssaints.com', 'NYG': 'https://www.giants.com',
    'NYJ': 'https://www.newyorkjets.com', 'PHI': 'https://www.philadelphiaeagles.com',
    'PIT': 'https://www.steelers.com', 'SEA': 'https://www.seahawks.com',
    'SF': 'https://www.49ers.com', 'TB': 'https://www.buccaneers.com',
    'TEN': 'https://www.tennesseetitans.com', 'WSH': 'https://www.commanders.com',
}


ROW = re.compile(r'<tr><td[^>]*>(\d{4}-\d{2}-\d{2})</td><td><a href="(/news/[^"]+)"[^>]*>(.*?)</a>', re.S)

SCHEMA = """
CREATE TABLE IF NOT EXISTS team_injury_article_observations (
    url TEXT NOT NULL,
    team TEXT NOT NULL,
    published_date TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    sitemap_month TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    sitemap_url TEXT NOT NULL,
    sitemap_sha256 TEXT NOT NULL,
    PRIMARY KEY (url, observed_at_utc, sitemap_sha256)
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


def _utc(stamp):
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone-qualified observation/cutoff required')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _month_url(base, month):
    if not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('month must be YYYY-MM')
    date.fromisoformat(month + '-01')
    return f'{base}/sitemap/html/articles/{month[:4]}/{month[5:]}'


def fetch_month(fetch, base, month):
    sitemap_url = _month_url(base, month)
    # Bypass both memory and disk cache: this observation must represent a fresh response.
    page = fetch.fetch_text(sitemap_url, retry=False)
    rows = parse_sitemap(page, base)
    if not rows:
        raise ValueError('sitemap parsed to 0 article rows; the page format may have changed')
    for published, _, _ in rows:
        date.fromisoformat(published)
    return [row for row in rows if row[0].startswith(month)], len(rows), sitemap_url, hashlib.sha256(page.encode('utf-8')).hexdigest()


def ingest(db, months, fetch, *, clock=None):
    """Append observations after each successful retrieval. Clock injectable for offline tests."""
    from contextlib import closing
    clock = clock or (lambda: datetime.now(timezone.utc))
    months = sorted(set(months))
    for month in months:
        _month_url('', month)
    if not months:
        raise ValueError('at least one month required')
    # Never create a mistyped DB. Explicit collector invocation can add the table.
    uri = Path(db).resolve(strict=True).as_uri() + '?mode=rw'
    lines, failures = [], []
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as con:
        con.execute(SCHEMA)
        for team, base in sorted(TEAM_SITES.items()):
            team = team_codes.normalize('nfl', team)
            for month in months:
                try:
                    rows, parsed, sitemap_url, digest = fetch_month(fetch, base, month)
                    observed = _utc(clock().isoformat())
                    kept = []
                    for published, url, title in rows:
                        kind = classify(url, title)
                        if kind is not None:
                            kept.append((url, team, published, title, kind, month, observed, sitemap_url, digest))
                except Exception as exc:
                    failures.append(f'{team} {month}: {exc}')
                    lines.append(f'{team} {month}: FAILED {exc}')
                    continue
                before = con.total_changes
                with con:
                    con.executemany('INSERT OR IGNORE INTO team_injury_article_observations VALUES (?,?,?,?,?,?,?,?,?)', kept)
                new = con.total_changes - before
                lines.append(f'{team} {month}: {parsed} sitemap rows, {len(kept)} matching titles, {new} new observations')
    return lines, failures


def list_observed(db, team, as_of):
    """Read-only catalog, latest observed version of each URL by cutoff.
    Unknown table/DB is an error, not a claim that no articles exist.
    """
    from contextlib import closing
    team = team_codes.normalize('nfl', team)
    cutoff = _utc(as_of)
    uri = Path(db).resolve(strict=True).as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            'SELECT * FROM team_injury_article_observations WHERE team=? AND observed_at_utc<=? '
            'AND published_date<=? ORDER BY observed_at_utc DESC, sitemap_sha256, url',
            (team, cutoff, cutoff[:10])).fetchall()
    latest = {}
    for row in rows:
        latest.setdefault(row['url'], dict(row))
    return {'team': team, 'as_of_utc': cutoff, 'evidence_kind': 'sitemap_discovery_only',
            'complete': False, 'player_status_verified': False,
            'articles': sorted(latest.values(), key=lambda r: (r['published_date'], r['url']), reverse=True)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', required=True, help='existing database; explicit collection writes only the discovery catalog')
    ap.add_argument('--months', nargs='+', required=True, metavar='YYYY-MM')
    a = ap.parse_args(argv)
    fetch = paced_http.Fetcher(min_interval=1.0, host_budget=20, on_exhausted='refuse')
    lines, failures = ingest(a.db, a.months, fetch)
    print('\n'.join(lines))
    for failure in failures:
        print('FAILURE', failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
