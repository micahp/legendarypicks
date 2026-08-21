"""MLS summary ingestion must retain ESPN's full body before parsing it."""
from __future__ import annotations

import json
import sqlite3

import pytest

import ingest_soccer_logs as soccer
from migrate_publisher_captures import apply_database
from publisher_capture import PublisherCaptureContractError


def test_capture_summary_preserves_unmapped_source_fields(tmp_path):
    path = tmp_path / "picks.db"
    sqlite3.connect(path).close()
    apply_database(str(path))
    payload = {
        "header": {"id": "727308"},
        "boxscore": {"publisher_stat_we_do_not_map": {"value": 17}},
        "keyEvents": [{"id": "publisher-event"}],
    }
    with sqlite3.connect(path) as connection:
        capture_id, inserted = soccer._capture_summary(connection, "mls", "727308", payload)
        connection.commit()
        stored = connection.execute(
            "SELECT endpoint, payload_json FROM publisher_captures WHERE id=?", (capture_id,)
        ).fetchone()

    assert inserted is True
    assert stored[0].endswith("/summary?event=727308")
    assert json.loads(stored[1]) == payload


def test_capture_summary_refuses_an_unmigrated_database(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as connection:
        with pytest.raises(PublisherCaptureContractError):
            soccer._capture_summary(connection, "mls", "727308", {"header": {}})


def test_core_document_is_captured_before_its_fields_are_used(monkeypatch):
    payload = {"items": [{"publisher_only": "kept"}]}
    captured = []
    monkeypatch.setattr(soccer._FETCH, "json", lambda url: payload)

    result = soccer._get_core(
        "https://sports.core.api.espn.com/example", capture=lambda endpoint, body: captured.append((endpoint, body))
    )

    assert result == payload
    assert captured == [("https://sports.core.api.espn.com/example", payload)]


def test_ingest_refuses_before_the_first_source_request_when_unmigrated(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(soccer, "DB", str(path))
    requested = []
    monkeypatch.setattr(soccer, "_published_types", lambda *args, **kwargs: requested.append(args))

    with pytest.raises(PublisherCaptureContractError):
        soccer.ingest("mls", 2026, request_budget=1)

    assert requested == []
