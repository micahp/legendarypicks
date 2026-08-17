#!/usr/bin/env python3
"""Publish the ESPN ATP/WTA ranking athlete spine into ``players``.

Tennis has no teams to traverse.  ESPN's generic core athlete collection is a
16,000-row list of ``$ref`` stubs, which would turn a spine refresh into one
request per athlete.  Its published rankings endpoint instead returns each
ranked athlete's ESPN id, display name, and active flag in one payload:

    https://site.web.api.espn.com/apis/site/v2/sports/tennis/{atp|wta}/rankings

That is one request per league (two total), never a per-athlete loop.  The
ranking collection is the publisher's complete ranked population for the
endpoint, so an empty collection, duplicate source id, missing identity field,
or a name that the name-only prop resolver could not distinguish fails before
any database row changes.

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
SOURCE = "espn_rankings"


class TennisSpineError(RuntimeError):
    """The published identity population is not safe to publish."""


def rankings_url(league: str) -> str:
    """The one bulk ESPN ranking request for one tennis league."""
    if league not in LEAGUES:
        raise TennisSpineError(f"unsupported tennis league {league!r}")
    return (
        espn_client._SITE.format(path=f"tennis/{league}")
        + "/rankings?region=us&lang=en&contentorigin=espn"
    )


def _fold_name(value: str) -> str:
    """Mirror the resolver's diacritic-insensitive identity boundary."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value.lower())).strip()


def extract_ranked_athletes(document: dict, league: str) -> list[dict]:
    """Validate ESPN's one ranking collection and return publisher identities.

    A source list that is merely *mostly* well formed is not a safe identity
    spine.  The downstream resolver only receives a name, so a duplicate
    folded name would make that resolver ambiguous even though the native IDs
    differ; reject it rather than publishing an apparently healthy unusable
    row.
    """
    rankings = document.get("rankings") if isinstance(document, dict) else None
    if not isinstance(rankings, list) or not rankings:
        raise TennisSpineError(
            f"{league} rankings endpoint published 0 ranking collections"
        )
    expected_name = league.upper()
    matching = [
        ranking for ranking in rankings
        if isinstance(ranking, dict) and str(ranking.get("name") or "").upper() == expected_name
    ]
    if len(matching) != 1:
        raise TennisSpineError(
            f"{league} rankings endpoint published {len(matching)} matching "
            f"{expected_name} collections, expected exactly 1"
        )
    ranks = matching[0].get("ranks")
    if not isinstance(ranks, list) or not ranks:
        raise TennisSpineError(
            f"{league} {expected_name} ranking collection published 0 athletes"
        )

    athletes: list[dict] = []
    for number, rank in enumerate(ranks, start=1):
        athlete = rank.get("athlete") if isinstance(rank, dict) else None
        if not isinstance(athlete, dict):
            raise TennisSpineError(
                f"{league} ranking {number} has no athlete identity"
            )
        source_id = str(athlete.get("id") or "").strip()
        name = athlete.get("displayName")
        active = athlete.get("active")
        if not source_id or source_id == "0":
            raise TennisSpineError(f"{league} ranking {number} has no ESPN athlete id")
        if not isinstance(name, str) or not name.strip():
            raise TennisSpineError(
                f"{league} ranking {number} ({source_id}) has no display name"
            )
        if not isinstance(active, bool):
            raise TennisSpineError(
                f"{league} ranking {number} ({source_id}) has non-boolean active status"
            )
        athletes.append({"espn_id": source_id, "name": name, "active": active})

    source_ids = [athlete["espn_id"] for athlete in athletes]
    if len(set(source_ids)) != len(source_ids):
        raise TennisSpineError(
            f"{league} rankings contain {len(set(source_ids))} unique ESPN ids "
            f"for {len(source_ids)} published athletes"
        )
    folded_names = [_fold_name(athlete["name"]) for athlete in athletes]
    if not all(folded_names) or len(set(folded_names)) != len(folded_names):
        raise TennisSpineError(
            f"{league} rankings contain {len(set(folded_names))} unique resolver names "
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
            dry_run: bool = False) -> dict:
    """Fetch both complete source populations, validate, then atomically publish."""
    selected = tuple(leagues)
    if not selected or len(set(selected)) != len(selected) or any(lg not in LEAGUES for lg in selected):
        raise TennisSpineError(f"leagues must be a unique non-empty subset of {LEAGUES}")
    request_counts = request_counts if request_counts is not None else collections.Counter()
    fetch_json = fetch_json or _new_fetch_json(len(selected))

    # Fetch and validate every league first.  Nothing in the database changes if
    # ESPN publishes one healthy ranking list and one empty/broken one.
    populations = {}
    for league in selected:
        url = rankings_url(league)
        request_counts[HOST] += 1
        try:
            document = fetch_json(url)
        except Exception as exc:  # status and endpoint are evidence, not a guess about ESPN
            raise TennisSpineError(
                f"{league} bulk rankings request failed at {url}: {exc}"
            ) from exc
        populations[league] = extract_ranked_athletes(document, league)

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
        print(f"{league}: published {published} of {published} ESPN ranking athletes")
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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    leagues = tuple(args.league or LEAGUES)
    request_counts = collections.Counter()
    planned = len(leagues)
    print(f"database: {args.db}{' (dry run)' if args.dry_run else ''}")
    print(f"request plan: {HOST} {planned} of {planned} "
          f"(one bulk rankings request per league; no per-athlete requests)")
    try:
        results = refresh(
            args.db, leagues=leagues, request_counts=request_counts, dry_run=args.dry_run
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
