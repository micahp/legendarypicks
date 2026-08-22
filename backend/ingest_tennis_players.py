#!/usr/bin/env python3
"""Publish ESPN's current ATP/WTA tournament-field identity spine into ``players``.

Tennis has no teams to traverse.  ESPN's generic core athlete collection is a
16,000-row list of ``$ref`` stubs, which would turn a spine refresh into one
request per athlete. Its published scoreboard instead returns every singles
draw participant and native athlete id in one payload per tour:

    https://site.api.espn.com/apis/site/v2/sports/tennis/{atp|wta}/scoreboard

That is one request per league (two total), never a per-athlete loop. The
payload carries both singles draws, even when asked through one tour path, so
the source boundary is the published bracket: ``mens-singles`` for ATP and
``womens-singles`` for WTA. An empty field, duplicate source id, cross-draw
identity, missing identity field, or a name that the resolver cannot
distinguish fails before any database row changes.

The publisher spelling is stored verbatim.  Bovada's resolver folds diacritics
on both sides; doing that here would lose the authoritative spelling and make
the table less useful as an identity record.

Usage:
  LP_DB_PATH=/absolute/picks.dev.db python ingest_tennis_players.py
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
from typing import Callable, Iterable

import espn_client
import paced_http


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
LEAGUES = ("atp", "wta")
HOST = "site.web.api.espn.com"
SOURCE = "espn_tournament_scoreboard"
SINGLES_GROUP = {"atp": "mens-singles", "wta": "womens-singles"}


class TennisSpineError(RuntimeError):
    """The published identity population is not safe to publish."""


def scoreboard_url(league: str, anchor: dt.date) -> str:
    """The one bulk ESPN tournament-field request for one tennis league."""
    if league not in LEAGUES:
        raise TennisSpineError(f"unsupported tennis league {league!r}")
    return (
        espn_client._SITE.format(path=f"tennis/{league}")
        + f"/scoreboard?dates={anchor:%Y%m%d}&limit=100"
    )


def _fold_name(value: str) -> str:
    """Mirror the resolver's diacritic-insensitive identity boundary."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value.lower())).strip()


def extract_tournament_athletes(document: dict, league: str) -> list[dict]:
    """Validate one tour's published singles draw and return identities."""
    if not isinstance(document, dict):
        raise TennisSpineError(f"{league} scoreboard response is not an object")
    source_league = ((document.get("leagues") or [{}])[0].get("slug") or "").lower()
    if source_league != league:
        raise TennisSpineError(f"{league} scoreboard identified itself as {source_league or 'missing'}")
    target_group = SINGLES_GROUP[league]
    identities: dict[str, str] = {}
    groups = 0
    for event in document.get("events") or []:
        for grouping in event.get("groupings") or []:
            if (grouping.get("grouping") or {}).get("slug") != target_group:
                continue
            groups += 1
            for competition in grouping.get("competitions") or []:
                for competitor in competition.get("competitors") or []:
                    source_id = str(competitor.get("id") or "").strip()
                    name = (competitor.get("athlete") or {}).get("displayName")
                    if not source_id or source_id == "0":
                        raise TennisSpineError(f"{league} {target_group} competitor has no ESPN athlete id")
                    if not isinstance(name, str) or not name.strip() or name.strip().upper() == "TBD":
                        # ESPN represents an unfilled future bracket side with a
                        # negative competitor id and no athlete. It is not an
                        # identity to publish. A non-negative id without a name
                        # would instead be a malformed real participant.
                        if source_id.startswith("-"):
                            continue
                        raise TennisSpineError(f"{league} {target_group} competitor {source_id} has no athlete name")
                    prior = identities.setdefault(source_id, name)
                    if prior != name:
                        raise TennisSpineError(f"{league} ESPN athlete id {source_id} maps to more than one name")
    if not groups:
        raise TennisSpineError(f"{league} scoreboard published no {target_group} draw")
    if not identities:
        raise TennisSpineError(f"{league} {target_group} draw published 0 athletes")
    athletes = [
        {"espn_id": source_id, "name": name, "active": True}
        for source_id, name in sorted(identities.items())
    ]
    folded_names = [_fold_name(athlete["name"]) for athlete in athletes]
    if not all(folded_names) or len(set(folded_names)) != len(folded_names):
        raise TennisSpineError(
            f"{league} {target_group} draw contains {len(set(folded_names))} unique resolver names "
            f"for {len(folded_names)} published athletes"
        )
    return athletes


