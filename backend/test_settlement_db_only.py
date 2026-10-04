import datetime as dt
import json
import sqlite3

import ingest_game_summaries
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
