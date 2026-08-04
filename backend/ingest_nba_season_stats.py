#!/usr/bin/env python3
"""Publish NBA season stats from ESPN's bulk byathlete report.

Why this exists
---------------
`ingest_nba_stats.py` asks `sports.core.api.espn.com` for one athlete at a time:
643 requests for one refresh. That is what tripped ESPN's block -- 143 athletes
in at 1s spacing, 21 at 2s -- and it is why `espn_core` has published zero rows
ever, which is why the NBA leaderboard has been serving the 2022-23 season.

Pacing was the wrong fix. The request count was the problem, and ESPN publishes
the same numbers in bulk:

    site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/
        byathlete?season=2026&seasontype=2&limit=100

578 athletes over 6 pages. Same publisher, same season, ~1% of the requests, and
on a host that answers when `site.api.espn.com` is refusing.

Reading the payload
-------------------
Each athlete's `categories[].values` is a bare list of numbers; the names live
ONCE at the top level in `categories[].names`, keyed by category. So the values
are positional and the schema arrives separately. This module zips them by name
and never indexes into `values` by a hardcoded position -- ESPN adding a column
would silently shift every stat one place to the left, and every number after it
would be wrong while every count stayed healthy.

`seasontype=2` is the regular season, asked for rather than filtered after.

`trueShootingPct` is NOT in this report -- it is published on the per-athlete
endpoint. It is not in the NBA MANIFEST either, so it stays NULL rather than
being computed from points and attempts. Nothing here is derived.

Usage:
  cd backend && venv/bin/python ingest_nba_season_stats.py \\
      --season 2026 --db data/picks.dev.db [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from league_stats import (  # noqa: E402
    LeagueStatContractError,
    load_unique_source_id_map,
    publish_player_stats,
    queue_unresolved_player,
)

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
URL = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/"
       "statistics/byathlete")
HDR = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "Chrome/124 Safari/537.36")}
SOURCE = "espn_web"
PAGE = 100

MIN_INTERVAL = float(os.environ.get("LP_ESPN_MIN_INTERVAL", "1.0"))
RETRY_WAITS = (10.0, 60.0, 300.0)

# Pacing, retries and the per-host budget come from `paced_http`, which
# exists because six modules had each written this block. The interval and
# ladder below are this publisher's (ESPN), unchanged.
_FETCH = paced_http.Fetcher(min_interval=MIN_INTERVAL, retry_waits=RETRY_WAITS,
                            headers=HDR, timeout=30, host_budget=None)

# our column -> the published name. Every one of these is in the NBA MANIFEST.
STAT_MAP = {
    "pts": "avgPoints",
    "reb": "avgRebounds",
    "ast": "avgAssists",
    "stl": "avgSteals",
    "blk": "avgBlocks",
    "tov": "avgTurnovers",
    "fgm": "fieldGoalsMade",
    "fga": "fieldGoalsAttempted",
    "fg3m": "threePointFieldGoalsMade",
    "fg3a": "threePointFieldGoalsAttempted",
    "ftm": "freeThrowsMade",
    "fta": "freeThrowsAttempted",
    "minutes": "avgMinutes",
}
_INTEGER_COLUMNS = {"fgm", "fga", "fg3m", "fg3a", "ftm", "fta"}


class NBASeasonStatsError(RuntimeError):
    """The published NBA snapshot was incomplete or invalid."""


def _get(url: str) -> dict:
    # host_budget defaults to 100 -- measured on ESPN, which this is.
    try:
        return _FETCH.fetch(url)
    except Exception as exc:
        raise NBASeasonStatsError(f"{url} failed: {exc}") from exc


def flatten(athlete: dict, schema: dict[str, list[str]]) -> dict[str, float]:
    """Zip one athlete's positional values against the published names.

    Positional data with the schema delivered separately is the setup for a
    silent, total corruption: one inserted column and every stat after it is
    someone else's number, with every row count still healthy.
    """
    flat: dict[str, float] = {}
    for category in athlete.get("categories") or []:
        names = schema.get(category.get("name"))
        values = category.get("values")
        if not names or values is None:
            continue
        if len(names) != len(values):
            raise NBASeasonStatsError(
                f"category {category.get('name')!r} published {len(names)} "
                f"names for {len(values)} values -- the schema and the row "
                f"disagree, so every value in it is unsafe to read"
            )
        flat.update(zip(names, values))
    return flat


def parse_athlete(flat: dict) -> dict | None:
    """Map one flattened athlete onto MANIFEST columns; None if it never played."""
    games = flat.get("gamesPlayed")
    if games is None:
        return None
    if int(games) <= 0:
        return None
    missing = [
        published for published in STAT_MAP.values() if flat.get(published) is None
    ]
    if missing:
        raise NBASeasonStatsError(
            "published athlete is missing: " + ", ".join(sorted(missing))
        )
    values = {}
    for column, published in STAT_MAP.items():
        raw = float(flat[published])
        values[column] = int(round(raw)) if column in _INTEGER_COLUMNS else round(raw, 1)
    return {"games": int(games), "values": values}


def fetch_all(season: int) -> tuple[list[dict], dict[str, list[str]]]:
    """Page the report to completion, returning athletes and the name schema."""
    athletes: list[dict] = []
    schema: dict[str, list[str]] = {}
    page, pages = 1, None
    expected = None
    while True:
        query = urllib.parse.urlencode({
            "region": "us", "lang": "en", "contentorigin": "espn",
            "season": int(season), "seasontype": 2,
            "limit": PAGE, "page": page,
        })
        document = _get(f"{URL}?{query}")
        if not schema:
            schema = {
                category.get("name"): category.get("names")
                for category in document.get("categories") or []
                if category.get("names")
            }
            if not schema:
                raise NBASeasonStatsError(
                    "the report published no category names -- without the "
                    "schema its values are unlabelled numbers"
                )
        pagination = document.get("pagination") or {}
        pages = int(pagination.get("pages") or 0)
        expected = int(pagination.get("count") or 0)
        batch = document.get("athletes") or []
        athletes.extend(batch)
        if not batch or page >= pages:
            break
        page += 1

    if expected and len(athletes) != expected:
        raise NBASeasonStatsError(
            f"published count is {expected} but {len(athletes)} athletes "
            f"were returned over {pages} pages"
        )
    return athletes, schema


def refresh(db_path: str, *, season: int, dry_run: bool = False,
            min_coverage: float = 0.80) -> dict:
    athletes, schema = fetch_all(season)
    print(f"published: {len(athletes)} athletes")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        espn_to_player, ambiguous = load_unique_source_id_map(
            connection, league="nba", id_column="espn_id"
        )
        counts = {"published": len(athletes), "written": 0, "no_games": 0,
                  "not_in_spine": 0, "rejected": 0}
        parsed: list[tuple[int, dict, str]] = []
        for entry in athletes:
            athlete = entry.get("athlete") or {}
            source_key = str(athlete.get("id") or "")
            record = parse_athlete(flatten(entry, schema))
            if record is None:
                counts["no_games"] += 1
                continue
            player_id = espn_to_player.get(source_key)
            if player_id is None:
                counts["not_in_spine"] += 1
                if not dry_run:
                    queue_unresolved_player(
                        connection, source=SOURCE,
                        raw_name=str(athlete.get("displayName") or ""),
                        league="nba", team=None, source_player_key=source_key,
                        reason=("duplicate_spine_espn_id"
                                if source_key in ambiguous
                                else "espn_id_not_in_spine"),
                    )
                continue
            parsed.append((player_id, record, str(athlete.get("displayName") or "")))

        # Everything is read and validated before a single row is written, so a
        # partial upstream page cannot replace a good snapshot with half a one.
        reachable = counts["published"] - counts["no_games"]
        if reachable and len(parsed) / reachable < min_coverage:
            raise NBASeasonStatsError(
                f"only {len(parsed)} of {reachable} playing athletes reach the "
                f"spine ({len(parsed) / reachable:.1%}), below the required "
                f"{min_coverage:.0%} -- refusing to publish a partial league"
            )
        if dry_run:
            counts["written"] = len(parsed)
            return counts

        for player_id, record, name in parsed:
            try:
                publish_player_stats(
                    connection, player_id=player_id, league="nba",
                    season=int(season), stat_type="season", source=SOURCE,
                    games=record["games"], values=record["values"],
                )
                counts["written"] += 1
            except LeagueStatContractError as exc:
                counts["rejected"] += 1
                print(f"  rejected {name}: {exc}")
        connection.commit()
        return counts
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-coverage", type=float, default=0.80)
    args = parser.parse_args(argv)
    print(f"database: {args.db}  season: {args.season}"
          f"{'  (dry run)' if args.dry_run else ''}")
    print(json.dumps(refresh(args.db, season=args.season, dry_run=args.dry_run,
                             min_coverage=args.min_coverage),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
