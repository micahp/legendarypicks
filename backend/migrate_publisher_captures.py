"""Explicit backup-first migration for the publisher raw-capture ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import migrate_schema
from publisher_capture import (
    PUBLISHER_CAPTURE_SCHEMA_SQL,
    create_publisher_capture_schema,
    publisher_capture_schema_issues,
)

MIGRATION_ID = "20260821_001_publisher_captures"
MIGRATION_CHECKSUM = hashlib.sha256(json.dumps(
    {"migration_id": MIGRATION_ID, "schema": " ".join(PUBLISHER_CAPTURE_SCHEMA_SQL.split())},
    sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()


class PublisherCaptureMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    path: str
    state: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.state == "applied"


def _path(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file():
        raise PublisherCaptureMigrationError("database path must be an existing absolute file: {}".format(path))
    return str(candidate)


def _check_connection(connection: sqlite3.Connection, path: str) -> CheckResult:
    issues = publisher_capture_schema_issues(connection)
    registered = None
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (migrate_schema.REGISTRY_TABLE,)).fetchone():
        row = connection.execute(
            "SELECT checksum FROM app_schema_migrations WHERE migration_id=?", (MIGRATION_ID,)
        ).fetchone()
        registered = str(row[0]) if row else None
    if issues:
        if registered:
            return CheckResult(path, "error", "registered migration has invalid schema: " + "; ".join(issues))
        return CheckResult(path, "pending", "; ".join(issues))
    if registered and registered != MIGRATION_CHECKSUM:
        return CheckResult(path, "error", "checksum mismatch: database has {}".format(registered))
    if registered:
        return CheckResult(path, "applied", "checksum={}".format(MIGRATION_CHECKSUM))
    return CheckResult(path, "adopt", "publisher capture schema is exact; registry adoption required")


def check_database(path: str) -> CheckResult:
    absolute = _path(path)
    connection = sqlite3.connect("file:{}?mode=ro".format(quote(absolute, safe="/")), uri=True)
    try:
        return _check_connection(connection, absolute)
    finally:
        connection.close()


def apply_database(path: str, *, backup_destination: str | None = None) -> tuple[str, CheckResult]:
    absolute = _path(path)
    before = check_database(absolute)
    if before.state == "error":
        raise PublisherCaptureMigrationError(before.detail)
    backup = migrate_schema.create_verified_backup(absolute, backup_destination)
    connection = sqlite3.connect(absolute)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(migrate_schema.REGISTRY_SQL)
        current = _check_connection(connection, absolute)
        if current.state == "pending":
            create_publisher_capture_schema(connection)
        elif current.state == "error":
            raise PublisherCaptureMigrationError(current.detail)
        if current.state in ("pending", "adopt"):
            connection.execute("INSERT INTO app_schema_migrations(migration_id,checksum) VALUES(?,?)",
                               (MIGRATION_ID, MIGRATION_CHECKSUM))
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    after = check_database(absolute)
    if not after.ok:
        raise PublisherCaptureMigrationError("post-commit verification failed: {} {}".format(after.state, after.detail))
    return backup, after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            result = check_database(args.db)
            print("{} {}: {}".format(result.state.upper(), MIGRATION_ID, result.detail))
            return 0 if result.ok else 1
        backup, result = apply_database(args.db)
        print("backup: {} (quick_check=ok)".format(backup))
        print("{} {}: {}".format(result.state.upper(), MIGRATION_ID, result.detail))
        return 0
    except (PublisherCaptureMigrationError, sqlite3.Error) as exc:
        print("ERROR: {}".format(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
