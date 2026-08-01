#!/usr/bin/env python3
"""Retired season-stat derivation entrypoint.

NFL totals are published directly by ``ingest_nfl_season_stats.py`` from
nflverse's regular-season summary artifact. NBA and NHL have their own direct
publishers. Keeping a rollup here would create a competing writer.
"""

import sys

from league_stats import LeagueStatContractError


def derive_league(_db_path: str, league: str):
    raise LeagueStatContractError(
        f"{str(league or '').lower() or 'blank'} season-stat derivation is retired; "
        "run the league's published-source ingester"
    )


def main():
    raise SystemExit(
        "derive_player_stats.py is retired; for NFL run "
        "ingest_nfl_season_stats.py"
    )


if __name__ == "__main__":
    main()
