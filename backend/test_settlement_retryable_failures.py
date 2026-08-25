"""Settlement failures must not masquerade as terminal void results.

``settle_props`` treats any ``prop_results`` row as final.  These regressions run
the same prop twice: an unmapped market or an unavailable published stat must be
seen on both runs, proving that a later mapping/data repair can still settle it.
"""
import sqlite3

import espn_client
import settlement


def _connection(league, market, side="over"):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
            id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
            espn_event_id TEXT, final_home REAL, final_away REAL, start_time TEXT
        );
        CREATE TABLE players(
            id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
            espn_id TEXT, mlbam_id INTEGER
        );
        CREATE TABLE props(
            id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
            market TEXT, line REAL, side TEXT
        );
        CREATE TABLE prop_results(
            prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
            settled_at TEXT
        );
    """)
    con.execute(
        "INSERT INTO prop_games VALUES(1,?,?,?,?,?,1,0,?)",
        (league, "Home", "Away", "2026-08-14", "event-1",
         "2026-08-14T20:00:00+00:00"),
    )
    con.execute(
        "INSERT INTO players VALUES(1,'Published Player','BOS',?, '123', NULL)",
        (league,),
    )
    con.execute("INSERT INTO props VALUES(1,1,1,?,0.5,?)", (market, side))
    return con


def _boxscore_without_shots():
    return {"players": [{
        "team": {"abbreviation": "BOS", "displayName": "Boston Bruins"},
        "statistics": [{
            "name": "offensive",
            "labels": ["G", "A"],
            "athletes": [{
                "athlete": {"id": "123", "displayName": "Published Player"},
                "stats": ["0", "0"],
            }],
        }],
    }]}


def test_generic_unmapped_market_remains_retryable(monkeypatch):
    # WC has a dedicated durable-log grader now; WNBA still exercises the
    # generic unmapped-market path this regression is about.
    con = _connection("wnba", "goals")
    monkeypatch.setattr(espn_client, "boxscore", lambda *args: {"players": [{}]})

    first = settlement.settle_game(con, 1)
    second = settlement.settle_game(con, 1)

    assert first["unmappable"] == second["unmappable"] == 1
    assert first["settled"] == second["settled"] == 0
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_generic_missing_stat_remains_retryable(monkeypatch):
    con = _connection("nhl", "shots")
    monkeypatch.setattr(espn_client, "boxscore", lambda *args: _boxscore_without_shots())

    first = settlement.settle_game(con, 1)
    second = settlement.settle_game(con, 1)

    assert first["pending"] == second["pending"] == 1
    assert first["void"] == second["void"] == 0
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_generic_invalid_side_remains_retryable(monkeypatch):
    con = _connection("nhl", "goals", side="yes")
    monkeypatch.setattr(espn_client, "boxscore", lambda *args: _boxscore_without_shots())

    first = settlement.settle_game(con, 1)
    second = settlement.settle_game(con, 1)

    assert first["unmappable"] == second["unmappable"] == 1
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0
