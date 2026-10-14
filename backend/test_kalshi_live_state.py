"""Tests for the Kalshi live-state reader (fixture files, no network)."""
import datetime as dt
import json

import pytest

import kalshi_live_state as kls

NOW = dt.datetime(2026, 10, 13, 12, 0, 30, tzinfo=dt.timezone.utc)


def _match(**over):
    m = {"milestone_id": "m1", "tour": "WTA", "finished": False,
         "polled_at": "2026-10-13T12:00:28+00:00", "status": "live"}
    m.update(over)
    return m


def _write(path, body):
    path.write_text(body if isinstance(body, str) else json.dumps(body))


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "KALSHI_LIVE_STATE.json"
    monkeypatch.setenv("LP_KALSHI_LIVE_STATE", str(path))
    kls._cache.update(mtime=None, body=None)
    return path


def _body(matches=None, generated="2026-10-13T12:00:29+00:00", version=2):
    return {"schema_version": version, "generated_at": generated, "poll_s": 4, "matches": matches or []}


def test_fresh_match_is_marked_fresh(state):
    _write(state, _body([_match()]))
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is True
    assert out["matches"][0]["freshness"] == "fresh"
    assert out["matches"][0]["age_s"] == 2.0


def test_aging_match_between_15_and_60s(state):
    _write(state, _body([_match(polled_at="2026-10-13T11:59:45+00:00")]))
    m = kls.read_live("wta", now=NOW)["matches"][0]
    assert m["freshness"] == "aging" and m["age_s"] == 45.0


def test_match_over_60s_is_dropped(state):
    _write(state, _body([_match(polled_at="2026-10-13T11:58:00+00:00")]))
    assert kls.read_live("wta", now=NOW)["matches"] == []


def test_finished_and_other_tour_are_dropped(state):
    _write(state, _body([_match(finished=True), _match(milestone_id="m2", tour="ATP")]))
    assert kls.read_live("wta", now=NOW)["matches"] == []


def test_zero_match_file_is_available_and_empty(state):
    _write(state, _body([]))
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is True and out["matches"] == []


def test_stale_file_is_unavailable_with_time(state):
    _write(state, _body([_match()], generated="2026-10-13T11:55:00+00:00"))
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is False
    assert "poller stale since 11:55:00 UTC" in out["reason"]


def test_torn_json_is_unavailable(state):
    _write(state, '{"schema_version": 2, "generated_at": ')
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is False and "unreadable" in out["reason"]


def test_missing_file_is_unavailable(state):
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is False and "missing" in out["reason"]


def test_schema_version_1_is_unavailable(state):
    _write(state, _body([_match()], version=1))
    out = kls.read_live("wta", now=NOW)
    assert out["available"] is False and "schema_version" in out["reason"]


def test_non_tennis_league_raises(state):
    with pytest.raises(ValueError):
        kls.read_live("nfl", now=NOW)
