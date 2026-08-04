#!/usr/bin/env python3
"""Apply a hash-bound MLB identity rebuild to an isolated SQLite copy only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


class RebuildInvariantError(RuntimeError):
    """A copy, plan, schema, or data invariant failed."""


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_copy_path(raw_path: str) -> Path:
    requested = Path(raw_path).expanduser()
    if requested.is_symlink():
        raise RebuildInvariantError("copy database must not be a symlink")
    path = requested.resolve(strict=True)
    tmp = Path("/tmp").resolve()
    if tmp not in path.parents:
        raise RebuildInvariantError(
            "copy-only applier refuses databases outside /tmp"
        )
    if path.is_symlink() or not path.is_file():
        raise RebuildInvariantError(
            "copy database must be an existing regular file"
        )
    if path.stat().st_nlink != 1:
        raise RebuildInvariantError(
            "copy database must not be hard-linked"
        )
    for suffix in ("-wal", "-shm"):
        if Path(f"{path}{suffix}").exists():
            raise RebuildInvariantError(
                f"copy database has an active SQLite sidecar: {suffix}"
            )
    return path


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_columns(
    connection: sqlite3.Connection, table: str
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_quote(table)})"
        )
    }


def _row_digest(rows: Sequence[sqlite3.Row]) -> str:
    payload = [
        {key: row[key] for key in row.keys()}
        for row in rows
    ]
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _marks(values: Sequence[int]) -> str:
    if not values:
        raise RebuildInvariantError("empty identifier population")
    return ",".join("?" for _ in values)


def _ensure_archive_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS player_identity_rebuild_archive(
             run_id TEXT NOT NULL,
             entity_type TEXT NOT NULL,
             original_id INTEGER NOT NULL,
             original_player_id INTEGER,
             source_player_key TEXT,
             disposition TEXT NOT NULL,
             payload_json TEXT NOT NULL,
             archived_at TEXT NOT NULL,
             PRIMARY KEY(run_id,entity_type,original_id)
           )"""
    )


def _archive_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    entity_type: str,
    rows: Iterable[sqlite3.Row],
    disposition: str,
    archived_at: str,
) -> int:
    count = 0
    for row in rows:
        payload = dict(row)
        connection.execute(
            """INSERT INTO player_identity_rebuild_archive(
                 run_id,entity_type,original_id,original_player_id,
                 source_player_key,disposition,payload_json,archived_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                run_id,
                entity_type,
                int(payload["id"]),
                payload.get("player_id"),
                payload.get("source_player_key"),
                disposition,
                json.dumps(payload, sort_keys=True, default=str),
                archived_at,
            ),
        )
        count += 1
    return count


def _ensure_unresolved_schema(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "unresolved_players")
    for column in ("source_player_key", "reason"):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE unresolved_players "
                f"ADD COLUMN {_quote(column)} TEXT"
            )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key
           ON unresolved_players(source,league,source_player_key)"""
    )


def _queue_detachment(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    timestamp: str,
) -> None:
    source_key = str(item["detached_mlbam_id"])
    player_key = f"player_id={int(item['player_id'])};mlbam_id={source_key}"
    existing = connection.execute(
        """SELECT id FROM unresolved_players
           WHERE source='mlb_identity_rebuild' AND league='mlb'
             AND source_player_key=?""",
        (player_key,),
    ).fetchone()
    if existing:
        raise RebuildInvariantError(
            f"detachment queue row already exists for {player_key}"
        )
    connection.execute(
        """INSERT INTO unresolved_players(
             source,raw_name,league,team,first_seen,count,
             source_player_key,reason
           ) VALUES('mlb_identity_rebuild',?,'mlb',NULL,?,1,?,?)""",
        (
            str(item.get("stored_name") or ""),
            timestamp,
            player_key,
            str(item["reason"]),
        ),
    )


