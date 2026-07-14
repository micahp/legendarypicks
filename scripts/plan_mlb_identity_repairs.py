#!/usr/bin/env python3
"""Build a read-only proposal for repairing MLB player identity crosswalks.

This script never mutates the database and has no apply mode. It compares the
current-season MLB player population with an authoritative MLB Stats API people
snapshot, then proposes only corrections supported by a unique exact-name match
to another authoritative MLBAM row already present in the spine. Ambiguous or
incomplete cases are placed in a review queue.

Typical usage:

  python scripts/plan_mlb_identity_repairs.py \
    --db /tmp/picks.identity-audit.db \
    --season 2026 \
    --fetch-official \
    --official-snapshot-output /tmp/mlb-people-2026.json \
    --output /tmp/mlb-identity-repair-plan.json

For a deterministic offline rerun, replace --fetch-official with:

  --people-json /tmp/mlb-people-2026.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


MLB_PEOPLE_ENDPOINT = "https://statsapi.mlb.com/api/v1/people"
PLANNER_VERSION = 1
REFERENCE_TABLES = ("player_stats", "player_game_logs", "props", "predictions")


def identity_name_key(value: str | None) -> str:
    """Normalize display variation without collapsing suffixes or nicknames."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def same_identity_display_key(value: str | None) -> str:
    """Compare one source ID to itself while tolerating only terminal suffix drift.

    Suffixes stay significant in identity_name_key and therefore can never make a
    cross-ID repair proposal match. This narrower key exists only to keep benign
    display variation such as "Victor Scott" versus "Victor Scott II" out of the
    corruption count for the same authoritative MLBAM ID.
    """
    key = identity_name_key(value)
    return re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", key).strip()


def clean_display_name(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def batched(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def connect_read_only(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve(strict=True)
    uri = f"file:{urllib.parse.quote(str(path))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(connection, table):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def load_players(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT id, name, team, espn_id, mlbam_id, active, position
           FROM players
           WHERE league='mlb'
           ORDER BY id"""
    ).fetchall()
    return [dict(row) for row in rows]


def load_population(
    connection: sqlite3.Connection, season: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT p.id, p.name, p.team, p.espn_id, p.mlbam_id, p.active,
                  p.position, COUNT(DISTINCT ps.id) AS current_stat_rows
           FROM players p
           JOIN player_stats ps ON ps.player_id=p.id
           WHERE p.league='mlb' AND ps.league='mlb' AND ps.season=?
           GROUP BY p.id
           ORDER BY p.id""",
        (season,),
    ).fetchall()
    return [dict(row) for row in rows]


def load_reference_counts(
    connection: sqlite3.Connection, player_ids: Sequence[int]
) -> dict[int, dict[str, int]]:
    counts = {player_id: {table: 0 for table in REFERENCE_TABLES} for player_id in player_ids}
    for table in REFERENCE_TABLES:
        columns = table_columns(connection, table)
        if "player_id" not in columns:
            continue
        for id_batch in batched(list(player_ids), 700):
            placeholders = ",".join("?" for _ in id_batch)
            query = (
                f"SELECT player_id, COUNT(*) AS n FROM {table} "
                f"WHERE player_id IN ({placeholders}) GROUP BY player_id"
            )
            for row in connection.execute(query, tuple(id_batch)):
                counts[int(row["player_id"])][table] = int(row["n"])
    return counts


def fetch_official_people(
    mlbam_ids: Sequence[int], batch_size: int = 100, retries: int = 3
) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    for batch_number, id_batch in enumerate(batched(list(mlbam_ids), batch_size), start=1):
        query = urllib.parse.urlencode({"personIds": ",".join(str(value) for value in id_batch)})
        url = f"{MLB_PEOPLE_ENDPOINT}?{query}"
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "LegendaryPicks-identity-audit/1.0"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                batch_people = payload.get("people")
                if not isinstance(batch_people, list):
                    raise ValueError("MLB people response did not contain a people list")
                people.extend(batch_people)
                last_error = None
                break
            except Exception as exc:  # pragma: no cover - network timing varies
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.5 * (2**attempt))
        if last_error is not None:
            raise RuntimeError(
                f"MLB people batch {batch_number} failed after {retries} attempts: {last_error}"
            ) from last_error
    return {
        "source": MLB_PEOPLE_ENDPOINT,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "requested_person_ids": list(mlbam_ids),
        "people": people,
    }


def load_people_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return {"people": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("people"), list):
        raise ValueError("people JSON must be a list or an object containing a people list")
    return payload


def source_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def official_indexes(
    payload: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]], dict[str, set[int]]]:
    by_id: dict[int, dict[str, Any]] = {}
    duplicate_ids: dict[int, list[str]] = defaultdict(list)
    ids_by_name: dict[str, set[int]] = defaultdict(set)

    for raw_person in payload.get("people", []):
        if not isinstance(raw_person, dict) or raw_person.get("id") is None:
            continue
        try:
            mlbam_id = int(raw_person["id"])
        except (TypeError, ValueError):
            continue
        full_name = clean_display_name(raw_person.get("fullName"))
        if mlbam_id in by_id:
            duplicate_ids[mlbam_id].append(full_name)
            continue
        person = {
            "id": mlbam_id,
            "full_name": full_name,
            "name_key": identity_name_key(full_name),
        }
        by_id[mlbam_id] = person
        if person["name_key"]:
            ids_by_name[person["name_key"]].add(mlbam_id)
    return by_id, dict(duplicate_ids), ids_by_name


