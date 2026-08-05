#!/usr/bin/env python3
"""One invocation, both databases: check or apply migrations to prod + dev.

The 2026-08-05 defects all shared one mechanism: "verify on dev" and "ship to
prod" were two manual actions with nothing coupling them. This runner removes
the second action. By default it targets BOTH databases:

    backend/venv/bin/python backend/migrate_all.py --check   # read-only
    backend/venv/bin/python backend/migrate_all.py --apply   # both DBs

``--apply`` for each database:

1. takes a verified VACUUM INTO backup (never cp);
2. applies every numbered schema migration in ``migrate_schema.MIGRATIONS``,
   checking the ledger before and inserting a row after (idempotent);
3. adopts the 20 legacy hand-run migration scripts into the ledger, probing
   each database read-only and recording ``applied`` / ``unknown`` /
   ``not_applicable`` rather than guessing.

Re-running is a no-op: already-applied migrations report ``applied`` with zero
new rows, and legacy probes that still hold record no ledger change.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Sequence

import migrate_schema
import migration_manifest
from migrate_schema import (
    REGISTRY_SQL,
    CheckResult,
    MigrationStatus,
    _read_only_connection,
    _table_exists,
    check_database,
)

HERE = Path(__file__).resolve().parent
DEFAULT_PROD = os.environ.get("LP_PROD_DB") or str(HERE / "data" / "picks.db")
DEFAULT_DEV = os.environ.get("LP_DEV_DB") or str(HERE / "data" / "picks.dev.db")

STATUS_ORDER = {"applied": 0, "unknown": 1, "not_applicable": 2, "error": 3}


def _absolute(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise migrate_schema.MigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file():
        raise migrate_schema.MigrationError(
            f"database does not exist or is not a file: {candidate}"
        )
    return str(candidate)


def _legacy_status(con: sqlite3.Connection, migration) -> str:
    if migration.applies_to == "prod":
        # dev->prod copy scripts write only the target; the source side has
        # nothing to probe (the effect lives in the target).
        return "not_applicable"
    try:
        return migration.probe(con)
    except sqlite3.Error as exc:
        return f"unknown: probe failed ({exc})"


def check_legacy(
    path: str,
    migrations: Sequence[migration_manifest.LegacyMigration] = migration_manifest.LEGACY_MIGRATIONS,
) -> list[tuple[str, str, str]]:
    """Read-only per-script status for one database.

    Returns (migration_id, status, note). Raises if the ledger cannot be read.
    """
    absolute = _absolute(path)
    rows = []
    with _read_only_connection(absolute) as con:
        for migration in migrations:
            status = _legacy_status(con, migration)
            rows.append((migration.migration_id, status, migration.note))
    return rows


def _ledger_rows(
    con: sqlite3.Connection,
) -> dict[str, tuple[str, str]]:
    """migration_id -> (checksum, status) from the registry."""
    if not _table_exists(con, migrate_schema.REGISTRY_TABLE):
        return {}
    out = {}
    for row in con.execute(
        "SELECT migration_id, checksum, status FROM app_schema_migrations"
    ):
        out[row["migration_id"]] = (row["checksum"], row["status"])
    return out


def apply_legacy(
    path: str,
    migrations: Sequence[migration_manifest.LegacyMigration] = migration_manifest.LEGACY_MIGRATIONS,
) -> list[tuple[str, str, str]]:
    """Record retroactive ledger rows for the legacy scripts.

    A row is written only when the probed status differs from what the ledger
    already holds, or when the ledger has no row. Applied rows with a matching
    checksum are left untouched (idempotent). Returns
    (migration_id, status, note) for every script after the call.
    """
    absolute = _absolute(path)
    con = sqlite3.connect(absolute)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(REGISTRY_SQL)
        existing = _ledger_rows(con)
        for migration in migrations:
            checksum = migration_manifest.script_checksum(migration.script)
            status = _legacy_status(con, migration)
            previous = existing.get(migration.migration_id)
            if previous is not None and previous[0] == checksum and previous[1] == status:
                continue
            con.execute(
                """INSERT INTO app_schema_migrations(
                     migration_id, checksum, status, note
                   ) VALUES(?,?,?,?)
                   ON CONFLICT(migration_id) DO UPDATE SET
                     checksum=excluded.checksum,
                     status=excluded.status,
                     note=excluded.note,
                     applied_at=datetime('now')""",
                (migration.migration_id, checksum, status, migration.note),
            )
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return check_legacy(path, migrations)


def run_database(
    path: str,
    *,
    apply: bool,
    backups: list[str],
) -> tuple[CheckResult, list[tuple[str, str, str]]]:
    absolute = _absolute(path)
    schema_before = check_database(absolute)
    legacy_before = check_legacy(absolute)

    if apply:
        if not schema_before.ok:
            # Schema migrations pending/adoptable: apply them (this takes the
            # verified VACUUM INTO backup and records ledger rows).
            backup, statuses = migrate_schema.apply_database(absolute)
            backups.append(backup)
            schema_after = check_database(absolute)
        else:
            schema_after = schema_before
        legacy_after = apply_legacy(absolute)
    else:
        schema_after = schema_before
        legacy_after = legacy_before

    return schema_after, legacy_after


def _print_schema(result: CheckResult) -> None:
    for status in result.statuses:
        print(f"  {status.state.upper():7} {status.migration_id}: {status.detail}")


def _print_legacy(rows: Sequence[tuple[str, str, str]]) -> None:
    for migration_id, status, note in rows:
        marker = "OK " if status == "applied" else "?? "
        print(f"  {marker} {status:14} {migration_id}")
        if status != "applied":
            print(f"          {note}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or apply migrations to prod and dev together"
    )
    parser.add_argument("--prod", default=DEFAULT_PROD)
    parser.add_argument("--dev", default=DEFAULT_DEV)
    parser.add_argument(
        "--only",
        choices=("prod", "dev"),
        help="restrict to one database (default: both)",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    targets = []
    if args.only in (None, "prod"):
        targets.append(("prod", _absolute(args.prod)))
    if args.only in (None, "dev"):
        targets.append(("dev", _absolute(args.dev)))

    backups: list[str] = []
    exit_code = 0
    for label, path in targets:
        print(f"== {label}: {path} ==")
        try:
            schema, legacy = run_database(path, apply=args.apply, backups=backups)
        except (migrate_schema.MigrationError, sqlite3.Error) as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        print("  schema migrations:")
        _print_schema(schema)
        print("  legacy scripts:")
        _print_legacy(legacy)

        if not schema.ok:
            print(f"  {label}: schema NOT ready", file=sys.stderr)
            exit_code = 1
        else:
            print(f"  {label}: schema ready")
        if not legacy:
            exit_code = 1

    if args.apply:
        print()
        if backups:
            print(f"backups taken ({len(backups)}):")
            for backup in backups:
                print(f"  {backup} (quick_check=ok)")
        else:
            print("no backups needed: schema already level")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
