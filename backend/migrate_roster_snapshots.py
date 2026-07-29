#!/usr/bin/env python3
"""Explicit backup-first migration for canonical roster snapshots."""

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
from roster_membership import (
    ROSTER_SCHEMA_SQL,
    create_roster_schema,
    roster_schema_issues,
)


MIGRATION_ID = "20260729_002_canonical_roster_snapshots"
MIGRATION_CHECKSUM = hashlib.sha256(
    json.dumps(
        {
            "migration_id": MIGRATION_ID,
            "schema": " ".join(ROSTER_SCHEMA_SQL.split()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


class RosterMigrationError(RuntimeError):
    """The roster schema migration cannot be safely checked or applied."""


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
        raise RosterMigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file():
        raise RosterMigrationError(
            f"database does not exist or is not a file: {candidate}"
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


def _check_connection(
    connection: sqlite3.Connection, path: str
) -> CheckResult:
    if not _table_exists(connection, "players"):
        return CheckResult(
            path, "error", "required table 'players' is missing"
        )
    present = [
        _table_exists(connection, table)
        for table in ("roster_snapshots", "roster_memberships")
    ]
    if any(present) and not all(present):
        return CheckResult(
            path, "error", "canonical roster schema is partially present"
        )

    issues = roster_schema_issues(connection) if all(present) else []
    if issues:
        return CheckResult(path, "error", "; ".join(issues))

    registered = None
    if _table_exists(connection, migrate_schema.REGISTRY_TABLE):
        row = connection.execute(
            """SELECT checksum FROM app_schema_migrations
               WHERE migration_id=?""",
            (MIGRATION_ID,),
        ).fetchone()
        registered = str(row["checksum"]) if row else None
    if registered is not None and registered != MIGRATION_CHECKSUM:
        return CheckResult(
            path, "error",
            f"checksum mismatch: database has {registered}",
        )
    if registered is not None and not all(present):
        return CheckResult(
            path, "error",
            "migration is registered but roster schema is absent",
        )
    if registered is not None:
        return CheckResult(
            path, "applied", f"checksum={MIGRATION_CHECKSUM}"
        )
    if all(present):
        return CheckResult(
            path, "adopt",
            "canonical roster schema is exact; registry adoption required",
        )
    return CheckResult(
        path, "pending", "canonical roster tables and indexes are absent"
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
        raise RosterMigrationError(before.detail)
    backup = migrate_schema.create_verified_backup(
        absolute, backup_destination
    )

    connection = sqlite3.connect(absolute)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(migrate_schema.REGISTRY_SQL)
        current = _check_connection(connection, absolute)
        if current.state == "error":
            raise RosterMigrationError(current.detail)
        if current.state == "pending":
            create_roster_schema(connection)
        if current.state in ("pending", "adopt"):
            connection.execute(
                """INSERT INTO app_schema_migrations(
                     migration_id,checksum
                   ) VALUES(?,?)""",
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
        raise RosterMigrationError(
            f"post-commit verification failed: "
            f"{after.state} {after.detail}"
        )
    return backup, after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.check:
            result = check_database(arguments.db)
            print(f"{result.state.upper():7} {MIGRATION_ID}: {result.detail}")
            return 0 if result.ok else 1
        backup, result = apply_database(arguments.db)
        print(f"backup: {backup} (quick_check=ok)")
        print(f"{result.state.upper():7} {MIGRATION_ID}: {result.detail}")
        return 0
    except (RosterMigrationError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
