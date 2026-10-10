import json
import sqlite3

import repair_ncaaf_prop_games as repair


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE scoreboard_snapshots(league TEXT,payload TEXT);
        CREATE TABLE prop_games(
            id INTEGER PRIMARY KEY,league TEXT,date TEXT,home TEXT,away TEXT,
            espn_event_id TEXT,start_time TEXT
        );
        CREATE TABLE props(id INTEGER PRIMARY KEY,game_id INTEGER,source TEXT);
        CREATE TABLE prop_game_source_ids(
            id INTEGER PRIMARY KEY,source TEXT,league TEXT,
            source_game_key TEXT,game_id INTEGER
        );
        """
    )
    game = {
        "game_id": "event-1",
        "date": "2099-10-10T01:00:00Z",
        "home": {"abbrev": "WASH", "name": "Washington Huskies",
                 "nickname": "Huskies"},
        "away": {"abbrev": "IOWA", "name": "Iowa Hawkeyes",
                 "nickname": "Hawkeyes"},
    }
    connection.execute(
        "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
        (json.dumps(game),),
    )
    connection.execute(
        "INSERT INTO prop_games VALUES(1,'ncaaf','2099-10-09',"
        "'Washington Huskies','Iowa Hawkeyes','event-1','2099-10-10T01:00:00Z')"
    )
    connection.execute(
        "INSERT INTO prop_games VALUES(2,'ncaaf','2099-10-09',"
        "'Washington','Iowa (#20)','', '2099-10-10T01:00:00+00:00')"
    )
    connection.executemany(
        "INSERT INTO props VALUES(?,?,?)",
        [(10, 1, "rotowire:p"), (11, 2, "bovada")],
    )
    connection.execute(
        "INSERT INTO prop_game_source_ids VALUES(1,'rotowire','ncaaf','key',1)"
    )
    return connection


def test_plan_is_read_only_and_finds_the_published_event_holder():
    connection = _connection()
    actions, unresolved = repair.plan(connection)

    assert unresolved == []
    assert actions == [{
        "loser_id": 2,
        "winner_id": 1,
        "event_id": "event-1",
        "home": "Washington Huskies",
        "away": "Iowa Hawkeyes",
        "start_time": "2099-10-10T01:00:00Z",
        "prop_count": 1,
    }]
    assert connection.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0] == 2


def test_apply_folds_games_and_preserves_every_prop_and_source_mapping():
    connection = _connection()
    actions, _ = repair.plan(connection)

    repair.apply(connection, actions)

    games = connection.execute(
        "SELECT id,home,away,espn_event_id FROM prop_games"
    ).fetchall()
    assert [tuple(row) for row in games] == [
        (1, "Washington Huskies", "Iowa Hawkeyes", "event-1")
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM props WHERE game_id=1"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM prop_game_source_ids WHERE game_id=1"
    ).fetchone()[0] == 1
