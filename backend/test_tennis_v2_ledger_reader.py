"""The V2 tennis reader refuses changed or malformed locked forecasts."""
import hashlib
import json
import sqlite3

import pytest
from fastapi import HTTPException

from routers.games import misc


def _ledger(path, payload, digest=None):
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE tennis_v2_research_forecasts(
        tour TEXT, game_id TEXT, locked_at TEXT, payload TEXT, payload_sha256 TEXT,
        PRIMARY KEY(tour,game_id)
      );
      CREATE TABLE tennis_v2_research_grades(
        tour TEXT, game_id TEXT, actual_winner TEXT, actual_total_games INTEGER,
        PRIMARY KEY(tour,game_id)
      );
    """)
    con.execute(
        "INSERT INTO tennis_v2_research_forecasts VALUES(?,?,?,?,?)",
        ("atp", "match-1", "2026-10-16T20:00:00+00:00", payload,
         digest if digest is not None else hashlib.sha256(payload.encode()).hexdigest()),
    )
    con.commit()
    con.close()


def test_reader_returns_record_when_stored_payload_hash_matches(tmp_path, monkeypatch):
    path = tmp_path / "tennis.sqlite3"
    payload = json.dumps({"model_version": "v2", "identity": {}}, sort_keys=True)
    _ledger(path, payload)
    monkeypatch.setenv("LP_TENNIS_V2_LEDGER_PATH", str(path))

    records = misc._tennis_v2_ledger_records("atp", ["match-1"])

    assert records["match-1"]["payload"]["model_version"] == "v2"


def test_reader_can_return_all_tour_records_for_accuracy_aggregation(tmp_path, monkeypatch):
    path = tmp_path / "tennis.sqlite3"
    payload = json.dumps({"model_version": "v2", "identity": {}}, sort_keys=True)
    _ledger(path, payload)
    monkeypatch.setenv("LP_TENNIS_V2_LEDGER_PATH", str(path))

    records = misc._tennis_v2_ledger_records("atp", None)

    assert list(records) == ["match-1"]


def test_reader_fails_closed_when_payload_hash_does_not_match(tmp_path, monkeypatch):
    path = tmp_path / "tennis.sqlite3"
    payload = json.dumps({"model_version": "tampered"}, sort_keys=True)
    _ledger(path, payload, digest="0" * 64)
    monkeypatch.setenv("LP_TENNIS_V2_LEDGER_PATH", str(path))

    with pytest.raises(HTTPException) as exc:
        misc._tennis_v2_ledger_records("atp", ["match-1"])
    assert exc.value.status_code == 503
    assert "checksum mismatch" in exc.value.detail


def test_reader_fails_closed_on_json_that_only_has_a_valid_hash(tmp_path, monkeypatch):
    path = tmp_path / "tennis.sqlite3"
    _ledger(path, "not json")
    monkeypatch.setenv("LP_TENNIS_V2_LEDGER_PATH", str(path))

    with pytest.raises(HTTPException) as exc:
        misc._tennis_v2_ledger_records("atp", ["match-1"])
    assert exc.value.status_code == 503
    assert "invalid JSON" in exc.value.detail
