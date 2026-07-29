#!/usr/bin/env python3
"""Explicit migration to the canonical ``player_stats`` identity key.

The migration is intentionally non-repairing. ``--check`` reports every data
condition that must be corrected by authoritative refreshes first. ``--apply``
refuses to choose among duplicates, take ownership from an unapproved source,
or preserve an orphaned identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

import migrate_schema
from league_stats import (
    LeagueStatContractError,
    canonical_stat_type,
    source_owns_stats,
)


MIGRATION_ID = "20260729_001_canonical_player_stats"
_CHECKSUM_PAYLOAD = {
    "migration_id": MIGRATION_ID,
    "key": ["player_id", "league", "season", "stat_type"],
    "required": [
        "player_id", "player_name", "league", "season",
        "stat_type", "source",
    ],
    "foreign_key": ["player_id", "players", "id"],
    "legacy_name_key_removed": True,
}
MIGRATION_CHECKSUM = hashlib.sha256(
    json.dumps(
        _CHECKSUM_PAYLOAD, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
).hexdigest()

_REQUIRED_COLUMNS = frozenset(_CHECKSUM_PAYLOAD["required"])
_CANONICAL_NOT_NULL = _REQUIRED_COLUMNS
_ISSUE_KEYS = (
    "null_canonical_fields",
    "orphan_players",
    "league_mismatches",
    "display_name_mismatches",
    "invalid_stat_types",
    "unowned_sources",
    "duplicate_canonical_keys",
    "unsupported_schema_dependents",
)


class PlayerStatsMigrationError(RuntimeError):
    """The migration contract or its data preconditions failed."""


@dataclass(frozen=True)
class CheckResult:
    path: str
    state: str
    detail: str
    issues: dict[str, int]

    @property
    def ok(self) -> bool:
        return self.state == "applied"


def _validated_path(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise PlayerStatsMigrationError(
            f"database path must be absolute: {path!r}"
        )
    if not candidate.is_file():
        raise PlayerStatsMigrationError(
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


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_exists(
    connection: sqlite3.Connection, table: str
) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(
    connection: sqlite3.Connection, table: str
) -> dict[str, sqlite3.Row]:
    return {
        str(row["name"]): row
        for row in connection.execute(
            f"PRAGMA table_info({_quote(table)})"
        )
    }


def _canonical_schema(connection: sqlite3.Connection) -> bool:
    columns = _columns(connection, "player_stats")
    if not _REQUIRED_COLUMNS.issubset(columns):
        return False
    if any(not bool(columns[name]["notnull"]) for name in _CANONICAL_NOT_NULL):
        return False
    sql_row = connection.execute(
        """SELECT sql FROM sqlite_master
           WHERE type='table' AND name='player_stats'"""
    ).fetchone()
    normalized = "".join(str(sql_row["sql"] or "").lower().split())
    if "unique(player_id,league,season,stat_type)" not in normalized:
        return False
    if "unique(name_norm,league,season,stat_type)" in normalized:
        return False
    foreign_keys = {
        (row["from"], row["table"], row["to"])
        for row in connection.execute(
            "PRAGMA foreign_key_list(player_stats)"
        )
    }
    return ("player_id", "players", "id") in foreign_keys


def _registry_checksum(
    connection: sqlite3.Connection,
) -> str | None:
    if not _table_exists(connection, migrate_schema.REGISTRY_TABLE):
        return None
    row = connection.execute(
        """SELECT checksum FROM app_schema_migrations
           WHERE migration_id=?""",
        (MIGRATION_ID,),
    ).fetchone()
    return str(row["checksum"]) if row else None


def _audit_data(connection: sqlite3.Connection) -> dict[str, int]:
    issues = {key: 0 for key in _ISSUE_KEYS}
    columns = _columns(connection, "player_stats")
    if not _REQUIRED_COLUMNS.issubset(columns):
        issues["null_canonical_fields"] = -1
        return issues

    null_clause = " OR ".join(
        f"{_quote(column)} IS NULL" for column in _CANONICAL_NOT_NULL
    )
    issues["null_canonical_fields"] = connection.execute(
        f"SELECT COUNT(*) FROM player_stats WHERE {null_clause}"
    ).fetchone()[0]
    issues["orphan_players"] = connection.execute(
        """SELECT COUNT(*) FROM player_stats ps
           LEFT JOIN players p ON p.id=ps.player_id
           WHERE ps.player_id IS NOT NULL AND p.id IS NULL"""
    ).fetchone()[0]
    issues["league_mismatches"] = connection.execute(
        """SELECT COUNT(*) FROM player_stats ps
           JOIN players p ON p.id=ps.player_id
           WHERE lower(ps.league)!=lower(p.league)"""
    ).fetchone()[0]
    issues["display_name_mismatches"] = connection.execute(
        """SELECT COUNT(*) FROM player_stats ps
           JOIN players p ON p.id=ps.player_id
           WHERE ps.player_name!=p.name"""
    ).fetchone()[0]
    issues["duplicate_canonical_keys"] = connection.execute(
        """SELECT COUNT(*) FROM (
             SELECT player_id,league,season,stat_type
             FROM player_stats
             WHERE player_id IS NOT NULL
               AND league IS NOT NULL
               AND season IS NOT NULL
               AND stat_type IS NOT NULL
             GROUP BY player_id,league,season,stat_type
             HAVING COUNT(*)>1
           )"""
    ).fetchone()[0]

    invalid_types = 0
    unowned_sources = 0
    for row in connection.execute(
        """SELECT league,stat_type,season,source
           FROM player_stats
           WHERE league IS NOT NULL AND season IS NOT NULL"""
    ):
        raw_type = str(row["stat_type"] or "").strip().lower()
        try:
            expected_type = canonical_stat_type(
                row["league"], row["stat_type"]
            )
        except LeagueStatContractError:
            invalid_types += 1
            unowned_sources += 1
            continue
        if raw_type != expected_type:
            invalid_types += 1
        if not source_owns_stats(
            row["league"], expected_type, row["season"], row["source"]
        ):
            unowned_sources += 1
    issues["invalid_stat_types"] = invalid_types
    issues["unowned_sources"] = unowned_sources

    dependent_count = connection.execute(
        """SELECT COUNT(*) FROM sqlite_master
           WHERE type IN ('trigger','view')
             AND lower(COALESCE(sql,'')) LIKE '%player_stats%'"""
    ).fetchone()[0]
    inbound_foreign_keys = 0
    for table_row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ):
        table = str(table_row["name"])
        if table == "player_stats":
            continue
        inbound_foreign_keys += sum(
            1
            for foreign_key in connection.execute(
                f"PRAGMA foreign_key_list({_quote(table)})"
            )
            if foreign_key["table"] == "player_stats"
        )
    issues["unsupported_schema_dependents"] = (
        dependent_count + inbound_foreign_keys
    )
    return issues


def _check_connection(
    connection: sqlite3.Connection, path: str
) -> CheckResult:
    if not _table_exists(connection, "players"):
        return CheckResult(
            path, "error", "required table 'players' is missing",
            {key: 0 for key in _ISSUE_KEYS},
        )
    if not _table_exists(connection, "player_stats"):
        return CheckResult(
            path, "error", "required table 'player_stats' is missing",
            {key: 0 for key in _ISSUE_KEYS},
        )
    issues = _audit_data(connection)
    blocked = {key: value for key, value in issues.items() if value}
    if blocked:
        detail = ", ".join(
            f"{key}={value}" for key, value in blocked.items()
        )
        return CheckResult(path, "blocked", detail, issues)

    registered = _registry_checksum(connection)
    if registered is not None and registered != MIGRATION_CHECKSUM:
        return CheckResult(
            path, "error",
            f"checksum mismatch: database has {registered}",
            issues,
        )
    canonical = _canonical_schema(connection)
    if registered is not None and not canonical:
        return CheckResult(
            path, "error",
            "migration is registered but canonical schema is absent",
            issues,
        )
    if registered is not None:
        return CheckResult(
            path, "applied",
            f"checksum={MIGRATION_CHECKSUM}",
            issues,
        )
    if canonical:
        return CheckResult(
            path, "adopt",
            "canonical schema is exact; registry adoption required",
            issues,
        )
    return CheckResult(
        path, "pending",
        "legacy name-keyed table requires canonical rebuild",
        issues,
    )


def check_database(path: str) -> CheckResult:
    absolute = _validated_path(path)
    with _read_only_connection(absolute) as connection:
        return _check_connection(connection, absolute)


def _column_definition(row: sqlite3.Row) -> str:
    name = str(row["name"])
    declared_type = str(row["type"] or "").strip() or "TEXT"
    if int(row["pk"]):
        return f"{_quote(name)} INTEGER PRIMARY KEY AUTOINCREMENT"
    parts = [_quote(name), declared_type]
    if name in _CANONICAL_NOT_NULL or bool(row["notnull"]):
        parts.append("NOT NULL")
    if row["dflt_value"] is not None and name not in _CANONICAL_NOT_NULL:
        parts.extend(("DEFAULT", str(row["dflt_value"])))
    return " ".join(parts)


def _rebuild_table(connection: sqlite3.Connection) -> None:
    legacy_table = "player_stats_pre_canonical_v0613"
    if _table_exists(connection, legacy_table):
        raise PlayerStatsMigrationError(
            f"temporary table {legacy_table!r} already exists"
        )
    column_rows = list(
        connection.execute("PRAGMA table_info(player_stats)")
    )
    column_names = [str(row["name"]) for row in column_rows]
    if not _REQUIRED_COLUMNS.issubset(column_names):
        missing = sorted(_REQUIRED_COLUMNS - set(column_names))
        raise PlayerStatsMigrationError(
            "player_stats is missing required columns: "
            + ", ".join(missing)
        )

    definitions = [_column_definition(row) for row in column_rows]
    definitions.extend(
        (
            "FOREIGN KEY(player_id) REFERENCES players(id)",
            "UNIQUE(player_id,league,season,stat_type)",
        )
    )
    connection.execute(
        f"ALTER TABLE player_stats RENAME TO {_quote(legacy_table)}"
    )
    connection.execute(
        "CREATE TABLE player_stats(\n  "
        + ",\n  ".join(definitions)
        + "\n)"
    )
    selected_columns = ",".join(_quote(name) for name in column_names)
    connection.execute(
        f"""INSERT INTO player_stats({selected_columns})
            SELECT {selected_columns} FROM {_quote(legacy_table)}"""
    )
    connection.execute(f"DROP TABLE {_quote(legacy_table)}")
    connection.execute(
        """CREATE INDEX idx_player_stats_player
           ON player_stats(player_id,season)"""
    )


def apply_database(
    path: str, *, backup_destination: str | None = None
) -> tuple[str, CheckResult]:
    absolute = _validated_path(path)
    before = check_database(absolute)
    if before.state in ("blocked", "error"):
        raise PlayerStatsMigrationError(
            f"{before.state}: {before.detail}"
        )
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
        if current.state in ("blocked", "error"):
            raise PlayerStatsMigrationError(
                f"{current.state}: {current.detail}"
            )
        if current.state == "pending":
            _rebuild_table(connection)
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
        raise PlayerStatsMigrationError(
            f"post-commit verification failed: {after.state} {after.detail}"
        )
    return backup, after


def _print(result: CheckResult) -> None:
    print(f"database: {result.path}")
    print(f"{result.state.upper():7} {MIGRATION_ID}: {result.detail}")
    for key, value in result.issues.items():
        print(f"  {key}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or apply canonical player_stats migration"
    )
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            result = check_database(args.db)
            _print(result)
            return 0 if result.ok else 1
        backup, result = apply_database(args.db)
        print(f"backup: {backup} (quick_check=ok)")
        _print(result)
        return 0
    except (PlayerStatsMigrationError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
