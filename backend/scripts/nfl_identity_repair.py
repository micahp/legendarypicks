#!/usr/bin/env python3
"""Plan NFL GSIS repairs from nflverse's complete player register.

Planning is read-only. ``apply-copy`` is deliberately restricted to a disposable
copy under /tmp; it refuses the database the plan was built from, picks.db, and
picks.dev.db. No names are used to discover a mapping: ESPN/ESB and other
publisher IDs do that. A source-published name is only a consistency gate.

Examples:
  python scripts/nfl_identity_repair.py plan --db /tmp/picks.dev.before.db \
    --register /tmp/players.parquet --output /tmp/nfl-id-plan.json
  python scripts/nfl_identity_repair.py apply-copy --copy-db /tmp/picks.identity.copy.db \
    --register /tmp/players.parquet --plan /tmp/nfl-id-plan.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from audit_league_stats.identity import _identity_name_key  # noqa: E402

REGISTER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet"
)
REGISTER_ID_COLUMNS = (
    "gsis_id", "espn_id", "esb_id", "nfl_id", "pfr_id", "pff_id", "otc_id", "smart_id"
)
ALTERNATE_SOURCES = {
    "espn_id": "espn",
    "esb_id": "esb",
    "nfl_id": "nfl",
    "pfr_id": "pfr",
    "pff_id": "pff",
    "otc_id": "otc",
    "smart_id": "nfl_smart",
}
PROTECTED_TABLES = ("player_game_logs", "player_game_shares", "player_stats", "props")
LEGACY_SOURCE = "legacy_nfl_gsis_id"
PLAN_VERSION = 1


class RepairError(RuntimeError):
    """The source, plan, or destination failed a repair invariant."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normal_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    value = str(value).strip()
    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]
    return value or None


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _connect_read_only(path: str) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve(strict=True)
    connection = sqlite3.connect("file:{}?mode=ro".format(quote(str(resolved)), safe="/"),
                                 uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> List[str]:
    return [str(row[1]) for row in connection.execute('PRAGMA table_info("{}")'.format(table))]


def _row_order(connection: sqlite3.Connection, table: str) -> str:
    columns = list(connection.execute('PRAGMA table_info("{}")'.format(table)))
    primary = [str(row[1]) for row in sorted(columns, key=lambda row: int(row[5]) if row[5] else 999)
               if int(row[5]) > 0]
    if primary:
        return ",".join('"{}"'.format(column) for column in primary)
    return "rowid"


def _table_fingerprint(connection: sqlite3.Connection, table: str) -> str:
    columns = _table_columns(connection, table)
    if not columns:
        return "ABSENT"
    quoted = ",".join('"{}"'.format(column) for column in columns)
    digest = hashlib.sha256()
    cursor = connection.execute(
        'SELECT {} FROM "{}" ORDER BY {}'.format(quoted, table, _row_order(connection, table))
    )
    for row in cursor:
        payload = json.dumps(list(row), ensure_ascii=False, separators=(",", ":"), default=str)
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _player_id_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute(
            "SELECT id,name,espn_id,nfl_gsis_id,position FROM players "
            "WHERE league='nfl' ORDER BY id"):
        digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":"))
                      .encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _reference_columns(connection: sqlite3.Connection) -> List[Tuple[str, str]]:
    found = []
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        if table == "players":
            continue
        columns = set(_table_columns(connection, table))
        foreign_keys = {row[3] for row in connection.execute(
            'PRAGMA foreign_key_list("{}")'.format(table)) if row[2] == "players"}
        for column in sorted(columns):
            if column in foreign_keys or column == "player_id":
                found.append((table, column))
    return sorted(found)


def _reference_counts(connection: sqlite3.Connection, player_ids: Sequence[int]
                      ) -> Dict[str, Dict[str, int]]:
    output: Dict[str, Dict[str, int]] = {str(player_id): {} for player_id in player_ids}
    for table, column in _reference_columns(connection):
        for start in range(0, len(player_ids), 400):
            batch = list(player_ids[start:start + 400])
            if not batch:
                continue
            marks = ",".join("?" for _ in batch)
            query = ('SELECT "{col}",COUNT(*) FROM "{table}" '
                     'WHERE "{col}" IN ({marks}) GROUP BY "{col}"').format(
                         col=column, table=table, marks=marks)
            for player_id, count in connection.execute(query, batch):
                if player_id is not None and count:
                    output[str(int(player_id))][table] = int(count)
    return output


