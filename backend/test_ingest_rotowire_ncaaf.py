import json
import os
import sqlite3
import tempfile

import ingest_rotowire_props as rw


KICKOFF = 1788019200


def _database(path):
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT,
              league TEXT NOT NULL, active INTEGER DEFAULT 1
            );
            CREATE TABLE prop_games(
              id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
              date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,
              start_time TEXT
            );
            CREATE TABLE props(
              id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
              player_id INTEGER, market TEXT NOT NULL, line REAL NOT NULL,
              side TEXT NOT NULL, source TEXT, captured_at TEXT NOT NULL,
              odds INTEGER, odds_captured_at TEXT
            );
            CREATE TABLE unresolved_players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
              first_seen TEXT NOT NULL, count INTEGER DEFAULT 1,
              source_player_key TEXT, reason TEXT
            );
            CREATE TABLE scoreboard_snapshots(league TEXT, payload TEXT);
            """
        )
        con.execute(
            "INSERT INTO players VALUES(1,'Taz Reddicks','UNLV','ncaaf',1)"
        )
        con.execute(
            "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
            (json.dumps({
                "game_id": "401858205",
                "date": "2026-08-29T16:00Z",
                "home": {"abbrev": "UNLV", "name": "UNLV Rebels", "nickname": "Rebels"},
                "away": {"abbrev": "MEM", "name": "Memphis Tigers", "nickname": "Tigers"},
            }),),
        )


def _payload(home="UNLV", away="Memphis"):
    return {
        "markets": [{
            "marketID": 114, "sport": "CFB", "category": "Game",
            "marketName": "Receiving Yards",
        }],
        "entities": [{
            "entityID": 1, "eventID": 1, "sport": "CFB", "name": "Taz Reddicks",
            "team": "UNLV", "pos": "WR",
            "link": "https://www.rotowire.com/cfootball/player/taz-reddicks-42103",
        }],
        "events": [{
            "eventID": 1, "gameID": 38402, "eventTime": KICKOFF,
            "homeTeam": home, "awayTeam": away,
        }],
        "props": [{
            "propID": "cfb-1", "marketID": 114, "entities": [1],
            "lines": [{"book": "prizepicks", "line": 15.5,
                       "over": -137, "under": -137}],
        }],
    }


def test_ncaaf_ingest_requires_and_links_the_published_fixture():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        rw.DB = path
        rows, report = rw.parse(_payload(), "ncaaf")

        summary = rw.ingest(rows, "ncaaf")

        assert report["counts"]["game_props"] == 1
        assert summary["new"] == 2
        assert summary["games"] == 1
        with sqlite3.connect(path) as con:
            assert con.execute(
                "SELECT league,espn_event_id,home,away FROM prop_games"
            ).fetchone() == ("ncaaf", "401858205", "UNLV Rebels", "Memphis Tigers")
            assert con.execute("SELECT COUNT(*) FROM props").fetchone()[0] == 2


def test_ncaaf_ingest_refuses_a_fixture_absent_from_the_scoreboard():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        rw.DB = path
        rows, _ = rw.parse(_payload(home="Ohio State", away="Ball State"), "ncaaf")

        summary = rw.ingest(rows, "ncaaf")

        assert summary["unknown_team"] == 2
        assert summary["new"] == 0
        with sqlite3.connect(path) as con:
            assert con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0] == 0


def test_ncaaf_cross_publisher_school_alias_is_scoped_to_a_scheduled_team():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
                (json.dumps({
                    "game_id": "401858202", "date": "2026-08-29T19:30Z",
                    "home": {"abbrev": "UVA", "name": "Virginia Cavaliers",
                             "nickname": "Cavaliers"},
                    "away": {"abbrev": "NCSU", "name": "NC State Wolfpack",
                             "nickname": "Wolfpack"},
                }),),
            )
            con.row_factory = sqlite3.Row
            vocabulary = rw.team_vocabulary(con, "ncaaf")
            assert rw.resolve_team(vocabulary, "North Carolina State") == "NCSU"


def test_ncaaf_official_nickname_alias_is_team_scoped():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "INSERT INTO players VALUES(2,'Jayden Scott','NCSU','ncaaf',1)"
            )
            row = {
                "source_player_key": "46363", "player_name": "Duke Scott",
                "team": "North Carolina State",
            }
            assert rw.resolve_player(
                con, "ncaaf", row, "2026-08-29T00:00:00Z", "NCSU"
            ) == 2


def test_multi_league_runner_fetches_the_relay_once(monkeypatch):
    fetched = []
    ingested = []
    payload = {"props": []}

    def fake_fetch():
        fetched.append(True)
        return payload, b"{}"

    def fake_ingest_payload(received, league, dry_run=False, captured_at=None):
        ingested.append((received, league, dry_run, captured_at))
        return 0

    monkeypatch.setattr(rw.archive, "fetch", fake_fetch)
    monkeypatch.setattr(rw, "ingest_payload", fake_ingest_payload)

    assert rw.main(["nfl", "mls", "ncaaf", "--dry-run"]) == 0
    assert len(fetched) == 1
    assert [(league, dry) for _, league, dry, _ in ingested] == [
        ("nfl", True), ("mls", True), ("ncaaf", True),
    ]


def test_archive_replay_cannot_replace_a_newer_live_line():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        rw.DB = path
        rows, _ = rw.parse(_payload(), "ncaaf")
        rw.ingest(rows, "ncaaf", captured_at="2026-08-29T18:00:00+00:00")

        older = rw.ingest(
            rows, "ncaaf", captured_at="2026-08-29T07:32:56+00:00")

        assert older["stale_archive"] == 2
        with sqlite3.connect(path) as con:
            assert con.execute(
                "SELECT DISTINCT captured_at FROM props"
            ).fetchall() == [("2026-08-29T18:00:00+00:00",)]
