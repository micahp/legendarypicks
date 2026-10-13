#!/usr/bin/env python3
"""Backup-first migration for team-stat provenance and evidence tables.

The current NHL publisher writes source/run identifiers alongside results and
team stats, and records the complete team inventory plus any ingestion
failures.  Older databases predate those additive columns and evidence tables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import migrate_schema


MIGRATION_ID = "20261002_001_team_evidence_schema"
COLUMN_ADDITIONS = {
    "team_game_results": (
        ("source", "TEXT"),
        ("run_id", "TEXT"),
    ),
    "team_game_stats": (("source", "TEXT"),),
}
INVENTORY_SQL = """
CREATE TABLE team_stats_team_inventory (
    run_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    team_abbrev TEXT,
    PRIMARY KEY (run_id, team_id)
)
""".strip()
FAILURES_SQL = """
CREATE TABLE team_stats_ingestion_failures (
    run_id TEXT NOT NULL,
    game_id TEXT,
    team TEXT,
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""".strip()
FAILURES_INDEX_SQL = (
    "CREATE INDEX idx_ingestion_failures_run "
    "ON team_stats_ingestion_failures(run_id)"
)
MIGRATION_CHECKSUM = hashlib.sha256(
    json.dumps(
        {
            "migration_id": MIGRATION_ID,
            "columns": COLUMN_ADDITIONS,
            "inventory": " ".join(INVENTORY_SQL.split()),
            "failures": " ".join(FAILURES_SQL.split()),
            "failures_index": " ".join(FAILURES_INDEX_SQL.split()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

TABLE_CONTRACTS = {
    "team_stats_team_inventory": (
        migrate_schema.ColumnContract("run_id", "TEXT", not_null=True, primary_key=1),
        migrate_schema.ColumnContract("team_id", "TEXT", not_null=True, primary_key=2),
        migrate_schema.ColumnContract("team_abbrev", "TEXT"),
    ),
    "team_stats_ingestion_failures": (
        migrate_schema.ColumnContract("run_id", "TEXT", not_null=True),
        migrate_schema.ColumnContract("game_id", "TEXT"),
        migrate_schema.ColumnContract("team", "TEXT"),
        migrate_schema.ColumnContract("reason", "TEXT", not_null=True),
        migrate_schema.ColumnContract(
            "recorded_at", "TEXT", not_null=True, default="datetime('now')"
        ),
    ),
}


class TeamEvidenceMigrationError(RuntimeError):
    """The team-evidence schema cannot be safely checked or applied."""


@dataclass(frozen=True)
class CheckResult:
    path: str
    state: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.state == "applied"


def _validated_path(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise TeamEvidenceMigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise TeamEvidenceMigrationError(
            f"database does not exist or is empty: {candidate}"
        )
    return str(candidate)


def _read_only_connection(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{quote(path, safe='/')}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _contract_issues(connection: sqlite3.Connection) -> list[str]:
    issues = []
    for table in COLUMN_ADDITIONS:
        if not _table_exists(connection, table):
            issues.append(f"required table {table!r} is missing")

    for table, expected_columns in TABLE_CONTRACTS.items():
        if not _table_exists(connection, table):
            continue
        actual = migrate_schema.table_columns(connection, table)
        for expected in expected_columns:
            found = actual.get(expected.name)
            if found is None:
                issues.append(f"{table}.{expected.name} is missing")
                continue
            difference = migrate_schema._contract_difference(found, expected)
            if difference:
                issues.append(
                    f"{table}.{expected.name} has wrong contract: {difference}"
                )
    return issues


def _missing_parts(connection: sqlite3.Connection) -> list[str]:
    missing = []
    for table, additions in COLUMN_ADDITIONS.items():
        columns = migrate_schema.table_columns(connection, table)
        for name, _declared_type in additions:
            if name not in columns:
                missing.append(f"{table}.{name}")
    for table in TABLE_CONTRACTS:
        if not _table_exists(connection, table):
            missing.append(table)
    if _table_exists(connection, "team_stats_ingestion_failures"):
        indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(team_stats_ingestion_failures)"
            )
        }
        if "idx_ingestion_failures_run" not in indexes:
            missing.append("idx_ingestion_failures_run")
    return missing


def _check_connection(
    connection: sqlite3.Connection, path: str
) -> CheckResult:
    issues = _contract_issues(connection)
    if issues:
        return CheckResult(path, "error", "; ".join(issues))

    missing = _missing_parts(connection)
    registered = None
    if _table_exists(connection, migrate_schema.REGISTRY_TABLE):
        row = connection.execute(
            "SELECT checksum FROM app_schema_migrations WHERE migration_id=?",
            (MIGRATION_ID,),
        ).fetchone()
        registered = str(row["checksum"]) if row else None
    if registered is not None and registered != MIGRATION_CHECKSUM:
        return CheckResult(
            path, "error", f"checksum mismatch: database has {registered}"
        )
    if registered is not None and missing:
        return CheckResult(
            path,
            "error",
            "migration is registered but schema is incomplete: "
            + ", ".join(missing),
        )
    if registered is not None:
        return CheckResult(path, "applied", f"checksum={MIGRATION_CHECKSUM}")
    if missing:
        return CheckResult(path, "pending", "missing " + ", ".join(missing))
    return CheckResult(
        path, "adopt", "team-evidence schema is exact; registry adoption required"
    )


def check_database(path: str) -> CheckResult:
    absolute = _validated_path(path)
    with _read_only_connection(absolute) as connection:
        return _check_connection(connection, absolute)


def apply_database(
    path: str, *, backup_destination: str | None = None
) -> tuple[str, CheckResult]:
    absolute = _validated_path(path)
    before = check_database(absolute)
    if before.state == "error":
        raise TeamEvidenceMigrationError(before.detail)
    backup = migrate_schema.create_verified_backup(absolute, backup_destination)

    connection = sqlite3.connect(absolute)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(migrate_schema.REGISTRY_SQL)
        for table, additions in COLUMN_ADDITIONS.items():
            columns = migrate_schema.table_columns(connection, table)
            for name, declared_type in additions:
                if name not in columns:
                    connection.execute(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declared_type}'
                    )
        if not _table_exists(connection, "team_stats_team_inventory"):
            connection.execute(INVENTORY_SQL)
        if not _table_exists(connection, "team_stats_ingestion_failures"):
            connection.execute(FAILURES_SQL)
        connection.execute(FAILURES_INDEX_SQL.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS"))

        current = _check_connection(connection, absolute)
        if current.state == "error":
            raise TeamEvidenceMigrationError(current.detail)
        if current.state in ("pending", "adopt"):
            connection.execute(
                "INSERT INTO app_schema_migrations(migration_id,checksum) VALUES(?,?)",
                (MIGRATION_ID, MIGRATION_CHECKSUM),
            )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    after = check_database(absolute)
    if not after.ok:
        raise TeamEvidenceMigrationError(
            f"post-commit verification failed: {after.state} {after.detail}"
        )
    return backup, after


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            result = check_database(args.db)
            print(f"{result.state.upper():7} {MIGRATION_ID}: {result.detail}")
            return 0 if result.ok else 1
        backup, result = apply_database(args.db)
        print(f"backup: {backup} (quick_check=ok)")
        print(f"{result.state.upper():7} {MIGRATION_ID}: {result.detail}")
        return 0
    except (TeamEvidenceMigrationError, migrate_schema.MigrationError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
