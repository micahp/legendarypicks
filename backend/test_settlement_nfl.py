import sqlite3

import espn_client
import settlement


def _database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
          espn_event_id TEXT, final_home INTEGER, final_away INTEGER,
          start_time TEXT
        );
        CREATE TABLE players(
          id INTEGER PRIMARY KEY, name TEXT, team TEXT, espn_id TEXT
        );
        CREATE TABLE props(
          id INTEGER PRIMARY KEY, game_id INTEGER, market TEXT, line REAL,
          side TEXT, player_id INTEGER
        );
        CREATE TABLE prop_results(
          prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
          settled_at TEXT
        );
        INSERT INTO prop_games VALUES
          (1, 'nfl', 'HOU', 'LV', '2026-08-20', '401873286', 20, 22,
           '2026-08-20T23:00:00Z');
        INSERT INTO players VALUES
          (10, 'Fernando Mendoza', 'LV', '4837248'),
          (11, 'Ka''imi Fairbairn', 'HOU', '2971573');
        INSERT INTO props VALUES
          (1, 1, 'passing_yards', 111.5, 'under', 10),
          (2, 1, 'field_goals_made', 1.5, 'over', 11);
    """)
    return con


def _boxscore():
    return {"players": [
        {
            "team": {"abbreviation": "LV"},
            "statistics": [{
                "name": "passing", "labels": ["C/ATT", "YDS"],
                "athletes": [{
                    "athlete": {"id": "4837248", "displayName": "Fernando Mendoza"},
                    "stats": ["8/15", "86"],
                }],
            }],
        },
        {
            "team": {"abbreviation": "HOU"},
            "statistics": [{
                "name": "kicking", "labels": ["FG", "PCT"],
                "athletes": [{
                    "athlete": {"id": "2971573", "displayName": "Ka'imi Fairbairn"},
                    "stats": ["2/2", "100.0"],
                }],
            }],
        },
    ]}


def test_nfl_label_case_and_made_attempted_stats_settle(monkeypatch):
    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())

    assert settlement.settle_game(con, 1) == {
        "settled": 2, "void": 0, "unmappable": 0, "pending": 0, "errors": 0,
    }
    rows = con.execute(
        "SELECT prop_id, actual_value, hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, 86.0, 1), (2, 2.0, 1)]
