import json
import sqlite3

from routers.props import _ncaaf_slate_display


def _connection(rank):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE prop_games(
            id INTEGER PRIMARY KEY,league TEXT,espn_event_id TEXT
        );
        CREATE TABLE scoreboard_snapshots(
            league TEXT,game_id TEXT,payload TEXT
        );
        INSERT INTO prop_games VALUES(1,'ncaaf','event-1');
        """
    )
    payload = {
        "home": {"name": "Washington Huskies"},
        "away": {"name": "Iowa Hawkeyes", "rank": rank},
    }
    connection.execute(
        "INSERT INTO scoreboard_snapshots VALUES('ncaaf','event-1',?)",
        (json.dumps(payload),),
    )
    return connection


def test_ncaaf_slate_uses_published_full_names_and_rank():
    assert _ncaaf_slate_display(_connection(20), [1]) == {
        1: {
            "home": "Washington Huskies",
            "away": "Iowa Hawkeyes",
            "away_rank": 20,
        }
    }


def test_ncaaf_slate_rejects_non_published_rank_values():
    assert _ncaaf_slate_display(_connection(26), [1]) == {
        1: {"home": "Washington Huskies", "away": "Iowa Hawkeyes"}
    }
