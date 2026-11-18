"""Application cache, quality checks, and append-only history for CPU stories."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from typing import Any
import uuid

import story_engine
import story_engine_audit
import story_rubric


TABLE = "game_story_deterministic"
HISTORY_TABLE = "game_story_deterministic_history"
ACCEPTED_KEYS_TABLE = "game_story_deterministic_accepted_keys"
FAILURE_TABLE = "game_story_deterministic_failures"
FAILURE_COOLDOWN_TABLE = "game_story_deterministic_failure_cooldowns"
ENGINE_VERSION = hashlib.sha256(b"\n".join(
    Path(module.__file__).read_bytes()
    for module in (story_engine, story_engine_audit, story_rubric)
)).hexdigest()


def _connect(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=15)


def _ensure_tables(connection: sqlite3.Connection) -> None:
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        story TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        facts_as_of TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        last_checked_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (league, game_id)
    )""")
    latest_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({TABLE})")}
    if "last_checked_at" not in latest_columns:
        connection.execute(
            f"ALTER TABLE {TABLE} ADD COLUMN last_checked_at TEXT NOT NULL DEFAULT ''")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
        generation_id TEXT PRIMARY KEY,
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        story TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        facts_as_of TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        quality_json TEXT NOT NULL,
        gate_status TEXT NOT NULL,
        score INTEGER
    )""")
    connection.execute(f"""CREATE INDEX IF NOT EXISTS idx_{HISTORY_TABLE}_game_time
        ON {HISTORY_TABLE}(league,game_id,generated_at)""")
    connection.execute(f"""CREATE INDEX IF NOT EXISTS idx_{HISTORY_TABLE}_idempotency
        ON {HISTORY_TABLE}(league,game_id,input_sha256,engine_version,gate_status)""")
    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_{HISTORY_TABLE}_no_update
        BEFORE UPDATE ON {HISTORY_TABLE}
        BEGIN SELECT RAISE(ABORT,'deterministic story history is append-only'); END""")
    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_{HISTORY_TABLE}_no_delete
        BEFORE DELETE ON {HISTORY_TABLE}
        BEGIN SELECT RAISE(ABORT,'deterministic story history is append-only'); END""")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {ACCEPTED_KEYS_TABLE} (
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        PRIMARY KEY (league,game_id,input_sha256,engine_version)
    )""")
    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_{ACCEPTED_KEYS_TABLE}_no_update
        BEFORE UPDATE ON {ACCEPTED_KEYS_TABLE}
        BEGIN SELECT RAISE(ABORT,'deterministic accepted keys are immutable'); END""")
    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_{ACCEPTED_KEYS_TABLE}_no_delete
        BEFORE DELETE ON {ACCEPTED_KEYS_TABLE}
        BEGIN SELECT RAISE(ABORT,'deterministic accepted keys are immutable'); END""")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {FAILURE_TABLE} (
        failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        failed_at TEXT NOT NULL,
        failure_type TEXT NOT NULL,
        detail TEXT NOT NULL
    )""")
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {FAILURE_COOLDOWN_TABLE} (
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        last_failed_at TEXT NOT NULL,
        PRIMARY KEY (league,game_id)
    )""")