def db_snapshot(connection: sqlite3.Connection, db_path: str) -> dict[str, Any]:
    path = Path(db_path).expanduser().resolve(strict=True)
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "schema_version": connection.execute("PRAGMA schema_version").fetchone()[0],
        "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        "query_only": bool(connection.execute("PRAGMA query_only").fetchone()[0]),
    }


def build_plan(
    connection: sqlite3.Connection,
    db_path: str,
    season: int,
    official_payload: dict[str, Any],
    source_label: str,
) -> dict[str, Any]:
    players = load_players(connection)
    population = load_population(connection, season)
    all_player_ids = [int(row["id"]) for row in players]
    reference_counts = load_reference_counts(connection, all_player_ids)

    official_by_id, duplicate_official_ids, official_ids_by_name = official_indexes(
        official_payload
    )
    players_by_id = {int(row["id"]): row for row in players}
    rows_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_by_mlbam: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in players:
        rows_by_name[identity_name_key(row.get("name"))].append(row)
        if row.get("mlbam_id") not in (None, 0, ""):
            rows_by_mlbam[int(row["mlbam_id"])].append(row)

    duplicate_db_mlbam = {
        mlbam_id: rows for mlbam_id, rows in rows_by_mlbam.items() if len(rows) > 1
    }
    proposals: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    unchanged = 0
    equivalent_display_variants = 0
    equivalent_display_variant_rows: list[dict[str, Any]] = []
    mismatches = 0
    population_without_mlbam = 0

    for row in population:
        player_id = int(row["id"])
        raw_mlbam = row.get("mlbam_id")
        if raw_mlbam in (None, 0, ""):
            population_without_mlbam += 1
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "population_player_missing_mlbam_id",
                    "player_id": player_id,
                    "stored_name": row.get("name"),
                }
            )
            continue

        mlbam_id = int(raw_mlbam)
        stored_name = clean_display_name(row.get("name"))
        stored_key = identity_name_key(stored_name)

        if mlbam_id in duplicate_db_mlbam:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "duplicate_database_mlbam_id",
                    "player_id": player_id,
                    "mlbam_id": mlbam_id,
                    "database_player_ids": [
                        int(candidate["id"]) for candidate in duplicate_db_mlbam[mlbam_id]
                    ],
                }
            )
            continue
        if mlbam_id in duplicate_official_ids:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "duplicate_official_mlbam_id",
                    "player_id": player_id,
                    "mlbam_id": mlbam_id,
                    "official_names": duplicate_official_ids[mlbam_id],
                }
            )
            continue

        official = official_by_id.get(mlbam_id)
        if official is None:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "official_person_missing",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                }
            )
            continue
        if not official["name_key"]:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "official_person_name_blank",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                }
            )
            continue
        if stored_key == official["name_key"]:
            unchanged += 1
            continue
        if same_identity_display_key(stored_name) == same_identity_display_key(
            official["full_name"]
        ):
            equivalent_display_variants += 1
            equivalent_display_variant_rows.append(
                {
                    "player_id": player_id,
                    "mlbam_id": mlbam_id,
                    "stored_name": stored_name,
                    "official_name": official["full_name"],
                }
            )
            continue

        mismatches += 1
        exact_official_ids = sorted(official_ids_by_name.get(stored_key, set()))
        exact_name_rows = rows_by_name.get(stored_key, [])
        espn_anchor_rows = [candidate for candidate in exact_name_rows if candidate.get("espn_id")]

        if not row.get("espn_id"):
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "mismatched_row_has_no_espn_anchor",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                    "official_name_for_current_mlbam": official["full_name"],
                }
            )
            continue
        if len(espn_anchor_rows) != 1 or int(espn_anchor_rows[0]["id"]) != player_id:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "stored_name_not_uniquely_anchored_by_espn",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                    "espn_anchor_player_ids": [
                        int(candidate["id"]) for candidate in espn_anchor_rows
                    ],
                }
            )
            continue
        if len(exact_official_ids) != 1:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "stored_name_not_unique_in_authoritative_population",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                    "authoritative_candidate_mlbam_ids": exact_official_ids,
                }
            )
            continue

        correct_mlbam_id = exact_official_ids[0]
        target_rows = rows_by_mlbam.get(correct_mlbam_id, [])
        if len(target_rows) != 1:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "authoritative_target_not_unique_in_database",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "current_mlbam_id": mlbam_id,
                    "correct_mlbam_id": correct_mlbam_id,
                    "target_player_ids": [int(candidate["id"]) for candidate in target_rows],
                }
            )
            continue

        target_row = target_rows[0]
        target_player_id = int(target_row["id"])
        if target_player_id == player_id:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "authoritative_target_equals_mismatched_row",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "mlbam_id": mlbam_id,
                }
            )
            continue
        if identity_name_key(target_row.get("name")) != stored_key:
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "authoritative_target_database_name_disagrees",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "correct_mlbam_id": correct_mlbam_id,
                    "target_player_id": target_player_id,
                    "target_stored_name": target_row.get("name"),
                }
            )
            continue
        if target_row.get("espn_id") and str(target_row["espn_id"]) != str(row["espn_id"]):
            review_queue.append(
                {
                    "scope": "player_repair",
                    "reason": "authoritative_target_has_conflicting_espn_id",
                    "player_id": player_id,
                    "stored_name": stored_name,
                    "espn_id": row.get("espn_id"),
                    "target_player_id": target_player_id,
                    "target_espn_id": target_row.get("espn_id"),
                }
            )
            continue

        displaced_name_key = official["name_key"]
        displaced_candidates = [
            candidate
            for candidate in rows_by_name.get(displaced_name_key, [])
            if int(candidate["id"]) != player_id
        ]
        proposal = {
            "action": "consolidate_exact_authoritative_crosswalk",
            "canonical_player_id": player_id,
            "source_player_id": target_player_id,
            "stored_name": stored_name,
            "espn_id": str(row["espn_id"]),
            "correct_mlbam_id": correct_mlbam_id,
            "correct_official_name": official_by_id[correct_mlbam_id]["full_name"],
            "displaced_mlbam_id": mlbam_id,
            "displaced_official_name": official["full_name"],
            "canonical_reference_counts": reference_counts[player_id],
            "source_reference_counts": reference_counts[target_player_id],
            "displaced_identity_candidate_player_ids": [
                int(candidate["id"]) for candidate in displaced_candidates
            ],
            "evidence": [
                "canonical row is the only exact-name ESPN-anchored row",
                "correct MLBAM ID is the only authoritative exact-name match",
                "correct MLBAM ID exists on exactly one separate database row with the same name",
            ],
            "required_followups": [
                "review this proposal before any database mutation",
                "apply only on a database copy in one transaction",
                "preserve the ESPN-anchored row as canonical",
                "re-resolve source-keyed game logs after crosswalk correction",
                "regenerate MLB player_stats from authoritative sources",
                "invalidate and regenerate affected predictions",
                "resolve or queue the displaced official identity; never create it silently",
            ],
        }
        proposals.append(proposal)

        if not displaced_candidates:
            displaced_reason = "displaced_official_identity_not_represented"
        elif len(displaced_candidates) == 1:
            displaced_reason = "displaced_official_identity_candidate_requires_review"
        else:
            displaced_reason = "displaced_official_identity_ambiguous"
        review_queue.append(
            {
                "scope": "displaced_identity",
                "reason": displaced_reason,
                "caused_by_player_id": player_id,
                "displaced_mlbam_id": mlbam_id,
                "displaced_official_name": official["full_name"],
                "candidate_player_ids": [
                    int(candidate["id"]) for candidate in displaced_candidates
                ],
            }
        )

    proposal_targets: dict[int, list[int]] = defaultdict(list)
    for proposal in proposals:
        proposal_targets[int(proposal["correct_mlbam_id"])].append(
            int(proposal["canonical_player_id"])
        )
    conflicting_targets = {
        mlbam_id: player_ids
        for mlbam_id, player_ids in proposal_targets.items()
        if len(player_ids) > 1
    }
    if conflicting_targets:
        safe_proposals = []
        for proposal in proposals:
            target_id = int(proposal["correct_mlbam_id"])
            if target_id in conflicting_targets:
                review_queue.append(
                    {
                        "scope": "player_repair",
                        "reason": "multiple_proposals_target_same_mlbam_id",
                        "player_id": proposal["canonical_player_id"],
                        "correct_mlbam_id": target_id,
                        "conflicting_player_ids": conflicting_targets[target_id],
                    }
                )
            else:
                safe_proposals.append(proposal)
        proposals = safe_proposals

    requested_ids = {
        int(row["mlbam_id"])
        for row in players
        if row.get("mlbam_id") not in (None, 0, "")
    }
    missing_official_ids = sorted(requested_ids - set(official_by_id))
    queue_reasons: dict[str, int] = defaultdict(int)
    for item in review_queue:
        queue_reasons[str(item["reason"])] += 1

    summary = {
        "season_population_players": len(population),
        "population_without_mlbam_id": population_without_mlbam,
        "database_mlbam_ids_requested": len(requested_ids),
        "official_people_loaded": len(official_by_id),
        "unchanged_exact_identity_matches": unchanged,
        "equivalent_suffix_only_display_variants": equivalent_display_variants,
        "stored_name_vs_official_name_mismatches": mismatches,
        "safe_crosswalk_proposals": len(proposals),
        "review_queue_items": len(review_queue),
        "review_queue_reasons": dict(sorted(queue_reasons.items())),
        "duplicate_database_mlbam_groups": len(duplicate_db_mlbam),
        "duplicate_official_mlbam_ids": len(duplicate_official_ids),
        "missing_official_mlbam_ids": len(missing_official_ids),
        "ready_for_apply_planner": False,
        "ready_for_apply_reason": (
            "This artifact is proposal-only. A separate reviewed applier must be tested "
            "on a database copy in one transaction before any shared-database mutation."
        ),
    }

    return {
        "planner_version": PLANNER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "proposal_only_read_only",
        "database": db_snapshot(connection, db_path),
        "population_rule": (
            "distinct MLB players referenced by player_stats for the requested season"
        ),
        "season": season,
        "authoritative_source": {
            "label": source_label,
            "endpoint": MLB_PEOPLE_ENDPOINT,
            "sha256": source_fingerprint(official_payload),
        },
        "safety_invariants": [
            "database opened with SQLite mode=ro and PRAGMA query_only=ON",
            "no apply flag or mutation path exists in this planner",
            "suffixes are preserved during exact-name identity matching",
            "suffix-only variation is tolerated only when comparing the same MLBAM ID",
            "every proposal requires one ESPN anchor and one unique authoritative MLBAM target",
            "ambiguous and missing identities are queued, never guessed or inserted",
            "player_stats must be regenerated after identity correction",
        ],
        "summary": summary,
        "equivalent_suffix_only_display_variants": equivalent_display_variant_rows,
        "missing_official_mlbam_ids": missing_official_ids,
        "duplicate_database_mlbam_groups": {
            str(mlbam_id): [int(row["id"]) for row in rows]
            for mlbam_id, rows in sorted(duplicate_db_mlbam.items())
        },
        "duplicate_official_mlbam_ids": {
            str(mlbam_id): names
            for mlbam_id, names in sorted(duplicate_official_ids.items())
        },
        "proposals": proposals,
        "review_queue": review_queue,
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite database to inspect read-only")
    parser.add_argument("--season", required=True, type=int)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fetch-official", action="store_true")
    source.add_argument("--people-json", help="Previously saved authoritative people snapshot")
    parser.add_argument("--official-snapshot-output")
    parser.add_argument("--output", required=True, help="Proposal JSON destination")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    connection = connect_read_only(args.db)
    try:
        players = load_players(connection)
        mlbam_ids = sorted(
            {
                int(row["mlbam_id"])
                for row in players
                if row.get("mlbam_id") not in (None, 0, "")
            }
        )
        if args.fetch_official:
            official_payload = fetch_official_people(mlbam_ids)
            source_label = "live MLB Stats API people endpoint"
            if args.official_snapshot_output:
                write_json(args.official_snapshot_output, official_payload)
        else:
            official_payload = load_people_json(args.people_json)
            source_label = str(
                official_payload.get("source")
                or Path(args.people_json).expanduser().resolve()
            )

        plan = build_plan(
            connection=connection,
            db_path=args.db,
            season=args.season,
            official_payload=official_payload,
            source_label=source_label,
        )
        write_json(args.output, plan)
    finally:
        connection.close()

    summary = plan["summary"]
    print(f"Proposal written to {Path(args.output).expanduser().resolve()}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
