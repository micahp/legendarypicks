import json
import sqlite3

from link_prop_games import link_prop_game


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE scoreboard_snapshots(league TEXT,payload TEXT)"
    )
    for game in _games():
        connection.execute(
            "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
            (json.dumps(game),),
        )
    return connection


def _games():
    return [
        {
            "game_id": "ranked",
            "date": "2026-10-10T01:00:00Z",
            "home": {
                "abbrev": "WASH", "name": "Washington Huskies",
                "nickname": "Huskies",
            },
            "away": {
                "abbrev": "IOWA", "name": "Iowa Hawkeyes",
                "nickname": "Hawkeyes",
            },
        },
        {
            "game_id": "renamed",
            "date": "2026-10-08T23:00:00Z",
            "home": {
                "abbrev": "LIB", "name": "Liberty Flames",
                "nickname": "Flames",
            },
            "away": {
                "abbrev": "SHSU", "name": "Sam Houston Bearkats",
                "nickname": "Bearkats",
            },
        },
    ]


def _row(connection, home, away, start):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS candidate("
        "league TEXT,home TEXT,away TEXT,start_time TEXT)"
    )
    connection.execute("DELETE FROM candidate")
    connection.execute(
        "INSERT INTO candidate VALUES('ncaaf',?,?,?)", (home, away, start)
    )
    return connection.execute("SELECT * FROM candidate").fetchone()


def test_school_names_and_rank_suffix_link_to_full_espn_names():
    connection = _connection()
    row = _row(
        connection, "Washington", "Iowa (#20)",
        "2026-10-10T01:00:00+00:00",
    )
    assert link_prop_game(connection, row, _games()) == "ranked"


def test_reviewed_former_school_name_links_to_current_espn_name():
    connection = _connection()
    row = _row(
        connection, "Liberty", "Sam Houston State",
        "2026-10-08T23:00:00+00:00",
    )
    assert link_prop_game(connection, row, _games()) == "renamed"


def test_unknown_school_fails_closed():
    connection = _connection()
    row = _row(
        connection, "Washington", "Imaginary State",
        "2026-10-10T01:00:00+00:00",
    )
    assert link_prop_game(connection, row, _games()) == ""
