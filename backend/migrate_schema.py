#!/usr/bin/env python3
"""Explicit, versioned SQLite schema migrations.

``--check`` is read-only. ``--apply`` requires an existing absolute database
path, takes a verified SQLite online backup, and applies/adopts migrations in a
single transaction. Migrations are never run implicitly by application startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote


REGISTRY_TABLE = "app_schema_migrations"
REGISTRY_SQL = """
CREATE TABLE IF NOT EXISTS app_schema_migrations (
    migration_id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""".strip()


class MigrationError(RuntimeError):
    """A migration precondition, contract, or verification failed."""


@dataclass(frozen=True)
class ColumnContract:
    name: str
    declared_type: str
    not_null: bool = False
    default: str | None = None
    primary_key: int = 0


@dataclass(frozen=True)
class ColumnAddition:
    contract: ColumnContract
    sql: str


@dataclass(frozen=True)
class Migration:
    migration_id: str
    table: str
    additions: tuple[ColumnAddition, ...]

    @property
    def checksum(self) -> str:
        payload = {
            "migration_id": self.migration_id,
            "table": self.table,
            "additions": [
                {
                    "contract": asdict(addition.contract),
                    "sql": " ".join(addition.sql.split()),
                }
                for addition in self.additions
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        migration_id="20260728_001_player_game_logs_game_type",
        table="player_game_logs",
        additions=(
            ColumnAddition(
                contract=ColumnContract("game_type", "TEXT"),
                sql=(
                    "ALTER TABLE player_game_logs "
                    "ADD COLUMN game_type TEXT"
                ),
            ),
        ),
    ),
    Migration(
        migration_id="20260728_002_team_game_stats_backfill_columns",
        table="team_game_stats",
        additions=tuple(
            ColumnAddition(
                contract=ColumnContract(name, declared_type),
                sql=(
                    f"ALTER TABLE team_game_stats "
                    f"ADD COLUMN {name} {declared_type}"
                ),
            )
            for name, declared_type in (
                ("run_id", "TEXT"),
                ("first_downs", "INTEGER"),
                ("total_offensive_plays", "INTEGER"),
                ("total_yards", "INTEGER"),
                ("net_passing_yards", "INTEGER"),
                ("rushing_yards", "INTEGER"),
                ("defensive_special_teams_tds", "INTEGER"),
            )
        ),
    ),
)

REGISTRY_CONTRACT = (
    ColumnContract("migration_id", "TEXT", primary_key=1),
    ColumnContract("checksum", "TEXT", not_null=True),
    ColumnContract(
        "applied_at",
        "TEXT",
        not_null=True,
        default="datetime('now')",
    ),
)


@dataclass(frozen=True)
class MigrationStatus:
    migration_id: str
    state: str
    detail: str


@dataclass(frozen=True)
class CheckResult:
    path: str
    statuses: tuple[MigrationStatus, ...]

    @property
    def ok(self) -> bool:
        return all(status.state == "applied" for status in self.statuses)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_only_connection(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(
        "file:{}?mode=ro".format(quote(path, safe="/")), uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _normalize_type(value: object) -> str:
    return " ".join(str(value or "").upper().split())


def _normalize_default(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    while (
        len(normalized) >= 2
        and normalized[0] == "("
        and normalized[-1] == ")"
    ):
        normalized = normalized[1:-1].strip()
    return normalized


def _table_exists(
    connection: sqlite3.Connection, table: str
) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def table_columns(
    connection: sqlite3.Connection, table: str
) -> dict[str, ColumnContract]:
    contracts = {}
    for row in connection.execute(
        f"PRAGMA table_info({_quote_identifier(table)})"
    ):
        contracts[row["name"]] = ColumnContract(
            name=row["name"],
            declared_type=_normalize_type(row["type"]),
            not_null=bool(row["notnull"]),
            default=_normalize_default(row["dflt_value"]),
            primary_key=int(row["pk"]),
        )
    return contracts


def _contract_difference(
    actual: ColumnContract, expected: ColumnContract
) -> str | None:
    differences = []
    checks = (
        (
            "type",
            _normalize_type(actual.declared_type),
            _normalize_type(expected.declared_type),
        ),
        ("not_null", actual.not_null, expected.not_null),
        (
            "default",
            _normalize_default(actual.default),
            _normalize_default(expected.default),
        ),
        ("primary_key", actual.primary_key, expected.primary_key),
    )
    for label, found, wanted in checks:
        if found != wanted:
            differences.append(
                f"{label}={found!r}, expected {wanted!r}"
            )
    return "; ".join(differences) if differences else None


def _verify_table_contract(
    connection: sqlite3.Connection,
    table: str,
    expected_columns: Iterable[ColumnContract],
) -> list[str]:
    if not _table_exists(connection, table):
        return [f"required table {table!r} is missing"]
    actual = table_columns(connection, table)
    errors = []
    for expected in expected_columns:
        found = actual.get(expected.name)
        if found is None:
            errors.append(f"{table}.{expected.name} is missing")
            continue
        difference = _contract_difference(found, expected)
        if difference:
            errors.append(
                f"{table}.{expected.name} has wrong contract: {difference}"
            )
    return errors


def _registry_rows(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    if not _table_exists(connection, REGISTRY_TABLE):
        return {}
    errors = _verify_table_contract(
        connection, REGISTRY_TABLE, REGISTRY_CONTRACT
    )
    if errors:
        raise MigrationError("; ".join(errors))
    return {
        row["migration_id"]: row["checksum"]
        for row in connection.execute(
            "SELECT migration_id, checksum FROM app_schema_migrations"
        )
    }


def inspect_connection(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> tuple[MigrationStatus, ...]:
    try:
        registry = _registry_rows(connection)
    except MigrationError as exc:
        return (MigrationStatus("registry", "error", str(exc)),)

    registry_exists = _table_exists(connection, REGISTRY_TABLE)
    statuses = []
    for migration in migrations:
        existing = table_columns(connection, migration.table)
        if not existing:
            statuses.append(
                MigrationStatus(
                    migration.migration_id,
                    "error",
                    f"required table {migration.table!r} is missing",
                )
            )
            continue

        missing = []
        wrong = []
        for addition in migration.additions:
            actual = existing.get(addition.contract.name)
            if actual is None:
                missing.append(addition.contract.name)
                continue
            difference = _contract_difference(
                actual, addition.contract
            )
            if difference:
                wrong.append(
                    f"{migration.table}.{addition.contract.name}: "
                    f"{difference}"
                )

        registered = registry.get(migration.migration_id)
        if wrong:
            state, detail = "error", (
                "wrong column contract: " + "; ".join(wrong)
            )
        elif registered is not None and registered != migration.checksum:
            state, detail = "error", (
                f"checksum mismatch: database has {registered}, "
                f"code has {migration.checksum}"
            )
        elif registered is not None and missing:
            state, detail = "error", (
                "registered migration is missing schema: "
                + ", ".join(missing)
            )
        elif registered is not None:
            state, detail = "applied", (
                f"checksum={migration.checksum}"
            )
        elif missing:
            state, detail = "pending", (
                "migration required; missing " + ", ".join(missing)
            )
        else:
            state, detail = "adopt", (
                "schema is exact; registry adoption required"
                if registry_exists
                else "schema is exact; registry creation and adoption required"
            )
        statuses.append(
            MigrationStatus(migration.migration_id, state, detail)
        )
    return tuple(statuses)


def _validated_database_path(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise MigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file():
        raise MigrationError(
            f"database does not exist or is not a file: {candidate}"
        )
    return str(candidate)


def check_database(
    path: str,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> CheckResult:
    absolute = _validated_database_path(path)
    with _read_only_connection(absolute) as connection:
        statuses = inspect_connection(connection, migrations)
    return CheckResult(absolute, statuses)


def _backup_path(path: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    return f"{path}.pre-schema-{timestamp}.bak"


def create_verified_backup(
    path: str, destination: str | None = None
) -> str:
    absolute = _validated_database_path(path)
    backup_path = destination or _backup_path(absolute)
    if not os.path.isabs(backup_path):
        raise MigrationError(
            f"backup path must be absolute: {backup_path!r}"
        )
    if os.path.exists(backup_path):
        raise MigrationError(
            f"backup path already exists: {backup_path}"
        )

    try:
        with _read_only_connection(absolute) as source:
            source_check = source.execute(
                "PRAGMA quick_check"
            ).fetchone()[0]
            if source_check != "ok":
                raise MigrationError(
                    f"source quick_check failed: {source_check}"
                )
            with sqlite3.connect(backup_path) as backup:
                source.backup(backup)
                backup_check = backup.execute(
                    "PRAGMA quick_check"
                ).fetchone()[0]
        if backup_check != "ok":
            raise MigrationError(
                f"backup quick_check failed: {backup_check}"
            )
    except Exception:
        if os.path.exists(backup_path):
            os.unlink(backup_path)
        raise
    return backup_path


def _raise_on_errors(
    statuses: Sequence[MigrationStatus],
) -> None:
    errors = [
        f"{status.migration_id}: {status.detail}"
        for status in statuses
        if status.state == "error"
    ]
    if errors:
        raise MigrationError("; ".join(errors))


def apply_database(
    path: str,
    migrations: Sequence[Migration] = MIGRATIONS,
    backup_destination: str | None = None,
) -> tuple[str, tuple[MigrationStatus, ...]]:
    absolute = _validated_database_path(path)
    before = check_database(absolute, migrations)
    _raise_on_errors(before.statuses)
    backup_path = create_verified_backup(
        absolute, backup_destination
    )

    connection = sqlite3.connect(absolute)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    applied = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(REGISTRY_SQL)
        registry = _registry_rows(connection)
        for migration in migrations:
            registered = registry.get(migration.migration_id)
            if registered is not None:
                if registered != migration.checksum:
                    raise MigrationError(
                        f"{migration.migration_id}: checksum mismatch"
                    )
                errors = _verify_table_contract(
                    connection,
                    migration.table,
                    (
                        addition.contract
                        for addition in migration.additions
                    ),
                )
                if errors:
                    raise MigrationError(
                        f"{migration.migration_id}: "
                        + "; ".join(errors)
                    )
                applied.append(
                    MigrationStatus(
                        migration.migration_id,
                        "applied",
                        f"unchanged checksum={migration.checksum}",
                    )
                )
                continue

            existing = table_columns(connection, migration.table)
            if not existing:
                raise MigrationError(
                    f"{migration.migration_id}: required table "
                    f"{migration.table!r} is missing"
                )
            changed = False
            for addition in migration.additions:
                actual = existing.get(addition.contract.name)
                if actual is not None:
                    difference = _contract_difference(
                        actual, addition.contract
                    )
                    if difference:
                        raise MigrationError(
                            f"{migration.migration_id}: "
                            f"{migration.table}."
                            f"{addition.contract.name} has wrong "
                            f"contract: {difference}"
                        )
                    continue
                connection.execute(addition.sql)
                changed = True

            errors = _verify_table_contract(
                connection,
                migration.table,
                (
                    addition.contract
                    for addition in migration.additions
                ),
            )
            if errors:
                raise MigrationError(
                    f"{migration.migration_id}: " + "; ".join(errors)
                )
            connection.execute(
                "INSERT INTO app_schema_migrations"
                "(migration_id, checksum) VALUES(?, ?)",
                (migration.migration_id, migration.checksum),
            )
            applied.append(
                MigrationStatus(
                    migration.migration_id,
                    "applied" if changed else "adopted",
                    f"checksum={migration.checksum}",
                )
            )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    verified = check_database(absolute, migrations)
    if not verified.ok:
        raise MigrationError(
            "post-commit verification failed: "
            + "; ".join(
                f"{status.migration_id}: {status.state} {status.detail}"
                for status in verified.statuses
            )
        )
    return backup_path, tuple(applied)


def _print_result(result: CheckResult) -> None:
    print(f"database: {result.path}")
    for status in result.statuses:
        print(
            f"{status.state.upper():7} "
            f"{status.migration_id}: {status.detail}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or apply LegendaryPicks SQLite migrations"
    )
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            result = check_database(args.db)
            _print_result(result)
            return 0 if result.ok else 1
        backup_path, statuses = apply_database(args.db)
        print(f"backup: {backup_path} (quick_check=ok)")
        for status in statuses:
            print(
                f"{status.state.upper():7} "
                f"{status.migration_id}: {status.detail}"
            )
        _print_result(check_database(args.db))
        return 0
    except (MigrationError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
