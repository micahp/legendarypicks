#!/usr/bin/env python3
"""Apply a reviewed MLB identity proposal to an isolated SQLite copy only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from plan_mlb_identity_repairs import identity_name_key


class InvariantError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_copy_path(raw_path: str) -> Path:
    requested = Path(raw_path).expanduser()
    if requested.is_symlink():
        raise InvariantError("copy database must not be a symlink")
    path = requested.resolve()
    tmp = Path("/tmp").resolve()
    if tmp not in path.parents:
        raise InvariantError("copy-only applier refuses databases outside /tmp")
    if path.is_symlink() or not path.is_file():
        raise InvariantError("copy database must be an existing regular file")
    if path.stat().st_nlink != 1:
        raise InvariantError("copy database must not be hard-linked")
    for suffix in ("-wal", "-shm"):
        if Path(f"{path}{suffix}").exists():
            raise InvariantError(f"copy database has an active SQLite sidecar: {suffix}")
    return path


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info({table})")]


def player(con: sqlite3.Connection, player_id: int) -> dict[str, Any] | None:
    row = con.execute(
        "SELECT id,name,team,espn_id,mlbam_id,active FROM players WHERE id=?",
        (player_id,),
    ).fetchone()
    return dict(row) if row else None


def reference_counts(con: sqlite3.Connection, player_id: int) -> dict[str, int]:
    counts = {}
    for key, table in (
        ("props", "props"),
        ("player_game_logs", "player_game_logs"),
        ("player_stats", "player_stats"),
    ):
        counts[key] = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE player_id=?", (player_id,)
        ).fetchone()[0]
    prediction_columns = set(table_columns(con, "predictions"))
    counts["predictions"] = (
        con.execute("SELECT COUNT(*) FROM predictions WHERE player_id=?", (player_id,)).fetchone()[0]
        if "player_id" in prediction_columns else 0
    )
    return counts


def preflight(con: sqlite3.Connection, artifact: dict[str, Any]) -> dict[str, Any]:
    proposals = artifact.get("proposals") or []
    if len(proposals) != 135 or artifact.get("summary", {}).get("safe_crosswalk_proposals") != 135:
        raise InvariantError("artifact is not the reviewed 135-proposal population")

    canonical_ids, source_ids, candidate_ids = set(), set(), set()
    correct_ids, displaced_ids = set(), set()
    log_dispositions = {"to_canonical": 0, "to_candidate": 0, "quarantine": 0}
    stats_to_archive = 0
    for proposal in proposals:
        canonical_id = int(proposal["canonical_player_id"])
        source_id = int(proposal["source_player_id"])
        candidates = [int(value) for value in proposal["displaced_identity_candidate_player_ids"]]
        if len(candidates) not in (0, 1):
            raise InvariantError(f"unexpected candidate count for {proposal['stored_name']}")
        canonical = player(con, canonical_id)
        source = player(con, source_id)
        if not canonical or not source:
            raise InvariantError(f"missing proposal row for {proposal['stored_name']}")
        expected_name = identity_name_key(proposal["stored_name"])
        checks = (
            identity_name_key(canonical["name"]) == expected_name,
            identity_name_key(source["name"]) == expected_name,
            identity_name_key(proposal["correct_official_name"]) == expected_name,
            str(canonical["espn_id"]) == str(proposal["espn_id"]),
            source["espn_id"] in (None, ""),
            int(canonical["mlbam_id"]) == int(proposal["displaced_mlbam_id"]),
            int(source["mlbam_id"]) == int(proposal["correct_mlbam_id"]),
            reference_counts(con, canonical_id) == proposal["canonical_reference_counts"],
            reference_counts(con, source_id) == proposal["source_reference_counts"],
        )
        if not all(checks):
            raise InvariantError(f"proposal drift for {proposal['stored_name']}")
        canonical_ids.add(canonical_id)
        source_ids.add(source_id)
        correct_ids.add(int(proposal["correct_mlbam_id"]))
        displaced_ids.add(int(proposal["displaced_mlbam_id"]))

        affected_ids = [canonical_id, source_id, *candidates]
        marks = ",".join("?" for _ in affected_ids)
        logs = con.execute(
            f"SELECT id,player_id,source_player_key FROM player_game_logs "
            f"WHERE player_id IN ({marks})", affected_ids,
        ).fetchall()
        for log in logs:
            key = str(log["source_player_key"] or "").strip()
            if log["player_id"] == source_id and key == str(proposal["correct_mlbam_id"]):
                log_dispositions["to_canonical"] += 1
            elif log["player_id"] == canonical_id and key == str(proposal["displaced_mlbam_id"]):
                log_dispositions["to_candidate" if candidates else "quarantine"] += 1
            else:
                raise InvariantError(
                    f"unclassified log {log['id']} for {proposal['stored_name']}"
                )
        stats_to_archive += con.execute(
            f"SELECT COUNT(*) FROM player_stats WHERE player_id IN ({','.join('?' for _ in [canonical_id, source_id])})",
            (canonical_id, source_id),
        ).fetchone()[0]

        for candidate_id in candidates:
            candidate = player(con, candidate_id)
            if not candidate:
                raise InvariantError(f"missing displaced candidate {candidate_id}")
            if identity_name_key(candidate["name"]) != identity_name_key(proposal["displaced_official_name"]):
                raise InvariantError(f"candidate name drift for {proposal['stored_name']}")
            if not candidate["espn_id"] or candidate["mlbam_id"] not in (None, 0):
                raise InvariantError(f"candidate identity drift for {proposal['stored_name']}")
            candidate_ids.add(candidate_id)

    if len(canonical_ids) != 135 or len(source_ids) != 135:
        raise InvariantError("canonical/source IDs are not unique")
    if canonical_ids & source_ids or candidate_ids & (canonical_ids | source_ids):
        raise InvariantError("proposal identity roles overlap")
    if correct_ids & displaced_ids:
        raise InvariantError("correct and displaced MLBAM populations overlap")
    for table in ("name_alias", "roster_snap"):
        all_ids = sorted(canonical_ids | source_ids | candidate_ids)
        marks = ",".join("?" for _ in all_ids)
        count = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE player_id IN ({marks})", all_ids
        ).fetchone()[0]
        if count:
            raise InvariantError(f"uninventoried {table} references: {count}")
    if log_dispositions != {"to_canonical": 2781, "to_candidate": 1380, "quarantine": 5213}:
        raise InvariantError(f"log population drift: {log_dispositions}")
    if stats_to_archive != 404:
        raise InvariantError(f"aggregate population drift: {stats_to_archive}")
    return {
        "canonical_ids": canonical_ids,
        "source_ids": source_ids,
        "candidate_ids": candidate_ids,
        "log_dispositions": log_dispositions,
        "stats_to_archive": stats_to_archive,
    }


def ensure_repair_schema(con: sqlite3.Connection) -> None:
    unresolved = set(table_columns(con, "unresolved_players"))
    for column in ("source_player_key", "reason"):
        if column not in unresolved:
            con.execute(f"ALTER TABLE unresolved_players ADD COLUMN {column} TEXT")
    con.execute(
        "CREATE TABLE IF NOT EXISTS mlb_identity_repair_archive("
        "run_id TEXT NOT NULL, entity_type TEXT NOT NULL, original_id INTEGER NOT NULL, "
        "original_player_id INTEGER, source_player_key TEXT, disposition TEXT NOT NULL, "
        "payload_json TEXT NOT NULL, archived_at TEXT NOT NULL, "
        "PRIMARY KEY(run_id,entity_type,original_id))"
    )


def archive_rows(
    con: sqlite3.Connection, run_id: str, table: str, rows: list[sqlite3.Row],
    disposition: str, archived_at: str,
) -> None:
    for row in rows:
        payload = dict(row)
        con.execute(
            "INSERT INTO mlb_identity_repair_archive"
            "(run_id,entity_type,original_id,original_player_id,source_player_key,"
            "disposition,payload_json,archived_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id, table, int(payload["id"]), payload.get("player_id"),
                payload.get("source_player_key"), disposition,
                json.dumps(payload, sort_keys=True), archived_at,
            ),
        )


def queue_absent_displaced(
    con: sqlite3.Connection, proposal: dict[str, Any], archived_at: str,
) -> None:
    source_key = str(proposal["displaced_mlbam_id"])
    existing = con.execute(
        "SELECT id FROM unresolved_players WHERE source='mlb_identity_repair' "
        "AND league='mlb' AND source_player_key=?", (source_key,),
    ).fetchone()
    if existing:
        raise InvariantError(f"displaced queue row already exists for {source_key}")
    con.execute(
        "INSERT INTO unresolved_players"
        "(source,raw_name,league,team,first_seen,count,source_player_key,reason) "
        "VALUES ('mlb_identity_repair',?,'mlb',NULL,?,1,?,?)",
        (
            proposal["displaced_official_name"], archived_at, source_key,
            "displaced_official_identity_not_represented",
        ),
    )


def apply_transaction(
    con: sqlite3.Connection, artifact: dict[str, Any], run_id: str,
) -> dict[str, Any]:
    before = preflight(con, artifact)
    ensure_repair_schema(con)
    now = datetime.now(timezone.utc).isoformat()
    archived_logs = 0
    archived_stats = 0

    for proposal in artifact["proposals"]:
        canonical_id = int(proposal["canonical_player_id"])
        source_id = int(proposal["source_player_id"])
        candidates = [int(value) for value in proposal["displaced_identity_candidate_player_ids"]]
        displaced_key = str(proposal["displaced_mlbam_id"])
        correct_key = str(proposal["correct_mlbam_id"])

        con.execute(
            "UPDATE player_game_logs SET player_id=? WHERE player_id=? AND source_player_key=?",
            (canonical_id, source_id, correct_key),
        )
        if candidates:
            con.execute(
                "UPDATE player_game_logs SET player_id=? WHERE player_id=? AND source_player_key=?",
                (candidates[0], canonical_id, displaced_key),
            )
        else:
            rows = con.execute(
                "SELECT * FROM player_game_logs WHERE player_id=? AND source_player_key=?",
                (canonical_id, displaced_key),
            ).fetchall()
            archive_rows(con, run_id, "player_game_logs", rows,
                         "unrepresented_displaced_identity", now)
            archived_logs += len(rows)
            con.executemany(
                "DELETE FROM player_game_logs WHERE id=?", [(row["id"],) for row in rows]
            )
            queue_absent_displaced(con, proposal, now)

        stats = con.execute(
            "SELECT * FROM player_stats WHERE player_id IN (?,?)", (canonical_id, source_id)
        ).fetchall()
        archive_rows(con, run_id, "player_stats", stats,
                     "requires_authoritative_regeneration", now)
        archived_stats += len(stats)
        con.execute("DELETE FROM player_stats WHERE player_id IN (?,?)", (canonical_id, source_id))

        con.execute("UPDATE players SET mlbam_id=NULL WHERE id IN (?,?)", (canonical_id, source_id))
        if candidates:
            con.execute(
                "UPDATE players SET mlbam_id=? WHERE id=?",
                (proposal["displaced_mlbam_id"], candidates[0]),
            )
        con.execute(
            "UPDATE players SET mlbam_id=? WHERE id=?",
            (proposal["correct_mlbam_id"], canonical_id),
        )

    source_ids = sorted(before["source_ids"])
    marks = ",".join("?" for _ in source_ids)
    for table in ("props", "player_game_logs", "player_stats", "name_alias", "roster_snap"):
        remaining = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE player_id IN ({marks})", source_ids
        ).fetchone()[0]
        if remaining:
            raise InvariantError(f"source rows retain {remaining} {table} references")
    con.execute(f"DELETE FROM players WHERE id IN ({marks})", source_ids)

    duplicate_mlbam = con.execute(
        "SELECT COUNT(*) FROM (SELECT mlbam_id FROM players WHERE league='mlb' "
        "AND mlbam_id IS NOT NULL AND mlbam_id!=0 GROUP BY mlbam_id HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if duplicate_mlbam:
        raise InvariantError(f"post-apply duplicate MLBAM groups: {duplicate_mlbam}")
    archive_counts = dict(
        con.execute(
            "SELECT entity_type,COUNT(*) FROM mlb_identity_repair_archive "
            "WHERE run_id=? GROUP BY entity_type", (run_id,)
        ).fetchall()
    )
    if archive_counts != {"player_game_logs": 5213, "player_stats": 404}:
        raise InvariantError(f"archive count mismatch: {archive_counts}")
    return {
        "source_players_deleted": len(source_ids),
        "correct_logs_to_canonical": 2781,
        "displaced_logs_to_candidates": 1380,
        "displaced_logs_archived": archived_logs,
        "stats_archived_for_regeneration": archived_stats,
        "absent_displaced_identities_queued": 103,
        "duplicate_mlbam_groups": duplicate_mlbam,
        "archive_counts": archive_counts,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-proposal-sha256", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--commit-copy", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    db_path = require_copy_path(args.db)
    before_hash = file_sha256(db_path)
    if before_hash != args.expected_sha256:
        raise InvariantError("copy database SHA-256 does not match --expected-sha256")
    artifact_path = Path(args.proposal).resolve()
    artifact_hash = file_sha256(artifact_path)
    if artifact_hash != args.expected_proposal_sha256:
        raise InvariantError(
            "proposal SHA-256 does not match --expected-proposal-sha256"
        )
    artifact = json.loads(artifact_path.read_text())
    run_id = f"mlb-identity-{artifact_hash[:16]}"

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("BEGIN IMMEDIATE")
    try:
        changes = apply_transaction(con, artifact, run_id)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise InvariantError(f"integrity check failed: {integrity}")
        if args.commit_copy:
            con.commit()
        else:
            con.rollback()
    except Exception:
        con.rollback()
        con.close()
        raise
    con.close()
    after_hash = file_sha256(db_path)
    report = {
        "mode": "copy_commit" if args.commit_copy else "rollback_dry_run",
        "run_id": run_id,
        "database": str(db_path),
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "artifact_sha256": artifact_hash,
        "transaction_committed": bool(args.commit_copy),
        "integrity_check": integrity,
        "changes": changes,
    }
    if args.commit_copy:
        # A consolidation without a log line is a defect.
        import name_aliases
        from datetime import datetime, timezone
        name_aliases.record_consolidation({
            "ts": datetime.now(timezone.utc).isoformat(),
            "script": "apply_mlb_identity_repairs_copy.py",
            "db": os.path.basename(str(db_path)),
            "run_id": run_id,
            "direction": "repair",
            "changes": changes,
            "note": f"mlb identity repair applied from {artifact_path.name}",
        })
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