def _load_register(path: str) -> List[Dict[str, Any]]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RepairError("pyarrow is required to read nflverse players.parquet") from exc
    columns = list(REGISTER_ID_COLUMNS) + ["display_name", "position"]
    table = parquet.ParquetFile(path).read(columns=columns)
    rows = table.to_pylist()
    if not rows:
        raise RepairError("nflverse published an empty player register")
    if any(not _normal_id(row.get("gsis_id")) or not row.get("display_name") for row in rows):
        raise RepairError("register contains a row without gsis_id or display_name")
    return rows


def _indexes(register_rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, List[dict]]]:
    indexes: Dict[str, Dict[str, List[dict]]] = {
        column: defaultdict(list) for column in REGISTER_ID_COLUMNS
    }
    for row in register_rows:
        for column in REGISTER_ID_COLUMNS:
            key = _normal_id(row.get(column))
            if key:
                indexes[column][key].append(row)
    return indexes


def _candidate_rows(player: sqlite3.Row, indexes: Dict[str, Dict[str, List[dict]]],
                    include_legacy_key: bool = True
                    ) -> Tuple[List[dict], List[str], List[str]]:
    candidates: List[dict] = []
    methods: List[str] = []
    ambiguous: List[str] = []
    local_espn = _normal_id(player["espn_id"])
    if local_espn:
        matches = indexes["espn_id"].get(local_espn, [])
        if len(matches) == 1:
            candidates.append(matches[0])
            methods.append("espn_id")
        elif len(matches) > 1:
            ambiguous.append("espn_id")

    if include_legacy_key:
        legacy_key = _normal_id(player["nfl_gsis_id"])
        for column in REGISTER_ID_COLUMNS[1:]:
            matches = indexes[column].get(legacy_key, []) if legacy_key else []
            if len(matches) == 1:
                candidates.append(matches[0])
                methods.append(column)
            elif len(matches) > 1:
                ambiguous.append(column)
    return candidates, methods, ambiguous


def _source_for_legacy_key(legacy_key: str, indexes: Dict[str, Dict[str, List[dict]]],
                           target_gsis: Optional[str]) -> str:
    sources = []
    for column in REGISTER_ID_COLUMNS[1:]:
        matches = indexes[column].get(legacy_key, [])
        if len(matches) == 1 and _normal_id(matches[0].get("gsis_id")) == target_gsis:
            sources.append(ALTERNATE_SOURCES[column])
    if len(sources) == 1:
        return sources[0]
    return LEGACY_SOURCE


def _current_usage(connection: sqlite3.Connection) -> Tuple[Optional[int], set[int]]:
    latest_by_table = {}
    for table in ("player_game_logs", "player_game_shares"):
        if not {"league", "season", "player_id"}.issubset(_table_columns(connection, table)):
            continue
        latest = connection.execute(
            'SELECT MAX(season) FROM "{}" WHERE league=\'nfl\''.format(table)
        ).fetchone()[0]
        if latest is not None:
            latest_by_table[table] = int(latest)
    if not latest_by_table:
        return None, set()
    season = max(latest_by_table.values())
    player_ids = set()
    for table, latest in latest_by_table.items():
        if latest == season:
            player_ids.update(int(row[0]) for row in connection.execute(
                'SELECT DISTINCT player_id FROM "{}" WHERE league=\'nfl\' '
                'AND season=? AND player_id IS NOT NULL'.format(table), (season,)))
    return season, player_ids


