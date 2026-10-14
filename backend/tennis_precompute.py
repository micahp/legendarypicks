#!/usr/bin/env python3
"""Precompute tennis projections for the next days and store them for the tennis page.

For each tour and UTC day, forget the stored projections, then run the tennis endpoint's own
projection step, which stores them again. The page reads the stored rows, so it does not compute
projections per request. Writes only to the database named by LP_DB_PATH.

Usage:
  LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db venv/bin/python tennis_precompute.py [--days 2]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=2, help="UTC days from today to precompute")
    args = parser.parse_args(argv)

    from routers.games import misc
    from tennis_daily_projections import forget_days

    today = dt.datetime.now(dt.timezone.utc).date()
    days = [(today + dt.timedelta(days=i)).isoformat() for i in range(args.days)]
    con = misc._db()
    try:
        for tour in ("atp", "wta"):
            forget_days(con, tour, days)
        con.commit()
    finally:
        con.close()

    for tour in ("atp", "wta"):
        for day in days:
            result = misc.tennis_model(date=day, tour=tour, utc_offset_minutes=0)
            matches = result.get("matches", [])
            projected = sum(1 for match in matches if match.get("projection"))
            print("%s %s: %d matches, %d projected" % (tour, day, len(matches), projected), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
