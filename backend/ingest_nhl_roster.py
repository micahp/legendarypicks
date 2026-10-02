#!/usr/bin/env python3
"""Publish the complete current NHL roster from NHL-native identities.

The canonical ESPN roster sync publishes useful membership, but it cannot fill
``players.nhl_id``.  NHL totals and game logs join on that native key, so this
publisher reads the league's own current-season rosters and publishes one
atomic, versioned snapshot only after all 32 teams and every identity resolve.

Source contract:

* team population: ``api-web.nhle.com/v1/standings/now``;
* current season: ``api-web.nhle.com/v1/club-schedule-season/CHI/now``;
* membership: ``api-web.nhle.com/v1/roster/{team}/{season}``.

The default is a dry run. ``--apply`` is required to mutate a database. The
publisher stays out of the scheduled registry until DEV and production have
each completed their separately authorized promotion checks.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sqlite3
import sys
from typing import Mapping, Sequence

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_league_stats import _identity_name_key  # noqa: E402
from roster_membership import (  # noqa: E402
    normalized_source_payload,
    publish_roster_snapshot,
    require_roster_schema,
)
from season_keys import normalize_season  # noqa: E402
from team_codes import UnknownTeamCode, normalize  # noqa: E402


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nhle.com"
SNAPSHOT_SOURCE = "nhle.com:roster"
EXPECTED_TEAMS = 32
TEAM_DIRECTORY_URL = "https://api-web.nhle.com/v1/standings/now"
SEASON_URL = "https://api-web.nhle.com/v1/club-schedule-season/CHI/now"
ROSTER_URL = "https://api-web.nhle.com/v1/roster/{team}/{season}"
MIN_INTERVAL = float(os.environ.get("LP_NHL_MIN_INTERVAL", "0.5"))

_FETCH = paced_http.Fetcher(
    min_interval=MIN_INTERVAL,
    retry_waits=(5.0, 20.0, 60.0),
    headers={"User-Agent": "legendarypicks/1.0"},
    timeout=30,
    host_budget=0,
)


class NHLRosterError(RuntimeError):
    """The NHL roster population cannot be safely published."""


def _get(url: str) -> dict:
    try:
        document = _FETCH.fetch(url)
    except Exception as exc:
        raise NHLRosterError(f"{url} failed: {exc}") from exc
    if not isinstance(document, dict):
        raise NHLRosterError(f"{url} returned {type(document).__name__}, expected object")
    return document


def _position(value) -> str | None:
    """Normalize NHL's L/R shorthand to the stored ESPN vocabulary."""
    code = str(value or "").strip().upper()
    if not code:
        return None
    return {"L": "LW", "R": "RW"}.get(code, code)


def fetch_population() -> tuple[int, dict[str, list[dict]]]:
    """Fetch and validate the complete current NHL roster before any DB write."""
    directory = _get(TEAM_DIRECTORY_URL)
    source_codes: dict[str, str] = {}
    for row in directory.get("standings") or []:
        raw = str(((row.get("teamAbbrev") or {}).get("default")) or "").strip()
        if not raw:
            continue
        try:
            canonical = normalize("nhl", raw)
        except UnknownTeamCode as exc:
            raise NHLRosterError(str(exc)) from exc
        previous = source_codes.setdefault(canonical, raw)
        if previous != raw:
            raise NHLRosterError(
                f"team directory reuses canonical code {canonical}: {previous}, {raw}"
            )
    if len(source_codes) != EXPECTED_TEAMS:
        raise NHLRosterError(
            f"team directory published {len(source_codes)} teams; expected {EXPECTED_TEAMS}"
        )

    season_document = _get(SEASON_URL)
    raw_season = season_document.get("currentSeason")
    try:
        season = int(raw_season)
        normalize_season(SOURCE, "nhl", season)
    except (TypeError, ValueError) as exc:
        raise NHLRosterError(f"invalid current NHL season {raw_season!r}") from exc

    rosters: dict[str, list[dict]] = {}
    all_source_ids: set[str] = set()
    for team in sorted(source_codes):
        raw_team = source_codes[team]
        document = _get(ROSTER_URL.format(team=raw_team, season=season))
        members = []
        for group in ("forwards", "defensemen", "goalies"):
            for player in document.get(group) or []:
                source_key = str(player.get("id") or "").strip()
                name = "{} {}".format(
                    (player.get("firstName") or {}).get("default", ""),
                    (player.get("lastName") or {}).get("default", ""),
                ).strip()
                position = _position(player.get("positionCode"))
                if not source_key or not name or not position:
                    raise NHLRosterError(
                        f"{raw_team} roster has incomplete member "
                        f"id={source_key!r} name={name!r} position={position!r}"
                    )
                if source_key in all_source_ids:
                    raise NHLRosterError(
                        f"NHL player id {source_key} appears on more than one team"
                    )
                all_source_ids.add(source_key)
                members.append({
                    "player_id": source_key,
                    "name": name,
                    "position": position,
                    "jersey": (
                        None if player.get("sweaterNumber") is None
                        else str(player.get("sweaterNumber"))
                    ),
                    "team": team,
                })
        if not members:
            raise NHLRosterError(f"{raw_team} published an empty roster")
        rosters[team] = members
    return season, rosters