def _queue_archived_log_source(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    timestamp: str,
) -> None:
    source_key = str(item["source_player_key"])
    existing = connection.execute(
        """SELECT id FROM unresolved_players
           WHERE source='mlb_identity_rebuild_log' AND league='mlb'
             AND source_player_key=?""",
        (source_key,),
    ).fetchone()
    if existing:
        raise RebuildInvariantError(
            f"archived-log queue row already exists for {source_key}"
        )
    raw_name = item.get("official_name") or f"mlbam_{source_key}"
    connection.execute(
        """INSERT INTO unresolved_players(
             source,raw_name,league,team,first_seen,count,
             source_player_key,reason
           ) VALUES('mlb_identity_rebuild_log',?,'mlb',NULL,?,?,?,?)""",
        (
            raw_name,
            timestamp,
            int(item["row_count"]),
            source_key,
            "archived_logs_have_no_corroborated_canonical_owner",
        ),
    )


def _validate_plan(
    connection: sqlite3.Connection,
    plan: dict[str, Any],
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if plan.get("planner_version") != 1:
        raise RebuildInvariantError("unsupported rebuild planner version")
    if plan.get("unsupported_references"):
        raise RebuildInvariantError(
            "plan contains unsupported player references"
        )
    foreign_key_rows = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    foreign_key_scope = plan["foreign_key_scope"]
    if (
        len(foreign_key_rows)
        != int(foreign_key_scope["baseline_count"])
        or _row_digest(foreign_key_rows)
        != foreign_key_scope["baseline_sha256"]
    ):
        raise RebuildInvariantError(
            "baseline foreign-key violations drifted"
        )
    summary = plan.get("summary") or {}
    if not summary.get("original_duplicate_mlbam_groups"):
        raise RebuildInvariantError(
            "plan does not describe a duplicate MLBAM population"
        )

    stats_scope = plan["player_stats_scope"]
    stats_rows = connection.execute(
        """SELECT * FROM player_stats
           WHERE lower(league)=? AND season=? ORDER BY id""",
        (stats_scope["league"], int(stats_scope["season"])),
    ).fetchall()
    if (
        len(stats_rows) != int(stats_scope["row_count"])
        or _row_digest(stats_rows) != stats_scope["rows_sha256"]
    ):
        raise RebuildInvariantError(
            "current-season MLB player_stats population drifted"
        )

    log_scope = plan["game_log_scope"]
    log_rows = connection.execute(
        """SELECT * FROM player_game_logs
           WHERE lower(league)=? ORDER BY id""",
        (log_scope["league"],),
    ).fetchall()
    if (
        len(log_rows) != int(log_scope["row_count"])
        or _row_digest(log_rows) != log_scope["rows_sha256"]
    ):
        raise RebuildInvariantError("MLB game-log population drifted")

    delete_ids = [int(value) for value in plan["delete_player_ids"]]
    if len(delete_ids) != int(summary["source_players_to_delete"]):
        raise RebuildInvariantError("source-player count drift in plan")
    rows = connection.execute(
        f"SELECT id FROM players WHERE id IN ({_marks(delete_ids)})",
        delete_ids,
    ).fetchall()
    if len(rows) != len(delete_ids):
        raise RebuildInvariantError("planned source player is missing")

    outside_stats = connection.execute(
        f"""SELECT COUNT(*) FROM player_stats
            WHERE player_id IN ({_marks(delete_ids)})
              AND NOT (lower(league)=? AND season=?)""",
        [*delete_ids, stats_scope["league"], int(stats_scope["season"])],
    ).fetchone()[0]
    if outside_stats:
        raise RebuildInvariantError(
            "source players have player_stats outside rebuild scope"
        )
    return stats_rows, log_rows


def apply_transaction(
    connection: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    stats_rows, log_rows = _validate_plan(connection, plan)
    _ensure_archive_schema(connection)
    _ensure_unresolved_schema(connection)
    now = datetime.now(timezone.utc).isoformat()

    props_before = int(
        connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    )
    stats_archived = _archive_rows(
        connection,
        run_id=run_id,
        entity_type="player_stats",
        rows=stats_rows,
        disposition="authoritative_regeneration_required",
        archived_at=now,
    )
    stats_ids = [int(row["id"]) for row in stats_rows]
    if stats_ids:
        connection.execute(
            f"DELETE FROM player_stats WHERE id IN ({_marks(stats_ids)})",
            stats_ids,
        )

    canonical_by_mlbam = {
        int(key): int(value)
        for key, value in plan["canonical_by_mlbam"].items()
    }
    delete_ids = {int(value) for value in plan["delete_player_ids"]}
    log_repoints = 0
    logs_to_archive = []
    for row in log_rows:
        try:
            source_mlbam = int(str(row["source_player_key"]).strip())
        except (TypeError, ValueError):
            source_mlbam = None
        target_player = (
            canonical_by_mlbam.get(source_mlbam)
            if source_mlbam is not None
            else None
        )
        if target_player is not None:
            if row["player_id"] != target_player:
                connection.execute(
                    "UPDATE player_game_logs SET player_id=? WHERE id=?",
                    (target_player, int(row["id"])),
                )
                log_repoints += 1
        elif row["player_id"] in delete_ids:
            logs_to_archive.append(row)

    logs_archived = _archive_rows(
        connection,
        run_id=run_id,
        entity_type="player_game_logs",
        rows=logs_to_archive,
        disposition="source_key_has_no_corroborated_identity",
        archived_at=now,
    )
    if logs_to_archive:
        log_ids = [int(row["id"]) for row in logs_to_archive]
        connection.execute(
            f"DELETE FROM player_game_logs "
            f"WHERE id IN ({_marks(log_ids)})",
            log_ids,
        )
    for item in plan["game_log_scope"]["archive_sources"]:
        _queue_archived_log_source(connection, item, now)

    props_repointed = 0
    for merge in plan["merges"]:
        canonical_id = int(merge["canonical_player_id"])
        for source_id in map(int, merge["source_player_ids"]):
            cursor = connection.execute(
                "UPDATE props SET player_id=? WHERE player_id=?",
                (canonical_id, source_id),
            )
            props_repointed += int(cursor.rowcount)
            if "alias_norm" in _table_columns(connection, "name_alias"):
                connection.execute(
                    """INSERT OR IGNORE INTO name_alias(player_id,alias_norm)
                       SELECT ?,alias_norm FROM name_alias
                       WHERE player_id=?""",
                    (canonical_id, source_id),
                )
                connection.execute(
                    "DELETE FROM name_alias WHERE player_id=?",
                    (source_id,),
                )

    assigned_ids = [int(value) for value in plan["assigned_player_ids"]]
    detached_ids = [
        int(item["player_id"]) for item in plan["detachments"]
    ]
    clear_ids = sorted(set(assigned_ids) | set(detached_ids))
    connection.execute(
        f"UPDATE players SET mlbam_id=NULL "
        f"WHERE id IN ({_marks(clear_ids)})",
        clear_ids,
    )
    for raw_mlbam, raw_player_id in sorted(
        plan["canonical_by_mlbam"].items(), key=lambda item: int(item[0])
    ):
        connection.execute(
            "UPDATE players SET mlbam_id=? WHERE id=?",
            (int(raw_mlbam), int(raw_player_id)),
        )
    for item in plan["detachments"]:
        _queue_detachment(connection, item, now)

    source_rows = connection.execute(
        f"SELECT * FROM players "
        f"WHERE id IN ({_marks(sorted(delete_ids))}) ORDER BY id",
        sorted(delete_ids),
    ).fetchall()
    players_archived = _archive_rows(
        connection,
        run_id=run_id,
        entity_type="players",
        rows=source_rows,
        disposition="merged_into_corroborated_canonical_identity",
        archived_at=now,
    )

    for table in ("props", "player_game_logs", "player_stats", "name_alias"):
        remaining = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table)} "
                f"WHERE player_id IN ({_marks(sorted(delete_ids))})",
                sorted(delete_ids),
            ).fetchone()[0]
        )
        if remaining:
            raise RebuildInvariantError(
                f"source players retain {remaining} references in {table}"
            )
    connection.execute(
        f"DELETE FROM players WHERE id IN ({_marks(sorted(delete_ids))})",
        sorted(delete_ids),
    )

    duplicate_mlbam = int(
        connection.execute(
            """SELECT COUNT(*) FROM (
                 SELECT mlbam_id FROM players
                 WHERE lower(league)='mlb' AND mlbam_id IS NOT NULL
                   AND mlbam_id!=0
                 GROUP BY mlbam_id HAVING COUNT(*)>1
               )"""
        ).fetchone()[0]
    )
    if duplicate_mlbam:
        raise RebuildInvariantError(
            f"post-rebuild duplicate MLBAM groups: {duplicate_mlbam}"
        )
    props_after = int(
        connection.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    )
    if props_after != props_before:
        raise RebuildInvariantError(
            f"props row count changed: {props_before} -> {props_after}"
        )

    expected = plan["summary"]
    observed = {
        "player_stats_archived": stats_archived,
        "game_logs_repointed": log_repoints,
        "game_logs_archived": logs_archived,
        "game_log_source_keys_queued": len(
            plan["game_log_scope"]["archive_sources"]
        ),
        "players_archived": players_archived,
        "players_deleted": len(delete_ids),
        "unresolved_conflicts_detached": len(detached_ids),
        "duplicate_mlbam_groups": duplicate_mlbam,
        "props_before": props_before,
        "props_after": props_after,
        "props_repointed": props_repointed,
    }
    checks = (
        stats_archived == int(expected["player_stats_to_archive"]),
        log_repoints == int(expected["game_logs_to_repoint"]),
        logs_archived == int(expected["game_logs_to_archive"]),
        len(plan["game_log_scope"]["archive_sources"])
        == int(expected["game_log_source_keys_to_queue"]),
        players_archived == int(expected["source_players_to_delete"]),
        len(detached_ids)
        == int(expected["unresolved_conflicts_to_detach"]),
        props_repointed == int(expected["props_to_repoint"]),
    )
    if not all(checks):
        raise RebuildInvariantError(
            f"rebuild counts disagree with plan: {observed}"
        )
    foreign_key_errors = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    foreign_key_scope = plan["foreign_key_scope"]
    if (
        len(foreign_key_errors)
        != int(foreign_key_scope["baseline_count"])
        or _row_digest(foreign_key_errors)
        != foreign_key_scope["baseline_sha256"]
    ):
        raise RebuildInvariantError(
            "rebuild changed the inherited foreign-key violation set"
        )
    return observed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-db-sha256", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--commit-copy", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    db_path = require_copy_path(args.db)
    before_hash = file_sha256(db_path)
    if before_hash != args.expected_db_sha256:
        raise RebuildInvariantError(
            "copy database SHA-256 does not match --expected-db-sha256"
        )

    plan_path = Path(args.plan).resolve(strict=True)
    plan_hash = file_sha256(plan_path)
    if plan_hash != args.expected_plan_sha256:
        raise RebuildInvariantError(
            "plan SHA-256 does not match --expected-plan-sha256"
        )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("candidate", {}).get("sha256") != before_hash:
        raise RebuildInvariantError(
            "plan was not generated from this exact database copy"
        )

    run_id = f"mlb-rebuild-{plan_hash[:16]}"
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        changes = apply_transaction(
            connection, plan, run_id=run_id
        )
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise RebuildInvariantError(
                f"integrity check failed: {integrity}"
            )
        if args.commit_copy:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        connection.close()
        raise
    connection.close()

    after_hash = file_sha256(db_path)
    if not args.commit_copy and after_hash != before_hash:
        raise RebuildInvariantError(
            "rollback dry run changed the copy's SHA-256"
        )
    report = {
        "mode": "copy_commit" if args.commit_copy else "rollback_dry_run",
        "run_id": run_id,
        "database": str(db_path),
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "plan_sha256": plan_hash,
        "transaction_committed": bool(args.commit_copy),
        "integrity_check": integrity,
        "changes": changes,
    }
    Path(args.report).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
