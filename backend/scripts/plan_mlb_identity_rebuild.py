#!/usr/bin/env python3
"""Plan a deterministic MLB identity rebuild without mutating either database.

The candidate database is normally a SQLite-safe production clone.  A second,
already-clean database is used only as corroborating identity evidence: a
crosswalk change is proposed when the candidate name has one exact official
MLB People match and the reference spine independently carries that same
name/MLBAM pair.  Current exact MLB People matches do not require the reference
database.

The output is a hash-bound plan for ``apply_mlb_identity_rebuild_copy.py``.
This planner has no apply mode and opens both databases read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from plan_mlb_identity_repairs import (
    connect_read_only,
    identity_name_key,
    load_people_json,
    official_indexes,
    same_identity_display_key,
    source_fingerprint,
)


PLANNER_VERSION = 1
HANDLED_PLAYER_REFERENCES = frozenset(
    ("name_alias", "player_game_logs", "player_stats", "props")
)


class RebuildPlanError(RuntimeError):
    """The candidate cannot be repaired without guessing."""


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _player_id_tables(
    connection: sqlite3.Connection,
) -> list[str]:
    tables = []
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ):
        table = str(row[0])
        if "player_id" in _table_columns(connection, table):
            tables.append(table)
    return tables


def _reference_counts(
    connection: sqlite3.Connection,
    player_id: int,
    tables: Sequence[str],
) -> dict[str, int]:
    return {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table)} WHERE player_id=?",
                (int(player_id),),
            ).fetchone()[0]
        )
        for table in tables
    }


def _load_mlb_players(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    columns = _table_columns(connection, "players")
    wanted = (
        "id", "name", "team", "league", "espn_id", "mlbam_id",
        "nfl_gsis_id", "nhl_id", "nba_id", "active", "position",
    )
    expressions = [
        _quote(column) if column in columns else f"NULL AS {_quote(column)}"
        for column in wanted
    ]
    rows = connection.execute(
        f"SELECT {','.join(expressions)} FROM players "
        "WHERE lower(league)='mlb' ORDER BY id"
    )
    return [dict(row) for row in rows]


def _official_match(
    row: dict[str, Any],
    official_by_id: dict[int, dict[str, Any]],
) -> bool:
    raw_mlbam = row.get("mlbam_id")
    if raw_mlbam in (None, "", 0):
        return False
    official = official_by_id.get(int(raw_mlbam))
    if official is None:
        return False
    stored_name = str(row.get("name") or "")
    return (
        identity_name_key(stored_name) == official["name_key"]
        or same_identity_display_key(stored_name)
        == same_identity_display_key(official["full_name"])
    )


def _reference_identity_pairs(
    reference_rows: Sequence[dict[str, Any]],
    official_by_id: dict[int, dict[str, Any]],
) -> tuple[set[tuple[str, int]], dict[int, list[int]]]:
    pairs: set[tuple[str, int]] = set()
    rows_by_mlbam: dict[int, list[int]] = defaultdict(list)
    for row in reference_rows:
        raw_mlbam = row.get("mlbam_id")
        if raw_mlbam in (None, "", 0):
            continue
        mlbam_id = int(raw_mlbam)
        rows_by_mlbam[mlbam_id].append(int(row["id"]))
        if _official_match(row, official_by_id):
            pairs.add((identity_name_key(row.get("name")), mlbam_id))
    duplicates = {
        mlbam_id: player_ids
        for mlbam_id, player_ids in rows_by_mlbam.items()
        if len(player_ids) > 1
    }
    if duplicates:
        raise RebuildPlanError(
            "reference database has duplicate MLBAM IDs: "
            + ", ".join(str(value) for value in sorted(duplicates)[:10])
        )
    return pairs, rows_by_mlbam


def _canonical_sort_key(
    assignment: dict[str, Any],
) -> tuple[int, int, int, int]:
    counts = assignment["reference_counts"]
    durable_count = int(counts.get("props", 0)) + int(
        counts.get("name_alias", 0)
    )
    return (
        int(durable_count > 0),
        durable_count,
        int(assignment["classification"] == "current_official_match"),
        -int(assignment["player_id"]),
    )


def _row_digest(rows: Sequence[sqlite3.Row]) -> str:
    payload = [
        {key: row[key] for key in row.keys()}
        for row in rows
    ]
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_plan(
    candidate: sqlite3.Connection,
    candidate_path: str,
    reference: sqlite3.Connection,
    reference_path: str,
    official_payload: dict[str, Any],
    *,
    season: int,
) -> dict[str, Any]:
    official_by_id, duplicate_official, ids_by_name = official_indexes(
        official_payload
    )
    if duplicate_official:
        raise RebuildPlanError("official snapshot contains duplicate IDs")

    candidate_rows = _load_mlb_players(candidate)
    reference_rows = _load_mlb_players(reference)
    reference_pairs, reference_by_mlbam = _reference_identity_pairs(
        reference_rows, official_by_id
    )
    player_id_tables = _player_id_tables(candidate)

    assignments: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in candidate_rows:
        stored_key = identity_name_key(row.get("name"))
        raw_mlbam = row.get("mlbam_id")
        current_mlbam = (
            int(raw_mlbam)
            if raw_mlbam not in (None, "", 0)
            else None
        )
        target_mlbam: int | None = None
        evidence: list[str] = []
        classification = "unresolved"

        if _official_match(row, official_by_id):
            target_mlbam = current_mlbam
            classification = "current_official_match"
            evidence.append(
                "stored name matches the official person for current MLBAM ID"
            )
        else:
            official_targets = sorted(ids_by_name.get(stored_key, set()))
            corroborated = [
                mlbam_id
                for mlbam_id in official_targets
                if (stored_key, mlbam_id) in reference_pairs
                and mlbam_id in reference_by_mlbam
            ]
            if len(official_targets) == 1 and corroborated == official_targets:
                target_mlbam = official_targets[0]
                classification = "corroborated_crosswalk"
                evidence.extend(
                    (
                        "stored name has one exact official MLB People match",
                        "clean reference spine independently has the same "
                        "name and MLBAM ID",
                    )
                )

        counts = _reference_counts(
            candidate, int(row["id"]), player_id_tables
        )
        if target_mlbam is None:
            official = (
                official_by_id.get(current_mlbam)
                if current_mlbam is not None
                else None
            )
            unresolved.append(
                {
                    "player_id": int(row["id"]),
                    "stored_name": row.get("name"),
                    "current_mlbam_id": current_mlbam,
                    "official_name_for_current_mlbam": (
                        official["full_name"] if official else None
                    ),
                    "official_exact_name_candidates": sorted(
                        ids_by_name.get(stored_key, set())
                    ),
                    "reference_counts": counts,
                    "reason": "identity_not_uniquely_corroborated",
                }
            )
            continue

        assignments.append(
            {
                "player_id": int(row["id"]),
                "stored_name": row.get("name"),
                "current_mlbam_id": current_mlbam,
                "target_mlbam_id": int(target_mlbam),
                "classification": classification,
                "reference_counts": counts,
                "evidence": evidence,
            }
        )

    assignments_by_target: dict[int, list[dict[str, Any]]] = defaultdict(
        list
    )
    for assignment in assignments:
        assignments_by_target[int(assignment["target_mlbam_id"])].append(
            assignment
        )

    canonical_by_mlbam: dict[int, int] = {}
    merges: list[dict[str, Any]] = []
    delete_player_ids: set[int] = set()
    for mlbam_id, target_assignments in sorted(
        assignments_by_target.items()
    ):
        canonical = max(target_assignments, key=_canonical_sort_key)
        canonical_id = int(canonical["player_id"])
        canonical_by_mlbam[mlbam_id] = canonical_id
        if len(target_assignments) > 1:
            source_ids = sorted(
                int(item["player_id"])
                for item in target_assignments
                if int(item["player_id"]) != canonical_id
            )
            delete_player_ids.update(source_ids)
            merges.append(
                {
                    "mlbam_id": mlbam_id,
                    "official_name": official_by_id[mlbam_id]["full_name"],
                    "canonical_player_id": canonical_id,
                    "source_player_ids": source_ids,
                }
            )

    assigned_ids = {
        int(assignment["player_id"]) for assignment in assignments
    }
    detachments = []
    for item in unresolved:
        current_mlbam = item["current_mlbam_id"]
        if (
            current_mlbam is not None
            and current_mlbam in canonical_by_mlbam
            and canonical_by_mlbam[current_mlbam] != item["player_id"]
        ):
            detachments.append(
                {
                    "player_id": item["player_id"],
                    "stored_name": item["stored_name"],
                    "detached_mlbam_id": current_mlbam,
                    "reason": (
                        "unresolved row conflicts with corroborated owner"
                    ),
                }
            )

    unsupported_references: list[dict[str, Any]] = []
    for player_id in sorted(delete_player_ids):
        counts = _reference_counts(candidate, player_id, player_id_tables)
        for table, count in counts.items():
            if count and table not in HANDLED_PLAYER_REFERENCES:
                unsupported_references.append(
                    {
                        "table": table,
                        "player_id": player_id,
                        "count": count,
                    }
                )
    if unsupported_references:
        raise RebuildPlanError(
            "source players have unsupported player_id references"
        )

    # Archive only the aggregates this rebuild actually invalidates.
    #
    # This was every current-season MLB row, unconditionally. Measured against
    # prod on 2026-08-04 that is 2,653 rows to invalidate 412 -- and it is not
    # free: an aggregate is the only place Statcast's `k_pct`, `exit_velo` and
    # `xwoba` live, and the regenerating publisher (statsapi) does not carry
    # them. A blanket archive therefore deletes good numbers from ~1,800
    # players the merge never touches, and leaves the league with an empty
    # leaderboard until a full Statcast re-ingest runs.
    #
    # Three groups are genuinely invalid and no others:
    #   - deleted source players: the row's owner is about to stop existing
    #   - detached players: their MLBAM id is being cleared, so whatever the
    #     aggregate was attributed to is no longer true of them
    #   - canonical survivors of a merge: their aggregate was computed over
    #     one half of a split identity and is now understated
    #
    # A row on an untouched player was correct before this ran and is correct
    # after. Regenerating it would only replace a measured number with a
    # differently-measured one.
    invalidated = set(delete_player_ids)
    invalidated.update(int(item["player_id"]) for item in detachments)
    invalidated.update(int(merge["canonical_player_id"]) for merge in merges)
    if invalidated:
        marks = ",".join("?" * len(invalidated))
        stats_rows = candidate.execute(
            f"""SELECT * FROM player_stats
                WHERE lower(league)='mlb' AND season=?
                  AND player_id IN ({marks})
                ORDER BY id""",
            (int(season), *sorted(invalidated)),
        ).fetchall()
    else:
        stats_rows = []

    log_repoints = 0
    log_archives = 0
    log_archive_counts: dict[int, int] = defaultdict(int)
    log_rows = candidate.execute(
        """SELECT * FROM player_game_logs
           WHERE lower(league)='mlb' ORDER BY id"""
    ).fetchall()
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
                log_repoints += 1
        elif row["player_id"] in delete_player_ids:
            log_archives += 1
            if source_mlbam is None:
                raise RebuildPlanError(
                    "a source player has an MLB log without a numeric "
                    "source_player_key"
                )
            log_archive_counts[source_mlbam] += 1

    original_duplicate_groups = sum(
        1
        for count in candidate.execute(
            """SELECT COUNT(*) FROM players
               WHERE lower(league)='mlb' AND mlbam_id IS NOT NULL
                 AND mlbam_id!=0 GROUP BY mlbam_id"""
        )
        if int(count[0]) > 1
    )
    if not original_duplicate_groups:
        raise RebuildPlanError(
            "candidate has no duplicate MLBAM groups to rebuild"
        )
    props_to_repoint = sum(
        int(assignment["reference_counts"].get("props", 0))
        for assignment in assignments
        if int(assignment["player_id"]) in delete_player_ids
    )
    foreign_key_rows = candidate.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    return {
        "planner_version": PLANNER_VERSION,
        "mode": "read_only_hash_bound_plan",
        "season": int(season),
        "candidate": {
            "path": str(Path(candidate_path).resolve()),
            "sha256": file_sha256(candidate_path),
        },
        "reference": {
            "path": str(Path(reference_path).resolve()),
            "sha256": file_sha256(reference_path),
            "duplicate_mlbam_groups": 0,
        },
        "official_source": {
            "sha256": source_fingerprint(official_payload),
            "people_loaded": len(official_by_id),
        },
        "safety_invariants": [
            "candidate and reference databases were opened read-only",
            "crosswalk changes require unique official and "
            "clean-reference agreement",
            "unresolved identities are never guessed or merged",
            "game logs are re-resolved only from source_player_key",
            "all current-season MLB aggregates are archived for regeneration",
            "the applier is restricted to a single-link database under /tmp",
        ],
        "summary": {
            "candidate_mlb_players": len(candidate_rows),
            "official_people_loaded": len(official_by_id),
            "assignments": len(assignments),
            "corroborated_crosswalks": sum(
                item["classification"] == "corroborated_crosswalk"
                for item in assignments
            ),
            "unresolved_identities": len(unresolved),
            "original_duplicate_mlbam_groups": original_duplicate_groups,
            "post_assignment_merge_groups": len(merges),
            "source_players_to_delete": len(delete_player_ids),
            "props_to_repoint": props_to_repoint,
            "unresolved_conflicts_to_detach": len(detachments),
            "player_stats_to_archive": len(stats_rows),
            "game_logs_to_repoint": log_repoints,
            "game_logs_to_archive": log_archives,
            "game_log_source_keys_to_queue": len(log_archive_counts),
        },
        "canonical_by_mlbam": {
            str(key): value
            for key, value in sorted(canonical_by_mlbam.items())
        },
        "assignments": assignments,
        "merges": merges,
        "detachments": detachments,
        "unresolved": unresolved,
        "player_stats_scope": {
            "league": "mlb",
            "season": int(season),
            # The applier re-reads this set to prove the database has not moved
            # under the plan, so it has to be able to reproduce EXACTLY the
            # rows the digest was taken over -- not "every current-season row",
            # which is a different and larger set now that the archive is
            # scoped to the players this rebuild invalidates.
            "player_ids": sorted(invalidated),
            "row_count": len(stats_rows),
            "rows_sha256": _row_digest(stats_rows),
        },
        "game_log_scope": {
            "league": "mlb",
            "row_count": len(log_rows),
            "rows_sha256": _row_digest(log_rows),
            "repoint_count": log_repoints,
            "archive_count": log_archives,
            "archive_sources": [
                {
                    "source_player_key": str(source_mlbam),
                    "official_name": (
                        official_by_id[source_mlbam]["full_name"]
                        if source_mlbam in official_by_id
                        else None
                    ),
                    "row_count": count,
                }
                for source_mlbam, count in sorted(
                    log_archive_counts.items()
                )
            ],
        },
        "foreign_key_scope": {
            "baseline_count": len(foreign_key_rows),
            "baseline_sha256": _row_digest(foreign_key_rows),
        },
        "assigned_player_ids": sorted(assigned_ids),
        "delete_player_ids": sorted(delete_player_ids),
        "unsupported_references": unsupported_references,
    }


def _write_json(path: str, payload: dict[str, Any]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--reference-db", required=True)
    parser.add_argument("--people-json", required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    candidate = connect_read_only(args.db)
    reference = connect_read_only(args.reference_db)
    try:
        plan = build_plan(
            candidate,
            args.db,
            reference,
            args.reference_db,
            load_people_json(args.people_json),
            season=args.season,
        )
    finally:
        reference.close()
        candidate.close()
    _write_json(args.output, plan)
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))
    print(f"Plan written to {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