def _normal_team(value) -> str | None:
    try:
        return normalize("nhl", str(value or ""))
    except UnknownTeamCode:
        return None


def _choose_unbound_candidate(candidates, member: Mapping[str, object]):
    """Resolve a name-only candidate only with team or position evidence."""
    unbound = [row for row in candidates if row["nhl_id"] is None]
    if not unbound:
        # A same-name row with a different NHL id is a different person.  The
        # source-native id wins, so the current member needs a new identity.
        return None, "insert"

    team = str(member["team"])
    position = str(member["position"])
    both = [
        row for row in unbound
        if _normal_team(row["team"]) == team and _position(row["position"]) == position
    ]
    if len(both) == 1:
        return both[0], "matched_team_position"
    same_team = [row for row in unbound if _normal_team(row["team"]) == team]
    if len(same_team) == 1:
        return same_team[0], "matched_team"
    same_position = [
        row for row in unbound if _position(row["position"]) == position
    ]
    if len(same_position) == 1:
        return same_position[0], "matched_position"
    return None, "ambiguous_name" if len(unbound) > 1 else "unverified_name"


def plan_population(
    connection: sqlite3.Connection,
    rosters: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict:
    """Plan every source identity without mutating the database."""
    connection.row_factory = sqlite3.Row
    require_roster_schema(connection)
    tables = {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "player_source_ids" not in tables:
        raise NHLRosterError("player_source_ids is required")

    by_source: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    by_name: dict[str, list[sqlite3.Row]] = collections.defaultdict(list)
    for row in connection.execute(
        "SELECT id,name,team,position,nhl_id FROM players WHERE league='nhl'"
    ):
        if row["nhl_id"] is not None:
            by_source[str(row["nhl_id"])].append(row)
        by_name[_identity_name_key(row["name"])].append(row)

    durable = {
        str(row["source_player_key"]): int(row["player_id"])
        for row in connection.execute(
            "SELECT source_player_key,player_id FROM player_source_ids "
            "WHERE source=? AND league='nhl'",
            (SOURCE,),
        )
    }
    planned = []
    failures = []
    counts = collections.Counter()
    for team in sorted(rosters):
        for raw_member in rosters[team]:
            member = dict(raw_member)
            source_key = str(member.get("player_id") or "")
            member["team"] = team
            member["position"] = _position(member.get("position"))
            exact = by_source.get(source_key, [])
            if len(exact) > 1:
                failures.append({**member, "reason": "duplicate_spine_nhl_id"})
                continue
            if exact:
                candidate = exact[0]
                action = "exact_id"
            else:
                candidates = by_name.get(_identity_name_key(member.get("name")), [])
                candidate, action = _choose_unbound_candidate(candidates, member)
                if action in {"ambiguous_name", "unverified_name"}:
                    failures.append({**member, "reason": action})
                    continue

            if candidate is not None:
                durable_owner = durable.get(source_key)
                if durable_owner is not None and durable_owner != int(candidate["id"]):
                    failures.append({
                        **member,
                        "reason": "source_crosswalk_conflict",
                        "existing_player_id": durable_owner,
                        "planned_player_id": int(candidate["id"]),
                    })
                    continue
                player_id = int(candidate["id"])
                write_action = "update"
            else:
                if source_key in durable:
                    failures.append({
                        **member,
                        "reason": "stranded_source_crosswalk",
                        "existing_player_id": durable[source_key],
                    })
                    continue
                player_id = None
                write_action = "insert"
            counts[action] += 1
            planned.append({
                **member,
                "source_player_key": source_key,
                "canonical_player_id": player_id,
                "write_action": write_action,
                "evidence": action,
            })

    return {
        "planned": planned,
        "failures": failures,
        "counts": dict(sorted(counts.items())),
    }


def publish_population(
    connection: sqlite3.Connection,
    *,
    source_season: int,
    rosters: Mapping[str, Sequence[Mapping[str, object]]],
    captured_at: str,
    apply: bool,
) -> dict:
    """Plan, then atomically publish a complete NHL roster snapshot."""
    if len(rosters) != EXPECTED_TEAMS or any(not rows for rows in rosters.values()):
        raise NHLRosterError(
            f"roster population has {len(rosters)} teams; expected {EXPECTED_TEAMS} non-empty teams"
        )
    plan = plan_population(connection, rosters)
    plan["teams"] = len(rosters)
    plan["players"] = sum(len(rows) for rows in rosters.values())
    plan["season"] = normalize_season(SOURCE, "nhl", source_season)
    plan["status"] = "identity_incomplete" if plan["failures"] else "ready"
    if plan["failures"] or not apply:
        return plan

    source_payload = normalized_source_payload("nhl", rosters)
    try:
        connection.execute("BEGIN IMMEDIATE")
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(players)")
        }
        entity_scope = (
            "COALESCE(entity_type,'player')='player'"
            if "entity_type" in columns else "1=1"
        )
        connection.execute(
            f"UPDATE players SET active=0,updated_at=? "
            f"WHERE league='nhl' AND {entity_scope}",
            (captured_at,),
        )
        memberships = []
        for item in plan["planned"]:
            if item["write_action"] == "insert":
                cursor = connection.execute(
                    "INSERT INTO players(name,league,team,position,nhl_id,active,updated_at) "
                    "VALUES(?,'nhl',?,?,?,?,?)",
                    (
                        item["name"], item["team"], item["position"],
                        int(item["source_player_key"]), 1, captured_at,
                    ),
                )
                player_id = int(cursor.lastrowid)
            else:
                player_id = int(item["canonical_player_id"])
                connection.execute(
                    "UPDATE players SET team=?,position=?,nhl_id=COALESCE(nhl_id,?),"
                    "active=1,updated_at=? WHERE id=? AND league='nhl'",
                    (
                        item["team"], item["position"],
                        int(item["source_player_key"]), captured_at, player_id,
                    ),
                )
            existing = connection.execute(
                "SELECT player_id FROM player_source_ids "
                "WHERE source=? AND league='nhl' AND source_player_key=?",
                (SOURCE, item["source_player_key"]),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO player_source_ids(source,league,source_player_key,"
                    "player_id,first_seen,last_seen) VALUES(?,'nhl',?,?,?,?)",
                    (
                        SOURCE, item["source_player_key"], player_id,
                        captured_at, captured_at,
                    ),
                )
            elif int(existing[0]) == player_id:
                connection.execute(
                    "UPDATE player_source_ids SET last_seen=? "
                    "WHERE source=? AND league='nhl' AND source_player_key=?",
                    (captured_at, SOURCE, item["source_player_key"]),
                )
            else:  # Defensive repeat of the read-only planner's refusal.
                raise NHLRosterError(
                    f"NHL source id {item['source_player_key']} changed owner"
                )
            item["canonical_player_id"] = player_id
            memberships.append({
                "player_id": player_id,
                "source_player_key": item["source_player_key"],
                "team": item["team"],
                "position": item["position"],
                "jersey": item.get("jersey"),
                "roster_status": "active",
                "display_name": item["name"],
            })

        snapshot_id = publish_roster_snapshot(
            connection,
            league="nhl",
            season=plan["season"],
            source=SNAPSHOT_SOURCE,
            captured_at=captured_at,
            source_payload=source_payload,
            team_count=EXPECTED_TEAMS,
            memberships=memberships,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    plan["status"] = "published"
    plan["snapshot_id"] = snapshot_id
    return plan


def refresh(db_path: str, *, apply: bool = False) -> dict:
    source_season, rosters = fetch_population()
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return publish_population(
            connection,
            source_season=source_season,
            rosters=rosters,
            captured_at=captured_at,
            apply=apply,
        )
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = refresh(args.db, apply=args.apply)
    printable = {key: value for key, value in result.items() if key != "planned"}
    print(json.dumps(printable, indent=2, sort_keys=True))
    if result["failures"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
