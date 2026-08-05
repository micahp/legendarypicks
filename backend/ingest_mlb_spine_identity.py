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

Position is written one level per column, but both are the publisher's own:
`position` gets `primaryPosition.abbreviation` **verbatim** -- `OF` included,
because MLB publishes it for players it does not give a designated spot (that
is a fact about the player, not a gap; the group lives in `position_group` so
anyone wanting all outfielders filters there) -- and `position_group` gets
`primaryPosition.type`. `SP`/`RP` never appear here: that is ESPN's role
vocabulary and lives in `pitcher_role` (written by roster_sync.py).

Players MLB does not publish for the season keep whatever they had. A retired
player has no current team, and a blank there is the honest answer, not a gap
to fill.

Usage:
  cd backend && venv/bin/python ingest_mlb_spine_identity.py \\
      --season 2026 --db data/picks.dev.db [--apply]

Dry run by default: prints the counts and writes nothing. Pass `--apply` to
write. (`--dry-run` is still accepted and is the same as the default.)
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

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_league_stats import _identity_name_key  # noqa: E402
from team_codes import normalize  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/sports/1/players?season={season}"
TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1"
HDR = {"User-Agent": "legendarypicks/1.0"}

# `SP`/`RP` are ESPN's role vocabulary, never MLB's; the fill writes only MLB's
# `primaryPosition.abbreviation` (P C 1B 2B 3B SS LF CF RF DH TWP OF) and its
# parent type, so the two vocabularies stay in their own columns.

MIN_INTERVAL = float(os.environ.get("LP_MLB_MIN_INTERVAL", "0.5"))
RETRY_WAITS = (5.0, 20.0, 60.0)

# Pacing, retries and the per-host budget come from `paced_http`, which
# exists because six modules had each written this block. The interval and
# ladder below are this publisher's (statsapi.mlb.com), unchanged.
_FETCH = paced_http.Fetcher(min_interval=MIN_INTERVAL, retry_waits=RETRY_WAITS,
                            headers=HDR, timeout=30, host_budget=0)


class MLBSpineIngestError(RuntimeError):
    """The published MLB identity snapshot was incomplete or invalid."""


def _get(url: str) -> dict:
    # host_budget=0: the 100-per-host ceiling is a measured ESPN
    # figure and no refusal has ever been observed from this host.
    try:
        return _FETCH.fetch(url)
    except Exception as exc:
        raise MLBSpineIngestError(f"{url} failed: {exc}") from exc


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
        # Pass 1 -- resolve ESPN-only rows against the published roster.
        #
        # roster_sync.py fills espn_id onto rows that already have an mlbam_id,
        # and on a miss INSERTs a row with no mlbam_id at all. Those rows are
        # invisible to the fill below (which reads WHERE mlbam_id IS NOT NULL),
        # so they never get team/position/position_group and keep a stale ESPN
        # role. The data is published -- we only never asked. Ask now, on every
        # run, so the hole closes for future roster_sync inserts too.
        #
        # The rule, and no clause of it gets loosened:
        #   * only rows with mlbam_id IS NULL or 0 are considered;
        #   * the name must match EXACTLY ONE published player (the identity
        #     key -- same normaliser the audit uses, not a third one);
        #   * the team must agree (MLB currentTeam vs the row's team);
        #   * a non-null mlbam_id is never overwritten -- such rows are not
        #     even candidates here;
        #   * a player MLB does not publish stays unknown -- counted, never
        #     widened away.
        name_index: dict[str, list[dict]] = {}
        for person in people:
            name_index.setdefault(
                _identity_name_key(person.get("fullName") or ""), []
            ).append(person)

        counts = {"published": len(people), "not_in_spine": 0,
                  "team_set": 0, "position_set": 0, "unchanged": 0,
                  "no_current_team": 0, "position_group_set": 0,
                  "considered": 0, "resolved": 0, "ambiguous": 0,
                  "team_mismatch": 0, "unpublished": 0}
        for row in connection.execute(
                """SELECT id, name, team FROM players
                   WHERE lower(league)='mlb'
                     AND (mlbam_id IS NULL OR mlbam_id=0)"""):
            counts["considered"] += 1
            candidates = name_index.get(_identity_name_key(row["name"]), [])
            if not candidates:
                # MLB does not publish this player for the season. Unknown is
                # the honest answer, and it is not a failure.
                counts["unpublished"] += 1
                continue
            if len(candidates) > 1:
                # Two or more published players share the name. Never take the
                # first; a confident wrong id is exactly what gate G exists to
                # catch, and it would catch it red.
                counts["ambiguous"] += 1
                continue
            person = candidates[0]
            published_team = (person.get("currentTeam") or {}).get("id")
            person_team = teams.get(int(published_team)) if published_team else None
            if person_team is None or (row["team"] or "").upper() != person_team:
                # A unique name whose team disagrees is a skip, not a match --
                # a traded or stale row is where a wrong answer would come from.
                counts["team_mismatch"] += 1
                continue
            if not dry_run:
                connection.execute(
                    "UPDATE players SET mlbam_id=? WHERE id=?",
                    (int(person["id"]), int(row["id"])),
                )
            counts["resolved"] += 1

        # Build the spine AFTER pass 1 so the fill below covers the newly
        # resolved rows in the same run, and they end up complete.
        spine = {
            int(row["mlbam_id"]): row
            for row in connection.execute(
                """SELECT id, mlbam_id, team, position, position_group
                   FROM players
                   WHERE lower(league)='mlb' AND mlbam_id IS NOT NULL
                     AND mlbam_id!=0"""
            )
        }
        for person in people:
            row = spine.get(int(person.get("id") or 0))
            if row is None:
                counts["not_in_spine"] += 1
                continue
            primary = person.get("primaryPosition") or {}
            position = (primary.get("abbreviation") or "").strip() or None
            position_group = (primary.get("type") or "").strip() or None
            # position is the published abbreviation verbatim -- `OF` included.
            # The parent/child coexistence this creates (OF beside LF/CF/RF) is
            # legitimate because `position_group` carries the parent, and check
            # C/vocabulary knows that. NULLing it here made the data bend to a
            # gate, which is backwards.
            published_team = (person.get("currentTeam") or {}).get("id")
            team = teams.get(int(published_team)) if published_team else None
            if team is None:
                counts["no_current_team"] += 1

            changes, params = [], []
            if team and team != row["team"]:
                changes.append("team=?")
                params.append(team)
                counts["team_set"] += 1
            if position != row["position"]:
                changes.append("position=?")
                params.append(position)
                counts["position_set"] += 1
            if position_group != row["position_group"]:
                changes.append("position_group=?")
                params.append(position_group)
                counts["position_group_set"] += 1
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
    parser.add_argument("--apply", action="store_true",
                        help="write to the database (default is a dry run)")
    # Accepted for compatibility; identical to the new default behaviour.
    parser.add_argument("--dry-run", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    dry_run = not args.apply
    print(f"database: {args.db}  season: {args.season}"
          f"{'  (dry run)' if dry_run else ''}")
    print(json.dumps(refresh(args.db, season=args.season,
                             dry_run=dry_run), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