def _input_sha256(bundle: dict[str, Any]) -> str:
    # Request time is not evidence content. Keep repeated kickoff observations stable too.
    material = {key: value for key, value in bundle.items() if key not in {"as_of", "source"}}
    if "matchup_evidence" in material:
        material["matchup_evidence"] = [
            ({**row, "available_at": "kickoff_observation"}
             if "_kickoff:" in str(row.get("id") or "") else row)
            for row in material["matchup_evidence"]
        ]
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _quality_record(rendered: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    audit = story_engine_audit.audit_story(rendered, bundle)
    return story_rubric.grade_record({
        "target_game_id": bundle.get("game_id"),
        "league": bundle.get("league"),
        "story": rendered.get("story"),
        "angle": rendered.get("angle"),
        "manifest": rendered.get("manifest"),
        "input_facts": bundle,
        "mechanical_audit": audit,
    })


def _append_failure(connection: sqlite3.Connection, league: str, game_id: str,
                    failure_type: str, detail: str) -> None:
    connection.execute(
        f"INSERT INTO {FAILURE_TABLE}(league,game_id,failed_at,failure_type,detail) "
        "VALUES (?,?,datetime('now'),?,?)",
        (league, str(game_id), failure_type, detail[:500]),
    )


def _mark_failure_cooldown(connection: sqlite3.Connection, league: str, game_id: str) -> None:
    connection.execute(
        f"INSERT INTO {FAILURE_COOLDOWN_TABLE}(league,game_id,last_failed_at) "
        "VALUES (?,?,datetime('now')) "
        "ON CONFLICT(league,game_id) DO UPDATE SET last_failed_at=excluded.last_failed_at",
        (league, str(game_id)),
    )


def record_generation_failure(db_path: str | Path, league: str, game_id: str,
                              error: Exception) -> None:
    """Append operational failures separately from rubric quality warnings."""
    with closing(_connect(db_path)) as connection:
        _ensure_tables(connection)
        _append_failure(connection, league, game_id, type(error).__name__, str(error))
        _mark_failure_cooldown(connection, league, game_id)
        connection.execute(
            f"UPDATE {TABLE} SET last_checked_at=datetime('now') WHERE league=? AND game_id=?",
            (league, str(game_id)),
        )
        connection.commit()


def _cached_fallback(connection: sqlite3.Connection, league: str, game_id: str) -> tuple[str | None, str | None]:
    for table in (TABLE, "game_story"):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        row = connection.execute(
            f"SELECT story,generated_at FROM {table} WHERE league=? AND game_id=?",
            (league, str(game_id)),
        ).fetchone()
        if row and row[0]:
            return row[0], row[1]
    return None, None


def get_cached_fallback(db_path: str | Path, league: str, game_id: str) -> tuple[str | None, str | None]:
    """Read the last saved story directly, including when the app DB helper failed."""
    with closing(_connect(db_path)) as connection:
        return _cached_fallback(connection, league, game_id)


def _record_unpublishable_generation(db_path: str | Path, game: dict[str, Any], story: str,
                                    as_of: str, input_sha: str, evidence: str,
                                    quality: dict[str, Any]) -> dict[str, Any]:
    league, game_id = str(game["league"]), str(game["game_id"])
    with closing(_connect(db_path)) as connection:
        _ensure_tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        gate = quality.get("gate") or "needs-audit"
        existing = connection.execute(
            f"SELECT gate_status FROM {HISTORY_TABLE} WHERE league=? AND game_id=? "
            "AND input_sha256=? AND engine_version=? ORDER BY generated_at DESC LIMIT 1",
            (league, game_id, input_sha, ENGINE_VERSION),
        ).fetchone()
        if existing:
            _mark_failure_cooldown(connection, league, game_id)
            connection.execute(
                f"UPDATE {TABLE} SET last_checked_at=datetime('now') WHERE league=? AND game_id=?",
                (league, game_id),
            )
            fallback_story, fallback_at = _cached_fallback(connection, league, game_id)
            connection.commit()
            return {"league": league, "game_id": game_id, "story": fallback_story,
                    "cached": bool(fallback_story), "cached_at": fallback_at,
                    "generator": "deterministic", "status": existing[0]}
        failure_type = "audit_blocked" if gate == "blocked" else "audit_incomplete"
        _append_failure(connection, league, game_id, failure_type,
                        ", ".join(quality.get("hard_failures") or ["independent audit incomplete"]))
        _mark_failure_cooldown(connection, league, game_id)
        connection.execute(
            f"INSERT INTO {HISTORY_TABLE} "
            "(generation_id,league,game_id,story,generated_at,facts_as_of,input_sha256,"
            "engine_version,evidence_json,quality_json,gate_status,score) "
            "VALUES (?,?,?, ?,datetime('now'),?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), league, game_id, story, as_of, input_sha, ENGINE_VERSION,
             evidence, json.dumps(quality, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
             quality["gate"], quality.get("score")),
        )
        fallback_story, fallback_at = _cached_fallback(connection, league, game_id)
        connection.execute(
            f"UPDATE {TABLE} SET last_checked_at=datetime('now') WHERE league=? AND game_id=?",
            (league, game_id),
        )
        connection.commit()
    return {"league": league, "game_id": game_id, "story": fallback_story,
            "cached": bool(fallback_story), "cached_at": fallback_at,
            "generator": "deterministic", "status": gate}


def generate_and_store_preview(db_path: str | Path, game: dict[str, Any], *,
                               as_of: str, refresh: bool = False) -> dict[str, Any]:
    """Collect cutoff-safe facts, audit and grade the preview, then atomically persist it."""
    bundle = story_engine.collect_story_facts(db_path, game, as_of=as_of)
    bundle["matchup_evidence"] = [dict(row) for row in game.get("matchup_evidence") or []]
    for row in bundle["matchup_evidence"]:
        if row.get("available_at") == "request_observation":
            row["available_at"] = as_of
    input_sha = _input_sha256(bundle)

    with closing(_connect(db_path)) as connection:
        _ensure_tables(connection)
        connection.commit()
        cached = connection.execute(
            f"SELECT story,generated_at FROM {TABLE} WHERE league=? AND game_id=? "
            "AND input_sha256=? AND engine_version=?",
            (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
        ).fetchone()
        if cached:
            # `refresh` means to re-collect facts; identical evidence and code do not
            # create duplicate scored history rows.
            connection.execute(
                f"UPDATE {TABLE} SET last_checked_at=datetime('now') WHERE league=? AND game_id=?",
                (game["league"], str(game["game_id"])),
            )
            connection.commit()
            return {"league": game["league"], "game_id": str(game["game_id"]),
                    "story": cached[0], "cached": True, "generator": "deterministic"}

    rendered = story_engine.generate_story(bundle)
    story = str(rendered.get("story") or "").strip()
    if not story:
        raise RuntimeError("deterministic story engine returned an empty preview")
    quality = _quality_record(rendered, bundle)
    evidence = json.dumps(
        {"angle": rendered.get("angle"), "manifest": rendered.get("manifest"),
         "matchup_evidence": bundle.get("matchup_evidence")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    if quality["gate"] not in {"eligible", "review"}:
        return _record_unpublishable_generation(db_path, game, story, as_of, input_sha, evidence, quality)

    generation_id = str(uuid.uuid4())
    quality_json = json.dumps(quality, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with closing(_connect(db_path)) as connection:
        _ensure_tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            accepted = connection.execute(
                f"SELECT story FROM {HISTORY_TABLE} WHERE league=? AND game_id=? "
                "AND input_sha256=? AND engine_version=? AND gate_status IN ('eligible','review') "
                "ORDER BY generated_at,generation_id LIMIT 1",
                (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
            ).fetchone()
            if accepted:
                connection.execute(
                    f"INSERT OR IGNORE INTO {ACCEPTED_KEYS_TABLE} "
                    "(league,game_id,input_sha256,engine_version) VALUES (?,?,?,?)",
                    (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
                )
                connection.execute(
                    f"UPDATE {TABLE} SET last_checked_at=datetime('now') "
                    "WHERE league=? AND game_id=? AND input_sha256=? AND engine_version=?",
                    (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
                )
                connection.commit()
                return {"league": game["league"], "game_id": str(game["game_id"]),
                        "story": accepted[0], "cached": True, "generator": "deterministic"}
            key_insert = connection.execute(
                f"INSERT OR IGNORE INTO {ACCEPTED_KEYS_TABLE} "
                "(league,game_id,input_sha256,engine_version) VALUES (?,?,?,?)",
                (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
            )
            if key_insert.rowcount == 0:
                connection.rollback()
                raise RuntimeError("accepted generation key exists without its history row")
            connection.execute(
                f"INSERT INTO {HISTORY_TABLE} "
                "(generation_id,league,game_id,story,generated_at,facts_as_of,input_sha256,"
                "engine_version,evidence_json,quality_json,gate_status,score) "
                "VALUES (?,?,?, ?,datetime('now'),?,?,?,?,?,?,?)",
                (generation_id, game["league"], str(game["game_id"]), story, as_of, input_sha,
                 ENGINE_VERSION, evidence, quality_json, quality["gate"], quality.get("score")),
            )
            connection.execute(
                f"INSERT OR REPLACE INTO {TABLE} "
                "(league,game_id,story,generated_at,facts_as_of,input_sha256,engine_version,evidence_json,last_checked_at) "
                "VALUES (?,?,?,datetime('now'),?,?,?,?,datetime('now'))",
                (game["league"], str(game["game_id"]), story, as_of, input_sha,
                 ENGINE_VERSION, evidence),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"league": game["league"], "game_id": str(game["game_id"]),
            "story": story, "cached": False, "generator": "deterministic"}
