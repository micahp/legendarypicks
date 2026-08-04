#!/usr/bin/env python3
"""Fill MLB team and position on the spine, from MLB's own API.

`docs/DATA-SPINE.md` says MLB has no team and no position because ESPN publishes
those and the spine carries no `espn_id` to ask ESPN with. The first half is
right -- `players.position` is 100% blank across every MLB player, and `team` is
89% blank on prod -- and the diagnosis is wrong.

MLB publishes both itself. `sports/1/players?season=YYYY` returns every player
in the season with `primaryPosition` and `currentTeam` on each. No ESPN
crosswalk was ever needed for this. Correct DATA-SPINE.md when this lands.

Team codes are normalised through `team_codes`, not copied. MLB publishes `AZ`
and `CWS` where this database is canonically `ARI` and `CHW`; writing the
published strings straight in would put two vocabularies in one column, which
is the exact failure `C/vocabulary` exists to catch. Both aliases already exist
in the alias table.

Players MLB does not publish for the season keep whatever they had. A retired
player has no current team, and a blank there is the honest answer, not a gap
to fill.

Usage:
  cd backend && venv/bin/python ingest_mlb_spine_identity.py \\
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
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from team_codes import normalize  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/sports/1/players?season={season}"
TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1"
HDR = {"User-Agent": "legendarypicks/1.0"}

MIN_INTERVAL = float(os.environ.get("LP_MLB_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)
_RETRYABLE = frozenset({403, 429, 500, 502, 503, 504})
_last_request_at = 0.0


class MLBSpineIngestError(RuntimeError):
    """The published MLB identity snapshot was incomplete or invalid."""


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
            raise MLBSpineIngestError(f"{url} failed: HTTP {exc.code}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            if wait is not None:
                time.sleep(wait)
                continue
            raise MLBSpineIngestError(f"{url} failed: {exc}") from exc
    raise MLBSpineIngestError(f"{url} failed: retries exhausted")


def team_abbreviations() -> dict[int, str]:
    """Published team id -> OUR canonical abbreviation."""
    teams = _get(TEAMS_URL).get("teams") or []
    if not teams:
        raise MLBSpineIngestError("no teams published")
    mapping: dict[int, str] = {}
    unknown: list[str] = []
    for team in teams:
        published = str(team.get("abbreviation") or "").strip()
        if not published:
            continue
        try:
            mapping[int(team["id"])] = normalize("mlb", published)
        except Exception:
            # Fail loud: an unmappable code is a new vocabulary entering the
            # column, which is the thing this normalisation exists to prevent.
            unknown.append(published)
    if unknown:
        raise MLBSpineIngestError(
            "published team codes with no canonical mapping: "
            + ", ".join(sorted(unknown))
        )
    return mapping


def published_people(season: int) -> list[dict]:
    people = _get(PEOPLE_URL.format(season=int(season))).get("people") or []
    if not people:
        raise MLBSpineIngestError(f"no people published for season {season}")
    return people


def refresh(db_path: str, *, season: int, dry_run: bool = False) -> dict:
    teams = team_abbreviations()
    people = published_people(season)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        spine = {
            int(row["mlbam_id"]): row
            for row in connection.execute(
                """SELECT id, mlbam_id, team, position FROM players
                   WHERE lower(league)='mlb' AND mlbam_id IS NOT NULL
                     AND mlbam_id!=0"""
            )
        }
        counts = {"published": len(people), "not_in_spine": 0,
                  "team_set": 0, "position_set": 0, "unchanged": 0,
                  "no_current_team": 0}
        for person in people:
            row = spine.get(int(person.get("id") or 0))
            if row is None:
                counts["not_in_spine"] += 1
                continue
            position = ((person.get("primaryPosition") or {})
                        .get("abbreviation") or "").strip() or None
            published_team = (person.get("currentTeam") or {}).get("id")
            team = teams.get(int(published_team)) if published_team else None
            if team is None:
                counts["no_current_team"] += 1

            changes, params = [], []
            if team and team != row["team"]:
                changes.append("team=?")
                params.append(team)
                counts["team_set"] += 1
            if position and position != row["position"]:
                changes.append("position=?")
                params.append(position)
                counts["position_set"] += 1
            if not changes:
                counts["unchanged"] += 1
                continue
            if dry_run:
                continue
            connection.execute(
                f"UPDATE players SET {', '.join(changes)} WHERE id=?",
                (*params, int(row["id"])),
            )
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
