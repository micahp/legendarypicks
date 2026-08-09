#!/usr/bin/env python3
"""
reconcile_totals.py — compare what we stored against what the publisher says exists.

Every ingest in this repo answers "did rows land?" Nothing answers "did *all* the rows
land?" — and a partial ingest is indistinguishable from a complete one by inspection.
The 2024 NFL game logs sat at 29% of 2025 for months looking entirely normal.

The cheap oracle: ESPN's core API returns the cardinality of any collection in the
envelope of a `limit=1` request. One HTTP call, no traversal, no key needed:

    GET .../seasons/2025/types/2/events?limit=1   ->  {"count": 272, ...}
    GET .../seasons/2025/teams?limit=1            ->  {"count": 32,  ...}
    GET .../athletes/<id>/eventlog?limit=1        ->  {"events": {"count": 17, ...}}

Usage:
    python3 reconcile_totals.py                    # all checks
    python3 reconcile_totals.py --league nfl
    python3 reconcile_totals.py --season 2024
    python3 reconcile_totals.py --sample 40        # per-player eventlog sample size

Exit code is 1 if any check MISMATCHes or its oracle is unreachable. An unreachable
oracle is a FAIL, not a skip: "evidence unavailable" must never read as green.

Environment:
    LP_DB_PATH — the sqlite database (default: backend/data/picks.db)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconcile_checks import check_generic, check_nfl
from reconcile_core import (
    CORE,
    DB,
    ESPN_PATH,
    OracleUnreachable,
    _DISK,
    _MIN_INTERVAL,
    _disk_flush,
    _get_json,
    _log,
    published_event_ids,
)
from reconcile_coverage import write_coverage
from reconcile_gap import ESPN_PATH_BY_URL, Gap, describe_gap, explain_gap
from reconcile_report import Report

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=sorted(ESPN_PATH), action="append")
    ap.add_argument("--season", type=int, action="append")
    ap.add_argument("--sample", type=int, default=25, help="players to spot-check per season")
    ap.add_argument(
        "--write-coverage",
        action="store_true",
        help="write the verdict into team_stats_coverage (opens the db read-write)",
    )
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"no database at {DB}", file=sys.stderr)
        return 1

    _log(f"run start: db={DB} leagues={args.league or 'all'} "
         f"seasons={args.season or 'all'} write_coverage={args.write_coverage} "
         f"pace={_MIN_INTERVAL}s cache={len(_DISK)} events")
    if args.write_coverage:
        conn = sqlite3.connect(DB, timeout=60)
    else:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rep = Report()

    leagues = args.league or ["nfl"]
    checked: List[Tuple[str, int]] = []
    for league in leagues:
        seasons = args.season or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT season FROM player_game_logs WHERE league=? ORDER BY season",
                (league,),
            )
        ]
        for season in seasons:
            rep.scope(league, season)
            checked.append((league, season))
            if league == "nfl":
                check_nfl(conn, rep, season, args.sample)
            else:
                check_generic(conn, rep, league, season)

    print(f"reconcile_totals — db={DB}\n")
    print(rep.render())
    print()

    if args.write_coverage:
        print("coverage:")
        for league, season in checked:
            status = write_coverage(conn, rep, league, season)
            print(f"  {league} {season} -> {status}")
            _log(f"coverage written: {league} {season} -> {status}")
        print()

    if rep.failed:
        verdict = f"FAIL — {rep.failed} check(s) disagree with the published total or had no oracle"
        print(verdict)
        _log(verdict)
        return 1
    print("PASS — every stored total matches the publisher")
    _log("PASS — every stored total matches the publisher")
    return 0



if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # Flush what this run learned even when it failed or was interrupted --
        # a killed run that discards 40 minutes of fetches is how the same slow
        # loop repeats.
        _disk_flush()
