import asyncio
import datetime as dt
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import routers.games as games
from routers.games import predictions


PREDICTION_COLUMNS = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    predicted_winner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    correct INTEGER,
    device_id TEXT,
    match_key TEXT,
    side TEXT,
    team_a TEXT,
    team_b TEXT,
    event_date TEXT,
    created_at_ms INTEGER,
    lock_at INTEGER,
    settled_at INTEGER,
    result TEXT,
    points REAL,
    crowd_share_at_lock REAL
"""


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _payload(game_id, start, state="pre", home_score=None, away_score=None, winner=None):
    return json.dumps({
        "game_id": game_id,
        "date": start,
        "state": state,
        "home": {"name": "Home", "abbrev": "HOM", "score": home_score, "winner": winner == "home", "seed": 1},
        "away": {"name": "Away", "abbrev": "AWY", "score": away_score, "winner": winner == "away"},
    })


def _create_db(path):
    with closing(sqlite3.connect(path)) as con:
        con.execute(f"CREATE TABLE predictions ({PREDICTION_COLUMNS})")
        con.execute("""CREATE TABLE scoreboard_snapshots (
            league TEXT, game_date TEXT, game_id TEXT, payload TEXT,
            state TEXT, start_time TEXT, fetched_at TEXT
        )""")
        con.execute("""CREATE TABLE prop_games (
            id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT,
            espn_event_id TEXT, start_time TEXT
        )""")


def _connection(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _body(response):
    return json.loads(response.body)


def test_stored_slate_uses_nearest_day_and_supports_soccer_draw(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    now = dt.datetime.now(dt.timezone.utc)
    first = now + dt.timedelta(hours=2)
    later = now + dt.timedelta(days=1)
    with closing(_connection(path)) as con:
        for game_id, start in (("one", first), ("two", later)):
            iso = start.isoformat()
            con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", (
                "mls", start.date().isoformat(), game_id, _payload(game_id, iso), "pre", iso, iso,
            ))
        con.commit()
    with patch.object(games, "_db", lambda: _connection(path)):
        slate, source = predictions._sports_slate("mls", int(now.timestamp() * 1000))
    assert source == "scoreboard_snapshots"
    assert [match["gameId"] for match in slate] == ["one"]
    assert slate[0]["allowDraw"] is True
    assert slate[0]["seedA"] is None
    assert slate[0]["seedB"] == 1


def test_prop_fallback_requires_exact_publisher_event_id(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
    with closing(_connection(path)) as con:
        con.execute("INSERT INTO prop_games VALUES(1,'nfl',?,'Home','Away','',?)", (start.date().isoformat(), start.isoformat()))
        con.execute("INSERT INTO prop_games VALUES(2,'nfl',?,'Home','Away','event-2',?)", (start.date().isoformat(), start.isoformat()))
        con.commit()
    with patch.object(games, "_db", lambda: _connection(path)):
        slate, source = predictions._sports_slate("nfl")
    assert source == "prop_games"
    assert [match["gameId"] for match in slate] == ["event-2"]


def test_pick_upserts_per_device_and_reveals_crowd(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    iso = start.isoformat()
    with closing(_connection(path)) as con:
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", ("mls", start.date().isoformat(), "one", _payload("one", iso), "pre", iso, iso))
        con.commit()
    with patch.object(games, "_db", lambda: _connection(path)):
        first = asyncio.run(predictions.post_sports_pick(FakeRequest({"league": "mls", "matchKey": "mls:one", "side": "A"}), "device-1"))
        changed = asyncio.run(predictions.post_sports_pick(FakeRequest({"league": "mls", "matchKey": "mls:one", "side": "D"}), "device-1"))
        other = asyncio.run(predictions.post_sports_pick(FakeRequest({"league": "mls", "matchKey": "mls:one", "side": "B"}), "device-2"))
        crowd = predictions.get_sports_crowd("mls", "mls:one")
    assert first.status_code == changed.status_code == other.status_code == 200
    assert _body(crowd) == {"countA": 0, "countB": 1, "countDraw": 1, "total": 2, "shareA": 0.0}
    with closing(_connection(path)) as con:
        assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 2


def test_non_soccer_draw_is_rejected(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    iso = start.isoformat()
    with closing(_connection(path)) as con:
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", ("nba", start.date().isoformat(), "one", _payload("one", iso), "pre", iso, iso))
        con.commit()
    with patch.object(games, "_db", lambda: _connection(path)):
        response = asyncio.run(predictions.post_sports_pick(FakeRequest({"league": "nba", "matchKey": "nba:one", "side": "D"}), "device"))
    assert response.status_code == 400
    assert _body(response)["error"] == "draw is not an outcome for this league"


def test_stored_final_settles_without_publisher_fetch(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    ended = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    iso = ended.isoformat()
    with closing(_connection(path)) as con:
        for device, side in (("minority", "A"), ("majority-1", "B"), ("majority-2", "B")):
            con.execute("""INSERT INTO predictions(
                league,game_id,predicted_winner,created_at,device_id,match_key,side,
                team_a,team_b,event_date,created_at_ms,lock_at
            ) VALUES('nba','final','x',?,?,?,?,?,?,?,?,?)""", (iso, device, "nba:final", side, "Away", "Home", ended.date().isoformat(), 1, 2))
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", ("nba", ended.date().isoformat(), "final", _payload("final", iso, "post", "91", "100", "away"), "post", iso, iso))
        con.commit()
    with patch.object(games, "_db", lambda: _connection(path)):
        assert predictions.settle_sports_picks() == {
            "settled": 3, "voided": 0, "pending": 0, "unsettleable": [],
        }
    with closing(_connection(path)) as con:
        rows = con.execute("SELECT device_id,result,points FROM predictions ORDER BY device_id").fetchall()
    assert [(row["device_id"], row["result"]) for row in rows] == [("majority-1", "loss"), ("majority-2", "loss"), ("minority", "win")]
    assert rows[2]["points"] > 1.0


def test_non_draw_league_ties_void_both_sides_end_to_end(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    ended = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    iso = ended.isoformat()
    leagues = ("nfl", "ncaaf", "nba", "mlb", "nhl", "wnba", "atp", "wta")
    with closing(_connection(path)) as con:
        for league in leagues:
            for side in ("A", "B"):
                con.execute("""INSERT INTO predictions(
                    league,game_id,predicted_winner,created_at,device_id,match_key,side,
                    team_a,team_b,event_date,created_at_ms,lock_at
                ) VALUES(?,?, 'x',?,?,?,?,?,?,?,?,?)""", (
                    league, f"{league}-tie", iso, f"{league}-{side}",
                    f"{league}:{league}-tie", side, "Away", "Home",
                    ended.date().isoformat(), 1, 2,
                ))
            con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", (
                league, ended.date().isoformat(), f"{league}-tie",
                _payload(f"{league}-tie", iso, "post", "17", "17"),
                "post", iso, iso,
            ))
        con.commit()

    with patch.object(games, "_db", lambda: _connection(path)):
        report = predictions.settle_sports_picks()

    assert report == {
        "settled": 16, "voided": 16, "pending": 0, "unsettleable": [],
    }
    with closing(_connection(path)) as con:
        rows = con.execute(
            "SELECT settled_at,result,points,correct FROM predictions ORDER BY id"
        ).fetchall()
    assert all(row["settled_at"] is not None for row in rows)
    assert all(row["result"] == "void" for row in rows)
    assert all(row["points"] is None and row["correct"] is None for row in rows)


def test_settlement_reports_unsettleable_final_and_retryable_pending(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    ended = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    iso = ended.isoformat()
    with closing(_connection(path)) as con:
        for game_id in ("broken", "waiting"):
            con.execute("""INSERT INTO predictions(
                league,game_id,predicted_winner,created_at,device_id,match_key,side,
                team_a,team_b,event_date,created_at_ms,lock_at
            ) VALUES('nfl',?,'x',?,'device',?,'A','Away','Home',?,1,2)""", (
                game_id, iso, f"nfl:{game_id}", ended.date().isoformat(),
            ))
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", (
            "nfl", ended.date().isoformat(), "broken", "{not-json", "post", iso, iso,
        ))
        con.commit()

    with patch.object(games, "_db", lambda: _connection(path)):
        report = predictions.settle_sports_picks()

    assert report == {
        "settled": 0,
        "voided": 0,
        "pending": 1,
        "unsettleable": [{
            "league": "nfl", "gameId": "broken", "matchKey": "nfl:broken",
            "reason": "invalid_snapshot_json",
        }],
    }


def test_get_my_picks_is_read_only_and_post_settles(tmp_path):
    path = tmp_path / "predict.db"
    _create_db(path)
    ended = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    iso = ended.isoformat()
    with closing(_connection(path)) as con:
        con.execute("""INSERT INTO predictions(
            league,game_id,predicted_winner,created_at,device_id,match_key,side,
            team_a,team_b,event_date,created_at_ms,lock_at
        ) VALUES('nba','final','x',?,'device','nba:final','A','Away','Home',?,1,2)""", (
            iso, ended.date().isoformat(),
        ))
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?)", (
            "nba", ended.date().isoformat(), "final",
            _payload("final", iso, "post", "91", "100", "away"),
            "post", iso, iso,
        ))
        con.commit()

    with patch.object(games, "_db", lambda: _connection(path)):
        before = _body(predictions.get_my_sports_picks(None, "device"))
        settled = _body(predictions.settle_sports_picks_endpoint())
        after = _body(predictions.get_my_sports_picks(None, "device"))

    assert before["picks"][0]["settledAt"] is None
    assert before["picks"][0]["result"] is None
    assert settled == {
        "settled": 1, "voided": 0, "pending": 0, "unsettleable": [],
    }
    assert after["picks"][0]["result"] == "win"
