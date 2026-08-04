#!/usr/bin/env python3
"""Atomically publish NBA season statistics from ESPN's Core API.

The ESPN athlete-season endpoint is the published owner for seasons after
2023.  Network reads and response validation finish before the writable
transaction starts, so a partial upstream outage cannot replace the last good
league snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

from league_stats import LeagueStatContractError, publish_player_stats


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
    "seasons/{season}/types/2/athletes/{espn_id}/statistics"
    "?lang=en&region=us"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
}

# One request per athlete, ~520 athletes, and the original loop issued them as
# fast as the socket allowed.  On 2026-08-04 that run died at 53s on an ESPN
# 403, and every `sports.core.api.espn.com` read from this box 403'd for the
# next few hours -- which also took out the live Standings tab, because the
# same host serves it.  The 403 came back on its own once the box went quiet,
# so it was volume, not a ban.  Hence: a floor on the gap between requests, and
# a retry that waits rather than aborting the whole snapshot on one refusal.
MIN_INTERVAL = float(os.environ.get("LP_ESPN_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)
_RETRYABLE = frozenset({403, 429, 500, 502, 503, 504})
_last_request_at = 0.0


class NBAStatsIngestError(RuntimeError):
    """The published NBA snapshot was incomplete or invalid."""


def _throttle() -> None:
    """Hold MIN_INTERVAL between consecutive upstream reads."""
    global _last_request_at
    gap = time.monotonic() - _last_request_at
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_request_at = time.monotonic()


def fetch_athlete_stats(espn_id: str, season: int) -> dict | None:
    """Fetch one published athlete season; a 404 means no published line.

    Paced, and patient with a refusal: a 403 here means we are asking too
    fast, and backing off recovers where retrying immediately does not.
    """
    request = urllib.request.Request(
        URL.format(season=int(season), espn_id=espn_id),
        headers=HEADERS,
    )
    for attempt, wait in enumerate((*RETRY_WAITS, None)):
        _throttle()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in _RETRYABLE and wait is not None:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = max(wait, float(retry_after))
                except (TypeError, ValueError):
                    pass
                time.sleep(wait)
                continue
            raise NBAStatsIngestError(
                f"ESPN statistics request failed for {espn_id}: "
                f"HTTP {exc.code} after {attempt + 1} attempt(s)"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            if wait is not None:
                time.sleep(wait)
                continue
            raise NBAStatsIngestError(
                f"ESPN statistics request failed for {espn_id}: {exc}"
            ) from exc
    raise NBAStatsIngestError(
        f"ESPN statistics request failed for {espn_id}: retries exhausted"
    )


def parse_athlete_stats(payload: Mapping[str, object]) -> dict:
    """Normalize an ESPN Core statistics response into player_stats fields."""
    splits = payload.get("splits")
    if not isinstance(splits, Mapping):
        raise NBAStatsIngestError("ESPN statistics response is missing splits")
    categories = splits.get("categories")
    if not isinstance(categories, list):
        raise NBAStatsIngestError(
            "ESPN statistics response is missing split categories"
        )

    stats: dict[str, object] = {}
    for category in categories:
        if not isinstance(category, Mapping):
            continue
        for stat in category.get("stats") or []:
            if not isinstance(stat, Mapping) or not stat.get("name"):
                continue
            stats[str(stat["name"])] = stat.get("value")

    required = (
        "gamesPlayed",
        "avgPoints",
        "avgRebounds",
        "avgAssists",
        "avgSteals",
        "avgBlocks",
        "avgTurnovers",
        "fieldGoalsMade",
        "fieldGoalsAttempted",
        "threePointFieldGoalsMade",
        "threePointFieldGoalsAttempted",
        "freeThrowsMade",
        "freeThrowsAttempted",
        "avgMinutes",
        "trueShootingPct",
    )
    missing = [name for name in required if stats.get(name) is None]
    if missing:
        raise NBAStatsIngestError(
            "ESPN statistics response is missing: " + ", ".join(missing)
        )

    return {
        "games": int(stats["gamesPlayed"]),
        "values": {
            "pts": round(float(stats["avgPoints"]), 1),
            "reb": round(float(stats["avgRebounds"]), 1),
            "ast": round(float(stats["avgAssists"]), 1),
            "stl": round(float(stats["avgSteals"]), 1),
            "blk": round(float(stats["avgBlocks"]), 1),
            "tov": round(float(stats["avgTurnovers"]), 1),
            "fgm": int(stats["fieldGoalsMade"]),
            "fga": int(stats["fieldGoalsAttempted"]),
            "fg3m": int(stats["threePointFieldGoalsMade"]),
            "fg3a": int(stats["threePointFieldGoalsAttempted"]),
            "ftm": int(stats["freeThrowsMade"]),
            "fta": int(stats["freeThrowsAttempted"]),
            "minutes": round(float(stats["avgMinutes"]), 1),
            "ts_pct": round(float(stats["trueShootingPct"]), 1),
        },
    }


def _load_targets(db_path: str) -> list[sqlite3.Row]:
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        missing_ids = connection.execute(
            """SELECT COUNT(*) FROM players
               WHERE league='nba' AND active=1
                 AND (
                   espn_id IS NULL OR TRIM(CAST(espn_id AS TEXT))=''
                 )"""
        ).fetchone()[0]
        if missing_ids:
            raise NBAStatsIngestError(
                f"{missing_ids} active NBA players lack canonical ESPN IDs"
            )
        duplicates = connection.execute(
            """SELECT CAST(espn_id AS TEXT),COUNT(*)
               FROM players
               WHERE league='nba' AND active=1
                 AND espn_id IS NOT NULL AND CAST(espn_id AS TEXT)!=''
               GROUP BY CAST(espn_id AS TEXT)
               HAVING COUNT(*)>1"""
        ).fetchall()
        if duplicates:
            raise NBAStatsIngestError(
                f"NBA spine has {len(duplicates)} duplicate active ESPN IDs"
            )
        return connection.execute(
            """SELECT id,name,CAST(espn_id AS TEXT) AS espn_id
               FROM players
               WHERE league='nba' AND active=1
                 AND espn_id IS NOT NULL AND CAST(espn_id AS TEXT)!=''
               ORDER BY id"""
        ).fetchall()
    finally:
        connection.close()


def refresh_nba_stats(
    db_path: str,
    *,
    season: int,
    fetcher: Callable[[str, int], Mapping[str, object] | None] = (
        fetch_athlete_stats
    ),
    min_coverage: float = 0.90,
) -> dict:
    """Fetch, validate, and atomically replace one NBA season population."""
    if int(season) <= 2023:
        raise NBAStatsIngestError(
            "ESPN Core owns NBA player_stats only after season 2023"
        )
    if not 0 < float(min_coverage) <= 1:
        raise NBAStatsIngestError(
            "min_coverage must be greater than 0 and at most 1"
        )
    targets = _load_targets(db_path)
    if not targets:
        raise NBAStatsIngestError(
            "no active NBA players with canonical ESPN IDs"
        )

    published: list[tuple[int, dict]] = []
    unavailable = 0
    for target in targets:
        payload = fetcher(target["espn_id"], int(season))
        if payload is None:
            unavailable += 1
            continue
        try:
            parsed = parse_athlete_stats(payload)
        except NBAStatsIngestError as exc:
            raise NBAStatsIngestError(
                f"invalid ESPN statistics for {target['name']} "
                f"({target['espn_id']}): {exc}"
            ) from exc
        if parsed["games"] > 0:
            published.append((int(target["id"]), parsed))

    coverage = len(published) / len(targets)
    if coverage < float(min_coverage):
        raise NBAStatsIngestError(
            f"NBA stats coverage {len(published)}/{len(targets)} "
            f"({coverage:.1%}) is below required {min_coverage:.1%}"
        )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM player_stats WHERE league='nba' AND season=?",
            (int(season),),
        )
        for player_id, parsed in published:
            publish_player_stats(
                connection,
                player_id=player_id,
                league="nba",
                season=int(season),
                stat_type="season",
                source="espn_core",
                games=parsed["games"],
                values=parsed["values"],
            )
        connection.commit()
    except (LeagueStatContractError, sqlite3.Error):
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "season": int(season),
        "targets": len(targets),
        "published": len(published),
        "unavailable": unavailable,
        "coverage": coverage,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--min-coverage", type=float, default=0.90)
    arguments = parser.parse_args()
    result = refresh_nba_stats(
        arguments.db,
        season=arguments.season,
        min_coverage=arguments.min_coverage,
    )
    print(
        "NBA {season}: published {published}/{targets} "
        "({coverage:.1%}); unavailable={unavailable}".format(**result)
    )


if __name__ == "__main__":
    main()
