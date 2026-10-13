"""NCAAF prop identity: step 2 of the 2026-10-02 repair order, Bovada/API path.

`_resolve_player_for_ingest` serves `/api/props/ingest` (the Bovada scraper's write
path). The strict rule — source team = roster team = one fixture team — applies to
its NCAAF resolutions without changing any other league's behavior.
"""
import json
import os
import sqlite3
import tempfile

import _core


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
            CREATE TABLE name_alias(
              id INTEGER PRIMARY KEY AUTOINCREMENT, alias TEXT,
              alias_norm TEXT, player_id INTEGER
            );
            """
        )
        con.execute(
            "INSERT INTO scoreboard_snapshots VALUES('ncaaf',?)",
            (json.dumps({
                "game_id": "401856702",
                "date": "2026-09-05T23:00Z",
                "home": {"abbrev": "LSU", "name": "LSU Tigers", "nickname": "Tigers"},
                "away": {"abbrev": "OM", "name": "Ole Miss Rebels",
                         "nickname": "Rebels"},
            }),),
        )


def test_ncaaf_sole_wrong_team_name_is_refused_even_in_a_known_fixture():
    # Winston Watkins, measured in the 10-02 diagnosis: a unique league-wide name
    # whose spine row is Towson, filed onto LSU fixtures because sole matches were
    # accepted before any team probe.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO players VALUES(1,'Winston Watkins','TOW','ncaaf',1)")
            con.execute(
                "INSERT INTO prop_games(id,league,date,home,away) "
                "VALUES(1,'ncaaf','2026-09-05','LSU Tigers','Ole Miss Rebels')")
            picked = _core._resolve_player_for_ingest(
                con, "Winston Watkins", "LSU", "ncaaf", game_id=1)
            assert picked == (None, None)
            assert con.execute(
                "SELECT source FROM unresolved_players WHERE raw_name=?",
                ("Winston Watkins",)).fetchone()[0] == "props"


def test_ncaaf_a_sole_team_verified_name_still_resolves():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO players VALUES(1,'Corey Simms','LSU','ncaaf',1)")
            con.execute(
                "INSERT INTO prop_games(id,league,date,home,away) "
                "VALUES(1,'ncaaf','2026-09-05','LSU Tigers','Ole Miss Rebels')")
            picked = _core._resolve_player_for_ingest(
                con, "Corey Simms", "LSU", "ncaaf", game_id=1)
            assert picked == (1, "high")


def test_ncaaf_fixture_membership_alone_can_resolve_a_missing_team_word():
    # The source's team parenthetical is the first probe; the fixture's two teams
    # are the second. The ncaaf vocabulary comes from the stored scoreboard
    # snapshots because no static 137-school map exists.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO players VALUES(1,'Corey Simms','LSU','ncaaf',1)")
            con.execute(
                "INSERT INTO prop_games(id,league,date,home,away) "
                "VALUES(1,'ncaaf','2026-09-05','LSU Tigers','Ole Miss Rebels')")
            picked = _core._resolve_player_for_ingest(
                con, "Corey Simms", "", "ncaaf", game_id=1)
            assert picked == (1, "high")


def test_other_leagues_keep_accepting_a_sole_league_wide_name():
    # The strict rule is NCAAF-scoped. Every other league's resolver behavior —
    # including its sole-candidate acceptance — stands untouched.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO players VALUES(1,'Wrong Team Wearer','TOW','mlb',1)")
            picked = _core._resolve_player_for_ingest(
                con, "Wrong Team Wearer", "BOS", "mlb")
            assert picked == (1, "high")


def test_ncaaf_a_reviewed_alias_still_honors_the_strict_team_rule():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO players VALUES(1,'Jayden Scott','TOW','ncaaf',1)")
            con.execute(
                "INSERT INTO name_alias(alias,alias_norm,player_id) "
                "VALUES('Duke Scott','duke scott',1)")
            picked = _core._resolve_player_for_ingest(
                con, "Duke Scott", "LSU", "ncaaf", game_id=1)
            assert picked == (None, None)


def test_game_team_abbrevs_uses_the_stored_scoreboard_vocabulary_for_ncaaf():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "picks.db")
        _database(path)
        _core._GAME_TEAM_VOCAB_CACHE.clear()
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                "INSERT INTO prop_games(id,league,date,home,away) "
                "VALUES(1,'ncaaf','2026-09-05','LSU Tigers','Ole Miss Rebels')")
            assert _core._game_team_abbrevs(con, 1, "ncaaf") == {"LSU", "OM"}