def _payload_sha256(athletes: Iterable[dict]) -> str:
    """Stable audit fingerprint of the source identity population."""
    canonical = sorted(
        (
            str(athlete["espn_id"]),
            athlete["name"],
            bool(athlete["active"]),
        )
        for athlete in athletes
    )
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_player_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(players)").fetchall()
    }
    required = {"id", "name", "team", "league", "espn_id", "active", "updated_at"}
    missing = sorted(required - columns)
    if missing:
        raise TennisSpineError(
            "players schema cannot hold the tennis spine; missing " + ", ".join(missing)
        )


def _plan_publication(connection: sqlite3.Connection, league: str,
                      athletes: list[dict]) -> list[dict]:
    """Plan by native ID only, refusing any name-only legacy collision."""
    rows = connection.execute(
        "SELECT id,name,team,league,espn_id,active FROM players WHERE league=?", (league,)
    ).fetchall()
    existing_by_id: dict[str, sqlite3.Row] = {}
    existing_by_folded_name: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in rows:
        source_id = str(row["espn_id"] or "").strip()
        if source_id:
            if source_id in existing_by_id:
                raise TennisSpineError(
                    f"{league} spine already has duplicate ESPN id {source_id}; refusing to publish"
                )
            existing_by_id[source_id] = row
        existing_by_folded_name[_fold_name(row["name"] or "")].append(row)

    plan = []
    name_conflicts = []
    for athlete in athletes:
        source_id = athlete["espn_id"]
        existing = existing_by_id.get(source_id)
        conflicts = [
            row for row in existing_by_folded_name[_fold_name(athlete["name"])]
            if existing is None or row["id"] != existing["id"]
        ]
        if conflicts:
            name_conflicts.append(
                f"{athlete['name']!r} (ESPN {source_id}) conflicts with players.id "
                + ", ".join(str(row["id"]) for row in conflicts)
            )
            continue
        plan.append({"athlete": athlete, "existing": existing})

    if name_conflicts:
        preview = "; ".join(name_conflicts[:3])
        suffix = "" if len(name_conflicts) <= 3 else f"; and {len(name_conflicts) - 3} more"
        raise TennisSpineError(
            f"{league} has {len(name_conflicts)} name-only/other-id spine conflicts; "
            f"will not attach or duplicate identities by name: {preview}{suffix}"
        )
    if len(plan) != len(athletes):
        raise TennisSpineError(
            f"{league} planned {len(plan)} of {len(athletes)} publisher identities"
        )
    return plan


def _new_fetch_json(host_budget: int) -> Callable[[str], dict]:
    """Create this job's bounded ESPN client; retries would hide request spend."""
    fetcher = paced_http.Fetcher(
        min_interval=0.0,
        retry_waits=(),
        headers=espn_client._HDRS,
        timeout=30,
        cache_dir="",
        host_budget=host_budget,
    )
    return fetcher.json


