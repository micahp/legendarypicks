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
          (1, 'ncaaf', 'NCSU', 'UNC', '2026-08-29', '401858202', 21, 17,
           '2026-08-29T19:30:00Z');
        INSERT INTO players VALUES
          (10, 'College Quarterback', 'NCSU', '1001'),
          (11, 'College Running Back', 'NCSU', '1002'),
          (12, 'College Kicker', 'NCSU', '1003');
        INSERT INTO props VALUES
          (1, 1, 'pass_attempts', 24.5, 'over', 10),
          (2, 1, 'pass_completions', 13.5, 'over', 10),
          (3, 1, 'passing_yards', 249.5, 'over', 10),
          (4, 1, 'passing_touchdowns', 1.5, 'over', 10),
          (5, 1, 'interceptions_thrown', 0.5, 'over', 10),
          (6, 1, 'rushing_yards', 19.5, 'over', 10),
          (7, 1, 'rushing_touchdowns', 0.5, 'over', 10),
          (8, 1, 'passing_rushing_yards', 269.5, 'over', 10),
          (9, 1, 'receiving_yards', 29.5, 'over', 11),
          (10, 1, 'receptions', 2.5, 'over', 11),
          (11, 1, 'rush_attempts', 9.5, 'over', 11),
          (12, 1, 'rushing_receiving_yards', 89.5, 'over', 11),
          (13, 1, 'rushing_receiving_touchdowns', 1.5, 'over', 11),
          (14, 1, 'total_touchdowns', 1.5, 'over', 11),
          (15, 1, 'field_goals_made', 1.5, 'over', 12),
          (16, 1, 'extra_points_made', 2.5, 'over', 12),
          (17, 1, 'kicking_points', 8.5, 'over', 12);
    """)
    return con


def _athlete(espn_id, name, stats):
    return {"athlete": {"id": espn_id, "displayName": name}, "stats": stats}


def _boxscore():
    # The boxscore uses NCST while our identity spine uses NCSU. Stable ESPN
    # athlete ids, not a guessed abbreviation alias, own the join.
    return {"players": [{
        "team": {"abbreviation": "NCST"},
        "statistics": [
            {"name": "passing", "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
             "athletes": [_athlete("1001", "College Quarterback", ["14/25", "250", "10", "2", "1"])]},
            {"name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD"],
             "athletes": [
                 _athlete("1001", "College Quarterback", ["5", "20", "4", "1"]),
                 _athlete("1002", "College Running Back", ["10", "60", "6", "1"]),
             ]},
            {"name": "receiving", "labels": ["REC", "YDS", "AVG", "TD"],
             "athletes": [_athlete("1002", "College Running Back", ["3", "30", "10", "1"])]},
            {"name": "kicking", "labels": ["FG", "PCT", "LONG", "XP", "PTS"],
             "athletes": [_athlete("1003", "College Kicker", ["2/2", "100", "45", "3/3", "9"])]},
        ],
    }]}


def test_all_ingested_ncaaf_markets_settle_from_published_boxscore(monkeypatch):
    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())

    assert settlement.settle_game(con, 1) == {
        "settled": 17, "void": 0, "unmappable": 0, "pending": 0, "errors": 0,
    }
    rows = con.execute(
        "SELECT prop_id, actual_value, hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, 25.0, 1), (2, 14.0, 1), (3, 250.0, 1), (4, 2.0, 1),
        (5, 1.0, 1), (6, 20.0, 1), (7, 1.0, 1), (8, 270.0, 1),
        (9, 30.0, 1), (10, 3.0, 1), (11, 10.0, 1), (12, 90.0, 1),
        (13, 2.0, 1), (14, 2.0, 1), (15, 2.0, 1), (16, 3.0, 1),
        (17, 9.0, 1),
    ]
