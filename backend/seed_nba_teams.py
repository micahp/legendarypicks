#!/usr/bin/env python3
"""Seed nba_teams: the thirty NBA clubs, their ESPN names, and their conference and division.

The clubs and the alignment are written once, in nba_standings_store.TEAMS. This writes them into the database that the
NBA standings and stakes read, for each season named here. A dry run unless --apply, and --db must be given explicitly,
so a seed never lands in a database by accident.

    python seed_nba_teams.py --db data/picks.dev.db            # dry run
    python seed_nba_teams.py --db data/picks.dev.db --apply
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_standings_store as store  # noqa: E402

SEASONS = (2026, 2027)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply:
        print(f"DRY RUN: would seed {len(store.TEAMS)} clubs for seasons {list(SEASONS)} in {args.db}. "
              f"Re-run with --apply.")
        return 0
    connection = sqlite3.connect(args.db)
    try:
        for season in SEASONS:
            store.seed(connection, season)
        counts = {season: len(store.load_teams(connection, season)) for season in SEASONS}
    finally:
        connection.close()
    print(f"seeded nba_teams in {args.db}: {counts}")
    return 0 if all(count == len(store.TEAMS) for count in counts.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
