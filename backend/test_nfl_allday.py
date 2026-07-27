"""Tests for nfl_allday.py — Flow AllDay collection endpoint.

Run: backend/venv/bin/python -m pytest backend/test_nfl_allday.py -q
"""

import json
import os
import re
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Return a TestClient with a temp DB to satisfy _core's init."""
    # _core.py does os.makedirs on the DB dir — need a real path, not :memory:
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test.db")
    os.environ["LP_DB_PATH"] = db_path
    # Create the file so sqlite3 doesn't complain
    open(db_path, "w").close()
    from sports_service import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------------


def test_invalid_address_too_short(client):
    resp = client.get("/api/nfl/allday/collection?address=0x123")
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_invalid_address_no_prefix(client):
    resp = client.get("/api/nfl/allday/collection?address=a16b948ba2c9a858a")
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_invalid_address_non_hex(client):
    resp = client.get("/api/nfl/allday/collection?address=0xGGGGGGGGGGGGGGGG")
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


@patch("routers.nfl_allday._get_ids")
def test_valid_address_format_accepted(mock_ids, client):
    """A valid-format address with a collection but no moments reads as empty."""
    mock_ids.return_value = (True, [])
    resp = client.get("/api/nfl/allday/collection?address=0xa16b948ba2c9a858")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["status"] == "empty"


@patch("routers.nfl_allday._account_exists")
@patch("routers.nfl_allday._get_children")
@patch("routers.nfl_allday._get_ids")
def test_missing_account_is_distinguished(mock_ids, mock_children, mock_exists, client):
    """An address that was never created must not read as 'owns nothing'."""
    mock_ids.return_value = (False, [])
    mock_children.return_value = []
    mock_exists.return_value = False
    data = client.get("/api/nfl/allday/collection?address=0xdeadbeefdeadbeef").json()
    assert data["status"] == "no_account"


@patch("routers.nfl_allday._account_exists")
@patch("routers.nfl_allday._get_children")
@patch("routers.nfl_allday._get_ids")
def test_existing_account_without_collection(mock_ids, mock_children, mock_exists, client):
    mock_ids.return_value = (False, [])
    mock_children.return_value = []
    mock_exists.return_value = True
    data = client.get("/api/nfl/allday/collection?address=0xa184e13ef8c3e0ef").json()
    assert data["status"] == "no_collection"


@patch("routers.nfl_allday._get_ids")
def test_flow_failure_does_not_leak_upstream(mock_ids, client):
    """A Flow error must not return our request URL or the raw node error."""
    from routers.nfl_allday import FlowError

    mock_ids.side_effect = FlowError("HTTP 400: rest-mainnet.onflow.org exploded")
    resp = client.get("/api/nfl/allday/collection?address=0xa16b948ba2c9a858&nocache=true")
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "onflow.org" not in detail
    assert "400" not in detail


# ---------------------------------------------------------------------------
# Player resolution
# ---------------------------------------------------------------------------


def _resolver_over(rows):
    """Build a PlayerResolver against an in-memory players table."""
    import sqlite3
    from unittest.mock import patch as _patch
    from routers.nfl_allday import PlayerResolver

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE players (id INT, name TEXT, position TEXT, team TEXT, "
        "nfl_gsis_id TEXT, active INT, league TEXT)"
    )
    conn.executemany(
        "INSERT INTO players VALUES (?,?,?,?,?,?, 'nfl')",
        [(r["id"], r["name"], r["position"], r["team"], r["nfl_gsis_id"], r["active"])
         for r in rows],
    )
    with _patch("routers.nfl_allday._get_db", return_value=conn):
        return PlayerResolver()


def test_resolve_player_exact_match():
    r = _resolver_over([
        {"id": 1, "name": "Brock Purdy", "position": "QB", "team": "SF",
         "nfl_gsis_id": "00-00", "active": 1}
    ])
    result = r.resolve("Brock", "Purdy", "QB")
    assert result is not None
    assert result["name"] == "Brock Purdy"
    assert result["position"] == "QB"


def test_resolve_player_no_match():
    r = _resolver_over([
        {"id": 1, "name": "Brock Purdy", "position": "QB", "team": "SF",
         "nfl_gsis_id": "00-00", "active": 1}
    ])
    assert r.resolve("Fake", "Player", "QB") is None


def test_resolve_player_prefers_position_on_ambiguous_name():
    """When multiple players share a name, prefer the one matching position."""
    r = _resolver_over([
        {"id": 1, "name": "Josh Allen", "position": "C", "team": "TB",
         "nfl_gsis_id": "00-01", "active": 1},
        {"id": 2, "name": "Josh Allen", "position": "QB", "team": "BUF",
         "nfl_gsis_id": "00-02", "active": 1},
    ])
    result = r.resolve("Josh", "Allen", "QB")
    assert result is not None
    assert result["position"] == "QB"
    assert result["team"] == "BUF"


def test_resolve_player_ignores_generational_suffix():
    """AllDay ships 'Murvin Kenion III'; our spine may store it without a suffix."""
    r = _resolver_over([
        {"id": 3, "name": "Marvin Harrison", "position": "WR", "team": "ARI",
         "nfl_gsis_id": "00-03", "active": 1}
    ])
    assert r.resolve("Marvin", "Harrison Jr.", "WR") is not None


def test_resolve_player_matches_retired_players():
    """Retired players still hold moments — active=0 must not exclude them."""
    r = _resolver_over([
        {"id": 4, "name": "Zach Ertz", "position": "TE", "team": "WAS",
         "nfl_gsis_id": "00-04", "active": 0}
    ])
    result = r.resolve("Zach", "Ertz", "TE")
    assert result is not None
    assert result["active"] == 0


# ---------------------------------------------------------------------------
# JSON-Cadence decoder
# ---------------------------------------------------------------------------


def test_decode_json_cadence_simple():
    from routers.nfl_allday import _decode_json_cadence

    assert _decode_json_cadence({"type": "String", "value": "hello"}) == "hello"
    assert _decode_json_cadence({"type": "UInt64", "value": "42"}) == "42"
    assert _decode_json_cadence({"type": "Optional", "value": None}) is None


def test_decode_json_cadence_dictionary():
    from routers.nfl_allday import _decode_json_cadence

    inp = {
        "type": "Dictionary",
        "value": [
            {"key": {"type": "String", "value": "name"}, "value": {"type": "String", "value": "Brock"}},
            {"key": {"type": "String", "value": "num"}, "value": {"type": "UInt64", "value": "13"}},
        ]
    }
    result = _decode_json_cadence(inp)
    assert result == {"name": "Brock", "num": "13"}


def test_decode_json_cadence_array():
    from routers.nfl_allday import _decode_json_cadence

    inp = {
        "type": "Array",
        "value": [
            {"type": "String", "value": "a"},
            {"type": "String", "value": "b"},
        ]
    }
    assert _decode_json_cadence(inp) == ["a", "b"]


# ---------------------------------------------------------------------------
# Flow address regex
# ---------------------------------------------------------------------------


def test_flow_address_regex():
    from routers.nfl_allday import FLOW_ADDRESS_RE

    assert re.match(FLOW_ADDRESS_RE, "0xa16b948ba2c9a858")
    assert re.match(FLOW_ADDRESS_RE, "0x0000000000000000")
    assert re.match(FLOW_ADDRESS_RE, "0xABCDEFabcdef1234")
    assert not re.match(FLOW_ADDRESS_RE, "0x123")
    assert not re.match(FLOW_ADDRESS_RE, "a16b948ba2c9a858a")
    assert not re.match(FLOW_ADDRESS_RE, "0xGGGGGGGGGGGGGGGG")
