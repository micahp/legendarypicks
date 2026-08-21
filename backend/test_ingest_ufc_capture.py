"""UFC plan payloads must enter the raw ledger in the same apply transaction."""
from __future__ import annotations

import json
import sqlite3

import ingest_ufc_fight_stats as ingest
from migrate_publisher_captures import apply_database


def test_apply_retains_carried_ufc_source_payload(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as con:
        con.executescript("CREATE TABLE players(id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT);")
    apply_database(str(path))
    plan = ingest.IngestPlan(
        target_count=0,
        source_payloads=[ingest.SourcePayload(
            endpoint="https://example.test/status", payload={"publisher_only": {"keep": 1}}
        )],
    )
    assert ingest.apply_plan(str(path), plan)["inserted_logs"] == 0
    with sqlite3.connect(path) as con:
        payload = con.execute("SELECT payload_json FROM publisher_captures").fetchone()[0]
    assert json.loads(payload) == {"publisher_only": {"keep": 1}}
