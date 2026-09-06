#!/usr/bin/env python3
"""ingest_league_clubs.py: store a league's published club list, one request per league.

`league_membership` decides whether a fixture belongs to the league claiming it, and it runs
inside a request handler, so it can only read what is already stored. Its club record was
whatever had happened to appear in a scoreboard snapshot or a linked game, which is
incomplete in exactly the way that makes a strict check refuse real fixtures.

Two repairs failed on that gap on 2026-09-06. Three genuine NCAAF fixtures read as foreign
until `ingest_ncaaf_rosters_cfbd` began storing CFBD's 139 schools. Then
`Guadalajara @ Atletico San Luis` could not be relabelled to `ligamx`, because our Liga MX
record held too few clubs to recognise either side, so a plainly Liga MX fixture was reported
as belonging to no league we carry.

ESPN publishes the whole club list for a soccer league in ONE request, and
`ingest_mls_ncaaf_rosters._site_teams` has always fetched it and kept only the
abbreviations. This keeps the names too.

Cost: 1 request per league to site.web.api. That host's limit is a burst rate, and this is
two or three requests run rarely, so it needs no pacing beyond the shared fetcher's own.
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

_SITE = "https://site.web.api.espn.com/apis/site/v2/sports/{path}"
_PATHS = {
    "mls": "soccer/usa.1",
    "ligamx": "soccer/mex.1",
    "lcup": "soccer/concacaf.leagues.cup",
}

_DDL = """
CREATE TABLE IF NOT EXISTS league_clubs (
    league     TEXT NOT NULL,
    name       TEXT NOT NULL,
    code       TEXT,
    source     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (league, name)
);
"""


def published_clubs(league):
    """Every name ESPN publishes for a league's clubs, with its abbreviation.

    Several spellings per club on purpose: `displayName`, `shortDisplayName`, `name` and
    `location` are all things a bookmaker might print, and the checker folds them anyway. A
    name we do not store is a real fixture we might refuse.
    """
    document = espn._get(_SITE.format(path=_PATHS[league]) + "/teams?limit=200", ttl=43200)
    out = {}
    for sport in document.get("sports") or []:
        for entry in sport.get("leagues") or []:
            for item in entry.get("teams") or []:
                team = item.get("team") or {}
                code = (team.get("abbreviation") or "").upper() or None
                for key in ("displayName", "shortDisplayName", "name", "location", "nickname"):
                    name = (team.get(key) or "").strip()
                    if name:
                        out[name] = code
    return out


def ingest(leagues, dry_run=False):
    con = sqlite3.connect(DB, timeout=30)
    con.executescript(_DDL)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    total = 0
    for league in leagues:
        clubs = published_clubs(league)
        if not clubs:
            # An empty list is not a league with no clubs, it is a request that told us
            # nothing. Writing it would shrink the record the checker depends on.
            print("  {}: published NOTHING; leaving the stored record alone".format(league))
            continue
        print("  {}: {} published names, {} distinct codes".format(
            league, len(clubs), len({c for c in clubs.values() if c})))
        if dry_run:
            continue
        con.executemany(
            "INSERT INTO league_clubs(league,name,code,source,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(league,name) DO UPDATE SET code=excluded.code, "
            "source=excluded.source, updated_at=excluded.updated_at",
            [(league, name, code, "espn", now) for name, code in clubs.items()])
        total += len(clubs)
    if not dry_run:
        con.commit()
    held = con.execute("SELECT league, COUNT(*) FROM league_clubs GROUP BY league").fetchall()
    con.close()
    print("  stored {} names{}".format(total, " (dry run: nothing written)" if dry_run else ""))
    for league, count in held:
        print("    league_clubs now holds {} names for {}".format(count, league))
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("leagues", nargs="*", default=None,
                        help="default: every soccer league we can ask about")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    leagues = args.leagues or sorted(_PATHS)
    unknown = [league for league in leagues if league not in _PATHS]
    if unknown:
        raise SystemExit("no published team list configured for: {}".format(unknown))
    ingest(leagues, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