def refresh(db_path: str, *, leagues: Iterable[str] = LEAGUES,
            fetch_json: Callable[[str], dict] | None = None,
            request_counts: collections.Counter | None = None,
            anchor: dt.date | None = None,
            dry_run: bool = False) -> dict:
    """Fetch both complete source populations, validate, then atomically publish."""
    selected = tuple(leagues)
    if not selected or len(set(selected)) != len(selected) or any(lg not in LEAGUES for lg in selected):
        raise TennisSpineError(f"leagues must be a unique non-empty subset of {LEAGUES}")
    request_counts = request_counts if request_counts is not None else collections.Counter()
    fetch_json = fetch_json or _new_fetch_json(len(selected))
    anchor = anchor or dt.date.today()

    # Fetch and validate every league first. Nothing changes if either published
    # singles field is empty, malformed, or crosses the other tour's draw.
    populations = {}
    for league in selected:
        url = scoreboard_url(league, anchor)
        request_counts[HOST] += 1
        try:
            document = fetch_json(url)
        except Exception as exc:  # status and endpoint are evidence, not a guess about ESPN
            raise TennisSpineError(
                f"{league} bulk scoreboard request failed at {url}: {exc}"
            ) from exc
        populations[league] = extract_tournament_athletes(document, league)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        _require_player_columns(connection)
        plans = {
            league: _plan_publication(connection, league, populations[league])
            for league in selected
        }
        results = {}
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if dry_run:
            for league in selected:
                matched = sum(item["existing"] is not None for item in plans[league])
                results[league] = {
                    "published": len(populations[league]),
                    "unique_ids": len(populations[league]),
                    "active": sum(athlete["active"] for athlete in populations[league]),
                    "matched": matched,
                    "inserted": len(populations[league]) - matched,
                    "refreshed": 0,
                    "unchanged": matched,
                    "sha256": _payload_sha256(populations[league]),
                }
            return results

        try:
            connection.execute("BEGIN IMMEDIATE")
            for league in selected:
                matched = inserted = refreshed = unchanged = 0
                for item in plans[league]:
                    athlete = item["athlete"]
                    existing = item["existing"]
                    if existing is None:
                        connection.execute(
                            """INSERT INTO players(name,team,league,espn_id,active,updated_at)
                               VALUES(?,NULL,?,?,?,?)""",
                            (athlete["name"], league, athlete["espn_id"],
                             int(athlete["active"]), now),
                        )
                        inserted += 1
                        continue
                    matched += 1
                    if (
                        existing["name"] != athlete["name"]
                        or existing["team"] is not None
                        or existing["active"] != int(athlete["active"])
                    ):
                        connection.execute(
                            """UPDATE players
                               SET name=?, team=NULL, active=?, updated_at=?
                               WHERE id=?""",
                            (athlete["name"], int(athlete["active"]), now, existing["id"]),
                        )
                        refreshed += 1
                    else:
                        unchanged += 1
                results[league] = {
                    "published": len(populations[league]),
                    "unique_ids": len(populations[league]),
                    "active": sum(athlete["active"] for athlete in populations[league]),
                    "matched": matched,
                    "inserted": inserted,
                    "refreshed": refreshed,
                    "unchanged": unchanged,
                    "sha256": _payload_sha256(populations[league]),
                }
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return results
    finally:
        connection.close()


def _print_results(results: dict) -> None:
    for league, result in results.items():
        published = result["published"]
        print(f"{league}: published {published} of {published} ESPN singles-draw athletes")
        print(f"  unique ESPN ids {result['unique_ids']} of {published}; "
              f"active {result['active']} of {published}; sha256 {result['sha256'][:12]}")
        print(f"  matched {result['matched']} of {published} existing ESPN ids; "
              f"inserted {result['inserted']} of {published}; "
              f"refreshed {result['refreshed']} of {published}; "
              f"unchanged {result['unchanged']} of {published}")


def _print_request_counts(request_counts: collections.Counter, planned: int) -> None:
    spent = request_counts.get(HOST, 0)
    print(f"requests spent: {HOST} {spent} of {planned}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB, help="absolute SQLite database path")
    parser.add_argument("--league", choices=LEAGUES, action="append",
                        help="publish only one league (repeatable)")
    parser.add_argument("--anchor", type=dt.date.fromisoformat,
                        help="published scoreboard date (default: today)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    leagues = tuple(args.league or LEAGUES)
    request_counts = collections.Counter()
    planned = len(leagues)
    print(f"database: {args.db}{' (dry run)' if args.dry_run else ''}")
    print(f"request plan: {HOST} {planned} of {planned} "
          f"(one bulk scoreboard request per league; no per-athlete requests)")
    try:
        results = refresh(
            args.db, leagues=leagues, request_counts=request_counts,
            anchor=args.anchor, dry_run=args.dry_run
        )
        _print_results(results)
        return 0
    except TennisSpineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        _print_request_counts(request_counts, planned)


if __name__ == "__main__":
    sys.exit(main())
