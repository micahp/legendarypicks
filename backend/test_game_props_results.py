"""Tests for settled prop results on the game props endpoint.

The board showed what was offered and then went quiet. Props are the product, so the one
page where we can show the lines were worth reading has to show how they landed — and it
has to keep 'not settled yet' distinguishable from 'missed'.
"""
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture()
def api(monkeypatch):
    """A throwaway DB with one game, three props, two of them settled."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, espn_event_id TEXT);
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
                           market TEXT, line REAL, side TEXT, captured_at TEXT);
        CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL, hit INTEGER,
                                  settled_at TEXT);
        INSERT INTO prop_games VALUES (1, '999');
        INSERT INTO players VALUES (10, 'Aaron Judge', 'NYY');
        INSERT INTO props VALUES (100, 1, 10, 'total_bases', 1.5, 'over',  '2026-08-09T00:00Z');
        INSERT INTO props VALUES (101, 1, 10, 'hits',        0.5, 'over',  '2026-08-09T00:00Z');
        INSERT INTO props VALUES (102, 1, 10, 'strikeouts',  1.5, 'under', '2026-08-09T00:00Z');
        INSERT INTO prop_results VALUES (100, 3.0, 1, '2026-08-09T04:00Z');
        INSERT INTO prop_results VALUES (101, 0.0, 0, '2026-08-09T04:00Z');
    """)
    con.commit()
    con.close()

    import _core
    monkeypatch.setattr(_core, "DB", path)
    from routers import game_extras
    monkeypatch.setattr(game_extras, "DB", path, raising=False)
    yield game_extras.game_props
    os.unlink(path)


def test_a_hit_carries_its_actual_value(api):
    props = {p["market"]: p for p in api("mlb", "999")["players"][0]["props"]}
    assert props["total_bases"]["result"] == {"actual": 3.0, "hit": True,
                                              "settled_at": "2026-08-09T04:00Z"}


def test_a_miss_is_recorded_as_a_miss_not_as_missing(api):
    props = {p["market"]: p for p in api("mlb", "999")["players"][0]["props"]}
    assert props["hits"]["result"]["hit"] is False
    assert props["hits"]["result"]["actual"] == 0.0


def test_an_unsettled_prop_is_null_rather_than_a_loss(api):
    """The distinction the whole feature rests on. A prop with no row in prop_results has
    not been graded; rendering it as a miss would claim a loss we never took."""
    props = {p["market"]: p for p in api("mlb", "999")["players"][0]["props"]}
    assert props["strikeouts"]["result"] is None


def test_counts_describe_settled_props_only(api):
    out = api("mlb", "999")
    assert out["settled_count"] == 2
    assert out["hit_count"] == 1


def test_a_game_with_no_props_reports_zero_rather_than_omitting_the_counts(api):
    out = api("mlb", "no-such-game")
    assert out["players"] == []
    assert out["settled_count"] == 0 and out["hit_count"] == 0
