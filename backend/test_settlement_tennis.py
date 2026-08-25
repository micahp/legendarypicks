import json
import sqlite3

import espn_client
import settlement


def _database(state="post", home_score=2, away_score=1):
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
        CREATE TABLE scoreboard_snapshots(
          league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT
        );
        INSERT INTO prop_games VALUES
          (1, 'atp', 'Stefanos Tsitsi', 'Jenson Broo', '2026-08-24',
           'match-1', NULL, NULL, '2026-08-24T22:30:00Z');
        INSERT INTO players VALUES
          (10, 'Stefanos Tsitsipas', 'ATP', NULL),
          (11, 'Jenson Brooksby', 'ATP', NULL);
    """)
    payload = {
        "home": {"name": "Stefanos Tsitsipas", "score": home_score,
                 "sets": [6, 4, 6]},
        "away": {"name": "Jenson Brooksby", "score": away_score,
                 "sets": [4, 6, 3]},
    }
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES (?,?,?,?,?)",
        ("atp", "match-1", state, json.dumps(payload), "2026-08-24T23:59:00Z"),
    )
    props = [
        (1, 1, "match_winner", 0.5, "over", 10),
        (2, 1, "match_winner", 0.5, "over", 11),
        (3, 1, "total_games", 15.5, "over", 10),
        (4, 1, "total_games", 13.5, "under", 11),
        (5, 1, "win_a_set", 0.5, "over", 11),
        (6, 1, "set_betting___2_1", 0.5, "over", 10),
        (7, 1, "set_betting___2_0", 0.5, "over", 10),
    ]
    con.executemany("INSERT INTO props VALUES (?,?,?,?,?,?)", props)
    con.commit()
    return con


def test_tennis_settles_all_published_markets_without_a_live_pull(monkeypatch):
    con = _database()
    monkeypatch.setattr(
        espn_client, "game_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live pull")),
    )
    monkeypatch.setattr(
        espn_client, "boxscore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live pull")),
    )

    assert settlement.settle_game(con, 1) == {
        "settled": 7, "void": 0, "unmappable": 0, "pending": 0, "errors": 0,
    }
    rows = con.execute(
        "SELECT prop_id, actual_value, hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, 1.0, 1), (2, 0.0, 0), (3, 16.0, 1), (4, 13.0, 1),
        (5, 1.0, 1), (6, 1.0, 1), (7, 0.0, 0),
    ]


def test_tennis_nonfinal_or_incomplete_snapshot_stays_pending():
    live = _database(state="in")
    assert settlement.settle_game(live, 1)["settled"] == 0
    assert live.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0

    retired = _database(home_score=1, away_score=1)
    result = settlement.settle_game(retired, 1)
    assert result["settled"] == 0
    assert result["pending"] == 7
    assert retired.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0
