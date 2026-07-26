#!/usr/bin/env python3
"""Plan, but never apply, an additive UFC history merge from dev to production.

Both databases are opened with SQLite ``mode=ro``. The source of identity is
``player_game_logs.source_player_key`` (ESPN athlete ID), never a local player
ID. Existing production values always win.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROD = os.path.join(HERE, "data", "picks.db")
DEFAULT_DEV = os.path.join(HERE, "data", "picks.dev.db")


def _name_key(value: Optional[str]) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _ro_connection(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    uri = "file:{}?mode=ro".format(quote(absolute, safe="/"))
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _json_value(value: str):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SourceIdentity:
    athlete_id: str
    name: str
    dev_player_id: int
    dev_espn_id: Optional[str]


@dataclass(frozen=True)
class IdentityAction:
    athlete_id: str
    name: str
    action: str
    prod_player_id: Optional[int]


@dataclass(frozen=True)
class PlannedLog:
    athlete_id: str
    source_name: str
    dev_player_id: int
    season: int
    game_no: str
    game_id: str
    game_date: str
    team: Optional[str]
    opponent: Optional[str]
    home_away: Optional[str]
    stats: str
    source: str
    ingested_at: Optional[str]


@dataclass
class MergePlan:
    source_rows: int = 0
    source_fighters: int = 0
    exact_identity_matches: int = 0
    identity_actions: Dict[str, IdentityAction] = field(default_factory=dict)
    identity_fills: List[IdentityAction] = field(default_factory=list)
    new_players: List[IdentityAction] = field(default_factory=list)
    planned_logs: List[PlannedLog] = field(default_factory=list)
    existing_identical: int = 0
    skipped_collisions: List[str] = field(default_factory=list)
    identity_conflicts: List[str] = field(default_factory=list)
    invalid_source_rows: List[str] = field(default_factory=list)


def _natural_key(row: sqlite3.Row) -> Tuple[str, str, int, str]:
    return (
        str(row["league"]),
        str(row["source_player_key"]),
        int(row["season"]),
        str(row["game_no"]),
    )


def _rows_equivalent(source: sqlite3.Row, prod: sqlite3.Row) -> bool:
    source_stats = _json_value(source["stats"])
    prod_stats = _json_value(prod["stats"])
    if source_stats is None or prod_stats is None or source_stats != prod_stats:
        return False
    fields = ("game_id", "game_date", "opponent", "source", "source_player_key")
    return all(
        str(source[field] or "") == str(prod[field] or "")
        for field in fields
    )


def _load_source_rows(con: sqlite3.Connection) -> List[sqlite3.Row]:
    return con.execute(
        """
        SELECT l.*, p.name AS source_name, p.espn_id AS dev_espn_id
        FROM player_game_logs l
        JOIN players p ON p.id=l.player_id
        WHERE l.league='ufc'
        ORDER BY l.source_player_key, l.season, l.game_no, l.id
        """
    ).fetchall()


def _load_prod_players(con: sqlite3.Connection):
    rows = con.execute(
        "SELECT id,name,espn_id FROM players WHERE league='ufc' ORDER BY id"
    ).fetchall()
    by_espn = {
        str(row["espn_id"]): row
        for row in rows
        if str(row["espn_id"] or "").strip()
    }
    by_name: Dict[str, List[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_name[_name_key(row["name"])].append(row)
    return by_espn, by_name


def _load_prod_logs(con: sqlite3.Connection):
    return {
        _natural_key(row): row
        for row in con.execute(
            """
            SELECT * FROM player_game_logs
            WHERE league='ufc' AND source_player_key IS NOT NULL AND game_no IS NOT NULL
            """
        )
    }


def _source_identities(
    rows: Sequence[sqlite3.Row],
    plan: MergePlan,
) -> Dict[str, SourceIdentity]:
    identities: Dict[str, SourceIdentity] = {}
    for row in rows:
        athlete_id = str(row["source_player_key"] or "").strip()
        game_no = str(row["game_no"] or "").strip()
        game_id = str(row["game_id"] or "").strip()
        stats = _json_value(row["stats"])
        if (
            not athlete_id
            or not game_no
            or not game_id
            or stats is None
            or row["source"] != "espn_mma_stats"
        ):
            plan.invalid_source_rows.append(
                "dev log {} has invalid identity/key/stats/source".format(row["id"])
            )
            continue
        dev_espn_id = str(row["dev_espn_id"] or "").strip() or None
        if dev_espn_id and dev_espn_id != athlete_id:
            plan.identity_conflicts.append(
                "{}: dev player ESPN {} conflicts with log source {}".format(
                    row["source_name"], dev_espn_id, athlete_id
                )
            )
            continue
        candidate = SourceIdentity(
            athlete_id=athlete_id,
            name=str(row["source_name"]),
            dev_player_id=int(row["player_id"]),
            dev_espn_id=dev_espn_id,
        )
        prior = identities.get(athlete_id)
        if prior and (
            prior.dev_player_id != candidate.dev_player_id
            or _name_key(prior.name) != _name_key(candidate.name)
        ):
            plan.identity_conflicts.append(
                "ESPN {} is attached to multiple dev fighter identities".format(
                    athlete_id
                )
            )
            continue
        identities[athlete_id] = candidate
    return identities


def build_merge_plan(
    prod_con: sqlite3.Connection,
    dev_con: sqlite3.Connection,
) -> MergePlan:
    plan = MergePlan()
    source_rows = _load_source_rows(dev_con)
    plan.source_rows = len(source_rows)
    identities = _source_identities(source_rows, plan)
    plan.source_fighters = len(identities)

    prod_by_espn, prod_by_name = _load_prod_players(prod_con)
    identity_actions: Dict[str, IdentityAction] = {}
    for athlete_id, identity in sorted(identities.items()):
        exact = prod_by_espn.get(athlete_id)
        if exact is not None:
            identity_actions[athlete_id] = IdentityAction(
                athlete_id, identity.name, "existing_espn", int(exact["id"])
            )
            plan.exact_identity_matches += 1
            continue

        name_matches = prod_by_name.get(_name_key(identity.name), [])
        if len(name_matches) > 1:
            plan.identity_conflicts.append(
                "{}: multiple production fighters share this normalized name".format(
                    identity.name
                )
            )
            continue
        if len(name_matches) == 1:
            row = name_matches[0]
            current_espn = str(row["espn_id"] or "").strip()
            if current_espn and current_espn != athlete_id:
                plan.identity_conflicts.append(
                    "{}: production ESPN {} conflicts with source ESPN {}".format(
                        identity.name, current_espn, athlete_id
                    )
                )
                continue
            action = IdentityAction(
                athlete_id, identity.name, "fill_existing", int(row["id"])
            )
            identity_actions[athlete_id] = action
            plan.identity_fills.append(action)
            continue

        action = IdentityAction(athlete_id, identity.name, "create_player", None)
        identity_actions[athlete_id] = action
        plan.new_players.append(action)
    plan.identity_actions = identity_actions

    prod_logs = _load_prod_logs(prod_con)
    seen_source_keys = set()
    for row in source_rows:
        athlete_id = str(row["source_player_key"] or "").strip()
        if athlete_id not in identity_actions:
            continue
        key = _natural_key(row)
        if key in seen_source_keys:
            plan.invalid_source_rows.append(
                "duplicate dev natural key {}".format(key)
            )
            continue
        seen_source_keys.add(key)
        if (
            not str(row["game_id"] or "").strip()
            or _json_value(row["stats"]) is None
            or row["source"] != "espn_mma_stats"
        ):
            continue

        existing = prod_logs.get(key)
        if existing is not None:
            if _rows_equivalent(row, existing):
                plan.existing_identical += 1
            else:
                plan.skipped_collisions.append(
                    "{} {} {}: production row wins".format(
                        row["source_name"], row["game_no"], row["game_id"]
                    )
                )
            continue
        plan.planned_logs.append(
            PlannedLog(
                athlete_id=athlete_id,
                source_name=str(row["source_name"]),
                dev_player_id=int(row["player_id"]),
                season=int(row["season"]),
                game_no=str(row["game_no"]),
                game_id=str(row["game_id"]),
                game_date=str(row["game_date"] or ""),
                team=row["team"],
                opponent=row["opponent"],
                home_away=row["home_away"],
                stats=str(row["stats"]),
                source=str(row["source"]),
                ingested_at=row["ingested_at"],
            )
        )
    return plan


def _integrity(con: sqlite3.Connection) -> str:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no result"


def print_plan(plan: MergePlan, prod_integrity: str, dev_integrity: str) -> None:
    print("UFC dev-history additive merge plan (READ-ONLY)")
    print("  prod integrity: {}".format(prod_integrity))
    print("  dev integrity: {}".format(dev_integrity))
    print("  dev UFC source rows: {}".format(plan.source_rows))
    print("  dev ESPN fighter identities: {}".format(plan.source_fighters))
    print("  exact production ESPN matches: {}".format(plan.exact_identity_matches))
    print("  production ESPN IDs to fill: {}".format(len(plan.identity_fills)))
    print("  durable production fighters to create: {}".format(len(plan.new_players)))
    print("  rows already identical: {}".format(plan.existing_identical))
    print("  rows that would insert: {}".format(len(plan.planned_logs)))
    print("  skipped data collisions: {}".format(len(plan.skipped_collisions)))
    print("  identity conflicts: {}".format(len(plan.identity_conflicts)))
    print("  invalid source rows: {}".format(len(plan.invalid_source_rows)))

    if plan.identity_fills:
        print("  identity fills:")
        for action in plan.identity_fills:
            print(
                "    - prod player {} {} -> ESPN {}".format(
                    action.prod_player_id, action.name, action.athlete_id
                )
            )
    if plan.new_players:
        print("  new durable fighters:")
        for action in plan.new_players:
            print("    - {} -> ESPN {}".format(action.name, action.athlete_id))
    if plan.skipped_collisions:
        print("  skipped collision detail:")
        for item in plan.skipped_collisions:
            print("    - {}".format(item))
    if plan.identity_conflicts:
        print("  identity conflict detail:")
        for item in plan.identity_conflicts:
            print("    - {}".format(item))
    if plan.invalid_source_rows:
        print("  invalid source detail:")
        for item in plan.invalid_source_rows:
            print("    - {}".format(item))
    print("\nDone (dry-run only; both databases opened read-only)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan a read-only additive UFC history merge from dev to prod"
    )
    parser.add_argument("--prod-db", default=DEFAULT_PROD)
    parser.add_argument("--dev-db", default=DEFAULT_DEV)
    args = parser.parse_args(argv)

    prod_path = os.path.abspath(args.prod_db)
    dev_path = os.path.abspath(args.dev_db)
    if prod_path == dev_path:
        parser.error("prod and dev paths must differ")
    for label, path in (("prod", prod_path), ("dev", dev_path)):
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            parser.error("{} database is missing or empty: {}".format(label, path))

    with closing(_ro_connection(prod_path)) as prod_con, closing(
        _ro_connection(dev_path)
    ) as dev_con:
        prod_integrity = _integrity(prod_con)
        dev_integrity = _integrity(dev_con)
        plan = build_merge_plan(prod_con, dev_con)
    print_plan(plan, prod_integrity, dev_integrity)
    if (
        prod_integrity != "ok"
        or dev_integrity != "ok"
        or plan.identity_conflicts
        or plan.invalid_source_rows
    ):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
