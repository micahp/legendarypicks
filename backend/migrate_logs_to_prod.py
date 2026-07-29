#!/usr/bin/env python3
"""Safely copy missing player-game logs into a production candidate.

This is additive: existing target logs and their JSON enrichment are never
overwritten. Both databases must pass the repository schema migration gate.
The apply path takes a verified SQLite online backup, names every copied
column, excludes shared player IDs whose identities disagree, and proves the
live prop tables are byte-for-byte unchanged inside the write transaction.

Examples:
    python3 migrate_logs_to_prod.py \
      --source /absolute/picks.dev.db --target /absolute/picks.db --check
    python3 migrate_logs_to_prod.py \
      --source /absolute/picks.dev.db --target /absolute/picks.db --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import quote

import migrate_schema


PLAYER_COLUMNS = (
    "id",
    "name",
    "team",
    "league",
    "espn_id",
    "mlbam_id",
    "nfl_gsis_id",
    "nhl_id",
    "nba_id",
    "active",
    "position",
    "updated_at",
)
LOG_COLUMNS = (
    "player_id",
    "league",
    "season",
    "game_no",
    "game_id",
    "game_date",
    "game_type",
    "team",
    "opponent",
    "home_away",
    "stats",
    "source",
    "source_player_key",
    "ingested_at",
)
PROTECTED_TABLES = ("props", "prop_results", "prop_games")


class LogMigrationError(RuntimeError):
    """A precondition or postcondition failed."""


@dataclass(frozen=True)
class Plan:
    source: str
    target: str
    leagues: tuple[str, ...]
    missing_players: tuple[tuple, ...]
    missing_logs: tuple[tuple, ...]
    identity_mismatches: tuple[int, ...]
    player_id_remaps: tuple[tuple[int, int], ...]
    skipped_identityless_logs: int


def _validated_path(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise LogMigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file():
        raise LogMigrationError(
            f"database does not exist or is not a file: {candidate}"
        )
    return str(candidate)


def _read_only(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(
        "file:{}?mode=ro".format(quote(path, safe="/")), uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _require_schema_gate(path: str) -> None:
    result = migrate_schema.check_database(path)
    if not result.ok:
        detail = "; ".join(
            f"{status.migration_id}={status.state} ({status.detail})"
            for status in result.statuses
        )
        raise LogMigrationError(
            f"schema migration check failed for {path}: {detail}"
        )


def _require_columns(
    connection: sqlite3.Connection,
    table: str,
    expected: Iterable[str],
) -> None:
    actual = migrate_schema.table_columns(connection, table)
    missing = [column for column in expected if column not in actual]
    if missing:
        raise LogMigrationError(
            f"{table} is missing required columns: {missing}"
        )


def _require_contract_parity(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    columns: Iterable[str],
) -> None:
    source_contract = migrate_schema.table_columns(source, table)
    target_contract = migrate_schema.table_columns(target, table)
    for column in columns:
        if source_contract[column] != target_contract[column]:
            raise LogMigrationError(
                f"{table}.{column} schema mismatch: "
                f"source={source_contract[column]} "
                f"target={target_contract[column]}"
            )


def _select_columns(columns: Iterable[str]) -> str:
    return ", ".join(f'"{column}"' for column in columns)


def _identity(row: sqlite3.Row) -> tuple[str, str]:
    return (
        str(row["name"] or "").strip().casefold(),
        str(row["league"] or "").strip().casefold(),
    )


def _stable_keys(row: sqlite3.Row) -> tuple[tuple[str, str], ...]:
    league = str(row["league"] or "").strip().casefold()
    keys = []
    for column in (
        "espn_id",
        "mlbam_id",
        "nfl_gsis_id",
        "nhl_id",
        "nba_id",
    ):
        value = row[column]
        if value is None or str(value).strip() in ("", "0"):
            continue
        keys.append(
            (f"{league}:{column}", str(value).strip().casefold())
        )
    return tuple(keys)


def build_plan(
    source_path: str,
    target_path: str,
    leagues: Optional[Sequence[str]] = None,
) -> Plan:
    source_path = _validated_path(source_path)
    target_path = _validated_path(target_path)
    if os.path.samefile(source_path, target_path):
        raise LogMigrationError("source and target must be different files")

    _require_schema_gate(source_path)
    _require_schema_gate(target_path)
    selected_leagues = tuple(
        sorted(
            {
                str(league).strip().lower()
                for league in (leagues or ())
                if str(league).strip()
            }
        )
    )
    league_clause = ""
    league_params: tuple[str, ...] = ()
    if selected_leagues:
        placeholders = ", ".join("?" for _ in selected_leagues)
        league_clause = f" AND league IN ({placeholders})"
        league_params = selected_leagues
    with _read_only(source_path) as source, _read_only(
        target_path
    ) as target:
        for connection in (source, target):
            _require_columns(
                connection, "players", PLAYER_COLUMNS
            )
            _require_columns(
                connection, "player_game_logs", LOG_COLUMNS
            )
        for table in PROTECTED_TABLES:
            if not migrate_schema._table_exists(target, table):
                raise LogMigrationError(
                    f"target protected table {table!r} is missing"
                )
        _require_contract_parity(
            source, target, "players", PLAYER_COLUMNS
        )
        _require_contract_parity(
            source, target, "player_game_logs", LOG_COLUMNS
        )

        source_players = {
            row["id"]: row
            for row in source.execute(
                f"SELECT {_select_columns(PLAYER_COLUMNS)} FROM players"
            )
        }
        target_players = {
            row["id"]: row
            for row in target.execute(
                f"SELECT {_select_columns(PLAYER_COLUMNS)} FROM players"
            )
        }
        source_log_player_ids = {
            row[0]
            for row in source.execute(
                "SELECT DISTINCT player_id FROM player_game_logs "
                "WHERE player_id IS NOT NULL" + league_clause,
                league_params,
            )
        }
        mismatches = tuple(
            sorted(
                player_id
                for player_id in (
                    source_log_player_ids & target_players.keys()
                )
                if _identity(source_players[player_id])
                != _identity(target_players[player_id])
            )
        )
        missing_player_ids = sorted(
            source_log_player_ids - target_players.keys()
        )
        target_by_stable_key = {}
        for target_id, row in target_players.items():
            for key in _stable_keys(row):
                target_by_stable_key.setdefault(key, set()).add(target_id)

        remaps = {}
        insert_player_ids = []
        for source_id in missing_player_ids:
            source_player = source_players[source_id]
            candidates = set()
            for key in _stable_keys(source_player):
                candidates.update(target_by_stable_key.get(key, ()))
            if not candidates:
                insert_player_ids.append(source_id)
                continue
            if len(candidates) != 1:
                raise LogMigrationError(
                    f"source player {source_id} {source_player['name']!r} "
                    f"matches multiple target ids by stable identity: "
                    f"{sorted(candidates)}"
                )
            target_id = next(iter(candidates))
            if _identity(source_player) != _identity(
                target_players[target_id]
            ):
                raise LogMigrationError(
                    f"source player {source_id} {source_player['name']!r} "
                    f"collides with target player {target_id} "
                    f"{target_players[target_id]['name']!r} by stable id"
                )
            remaps[source_id] = target_id

        missing_players = tuple(
            tuple(source_players[player_id][column] for column in PLAYER_COLUMNS)
            for player_id in insert_player_ids
        )

        target_keys = {
            tuple(row)
            for row in target.execute(
                "SELECT league, source_player_key, season, game_no "
                "FROM player_game_logs "
                "WHERE source_player_key IS NOT NULL "
                "AND game_no IS NOT NULL" + league_clause,
                league_params,
            )
        }
        missing_logs = []
        skipped_identityless = 0
        mismatch_set = set(mismatches)
        for row in source.execute(
            f"SELECT {_select_columns(LOG_COLUMNS)} "
            "FROM player_game_logs WHERE 1=1" + league_clause,
            league_params,
        ):
            if (
                row["source_player_key"] is None
                or row["game_no"] is None
            ):
                skipped_identityless += 1
                continue
            if row["player_id"] in mismatch_set:
                continue
            key = (
                row["league"],
                row["source_player_key"],
                row["season"],
                row["game_no"],
            )
            if key not in target_keys:
                values = [
                    row[column] for column in LOG_COLUMNS
                ]
                if row["player_id"] in remaps:
                    values[LOG_COLUMNS.index("player_id")] = remaps[
                        row["player_id"]
                    ]
                missing_logs.append(tuple(values))

    return Plan(
        source=source_path,
        target=target_path,
        leagues=selected_leagues,
        missing_players=missing_players,
        missing_logs=tuple(missing_logs),
        identity_mismatches=mismatches,
        player_id_remaps=tuple(sorted(remaps.items())),
        skipped_identityless_logs=skipped_identityless,
    )


def _feed_hash(hasher, value: object) -> None:
    if value is None:
        payload = b"N"
    elif isinstance(value, bytes):
        payload = b"B" + value
    else:
        payload = (
            type(value).__name__.encode("ascii")
            + b":"
            + str(value).encode("utf-8")
        )
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)


def table_fingerprint(
    connection: sqlite3.Connection, table: str
) -> tuple[int, str]:
    columns = [
        row["name"]
        for row in connection.execute(
            f'PRAGMA table_info("{table}")'
        )
    ]
    if not columns:
        raise LogMigrationError(
            f"protected table {table!r} is missing"
        )
    hasher = hashlib.sha256()
    count = 0
    query = (
        f"SELECT {_select_columns(columns)} "
        f'FROM "{table}" ORDER BY rowid'
    )
    for row in connection.execute(query):
        count += 1
        for value in row:
            _feed_hash(hasher, value)
    return count, hasher.hexdigest()


def apply_plan(
    plan: Plan, backup_destination: str | None = None
) -> str:
    # The source has already been materialized in ``plan``. The backup and
    # target transaction therefore contain no cross-database read dependency.
    backup = migrate_schema.create_verified_backup(
        plan.target, backup_destination
    )
    connection = sqlite3.connect(plan.target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        protected_before = {
            table: table_fingerprint(connection, table)
            for table in PROTECTED_TABLES
        }
        if plan.missing_players:
            placeholders = ", ".join("?" for _ in PLAYER_COLUMNS)
            connection.executemany(
                f"INSERT INTO players "
                f"({_select_columns(PLAYER_COLUMNS)}) "
                f"VALUES ({placeholders})",
                plan.missing_players,
            )
        if plan.missing_logs:
            placeholders = ", ".join("?" for _ in LOG_COLUMNS)
            connection.executemany(
                f"INSERT INTO player_game_logs "
                f"({_select_columns(LOG_COLUMNS)}) "
                f"VALUES ({placeholders})",
                plan.missing_logs,
            )
        protected_after = {
            table: table_fingerprint(connection, table)
            for table in PROTECTED_TABLES
        }
        if protected_after != protected_before:
            raise LogMigrationError(
                "protected prop table count/content changed"
            )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    with _read_only(plan.target) as verified:
        quick_check = verified.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]
    if quick_check != "ok":
        raise LogMigrationError(
            f"post-copy quick_check failed: {quick_check}; restore {backup}"
        )
    return backup


def _print_plan(plan: Plan) -> None:
    print(f"source: {plan.source}")
    print(f"target: {plan.target}")
    print(
        "leagues: "
        + (", ".join(plan.leagues) if plan.leagues else "all")
    )
    print(f"missing players: {len(plan.missing_players)}")
    print(f"missing logs: {len(plan.missing_logs)}")
    print(
        "identity-mismatched shared player ids excluded: "
        f"{len(plan.identity_mismatches)}"
    )
    print(
        "missing source player ids remapped by stable identity: "
        f"{len(plan.player_id_remaps)}"
    )
    print(
        "identityless source logs skipped: "
        f"{plan.skipped_identityless_logs}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy only missing player-game logs safely"
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--league",
        action="append",
        choices=("nfl", "nba", "nhl", "mlb", "ufc", "wc"),
        help="repeatable; omit to preserve the legacy all-league behavior",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            args.source, args.target, leagues=args.league
        )
        _print_plan(plan)
        if args.check:
            print("check only -- nothing written")
            return 0
        backup = apply_plan(plan)
        print(f"backup: {backup} (quick_check=ok)")
        print(
            f"applied: {len(plan.missing_players)} players, "
            f"{len(plan.missing_logs)} logs"
        )
        print(
            "protected tables unchanged by count and content checksum"
        )
        return 0
    except (
        LogMigrationError,
        migrate_schema.MigrationError,
        sqlite3.Error,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
