"""A live box score is not a result.

The finality gate in settle_game sat BELOW the MLB branch, which returns before reaching
it — so for the one league with real prop volume it was dead code. Measured on 401816457
(Reds at Nationals, 2026-08-09): first pitch 16:15Z, every prop settled at 17:00Z, 45
minutes in. Brady Singer graded at 6 outs and 0 strikeouts against a real line of 18 and 3.
Other games were graded as zeros roughly 22 hours BEFORE first pitch.
"""
import sqlite3

import pytest

import settlement


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT,
                                date TEXT, espn_event_id TEXT, final_home REAL, final_away REAL,
                                start_time TEXT);
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, mlbam_id INTEGER,
                             espn_id TEXT, league TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
                           market TEXT, line REAL, side TEXT);
        CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL, hit INTEGER, settled_at TEXT);
        INSERT INTO prop_games VALUES (1,'mlb','Washington Nationals','Cincinnati Reds',
                                       '2026-08-09','401816457',NULL,NULL,
                                       '2026-08-09T16:15:00+00:00');
        INSERT INTO players VALUES (10,'Brady Singer','CIN',12345,'4239580','mlb');
        INSERT INTO props VALUES (100,1,10,'outs',17.5,'over');
    """)
    c.commit()
    return c


def _state(monkeypatch, state, winner="WSH", completed=None):
    """Stub `game_result` in the shape it actually returns.

    This stub used to key `scores` by DISPLAY NAME and omit home_score/away_score,
    which is not what ESPN publishes or what the client returns — so it passed the
    gate while proving nothing about the write below it. `completed` defaults to
    `state == "post"`; pass it explicitly to model a POSTPONED game, which ESPN
    also files as state="post". See test_finality_gate_completed.
    """
    # settle_game imports espn_client inside the function, so patch the module it reaches.
    import espn_client
    monkeypatch.setattr(espn_client, "game_result",
                        lambda lg, gid: {"state": state,
                                         "completed": (state == "post") if completed is None
                                                      else completed,
                                         "winner": winner,
                                         "scores": {"WSH": 7, "CIN": 1},
                                         "home": "WSH", "away": "CIN",
                                         "home_score": 7, "away_score": 1})


def test_a_game_in_progress_settles_nothing(con, monkeypatch):
    """The exact 401816457 case: the job ran 45 minutes after first pitch."""
    _state(monkeypatch, "in", winner=None)
    called = []
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: called.append(1) or {"settled": 99})
    out = settlement.settle_game(con, 1)
    assert out["settled"] == 0
    assert "not final" in out["msg"]
    assert called == [], "the MLB grader must not run on a live game"


def test_a_scheduled_game_settles_nothing(con, monkeypatch):
    """Two games in the real table were graded ~22 hours BEFORE first pitch, as zeros."""
    _state(monkeypatch, "pre", winner=None)
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: pytest.fail("graded a game that had not started"))
    assert settlement.settle_game(con, 1)["settled"] == 0


def test_a_final_game_does_settle(con, monkeypatch):
    """The gate blocks live games, not grading itself."""
    _state(monkeypatch, "post")
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: {"settled": 1, "void": 0, "unmappable": 0})
    assert settlement.settle_game(con, 1)["settled"] == 1


def test_the_final_score_is_recorded_when_the_gate_passes(con, monkeypatch):
    _state(monkeypatch, "post")
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: {"settled": 1, "void": 0, "unmappable": 0})
    settlement.settle_game(con, 1)
    row = con.execute("SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert (row["final_home"], row["final_away"]) == (7, 1)


def test_a_postponed_game_settles_nothing(con, monkeypatch):
    """ESPN files POSTPONED as state="post" with completed=false and 0-0. The gate
    read `state`, so it admitted one and the MLB grader ran on an unplayed game."""
    _state(monkeypatch, "post", winner=None, completed=False)
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: pytest.fail("graded a game that was postponed"))
    out = settlement.settle_game(con, 1)
    assert out["settled"] == 0
    row = con.execute("SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert (row["final_home"], row["final_away"]) == (None, None)


def test_a_draw_settles(con, monkeypatch):
    """The gate also required a winner, which refused an honest draw — a real
    result in soccer and NHL. Measured: MLS event 726528 is completed, 2-2, no
    winner, and could never have settled."""
    _state(monkeypatch, "post", winner=None)
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: {"settled": 1, "void": 0, "unmappable": 0})
    assert settlement.settle_game(con, 1)["settled"] == 1


def test_the_gate_applies_to_mlb_which_is_where_it_was_being_skipped(con, monkeypatch):
    """Regression pin on the control flow itself: the MLB branch used to return before the
    check, so a passing suite that only exercised non-MLB leagues proved nothing."""
    assert con.execute("SELECT league FROM prop_games WHERE id=1").fetchone()["league"] == "mlb"
    _state(monkeypatch, "in", winner=None)
    monkeypatch.setattr(settlement, "_settle_mlb_props",
                        lambda *a, **k: pytest.fail("MLB skipped the finality gate"))
    settlement.settle_game(con, 1)
