import json
import sqlite3

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
        CREATE TABLE game_summaries(
          league TEXT, espn_event_id TEXT, payload TEXT, state TEXT,
          completed INTEGER, fetched_at TEXT, source TEXT,
          PRIMARY KEY(league, espn_event_id)
        );
        INSERT INTO prop_games VALUES
          (1, 'nfl', 'HOU', 'LV', '2026-08-20', '401873286', 20, 22,
           '2026-08-20T23:00:00Z');
        INSERT INTO players VALUES
          (10, 'Fernando Mendoza', 'LV', '4837248'),
          (11, 'Ka''imi Fairbairn', 'HOU', '2971573'),
          (12, 'Example Receiver', 'LV', '1200'),
          (13, 'Example Defender', 'HOU', '1300'),
          (14, 'Example Runner', 'LV', '1400');
        INSERT INTO props VALUES
          (1, 1, 'passing_yards', 111.5, 'under', 10),
          (2, 1, 'field_goals_made', 1.5, 'over', 11);
    """)
    con.execute(
        "INSERT INTO game_summaries VALUES (?,?,?,?,?,?,?)",
        ("nfl", "401873286", json.dumps({"boxscore": _boxscore()}),
         "post", 1, "2026-08-20T23:00:00Z", "test"),
    )
    return con


def _boxscore():
    return {"players": [
        {
            "team": {"abbreviation": "LV"},
            "statistics": [{
                "name": "passing",
                "labels": ["C/ATT", "YDS", "AVG", "TD", "INT", "SACKS"],
                "athletes": [{
                    "athlete": {"id": "4837248", "displayName": "Fernando Mendoza"},
                    "stats": ["8/15", "86", "5.7", "2", "1", "1-5"],
                }],
            }, {
                "name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD", "LONG"],
                "athletes": [
                    {"athlete": {"id": "4837248", "displayName": "Fernando Mendoza"},
                     "stats": ["4", "20", "5.0", "1", "12"]},
                    {"athlete": {"id": "1400", "displayName": "Example Runner"},
                     "stats": ["10", "60", "6.0", "2", "20"]},
                ],
            }, {
                "name": "receiving", "labels": ["REC", "YDS", "AVG", "TD", "LONG", "TGTS"],
                "athletes": [
                    {"athlete": {"id": "1200", "displayName": "Example Receiver"},
                     "stats": ["5", "70", "14.0", "1", "30", "8"]},
                    {"athlete": {"id": "1400", "displayName": "Example Runner"},
                     "stats": ["2", "15", "7.5", "0", "9", "3"]},
                ],
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
            }, {
                "name": "defensive",
                "labels": ["TOT", "SOLO", "SACKS", "TFL", "PD", "QB HTS", "TD"],
                "athletes": [{
                    "athlete": {"id": "1300", "displayName": "Example Defender"},
                    "stats": ["5", "4", "2", "1", "0", "3", "1"],
                }],
            }],
        },
    ]}


def test_nfl_label_case_and_made_attempted_stats_settle():
    con = _database()

    assert settlement.settle_game(con, 1) == {
        "settled": 2, "void": 0, "unmappable": 0, "pending": 0, "errors": 0,
    }
    rows = con.execute(
        "SELECT prop_id, actual_value, hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, 86.0, 1), (2, 2.0, 1)]


def test_requested_nfl_markets_settle_from_stored_boxscore():
    con = _database()
    # ESPN publishes kicking PTS in the real summary. Add it to this stored
    # fixture without changing the production-shaped category or athlete.
    payload = json.loads(con.execute(
        "SELECT payload FROM game_summaries WHERE league='nfl'"
    ).fetchone()[0])
    kicking = payload["boxscore"]["players"][1]["statistics"][0]
    kicking["labels"] += ["LONG", "XP", "PTS"]
    kicking["athletes"][0]["stats"] += ["52", "3/3", "9"]
    con.execute("UPDATE game_summaries SET payload=?", (json.dumps(payload),))

    rows = [
        (10, "passing_rushing_yards", 105.5, 10),
        (11, "rush_attempts", 9.5, 14),
        (12, "pass_attempts", 14.5, 10),
        (13, "pass_completions", 7.5, 10),
        (14, "passing_touchdowns", 1.5, 10),
        (15, "longest_reception", 29.5, 12),
        (16, "kicking_points", 8.5, 11),
        (17, "interceptions_thrown", 0.5, 10),
        (18, "targets", 7.5, 12),
        (19, "sacks", 1.5, 13),
        (20, "total_rush_attempts", 9.5, 14),
        (21, "total_passing_attempts", 14.5, 10),
        (22, "total_touchdowns", 0.5, 12),
        (23, "total_kicking_points", 8.5, 11),
        (24, "longest_rushing_attempt", 19.5, 14),
        (25, "rushing_receiving_yards", 74.5, 14),
    ]
    con.executemany(
        "INSERT INTO props VALUES (?,1,?,?,'over',?)", rows)

    assert settlement.settle_game(con, 1) == {
        "settled": 18, "void": 0, "unmappable": 0, "pending": 0, "errors": 0,
    }
    actual = dict(con.execute(
        "SELECT p.market,r.actual_value FROM props p JOIN prop_results r "
        "ON r.prop_id=p.id WHERE p.id>=10"
    ))
    assert actual == {
        "passing_rushing_yards": 106.0,
        "rush_attempts": 10.0,
        "pass_attempts": 15.0,
        "pass_completions": 8.0,
        "passing_touchdowns": 2.0,
        "longest_reception": 30.0,
        "kicking_points": 9.0,
        "interceptions_thrown": 1.0,
        "targets": 8.0,
        "sacks": 2.0,
        "total_rush_attempts": 10.0,
        "total_passing_attempts": 15.0,
        "total_touchdowns": 1.0,
        "total_kicking_points": 9.0,
        "longest_rushing_attempt": 20.0,
        "rushing_receiving_yards": 75.0,
    }
