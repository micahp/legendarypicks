"""Application cache for deterministic pregame stories.

The public prose and the private evidence manifest are stored in a dedicated
table so deterministic previews never overwrite legacy LLM story rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from typing import Any

import story_engine


ENGINE_VERSION = hashlib.sha256(Path(story_engine.__file__).read_bytes()).hexdigest()
TABLE = "game_story_deterministic"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=15)


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        league TEXT NOT NULL,
        game_id TEXT NOT NULL,
        story TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        facts_as_of TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        PRIMARY KEY (league, game_id)
    )""")


def _input_sha256(bundle: dict[str, Any]) -> str:
    # as_of moves on every request; the cutoff-filtered evidence itself is the
    # cache key, so unchanged inputs reuse the saved prose.
    material = {key: value for key, value in bundle.items() if key not in {"as_of", "source"}}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def generate_and_store_preview(db_path: str | Path, game: dict[str, Any], *,
                               as_of: str, refresh: bool = False) -> dict[str, Any]:
    """Collect cutoff-safe facts, render locally, and persist text plus evidence."""
    bundle = story_engine.collect_story_facts(db_path, game, as_of=as_of)
    input_sha = _input_sha256(bundle)

    with closing(_connect(db_path)) as connection:
        _ensure_table(connection)
        connection.commit()
        cached = connection.execute(
            f"SELECT story, generated_at FROM {TABLE} WHERE league=? AND game_id=? "
            "AND input_sha256=? AND engine_version=?",
            (game["league"], str(game["game_id"]), input_sha, ENGINE_VERSION),
        ).fetchone()
    if cached and not refresh:
        return {"league": game["league"], "game_id": str(game["game_id"]),
                "story": cached[0], "cached": True, "generator": "deterministic"}

    rendered = story_engine.generate_story(bundle)
    story = str(rendered.get("story") or "").strip()
    if not story:
        raise RuntimeError("deterministic story engine returned an empty preview")
    evidence = json.dumps(
        {"angle": rendered.get("angle"), "manifest": rendered.get("manifest")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    with closing(_connect(db_path)) as connection:
        _ensure_table(connection)
        connection.execute(
            f"INSERT OR REPLACE INTO {TABLE} "
            "(league,game_id,story,generated_at,facts_as_of,input_sha256,engine_version,evidence_json) "
            "VALUES (?,?,?,datetime('now'),?,?,?,?)",
            (game["league"], str(game["game_id"]), story, as_of, input_sha, ENGINE_VERSION, evidence),
        )
        connection.commit()
    return {"league": game["league"], "game_id": str(game["game_id"]),
            "story": story, "cached": False, "generator": "deterministic"}
