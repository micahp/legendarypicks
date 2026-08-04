#!/usr/bin/env python3
"""Fill MLB's counting stats from MLB's own API, on the rows Statcast already owns.

`docs/LEAGUE-STAT-GAPS.md` had MLB down as having no PA, hits, runs, RBI, ERA,
innings or WHIP, and both published qualifier rules as unmeasurable. The cause
was recorded as a missing publisher. It was not: we were reading Statcast, which
publishes exit velocity and xwOBA and was never going to carry an RBI, and never
asked MLB. `statsapi.mlb.com` publishes the whole batting line and the whole
pitching line, for the full player pool, in one request each.

Where a Statcast row exists, this does not take it
--------------------------------------------------
`exit_velo`, `barrel_pct`, `xwoba` and `whiff_pct` are on the props page today.
On a row that already exists this writes only columns Statcast never had and
stamps `counting_source`, so the row can say which publisher filled which half.
`source` stays `statcast` and nothing of theirs is overwritten.

Where no row exists, this creates one
-------------------------------------
`statsapi` is an owning source for MLB (`league_stats.source_owns_stats`). It
had to become one: the identity rebuild archives every current-season MLB
aggregate for regeneration -- an average computed over half a split identity is
wrong, not merely misfiled -- so after it runs there is nothing to update and
every row is a create. Creation goes through `publish_player_stats`, not a bare
INSERT, because that is what enforces ownership, the canonical player key and
the column whitelist.

**Order matters and nothing can enforce it.** Publishing is delete-then-insert
per (player_id, league, season, stat_type), so whichever of the two publishers
runs last owns the row and the other's columns are gone. This job is idempotent
and costs two requests. Run it AFTER any Statcast refresh, never before.

Innings are stored as true innings
----------------------------------
MLB publishes `inningsPitched` in baseball notation -- "128.2" means 128 and
two thirds, not 128.2 -- and also publishes `outs`. The published qualifier is
"1.0 IP x team games", which is a comparison, and comparing 128.2 to a threshold
is arithmetic on a number that does not mean what it looks like. So `innings`
holds outs/3, computed from the published `outs`. Format it back to baseball
notation for display.

Usage:
  cd backend && venv/bin/python ingest_mlb_counting_stats.py \\
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
    publish_player_stats,
)

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
URL = "https://statsapi.mlb.com/api/v1/stats"
HDR = {"User-Agent": "legendarypicks/1.0"}
COUNTING_SOURCE = "statsapi"

MIN_INTERVAL = float(os.environ.get("LP_MLB_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)

# Pacing, retries and the per-host budget come from `paced_http`, which
# exists because six modules had each written this block. The interval and
# ladder below are this publisher's (statsapi.mlb.com), unchanged.
_FETCH = paced_http.Fetcher(min_interval=MIN_INTERVAL, retry_waits=RETRY_WAITS,
                            headers=HDR, timeout=30, host_budget=0)

# published key -> our column.
#
# `avg` and `hr` were once left to Statcast, on the reasoning that this job
# should only write columns Statcast never filled. That reasoning breaks the
# moment the identity rebuild runs: it archives every Statcast row, so a
# regenerated league had `avg` and `hr` empty on all 1,325 players and
# `A/required-stats[batting]` failed with "column exists but 0 rows
# populated". MLB publishes both. A column another publisher also fills is not
# a reason to leave it blank.
BATTING_MAP = {
    "avg": "avg",
    "homeRuns": "hr",
    "plateAppearances": "pa",
    "atBats": "ab",
    "hits": "mlb_hits",
    "runs": "runs",
    "rbi": "rbi",
    "doubles": "doubles",
    "triples": "triples",
    "baseOnBalls": "bb",
    "stolenBases": "sb",
    "obp": "obp",
    "slg": "slg",
    "ops": "ops",
    "totalBases": "tb",
}
PITCHING_MAP = {
    "era": "era",
    "whip": "whip",
    "earnedRuns": "earned_runs",
    "strikeOuts": "strikeouts",
    "saves": "mlb_saves",
    "wins": "wins",
    "losses": "losses",
    "shutouts": "shutouts",
}
_FLOAT_COLUMNS = {"obp", "slg", "ops", "era", "whip", "innings"}


class MLBStatsIngestError(RuntimeError):
    """The published MLB snapshot was incomplete or invalid."""


def _get(url: str) -> dict:
    # host_budget=0: the 100-per-host ceiling is a measured ESPN
    # figure and no refusal has ever been observed from this host.
    try:
        return _FETCH.fetch(url)
    except Exception as exc:
        raise MLBStatsIngestError(f"{url} failed: {exc}") from exc


def fetch_group(group: str, season: int) -> list[dict]:
    """Fetch one published season group for the FULL player pool.

    `playerPool=All` matters: the default is `Qualified`, which for 2026 is 149
    hitters out of 679. A league snapshot built from the default would silently
    be the leaderboard.
    """
    query = urllib.parse.urlencode({
        "stats": "season",
        "group": group,
        "season": int(season),
        "sportId": 1,
        "limit": 5000,
        "playerPool": "All",
    })
    document = _get(f"{URL}?{query}")
    blocks = document.get("stats") or []
    if not blocks:
        raise MLBStatsIngestError(f"{group}: no stats block published")
    splits = blocks[0].get("splits") or []
    total = blocks[0].get("totalSplits")
    if total is not None and len(splits) != int(total):
        raise MLBStatsIngestError(
            f"{group}: published totalSplits is {total} but "
            f"{len(splits)} rows were returned"
        )
    return splits


def _number(value):
    """statsapi publishes rates as strings ('3.57', '.299') and counts as ints."""
    if value is None or value == "" or value == "-.--" or value == "-":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def batting_values(stat: dict) -> dict:
    return {
        column: _number(stat.get(key)) for key, column in BATTING_MAP.items()
    }


def pitching_values(stat: dict) -> dict:
    values = {
        column: _number(stat.get(key)) for key, column in PITCHING_MAP.items()
    }
    # See the module docstring: `inningsPitched` "128.2" is 128 and two thirds.
    # `outs` is published, so the true value needs no interpretation.
    outs = _number(stat.get("outs"))
    values["innings"] = None if outs is None else round(float(outs) / 3, 3)
    return values


def refresh(db_path: str, *, season: int, dry_run: bool = False) -> dict:
    groups = {
        "hitting": ("batting", batting_values),
        "pitching": ("pitching", pitching_values),
    }
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    counts = {}
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(player_stats)")
        }
        for needed in ("pa", "innings", "counting_source"):
            if needed not in columns:
                raise MLBStatsIngestError(
                    f"player_stats has no `{needed}` column -- run "
                    "migrate_mlb_counting_stats.py first"
                )

        spine = {
            int(row["mlbam_id"]): int(row["id"])
            for row in connection.execute(
                """SELECT id, mlbam_id FROM players
                   WHERE lower(league)='mlb' AND mlbam_id IS NOT NULL
                     AND mlbam_id!=0"""
            )
        }

        for group, (stat_type, mapper) in groups.items():
            splits = fetch_group(group, season)
            updated = no_spine = no_row = created = rejected = 0
            for split in splits:
                published_id = (split.get("player") or {}).get("id")
                if published_id is None:
                    continue
                player_id = spine.get(int(published_id))
                if player_id is None:
                    no_spine += 1
                    continue
                values = mapper(split.get("stat") or {})
                values["counting_source"] = COUNTING_SOURCE
                assignments = ", ".join(f"{c}=?" for c in values)
                params = [
                    (round(v, 4) if c in _FLOAT_COLUMNS and v is not None else v)
                    for c, v in values.items()
                ]
                if dry_run:
                    exists = connection.execute(
                        """SELECT 1 FROM player_stats WHERE player_id=?
                           AND lower(league)='mlb' AND season=? AND stat_type=?""",
                        (player_id, int(season), stat_type),
                    ).fetchone()
                    if exists:
                        updated += 1
                    else:
                        no_row += 1
                    continue
                cursor = connection.execute(
                    f"""UPDATE player_stats SET {assignments}
                        WHERE player_id=? AND lower(league)='mlb'
                          AND season=? AND stat_type=?""",
                    (*params, player_id, int(season), stat_type),
                )
                if cursor.rowcount:
                    updated += cursor.rowcount
                    continue
                # No row to fill. Create one through the contract rather than
                # with a bare INSERT -- publish_player_stats is what enforces
                # ownership, the canonical player key and the column
                # whitelist, and going around it is how a row ends up in this
                # table that no publisher will admit to.
                #
                # This is the path the identity rebuild depends on: it
                # archives every current-season MLB aggregate, so after it
                # runs there is nothing to update and every row here is a
                # create.
                try:
                    publish_player_stats(
                        connection,
                        player_id=player_id,
                        league="mlb",
                        season=int(season),
                        stat_type=stat_type,
                        source=COUNTING_SOURCE,
                        games=_number((split.get("stat") or {}).get("gamesPlayed")),
                        values={k: v for k, v in values.items()
                                if k != "counting_source"},
                    )
                    connection.execute(
                        """UPDATE player_stats SET counting_source=?
                           WHERE player_id=? AND lower(league)='mlb'
                             AND season=? AND stat_type=?""",
                        (COUNTING_SOURCE, player_id, int(season), stat_type),
                    )
                    created += 1
                except LeagueStatContractError as exc:
                    rejected += 1
                    print(f"  rejected {published_id}: {exc}")
            counts[stat_type] = {
                "published": len(splits),
                "updated": updated,
                "not_in_spine": no_spine,
                "created": created,
                "rejected": rejected,
                # Stated, not hidden: MLB publishes these players and we have
                # no Statcast row to hang the numbers on.
                "published_but_no_row": no_row,
            }
        if not dry_run:
            connection.commit()
        return counts
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print(f"database: {args.db}  season: {args.season}"
          f"{'  (dry run)' if args.dry_run else ''}")
    print(json.dumps(refresh(args.db, season=args.season,
                             dry_run=args.dry_run), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
