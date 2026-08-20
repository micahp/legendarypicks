#!/usr/bin/env python3
"""`(league, date, home, away)` cannot tell a doubleheader from a duplicate.

That tuple is the key both ingest paths match an existing fixture on. On
2026-08-19, re-dating every row onto the local slate day made five pairs collide
at once. Four were one game stored twice. The fifth was real: ESPN says the
07-27 Reds/Guardians game was Postponed and replayed as two games on 07-28.

Nothing in the codebase could state the difference, so it got decided by hand
each time. These pin the rule: the published final score separates them, and it
is the only thing that does.
"""
import sqlite3
import sys

sys.path.insert(0, '.')

from prop_game_merge import (  # noqa: E402
    dangling_source_mappings, fold_prop_game, shared_match_keys,
)


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE prop_games(
             id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
             date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,
             final_home INTEGER, final_away INTEGER, start_time TEXT)""")
    con.execute(
        """CREATE TABLE props(
             id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
             player_id INTEGER, market TEXT, line REAL, side TEXT)""")
    con.execute(
        """CREATE TABLE prop_game_source_ids(
             id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, league TEXT,
             source_game_key TEXT, game_id INTEGER)""")
    return con


def _game(con, date, fh, fa, start, home="Reds", away="Guardians"):
    return con.execute(
        "INSERT INTO prop_games(league,date,home,away,espn_event_id,"
        "final_home,final_away,start_time) VALUES('mlb',?,?,?,'',?,?,?)",
        (date, home, away, fh, fa, start)).lastrowid


def test_two_settled_rows_with_different_finals_are_a_doubleheader():
    con = _db()
    _game(con, "2026-07-27", 5, 6, "2026-07-28T17:40:00+00:00")
    _game(con, "2026-07-27", 2, 0, "2026-07-28T23:10:00+00:00")
    shared = shared_match_keys(con)
    assert len(shared) == 1
    assert shared[0]["verdict"] == "doubleheader", shared[0]


def test_two_rows_with_the_same_final_are_one_game_stored_twice():
    con = _db()
    _game(con, "2026-07-22", 1, 5, "2026-07-23T00:00:00+00:00")
    _game(con, "2026-07-22", 1, 5, "2026-07-23T00:10:00+00:00")
    shared = shared_match_keys(con)
    assert len(shared) == 1
    assert shared[0]["verdict"] == "duplicate", shared[0]


def test_an_unsettled_pair_is_a_duplicate_not_a_doubleheader():
    """Absence of a final is not evidence of a second game.

    Guessing "doubleheader" here would let a real duplicate survive on the
    board unremarked, which is the more expensive mistake: a duplicate serves
    the same prop twice.
    """
    con = _db()
    _game(con, "2026-08-22", None, None, "2026-08-22T23:40:00+00:00")
    _game(con, "2026-08-22", None, None, "2026-08-23T00:15:00+00:00")
    assert shared_match_keys(con)[0]["verdict"] == "duplicate"


def test_distinct_fixtures_do_not_share_a_key():
    con = _db()
    _game(con, "2026-07-27", 5, 6, "2026-07-27T23:10:00+00:00")
    _game(con, "2026-07-28", 2, 0, "2026-07-28T23:10:00+00:00")
    assert shared_match_keys(con) == []


def test_a_fold_moves_every_reference_not_just_props():
    """The UFC timer failed every 30 minutes for two hours because a hand-rolled
    fold moved `props` and left `prop_game_source_ids` pointing at a deleted row.
    """
    con = _db()
    winner = _game(con, "2026-07-22", 1, 5, "2026-07-23T00:00:00+00:00")
    loser = _game(con, "2026-07-22", 1, 5, "2026-07-23T00:10:00+00:00")
    con.execute("INSERT INTO props(game_id) VALUES(?)", (loser,))
    con.execute("INSERT INTO prop_game_source_ids(source,league,source_game_key,"
                "game_id) VALUES('bovada','mlb','k',?)", (loser,))

    assert fold_prop_game(con, loser, winner) == winner
    assert con.execute("SELECT COUNT(*) FROM prop_games WHERE id=?",
                       (loser,)).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM props WHERE game_id=?",
                       (winner,)).fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM prop_game_source_ids WHERE game_id=?",
                       (winner,)).fetchone()[0] == 1
    assert dangling_source_mappings(con) == []


def test_folding_a_row_into_itself_is_a_no_op():
    con = _db()
    only = _game(con, "2026-07-22", 1, 5, "2026-07-23T00:00:00+00:00")
    con.execute("INSERT INTO props(game_id) VALUES(?)", (only,))
    assert fold_prop_game(con, only, only) == only
    assert con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM props").fetchone()[0] == 1
