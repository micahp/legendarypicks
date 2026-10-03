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
              league TEXT NOT NULL, active INTEGER DEFAULT 1, position TEXT
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
            "INSERT INTO players VALUES(1,'Taz Reddicks','UNLV','ncaaf',1,NULL)"
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
                "INSERT INTO players VALUES(2,'Jayden Scott','NCSU','ncaaf',1,NULL)"
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


NOW = "2026-10-03T00:30:00+00:00"


def test_ncaaf_a_stale_binding_is_revalidated_onto_the_team_verified_row():
    # Jack Stevens, measured in the 10-02 diagnosis: the RotoWire key was bound to
    # the sole then-visible Stevens, a Wagner player, and every later run kept
    # returning him after the real Washington State row arrived.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "INSERT INTO players VALUES(2,'Jack Stevens','WAG','ncaaf',1,NULL)")
            con.execute(
                "INSERT INTO players VALUES(3,'Jack Stevens','WSU','ncaaf',1,'WR')")
            con.execute(
                "INSERT INTO player_source_ids(source,league,source_player_key,"
                "player_id,first_seen,last_seen) VALUES('rotowire','ncaaf','9001',2,"
                "'2026-09-06T03:05:05Z','2026-09-06T03:05:05Z')")
            row = {
                "source_player_key": "9001", "player_name": "Jack Stevens",
                "team": "Washington State", "position": "WR",
            }
            assert rw.resolve_player(con, "ncaaf", row, NOW, "WSU") == 3
            assert con.execute(
                "SELECT player_id FROM player_source_ids "
                "WHERE source_player_key='9001'").fetchone()[0] == 3


def test_ncaaf_a_sole_wrong_team_name_is_queued_never_published():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "INSERT INTO players VALUES(2,'Winston Watkins','TOW','ncaaf',1,'WR')")
            row = {
                "source_player_key": "9002", "player_name": "Winston Watkins",
                "team": "LSU", "position": "WR",
            }
            assert rw.resolve_player(con, "ncaaf", row, NOW, "LSU") is None
            assert con.execute(
                "SELECT reason FROM unresolved_players "
                "WHERE source_player_key='9002'").fetchone()[0] == "not_in_spine"
            assert con.execute(
                "SELECT COUNT(*) FROM player_source_ids "
                "WHERE source_player_key='9002'").fetchone()[0] == 0


def test_ncaaf_an_unresolvable_relay_team_queues_instead_of_guessing():
    # The relay names a school the stored scoreboard vocabulary cannot resolve:
    # nothing downstream can verify source team = roster team, so the name is
    # refused even though the spine holds exactly one person by it.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "INSERT INTO players VALUES(2,'Phil Terence','CLEM','ncaaf',1,'LB')")
            row = {
                "source_player_key": "9003", "player_name": "Phil Terence",
                "team": "Clemson", "position": "LB",
            }
            assert rw.resolve_player(con, "ncaaf", row, NOW, None) is None
            assert con.execute(
                "SELECT reason FROM unresolved_players "
                "WHERE source_player_key='9003'").fetchone()[0] == "unverified_team"


def test_ncaaf_position_narrows_two_same_team_candidates():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "INSERT INTO players VALUES(2,'Chris Ford','UNLV','ncaaf',1,'CB')")
            con.execute(
                "INSERT INTO players VALUES(3,'Chris Ford','UNLV','ncaaf',1,'WR')")
            row = {
                "source_player_key": "9004", "player_name": "Chris Ford",
                "team": "UNLV", "position": "WR",
            }
            assert rw.resolve_player(con, "ncaaf", row, NOW, "UNLV") == 3


def test_ncaaf_a_position_mismatch_never_disqualifies_a_sole_team_match():
    # Position is the secondary guard: it narrows, it does not veto. Publishers
    # disagree about positions (PK/K, DB/CB), so a sole team-verified match stands
    # even when the relay's position word differs.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            rw.ensure_schema(con)
            con.execute(
                "UPDATE players SET position='CB' WHERE id=1")
            row = {
                "source_player_key": "9005", "player_name": "Taz Reddicks",
                "team": "UNLV", "position": "WR",
            }
            assert rw.resolve_player(con, "ncaaf", row, NOW, "UNLV") == 1


def test_ncaaf_publish_refuses_a_player_on_neither_fixture_team():
    # Third edge of the strict rule: the canonical player's roster team must be one
    # of the fixture's two teams before the prop is written. This catches a stale
    # binding and any other path that never saw the relay's team word.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        rw.DB = path
        with sqlite3.connect(path) as con:
            con.execute(
                "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
                (json.dumps({
                    "game_id": "401858206",
                    "date": "2026-08-29T16:00Z",
                    "home": {"abbrev": "WSU",
                             "name": "Washington State Cougars",
                             "nickname": "Cougars"},
                    "away": {"abbrev": "MEM", "name": "Memphis Tigers",
                             "nickname": "Tigers"},
                }),),
            )
        rows, report = rw.parse(_payload(home="Washington State"), "ncaaf")
        assert report["counts"]["game_props"] == 1

        summary = rw.ingest(rows, "ncaaf")

        assert summary["wrong_team_rows"] == 2
        assert summary["new"] == 0
        with sqlite3.connect(path) as con:
            assert con.execute("SELECT COUNT(*) FROM props").fetchone()[0] == 0
            assert con.execute(
                "SELECT DISTINCT reason FROM unresolved_players"
            ).fetchall() == [("wrong_team",)]
