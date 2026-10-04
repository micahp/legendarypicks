import datetime as dt
import json
import sqlite3

import espn_client
import ingest_game_summaries
import settlement
from settlement import stored_summary


def _database():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, date TEXT, start_time TEXT,
          espn_event_id TEXT
        );
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
        CREATE TABLE prop_results(prop_id INTEGER PRIMARY KEY);
        CREATE TABLE scoreboard_snapshots(
          league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT
        );
    """)
    return con


def _add_game(con, game_id, event_id, snapshot_state="post"):
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
    con.execute(
        "INSERT INTO prop_games VALUES (?,?,?,?,?)",
        (game_id, "nfl", start[:10], start, event_id),
    )
    con.execute("INSERT INTO props VALUES (?,?)", (game_id, game_id))
    if snapshot_state is not None:
        con.execute(
            "INSERT INTO scoreboard_snapshots VALUES (?,?,?,?,?)",
            ("nfl", event_id, snapshot_state, "{}",
             dt.datetime.now(dt.timezone.utc).isoformat()),
        )
    con.commit()


def _summary(event_id, *, state="post", completed=True):
    return {
        "header": {"competitions": [{
            "id": event_id,
            "status": {"type": {"state": state, "completed": completed}},
        }]},
        "boxscore": {"players": [{"team": {"id": "1"}}]},
    }


def _settlement_database(*, state="post", with_summary=True):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
          espn_event_id TEXT, final_home REAL, final_away REAL, start_time TEXT,
          cancelled_at TEXT, cancel_reason TEXT, cancel_source TEXT
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
        INSERT INTO prop_games VALUES(
          1,'nhl','BOS','NYR','2026-10-03','event-1',NULL,NULL,
          '2026-10-03T20:00:00Z',NULL,NULL,NULL
        );
        INSERT INTO players VALUES(1,'Published Player','BOS','123');
        INSERT INTO props VALUES(1,1,'goals',0.5,'over',1);
    """)
    snapshot = {
        "state": state,
        "completed": state == "post",
        "status": "Final" if state == "post" else "In Progress",
        "status_detail": "Final" if state == "post" else "2nd Period",
        "home": {"abbrev": "BOS", "score": 4},
        "away": {"abbrev": "NYR", "score": 2},
    }
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?)",
        ("nhl", "event-1", state, json.dumps(snapshot),
         dt.datetime.now(dt.timezone.utc).isoformat()),
    )
    if with_summary:
        payload = {
            "header": {"competitions": [{
                "status": {"type": {"state": "post", "completed": True}},
                "competitors": [
                    {"homeAway": "home", "score": "4"},
                    {"homeAway": "away", "score": "2"},
                ],
            }]},
            "boxscore": {"players": [{
                "team": {"abbreviation": "BOS"},
                "statistics": [{
                    "name": "offensive", "labels": ["G", "A"],
                    "athletes": [{
                        "athlete": {"id": "123", "displayName": "Published Player"},
                        "stats": ["1", "0"],
                    }],
                }],
            }]},
        }
        stored_summary.ensure_table(con)
        con.execute(
            "INSERT INTO game_summaries VALUES(?,?,?,?,?,?,?)",
            ("nhl", "event-1", json.dumps(payload), "post", 1,
             dt.datetime.now(dt.timezone.utc).isoformat(), "espn_summary"),
        )
    con.commit()
    return con


def test_stored_summary_reader_returns_none_for_missing_row():
    con = _database()
    assert stored_summary.load(con, "nfl", "missing") is None
    assert stored_summary.boxscore(con, "nfl", "missing") is None


def test_ingest_stores_final_once_and_second_run_fetches_nothing(monkeypatch):
    con = _database()
    _add_game(con, 1, "final")
    calls = []
    monkeypatch.setattr(
        ingest_game_summaries.espn, "summary",
        lambda league, event_id: calls.append((league, event_id)) or _summary(event_id),
    )

    first = ingest_game_summaries.ingest(con)
    second = ingest_game_summaries.ingest(con)

    assert first == {"candidates": 1, "fetched": 1, "stored": 1,
                     "not_final": 0, "failed": 0}
    assert second == {"candidates": 0, "fetched": 0, "stored": 0,
                      "not_final": 0, "failed": 0}
    assert calls == [("nfl", "final")]
    assert stored_summary.load(con, "nfl", "final") == _summary("final")
    assert stored_summary.boxscore(con, "nfl", "final") == {
        "players": [{"team": {"id": "1"}}]
    }


def test_ingest_skips_nonfinal_payload(monkeypatch):
    con = _database()
    _add_game(con, 1, "live")
    monkeypatch.setattr(
        ingest_game_summaries.espn, "summary",
        lambda *_args: _summary("live", state="in", completed=False),
    )

    result = ingest_game_summaries.ingest(con)

    assert result == {"candidates": 1, "fetched": 1, "stored": 0,
                      "not_final": 1, "failed": 0}
    assert stored_summary.load(con, "nfl", "live") is None


def test_ingest_skips_game_without_latest_post_snapshot(monkeypatch):
    con = _database()
    _add_game(con, 1, "pre", snapshot_state="pre")
    calls = []
    monkeypatch.setattr(
        ingest_game_summaries.espn, "summary",
        lambda *args: calls.append(args) or _summary("pre"),
    )

    result = ingest_game_summaries.ingest(con)

    assert result["candidates"] == 0
    assert calls == []


def test_settlement_uses_stored_snapshot_and_summary_without_network(monkeypatch):
    con = _settlement_database()

    def no_network(*_args, **_kwargs):
        raise AssertionError("settlement attempted an ESPN request")

    monkeypatch.setattr(espn_client, "summary", no_network)
    monkeypatch.setattr(espn_client, "boxscore", no_network)
    monkeypatch.setattr(espn_client, "game_result", no_network)
    monkeypatch.setattr(espn_client, "_get", no_network)

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 1, "void": 0, "unmappable": 0,
                      "pending": 0, "errors": 0}
    assert tuple(con.execute(
        "SELECT final_home,final_away FROM prop_games WHERE id=1"
    ).fetchone()) == (4, 2)
    assert tuple(con.execute(
        "SELECT actual_value,hit FROM prop_results WHERE prop_id=1"
    ).fetchone()) == (1.0, 1)


def test_settlement_missing_summary_stays_pending_with_reason():
    con = _settlement_database(with_summary=False)

    result = settlement.settle_game(con, 1)

    assert result["settled"] == 0
    assert result["pending"] == 1
    assert result["msg"] == "game 1: no_stored_summary"


def test_settlement_nonfinal_snapshot_stays_pending():
    con = _settlement_database(state="in", with_summary=False)

    result = settlement.settle_game(con, 1)

    assert result["settled"] == 0
    assert result["pending"] == 1
    assert result["msg"] == "game 1: scoreboard snapshot is in"


def test_settlement_uses_stored_status_text_for_cancellation():
    con = _settlement_database(with_summary=False)
    payload = {
        "state": "post", "completed": False, "status": "Postponed",
        "status_detail": "Postponed", "home": {"score": 0},
        "away": {"score": 0},
    }
    con.execute(
        "UPDATE scoreboard_snapshots SET payload=? WHERE game_id='event-1'",
        (json.dumps(payload),),
    )

    result = settlement.settle_game(con, 1)

    assert result["void"] == 1
    assert tuple(con.execute(
        "SELECT cancel_reason,cancel_source FROM prop_games WHERE id=1"
    ).fetchone()) == ("Postponed", "espn")
    assert tuple(con.execute(
        "SELECT actual_value,hit FROM prop_results WHERE prop_id=1"
    ).fetchone()) == (None, None)
