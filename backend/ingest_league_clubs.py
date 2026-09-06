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

NOT FROM ESPN. The first version of this read ESPN's team list, which was the wrong instinct
twice over: identity should not depend on the one publisher whose budget constrains
everything else, and on this box that endpoint returned 403 on the very first dev run. NCAAF
rosters had already been moved off ESPN to CFBD for the same reason, at 2 requests instead
of 149.

FotMob publishes a league's full table, and we already depend on it for soccer appearances.
One request per league, on a host that is not the bottleneck: Liga MX returns all 18 clubs
with `name`, `shortName` and an id.
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_fotmob_soccer_logs import LEAGUES as _FOTMOB_LEAGUES, _get as _fotmob_get

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# The same league ids the appearance ingest already uses, so the two cannot drift.
_PATHS = {league: ids[0] for league, ids in _FOTMOB_LEAGUES.items()}

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


def _rows(node):
    """Every club row, whatever nesting the league uses.

    Liga MX publishes `data.table.all`. MLS and Leagues Cup publish `data.tables`, a list of
    conference groups each holding its own `table.all`. The first version handled the first
    shape and half of the second, so both leagues stored nothing while reporting success;
    only the "published NOTHING" guard stopped that from shrinking the record.

    Walks the structure instead of naming one path, so a third shape costs nothing.
    """
    if isinstance(node, dict):
        if node.get("all"):
            return list(node["all"])
        for key in ("table", "tables"):
            if node.get(key):
                return _rows(node[key])
        return []
    if isinstance(node, list):
        rows = []
        for item in node:
            rows.extend(_rows(item))
        return rows
    return []


def published_clubs(league):
    """Every name FotMob publishes for a league's clubs, keyed to its own id.

    Both `name` and `shortName` on purpose: "CF America" and "America" are both things a
    bookmaker might print, and the checker folds them anyway. A name we do not store is a
    real fixture we might refuse.
    """
    document = _fotmob_get(
        "https://www.fotmob.com/api/data/leagues?id={}".format(_PATHS[league]))
    out = {}
    for entry in document.get("table") or []:
        data = (entry or {}).get("data") or {}
        # `table` for a single-table league, `tables` for one with conferences. MLS and
        # Leagues Cup publish the plural and returned nothing until this read both.
        table = data.get("table") or data.get("tables")
        for row in _rows(table):
            club_id = str(row.get("id") or "") or None
            for key in ("name", "shortName"):
                name = (row.get(key) or "").strip()
                if name:
                    out[name] = club_id
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
        print("  {}: {} published names, {} distinct clubs".format(
            league, len(clubs), len({c for c in clubs.values() if c})))
        if dry_run:
            continue
        con.executemany(
            "INSERT INTO league_clubs(league,name,code,source,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(league,name) DO UPDATE SET code=excluded.code, "
            "source=excluded.source, updated_at=excluded.updated_at",
            [(league, name, code, "fotmob", now) for name, code in clubs.items()])
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
