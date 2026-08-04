#!/usr/bin/env python3
"""Fill MLB's counting stats from MLB's own API, on the rows Statcast already owns.

`docs/LEAGUE-STAT-GAPS.md` had MLB down as having no PA, hits, runs, RBI, ERA,
innings or WHIP, and both published qualifier rules as unmeasurable. The cause
was recorded as a missing publisher. It was not: we were reading Statcast, which
publishes exit velocity and xwOBA and was never going to carry an RBI, and never
asked MLB. `statsapi.mlb.com` publishes the whole batting line and the whole
pitching line, for the full player pool, in one request each.

This does not take the row from Statcast
----------------------------------------
`exit_velo`, `barrel_pct`, `xwoba` and `whiff_pct` are on the props page today.
This job writes only columns Statcast never had, on rows that already exist, and
stamps `counting_source` so the row can say which publisher filled which half.
`source` stays `statcast`; ownership is unchanged and nothing is overwritten.

The consequence, stated rather than hidden: a player MLB publishes who has no
Statcast row gets no row here. Measured 2026-08-04 that is 68 of 679 hitters and
7 of 777 pitchers. Creating those rows means making `statsapi` an owning source
in `league_stats.source_owns_stats`, which is a contract change and is not
smuggled in here. The count is reported on every run.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
URL = "https://statsapi.mlb.com/api/v1/stats"
HDR = {"User-Agent": "legendarypicks/1.0"}
COUNTING_SOURCE = "statsapi"

MIN_INTERVAL = float(os.environ.get("LP_MLB_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)
_RETRYABLE = frozenset({403, 429, 500, 502, 503, 504})
_last_request_at = 0.0

# published key -> our column. Only columns Statcast never filled.
BATTING_MAP = {
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


def _throttle() -> None:
    global _last_request_at
    gap = time.monotonic() - _last_request_at
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_request_at = time.monotonic()


def _get(url: str) -> dict:
    for wait in (*RETRY_WAITS, None):
        _throttle()
        try:
            request = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE and wait is not None:
                time.sleep(wait)
                continue
            raise MLBStatsIngestError(f"{url} failed: HTTP {exc.code}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            if wait is not None:
                time.sleep(wait)
                continue
            raise MLBStatsIngestError(f"{url} failed: {exc}") from exc
    raise MLBStatsIngestError(f"{url} failed: retries exhausted")


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
            updated = no_spine = no_row = 0
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
                else:
                    no_row += 1
            counts[stat_type] = {
                "published": len(splits),
                "updated": updated,
                "not_in_spine": no_spine,
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