def build_plan(connection: sqlite3.Connection, db_path: str, register_path: str,
               register_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    required = {"players", "player_source_ids"}
    missing_tables = [table for table in required if not _table_exists(connection, table)]
    if missing_tables:
        raise RepairError("required tables are missing: {}".format(", ".join(missing_tables)))
    player_columns = set(_table_columns(connection, "players"))
    if not {"id", "name", "league", "espn_id", "nfl_gsis_id", "position"}.issubset(player_columns):
        raise RepairError("players is missing required NFL identity columns")
    source_columns = set(_table_columns(connection, "player_source_ids"))
    if not {"source", "league", "source_player_key", "player_id", "first_seen", "last_seen"}.issubset(source_columns):
        raise RepairError("player_source_ids does not match the crosswalk contract")

    indexes = _indexes(register_rows)
    gsis_ids = set(indexes["gsis_id"])
    register_duplicates = {
        column: sorted(key for key, rows in indexes[column].items() if len(rows) > 1)
        for column in REGISTER_ID_COLUMNS
    }
    if register_duplicates["gsis_id"]:
        raise RepairError("register contains duplicate gsis_id values")

    players = connection.execute(
        "SELECT id,name,espn_id,nfl_gsis_id,position FROM players "
        "WHERE league='nfl' ORDER BY id"
    ).fetchall()
    existing_owners: Dict[str, List[int]] = defaultdict(list)
    local_espn_owners: Dict[str, List[int]] = defaultdict(list)
    for player in players:
        if _normal_id(player["nfl_gsis_id"]):
            existing_owners[_normal_id(player["nfl_gsis_id"])].append(int(player["id"]))
        if _normal_id(player["espn_id"]):
            local_espn_owners[_normal_id(player["espn_id"])].append(int(player["id"]))

    current_season, current_ids = _current_usage(connection)
    actions: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    unchanged = 0
    counts = defaultdict(int)
    proposed_owners: Dict[str, List[int]] = defaultdict(list)

    for player in players:
        player_id = int(player["id"])
        legacy_key = _normal_id(player["nfl_gsis_id"])
        if not legacy_key:
            counts["already_null"] += 1
            continue
        candidates, methods, ambiguous = _candidate_rows(
            player, indexes, include_legacy_key=legacy_key not in gsis_ids
        )
        candidate_gsis = {_normal_id(row.get("gsis_id")) for row in candidates}
        candidate_gsis.discard(None)
        identity_key = _identity_name_key(player["name"] or "")
        matching_candidates = [row for row in candidates
                               if _identity_name_key(row.get("display_name") or "") == identity_key]
        new_gsis = None
        reason = None
        if legacy_key in gsis_ids:
            if not candidates and not ambiguous:
                counts["already_published_gsis"] += 1
                if not legacy_key.startswith("00-"):
                    counts["already_published_nonstandard_gsis"] += 1
                continue
            if not ambiguous and candidate_gsis == {legacy_key}:
                counts["already_published_gsis"] += 1
                if not legacy_key.startswith("00-"):
                    counts["already_published_nonstandard_gsis"] += 1
                continue

            # A publisher-valid value in this column can still belong to a
            # different person. Reconcile only when a unique independent source
            # ID identifies another GSIS row and both the local name and
            # position agree with that target. Otherwise preserve the current
            # value and require review rather than guessing between two valid IDs.
            if ambiguous:
                reason = "publisher identifier is not unique: " + ",".join(sorted(set(ambiguous)))
            elif len(candidate_gsis) != 1:
                reason = "stable publisher IDs do not identify one replacement GSIS ID"
            elif legacy_key in candidate_gsis:
                reason = "stable publisher IDs disagree about the target GSIS ID"
            else:
                target = next(iter(candidate_gsis))
                target_rows = [row for row in candidates
                               if _normal_id(row.get("gsis_id")) == target]
                target_name_match = [row for row in target_rows
                                     if _identity_name_key(row.get("display_name") or "") == identity_key]
                local_position = str(player["position"] or "").strip().upper()
                position_match = [row for row in target_name_match
                                  if not local_position or not str(row.get("position") or "").strip()
                                  or str(row.get("position")).strip().upper() == local_position]
                if len(target_name_match) != len(target_rows):
                    reason = "replacement stable ID target does not match the local name"
                elif len(position_match) != len(target_rows):
                    reason = "replacement stable ID target does not match the local position"
                else:
                    new_gsis = target
                    reason = "existing published GSIS belongs to another publisher identity"
                    counts["reconciled_published_gsis_conflict"] += 1
            if not new_gsis:
                blocked.append({
                    "player_id": player_id,
                    "legacy_key": legacy_key,
                    "target_gsis_id": sorted(candidate_gsis),
                    "reason": reason,
                    "other_player_ids": [],
                })
                counts["blocked_published_gsis_conflict"] += 1
                continue
        elif ambiguous:
            reason = "publisher identifier is not unique: " + ",".join(sorted(set(ambiguous)))
        elif len(candidate_gsis) > 1:
            reason = "stable publisher IDs disagree about the target GSIS ID"
        elif len(candidate_gsis) == 1 and len(matching_candidates) != len(candidates):
            reason = "stable ID bridge found, but the publisher name does not match the row"
        elif len(candidate_gsis) == 1 and candidates and new_gsis is None:
            new_gsis = next(iter(candidate_gsis))
        elif not candidates:
            reason = "no unique publisher-ID bridge in the complete register"

        methods = sorted(set(methods))
        # The old value can still have a known source type when it is preserved
        # but deliberately not promoted to GSIS (for example, a name mismatch).
        source_target = new_gsis
        if source_target is None and len(candidate_gsis) == 1:
            source_target = next(iter(candidate_gsis))
        alias_source = _source_for_legacy_key(legacy_key, indexes, source_target)
        if new_gsis:
            other_owners = [owner for owner in existing_owners.get(new_gsis, [])
                            if owner != player_id]
            if other_owners:
                blocked.append({
                    "player_id": player_id,
                    "legacy_key": legacy_key,
                    "target_gsis_id": new_gsis,
                    "reason": "target GSIS belongs to another players.id; use spine_merge",
                    "other_player_ids": other_owners,
                })
                counts["blocked_requires_spine_merge"] += 1
                continue
            same_espn_owners = [owner for owner in local_espn_owners.get(
                _normal_id(player["espn_id"]), []) if owner != player_id]
            if same_espn_owners:
                blocked.append({
                    "player_id": player_id,
                    "legacy_key": legacy_key,
                    "target_gsis_id": new_gsis,
                    "reason": "local espn_id is shared by multiple player rows",
                    "other_player_ids": same_espn_owners,
                })
                counts["blocked_duplicate_local_espn_id"] += 1
                continue
            proposed_owners[new_gsis].append(player_id)

        # Preserve the old value under its known publisher namespace when the
        # register proves one; otherwise record its exact legacy column origin.
        existing_crosswalk = connection.execute(
            "SELECT player_id FROM player_source_ids "
            "WHERE source=? AND league='nfl' AND source_player_key=?",
            (alias_source, legacy_key),
        ).fetchone()
        if existing_crosswalk and int(existing_crosswalk[0]) != player_id:
            blocked.append({
                "player_id": player_id,
                "legacy_key": legacy_key,
                "target_gsis_id": new_gsis,
                "reason": "typed source key is already owned by another player row",
                "other_player_ids": [int(existing_crosswalk[0])],
            })
            counts["blocked_crosswalk_owner_conflict"] += 1
            continue

        if new_gsis:
            counts["set_published_gsis"] += 1
            counts["bridged_by_" + "+".join(methods or ["unknown"])] += 1
            if _identity_name_key(next(row["display_name"] for row in candidates
                                       if _normal_id(row.get("gsis_id")) == new_gsis)) == identity_key:
                counts["name_consistent_bridges"] += 1
            if player["position"] and any(
                    str(row.get("position") or "").strip().upper()
                    != str(player["position"]).strip().upper()
                    for row in candidates if _normal_id(row.get("gsis_id")) == new_gsis):
                counts["position_differences_on_id_bridges"] += 1
        else:
            counts["clear_unpublished_value"] += 1
            if reason and reason.startswith("stable ID bridge found"):
                counts["hold_name_disagreement"] += 1
            else:
                counts["unbridged"] += 1

        actions.append({
            "player_id": player_id,
            "name": player["name"],
            "legacy_nfl_gsis_id": legacy_key,
            "new_gsis_id": new_gsis,
            "disposition": "set" if new_gsis else "clear",
            "matched_by": methods,
            "legacy_source": alias_source,
            "reason": reason,
            "current_season_used": player_id in current_ids,
        })

    # Two local rows must not acquire one published key. This is a split identity,
    # not a field update: refuse it until the generic spine_merge path is used.
    conflicted = {gsis: ids for gsis, ids in proposed_owners.items() if len(ids) > 1}
    if conflicted:
        conflicts = {pid for ids in conflicted.values() for pid in ids}
        retained = []
        for action in actions:
            if action["player_id"] in conflicts:
                blocked.append({
                    "player_id": action["player_id"],
                    "legacy_key": action["legacy_nfl_gsis_id"],
                    "target_gsis_id": action["new_gsis_id"],
                    "reason": "multiple local rows resolve to one published GSIS; use spine_merge",
                    "other_player_ids": [pid for pid in conflicted[action["new_gsis_id"]]
                                         if pid != action["player_id"]],
                })
                counts["blocked_requires_spine_merge"] += 1
            else:
                retained.append(action)
        actions = retained

    action_ids = [int(action["player_id"]) for action in actions]
    references = _reference_counts(connection, action_ids)
    for action in actions:
        action["references_by_table"] = references[str(action["player_id"])]

    db = Path(db_path).expanduser().resolve(strict=True)
    stat = db.stat()
    plan = {
        "version": PLAN_VERSION,
        "created_at": _utc_now(),
        "database": {
            "path": str(db),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "schema_version": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
            "identity_fingerprint": _player_id_fingerprint(connection),
        },
        "source": {
            "url": REGISTER_URL,
            "register_path": str(Path(register_path).resolve(strict=True)),
            "sha256": _sha256_file(register_path),
            "rows": len(register_rows),
            "gsis_ids": len(gsis_ids),
            "nonstandard_gsis_ids": sum(1 for key in gsis_ids if not key.startswith("00-")),
            "duplicate_ids_by_column": {key: len(value) for key, value in register_duplicates.items()},
        },
        "scope": {
            "league": "nfl",
            "current_season": current_season,
            "current_player_ids_used": len(current_ids),
            "player_rows": len(players),
            "actions": len(actions),
            "blocked": len(blocked),
        },
        "summary": dict(sorted(counts.items())),
        "actions": actions,
        "blocked": blocked,
    }
    plan["plan_sha256"] = _canonical_sha256(plan)
    return plan


def _validate_plan(plan: Dict[str, Any], register_path: str) -> None:
    expected = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if not expected or expected != _canonical_sha256(unsigned):
        raise RepairError("plan checksum does not match its contents")
    if plan.get("version") != PLAN_VERSION:
        raise RepairError("unsupported plan version")
    if _sha256_file(register_path) != plan.get("source", {}).get("sha256"):
        raise RepairError("publisher register checksum differs from the reviewed plan")
    if plan.get("blocked"):
        raise RepairError(
            "plan contains {} identity/ownership conflicts; use spine_merge or review first"
            .format(len(plan["blocked"]))
        )


def apply_plan_to_copy(copy_db: str, plan: Dict[str, Any], register_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if plan.get("blocked"):
        raise RepairError(
            "plan contains {} identity/ownership conflicts; use spine_merge or review first"
            .format(len(plan["blocked"]))
        )
    path = Path(copy_db).expanduser().resolve(strict=True)
    source_path = Path(plan["database"]["path"]).resolve(strict=True)
    if path == source_path:
        raise RepairError("refusing to apply to the database used to build the plan")
    if os.path.commonpath(["/tmp", str(path)]) != "/tmp":
        raise RepairError("apply-copy accepts only a disposable database under /tmp")
    if path.name in ("picks.db", "picks.dev.db"):
        raise RepairError("refusing a database named picks.db or picks.dev.db")

    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RepairError("copy failed PRAGMA quick_check before apply")
        if _player_id_fingerprint(connection) != plan["database"]["identity_fingerprint"]:
            raise RepairError("copy's NFL player identity rows differ from the plan baseline")
        if not _table_exists(connection, "player_source_ids"):
            raise RepairError("copy has no player_source_ids crosswalk table")

        protected_before = {
            table: _table_fingerprint(connection, table)
            for table in PROTECTED_TABLES if _table_exists(connection, table)
        }
        reference_before = {
            "{}.{}".format(table, column): _reference_fingerprint(connection, table, column)
            for table, column in _reference_columns(connection)
            if table != "player_source_ids"
        }
        gsis_ids = {_normal_id(row.get("gsis_id")) for row in register_rows}
        gsis_ids.discard(None)
        inserted_crosswalk = 0
        updated_players = 0
        connection.execute("BEGIN IMMEDIATE")
        for action in plan["actions"]:
            player_id = int(action["player_id"])
            legacy = str(action["legacy_nfl_gsis_id"])
            new_gsis = action["new_gsis_id"]
            current = connection.execute(
                "SELECT nfl_gsis_id FROM players WHERE id=? AND league='nfl'", (player_id,)
            ).fetchone()
            if current is None or _normal_id(current[0]) != legacy:
                raise RepairError("player {} no longer has the planned legacy ID".format(player_id))
            if new_gsis:
                owners = connection.execute(
                    "SELECT id FROM players WHERE league='nfl' AND nfl_gsis_id=? AND id!=?",
                    (new_gsis, player_id),
                ).fetchall()
                if owners:
                    raise RepairError("target GSIS {} acquired another owner".format(new_gsis))
                if _normal_id(new_gsis) not in gsis_ids:
                    raise RepairError("planned GSIS ID is absent from the publisher register")

            source = action["legacy_source"]
            existed = connection.execute(
                "SELECT player_id FROM player_source_ids "
                "WHERE source=? AND league='nfl' AND source_player_key=?",
                (source, legacy),
            ).fetchone()
            if existed and int(existed[0]) != player_id:
                raise RepairError("legacy source key changed owner after planning")
            if not existed:
                connection.execute(
                    "INSERT INTO player_source_ids"
                    "(source,league,source_player_key,player_id,first_seen,last_seen) "
                    "VALUES(?,'nfl',?,?,?,?)",
                    (source, legacy, player_id, plan["created_at"], plan["created_at"]),
                )
                inserted_crosswalk += 1
            result = connection.execute(
                "UPDATE players SET nfl_gsis_id=? "
                "WHERE id=? AND league='nfl' AND nfl_gsis_id=?",
                (new_gsis, player_id, legacy),
            )
            if result.rowcount != 1:
                raise RepairError("expected one identity update for player {}".format(player_id))
            updated_players += 1

        for action in plan["actions"]:
            owner = connection.execute(
                "SELECT player_id FROM player_source_ids "
                "WHERE source=? AND league='nfl' AND source_player_key=?",
                (action["legacy_source"], action["legacy_nfl_gsis_id"]),
            ).fetchone()
            if owner is None or int(owner[0]) != int(action["player_id"]):
                raise RepairError("legacy ID was not preserved on its planned player")

        invalid_remaining = [row[0] for row in connection.execute(
            "SELECT DISTINCT nfl_gsis_id FROM players WHERE league='nfl' "
            "AND nfl_gsis_id IS NOT NULL AND TRIM(nfl_gsis_id)!=''"
        ) if _normal_id(row[0]) not in gsis_ids]
        if invalid_remaining:
            raise RepairError("unpublished nfl_gsis_id values remain: {}".format(len(invalid_remaining)))

        protected_after = {
            table: _table_fingerprint(connection, table)
            for table in PROTECTED_TABLES if _table_exists(connection, table)
        }
        if protected_before != protected_after:
            raise RepairError("protected table rows changed during identity repair")
        reference_after = {
            "{}.{}".format(table, column): _reference_fingerprint(connection, table, column)
            for table, column in _reference_columns(connection)
            if table != "player_source_ids"
        }
        if reference_before != reference_after:
            raise RepairError("player references changed; use spine_merge for a merge")
        connection.commit()
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RepairError("copy failed PRAGMA quick_check after apply")
        return {
            "copy_db": str(path),
            "updated_players": updated_players,
            "inserted_crosswalk_rows": inserted_crosswalk,
            "remaining_unpublished_ids": len(invalid_remaining),
            "protected_fingerprints": protected_after,
            "player_reference_fingerprints": reference_after,
            "quick_check": quick_check,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _reference_fingerprint(connection: sqlite3.Connection, table: str, column: str) -> str:
    digest = hashlib.sha256()
    order = _row_order(connection, table)
    cursor = connection.execute(
        'SELECT "{}" FROM "{}" ORDER BY {}'.format(column, table, order)
    )
    for row in cursor:
        digest.update(json.dumps(row[0], ensure_ascii=False, separators=(",", ":"), default=str)
                      .encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="read-only plan from a database and register")
    plan_parser.add_argument("--db", required=True)
    plan_parser.add_argument("--register", required=True)
    plan_parser.add_argument("--output", required=True)
    apply_parser = commands.add_parser("apply-copy", help="rehearse only on a disposable /tmp copy")
    apply_parser.add_argument("--copy-db", required=True)
    apply_parser.add_argument("--register", required=True)
    apply_parser.add_argument("--plan", required=True)
    args = parser.parse_args(argv)

    try:
        register_path = str(Path(args.register).expanduser().resolve(strict=True))
        register_rows = _load_register(register_path)
        if args.command == "plan":
            connection = _connect_read_only(args.db)
            try:
                plan = build_plan(connection, args.db, register_path, register_rows)
            finally:
                connection.close()
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = str(output) + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(plan, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
            os.replace(temporary, output)
            print(json.dumps({"plan": str(output), "summary": plan["summary"],
                              "scope": plan["scope"], "blocked": plan["blocked"]},
                             ensure_ascii=False, sort_keys=True))
            return 0

        with open(args.plan, encoding="utf-8") as handle:
            plan = json.load(handle)
        _validate_plan(plan, register_path)
        result = apply_plan_to_copy(args.copy_db, plan, register_rows)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, ValueError, RepairError) as exc:
        print("NFL identity repair refused: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
