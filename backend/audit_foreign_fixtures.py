#!/usr/bin/env python3
"""audit_foreign_fixtures.py: fixtures filed under a league they do not belong to.

The guard in `/api/props/ingest` stops new ones. This is the surface that says whether the
guard is working, and it is the one that catches what the guard cannot: a fixture created
before the guard existed, one admitted while a league was too sparsely covered to judge, and
one that arrives by a path nobody has thought about yet.

Both are needed. A guard nobody checks is a claim; a check with no guard is a chore. On
2026-09-05 two Serie A and Liga MX fixtures sat in prod as MLS for a day and were found by
someone looking at their phone, which is not a monitoring strategy.

Reads only stored data and issues no request, so it is safe to run anywhere, any time.

Exit 1 when any foreign fixture is found, so a timer can carry it.

Usage:
  LP_DB_PATH=.../picks.db venv/bin/python audit_foreign_fixtures.py
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import league_membership

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def audit(db_path=None, since=None):
    con = sqlite3.connect("file:{}?mode=ro".format(db_path or DB), uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    where = "WHERE date >= ?" if since else ""
    args = (since,) if since else ()
    rows = con.execute(
        "SELECT id, league, date, home, away, espn_event_id FROM prop_games "
        + where + " ORDER BY league, date", args).fetchall()

    cache = {}
    foreign, unjudged, checked = [], set(), 0
    for row in rows:
        # strict: BOTH clubs must be on record. The guard only refuses when NEITHER is,
        # so this reports a superset of what the guard blocks, which is the point: the
        # audit exists to see what the guard is not allowed to be strict enough to stop.
        verdict = league_membership.belongs(
            con, row["league"], row["home"], row["away"], _cache=cache, strict=True)
        if verdict is None:
            unjudged.add(row["league"])
            continue
        checked += 1
        if verdict is False:
            props = con.execute(
                "SELECT COUNT(*) FROM props WHERE game_id=?", (row["id"],)).fetchone()[0]
            settled = con.execute(
                "SELECT COUNT(*) FROM prop_results r JOIN props p ON p.id=r.prop_id "
                "WHERE p.game_id=?", (row["id"],)).fetchone()[0]
            foreign.append((row, props, settled))
    con.close()

    # Say the zero. A run that finds nothing must look different from a run that never
    # happened, which is the state the news collector sat in for its entire existence.
    print("prop_games examined: {}, judged: {}".format(len(rows), checked))
    print("foreign fixtures: {}".format(len(foreign)))
    for row, props, settled in foreign:
        print("  {:<7} id={:<6} {} {:<25} @ {:<25} props={:<4} settled={}".format(
            row["league"], row["id"], row["date"], row["away"][:25], row["home"][:25],
            props, settled))
    if unjudged:
        # NOT a pass. These leagues have too few clubs on record for an absence to mean
        # anything, so nothing was checked for them and the report says so rather than
        # letting silence read as clean.
        print("leagues with too few clubs on record to judge: {}".format(
            ", ".join(sorted(unjudged))))
    return foreign


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="only examine games on or after this date")
    args = parser.parse_args(argv)
    return 1 if audit(since=args.since) else 0


if __name__ == "__main__":
    sys.exit(main())
