"""The settlement driver must bound selection before it calls a publisher."""
from __future__ import annotations

import sqlite3

from settle_props import _candidate_games


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT,
          espn_event_id TEXT, final_home INTEGER, final_away INTEGER, date TEXT
        );
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
        CREATE TABLE prop_results(prop_id INTEGER);
        INSERT INTO prop_games VALUES
          (1, 'nfl', 'A', 'B', 'e1', NULL, NULL, '2026-08-21'),
          (2, 'nfl', 'C', 'D', 'e2', NULL, NULL, '2026-08-20'),
          (3, 'ufc', 'E', 'F', 'e3', NULL, NULL, '2026-08-22');
        INSERT INTO props VALUES (11,1), (12,2), (13,3);
    """)
    return con


def test_candidate_selection_filters_and_limits_before_settlement():
    con = _db()
    rows = _candidate_games(con, leagues=['nfl'], limit=1)
    assert [(row['id'], row['league']) for row in rows] == [(1, 'nfl')]


def test_candidate_selection_respects_the_historical_boundary():
    con = _db()
    rows = _candidate_games(con, leagues=['nfl'], through='2026-08-20')
    assert [row['id'] for row in rows] == [2]


def test_candidate_selection_can_target_an_exact_game_id():
    con = _db()
    rows = _candidate_games(con, game_ids=[3])
    assert [(row['id'], row['league']) for row in rows] == [(3, 'ufc')]


def test_candidate_selection_excludes_fully_settled_games():
    con = _db()
    con.execute("INSERT INTO prop_results VALUES (11)")
    assert [row['id'] for row in _candidate_games(con, leagues=['nfl'])] == [2]
