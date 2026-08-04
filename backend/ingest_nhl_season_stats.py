#!/usr/bin/env python3
"""Publish NHL season stats for all three player types from nhle.com's own reports.

Hockey has three player types -- forwards, defencemen, goaltenders -- and each
has a different job, so each gets a different published report:

  skater/summary    goals, assists, points, shots, shooting%, +/-, PIM, PP,
                    SH, TOI/GP, faceoff%          -- forwards and defencemen
  skater/realtime   blockedShots, hits, takeaways, giveaways
                    -- a defenceman's actual job, and absent from `summary`
  goalie/summary    saves, shotsAgainst, goalsAgainst, savePct, GAA, shutouts,
                    wins, losses, otLosses, gamesStarted

Why this exists alongside `ingest_nhl.py`
-----------------------------------------
`ingest_nhl.py` reads the per-player landing endpoint and maps forward fields
only, so every goaltender in the database reads 0 goals, 0 assists, 0 shots --
a goalie described entirely by things goalies do not do. That is the whole of
the "no goalie has ever recorded a save" gap. `saves` is published directly
here, so nothing below is derived from shotsAgainst - goalsAgainst.

It also reads `seasonTotals[-1]` -- the last row published for a player, with
no filter on which competition it belongs to. Measured 2026-08-04 on Frederik
Andersen: that row is the POSTSEASON (gameTypeId 3, 16 GP) while his published
regular season is 35 GP, 16-14, .874. Other players' last rows are AHL,
Olympic or Swedish league lines. This module asks for `gameTypeId=2` and
`leagueAbbrev=NHL` explicitly, because both are published discriminators and
neither should be inferred from position in a list.

Volume: these are league-wide reports, so a full refresh is ~20 requests
instead of the ~800 per-player calls the landing approach needs.

Usage:
  cd backend && venv/bin/python ingest_nhl_season_stats.py \\
      --season 20252026 --db data/picks.dev.db [--dry-run]
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
from season_keys import normalize_season  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
BASE = "https://api.nhle.com/stats/rest/en/{report}"
HDR = {"User-Agent": "legendarypicks/1.0"}
SOURCE = "nhle.com"
PAGE = 100

# Same reasoning as the NBA ingest: be a good guest. These are cheap
# league-wide reads, but an unpaced loop is how this box lost ESPN for a day.
MIN_INTERVAL = float(os.environ.get("LP_NHL_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)

# Pacing, retries and the per-host budget come from `paced_http`, which
# exists because six modules had each written this block. The interval and
# ladder below are this publisher's (nhle.com), unchanged.
_FETCH = paced_http.Fetcher(min_interval=MIN_INTERVAL, retry_waits=RETRY_WAITS,
                            headers=HDR, timeout=30, host_budget=0)


class NHLStatsIngestError(RuntimeError):
    """The published NHL snapshot was incomplete or invalid."""


def _get(url: str) -> dict:
    # host_budget=0: the 100-per-host ceiling is a measured ESPN
    # figure and no refusal has ever been observed from this host.
    try:
        return _FETCH.fetch(url)
    except Exception as exc:
        raise NHLStatsIngestError(f"{url} failed: {exc}") from exc


def fetch_report(report: str, season: int) -> list[dict]:
    """Page one published report to completion, keyed by playerId.

    `gameTypeId=2` is the regular season. It is asked for rather than filtered
    afterwards, so a postseason row can never arrive and be mistaken for one.
    """
    rows: list[dict] = []
    start = 0
    while True:
        query = urllib.parse.urlencode({
            "isAggregate": "false",
            "isGame": "false",
            "start": start,
            "limit": PAGE,
            "cayenneExp": f"seasonId={int(season)} and gameTypeId=2",
        })
        document = _get(f"{BASE.format(report=report)}?{query}")
        page = document.get("data") or []
        total = int(document.get("total") or 0)
        rows.extend(page)
        if len(rows) >= total:
            break
        # A page shorter than the page size while the publisher still claims
        # more rows means the report stopped early. Asking again just walks off
        # the end of it -- request after request, which is how this box got
        # itself blocked once already.
        if len(page) < PAGE:
            raise NHLStatsIngestError(
                f"{report}: page at start={start} returned {len(page)} rows "
                f"of a published {total}; the report ended early"
            )
        start += PAGE

    if len(rows) != total:
        raise NHLStatsIngestError(
            f"{report}: published total is {total} but "
            f"{len(rows)} rows were returned"
        )
    return rows


def _pct(value) -> float | None:
    """nhle.com publishes save/shooting percentages as a 0-1 fraction."""
    if value is None:
        return None
    return round(float(value) * 100, 1)


def _num(value):
    return None if value is None else value


def goalie_values(row: dict) -> dict:
    return {
        "nhl_position": "G",
        "nhl_team": str(row.get("teamAbbrevs") or "").split(",")[-1].strip(),
        "saves": _num(row.get("saves")),
        "shots_against": _num(row.get("shotsAgainst")),
        "goals_against": _num(row.get("goalsAgainst")),
        "save_pct": _pct(row.get("savePct")),
        "gaa": (None if row.get("goalsAgainstAverage") is None
                else round(float(row["goalsAgainstAverage"]), 2)),
        "shutouts": _num(row.get("shutouts")),
        "wins": _num(row.get("wins")),
        "losses": _num(row.get("losses")),
        "ot_losses": _num(row.get("otLosses")),
        "games_started": _num(row.get("gamesStarted")),
    }


def skater_values(row: dict, realtime: dict | None) -> dict:
    position = str(row.get("positionCode") or "?").upper()
    values = {
        "nhl_position": position,
        "nhl_team": str(row.get("teamAbbrevs") or "").split(",")[-1].strip(),
        "goals": _num(row.get("goals")),
        "assists": _num(row.get("assists")),
        "points_nhl": _num(row.get("points")),
        "shots": _num(row.get("shots")),
        "shooting_pct": _pct(row.get("shootingPct")),
        "plus_minus": _num(row.get("plusMinus")),
        "pim": _num(row.get("penaltyMinutes")),
        "ppg": _num(row.get("ppGoals")),
        "ppp": _num(row.get("ppPoints")),
        "shg": _num(row.get("shGoals")),
        "toi": _toi(row.get("timeOnIcePerGame")),
        "faceoff_pct": _pct(row.get("faceoffWinPct")),
    }
    # Blocks and hits are what a defenceman is measured on, and they live in a
    # different report. A forward gets them too -- they are real for everyone,
    # just not the headline.
    if realtime:
        values.update({
            "blocked_shots": _num(realtime.get("blockedShots")),
            "hits": _num(realtime.get("hits")),
            "takeaways": _num(realtime.get("takeaways")),
            "giveaways": _num(realtime.get("giveaways")),
        })
    return values


def _toi(seconds) -> str | None:
    """`timeOnIcePerGame` is published in seconds; the column is MM:SS text."""
    if seconds is None:
        return None
    total = int(round(float(seconds)))
    return f"{total // 60}:{total % 60:02d}"


def refresh(db_path: str, *, season: int, dry_run: bool = False) -> dict:
    goalies = fetch_report("goalie/summary", season)
    skaters = fetch_report("skater/summary", season)
    realtime = {
        int(row["playerId"]): row for row in fetch_report("skater/realtime", season)
    }
    print(f"published: {len(goalies)} goalies, {len(skaters)} skaters, "
          f"{len(realtime)} realtime rows")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        nhl_id_to_player, ambiguous = load_unique_source_id_map(
            connection, league="nhl", id_column="nhl_id"
        )
        counts = {"goalies": 0, "defence": 0, "forwards": 0,
                  "unresolved": 0, "rejected": 0}
        espn_season = normalize_season(SOURCE, "nhl", season)

        work = [(row, goalie_values(row), "goalies", row.get("goalieFullName"))
                for row in goalies]
        for row in skaters:
            position = str(row.get("positionCode") or "?").upper()
            bucket = "defence" if position == "D" else "forwards"
            work.append((row, skater_values(row, realtime.get(int(row["playerId"]))),
                         bucket, row.get("skaterFullName")))

        for row, values, bucket, name in work:
            source_key = str(row.get("playerId"))
            player_id = nhl_id_to_player.get(source_key)
            if player_id is None:
                counts["unresolved"] += 1
                if not dry_run:
                    queue_unresolved_player(
                        connection,
                        source=SOURCE,
                        raw_name=str(name or ""),
                        league="nhl",
                        team=values.get("nhl_team"),
                        source_player_key=source_key,
                        reason=("duplicate_spine_nhl_id"
                                if source_key in ambiguous
                                else "nhl_id_not_in_spine"),
                    )
                continue
            if dry_run:
                counts[bucket] += 1
                continue
            try:
                publish_player_stats(
                    connection,
                    player_id=player_id,
                    league="nhl",
                    season=espn_season,
                    stat_type="season",
                    source=SOURCE,
                    games=row.get("gamesPlayed"),
                    values=values,
                )
                counts[bucket] += 1
            except LeagueStatContractError as exc:
                counts["rejected"] += 1
                print(f"  rejected {name}: {exc}")

        if not dry_run:
            connection.commit()
        return counts
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True,
                        help="nhle.com season key, e.g. 20252026")
    parser.add_argument("--db", default=DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    print(f"database: {args.db}  season: {args.season}"
          f"{'  (dry run)' if args.dry_run else ''}")
    counts = refresh(args.db, season=args.season, dry_run=args.dry_run)
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
