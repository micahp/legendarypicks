"""Bovada's complete coupon must survive before parsers flatten it."""
from __future__ import annotations

import json
import sqlite3

import pytest

from bovada_scraper.client import (events_from_coupon, record_coupon_capture)
from migrate_publisher_captures import apply_database


def test_coupon_capture_retains_outer_and_unparsed_fields(tmp_path):
    path = tmp_path / "picks.db"
    sqlite3.connect(path).close()
    apply_database(str(path))
    coupon = [{
        "couponMetadata": {"publisher_only": "retain-me"},
        "events": [{"id": "event-1", "description": "A @ B", "ignored": {"new": 1}}],
    }]

    capture_id, inserted = record_coupon_capture(
        coupon, league="nfl", endpoint="https://example.test/nfl", db_path=str(path)
    )

    assert capture_id > 0
    assert inserted is True
    with sqlite3.connect(path) as connection:
        payload = json.loads(connection.execute(
            "SELECT payload_json FROM publisher_captures WHERE id=?", (capture_id,)
        ).fetchone()[0])
    assert payload == coupon
    assert events_from_coupon(coupon) == coupon[0]["events"]


def test_coupon_capture_deduplicates_a_repeat_observation(tmp_path):
    path = tmp_path / "picks.db"
    sqlite3.connect(path).close()
    apply_database(str(path))
    kwargs = dict(league="nfl", endpoint="https://example.test/nfl", db_path=str(path))
    first = record_coupon_capture([{"events": []}], **kwargs)
    second = record_coupon_capture([{"events": []}], **kwargs)

    assert first == (first[0], True)
    assert second == (first[0], False)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT capture_count FROM publisher_captures WHERE id=?", (first[0],)
        ).fetchone()[0] == 2


def test_coupon_capture_rejects_implicit_or_relative_database(monkeypatch):
    monkeypatch.delenv("LP_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="existing absolute LP_DB_PATH"):
        record_coupon_capture([], league="nfl", endpoint="https://example.test/nfl")
    monkeypatch.setenv("LP_DB_PATH", "data/picks.db")
    with pytest.raises(RuntimeError, match="existing absolute LP_DB_PATH"):
        record_coupon_capture([], league="nfl", endpoint="https://example.test/nfl")
    monkeypatch.setenv("LP_DB_PATH", "/no/such/picks.db")
    with pytest.raises(RuntimeError, match="existing absolute LP_DB_PATH"):
        record_coupon_capture([], league="nfl", endpoint="https://example.test/nfl")
