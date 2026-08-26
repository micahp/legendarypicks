#!/usr/bin/env python3
"""The lazy Liga MX form endpoint, and the write it leaves behind.

Liga MX has no season ingest, so its athletes charted three Leagues Cup games
against an MLS player's forty-two. This endpoint reads five matches from ESPN on
a click and STORES them, so the chart fills in from ordinary use.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="soccer-form-", suffix=".db",
                                         delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers.games import soccer_form  # noqa: E402

_MATCHES = [
    {"date": "2026-08-22", "event_id": "401877008", "matchup": "AME @ JUA",
     "home": False, "minutes": 90.0, "goals": 1.0, "assists": 0.0,
     "shots": 3.0, "shots_on_target": 2.0, "tackles": 4.0, "clearances": 1.0,
     "crosses": 0.0, "passes_attempted": 55.0, "passes": 48.0,
     "fouls_committed": 2.0, "saves": 0.0},
    # A bench appearance: no minutes. Stored anyway -- the row is a real record
    # of not playing, and the chart's own didNotPlay handling reads it.
    {"date": "2026-08-16", "event_id": "401877014", "matchup": "ASL @ AME",
     "home": True, "minutes": 0.0, "goals": 0.0, "assists": 0.0, "shots": 0.0,
     "shots_on_target": 0.0, "tackles": 0.0, "clearances": 0.0, "crosses": 0.0,
     "passes_attempted": 0.0, "passes": 0.0, "fouls_committed": 0.0,
     "saves": 0.0},
]


class TheFormWritesWhatItReads(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="sf-", suffix=".db",
                                             delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
              espn_id TEXT
            );
            CREATE TABLE player_game_logs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER,
              league TEXT NOT NULL, season INTEGER NOT NULL, game_no TEXT,
              game_id TEXT, game_date TEXT, team TEXT, opponent TEXT,
              home_away TEXT, stats TEXT NOT NULL, source TEXT,
              source_player_key TEXT, ingested_at TEXT, game_type TEXT,
              UNIQUE(league, source_player_key, season, game_no)
            );
        """)
        con.execute("INSERT INTO players VALUES(1,'Liga MX Player','AME','ligamx','49306')")
        con.execute("INSERT INTO players VALUES(2,'MLS Player','CLB','mls','303512')")
        con.execute("INSERT INTO players VALUES(3,'No Crosswalk','AME','ligamx',NULL)")
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        patch = mock.patch.object(soccer_form, "_db", side_effect=connection)
        patch.start()
        self.addCleanup(patch.stop)

    def _rows(self):
        con = sqlite3.connect(self.path)
        try:
            return con.execute(
                "SELECT game_id, game_date, stats, source FROM player_game_logs "
                "WHERE league='ligamx' ORDER BY game_date DESC").fetchall()
        finally:
            con.close()

    def test_a_click_stores_the_matches_it_read(self):
        with mock.patch.object(soccer_form.espn, "soccer_athlete_form",
                               return_value=_MATCHES):
            result = soccer_form.soccer_player_form(1)
        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(result["stored"], 2)
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0][2])["tackles"], 4.0)
        self.assertEqual(rows[0][3], "espn-core")

    def test_a_second_click_writes_nothing(self):
        with mock.patch.object(soccer_form.espn, "soccer_athlete_form",
                               return_value=_MATCHES):
            soccer_form.soccer_player_form(1)
            again = soccer_form.soccer_player_form(1)
        self.assertEqual(again["stored"], 0)
        self.assertEqual(len(self._rows()), 2)

    def test_a_richer_existing_row_is_never_overwritten(self):
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO player_game_logs(player_id, league, season, game_no,"
            " game_id, game_date, stats, source, source_player_key)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (1, "ligamx", 2026, "401877008", "401877008", "2026-08-22",
             json.dumps({"tackles": 99.0, "game_type_marker": 1}),
             "espn", "49306"))
        con.commit()
        con.close()
        with mock.patch.object(soccer_form.espn, "soccer_athlete_form",
                               return_value=_MATCHES):
            soccer_form.soccer_player_form(1)
        stored = {r[0]: json.loads(r[2]) for r in self._rows()}
        # The ingest's own row wins: it knows game_type and team codes, this
        # path is a read-through that happens to have the same numbers.
        self.assertEqual(stored["401877008"]["tackles"], 99.0)

    def test_another_league_is_answered_not_errored(self):
        # A Leagues Cup card mixes MLS and Liga MX players. The MLS ones chart
        # from their own season; a 400 here would render a failure on a row
        # that is simply served another way.
        result = soccer_form.soccer_player_form(2)
        self.assertEqual(result["matches"], [])
        self.assertIn("not wired", result["note"])

    def test_a_player_without_a_crosswalk_is_not_guessed_by_name(self):
        # An ambiguous key does not raise, it returns somebody else's season.
        result = soccer_form.soccer_player_form(3)
        self.assertEqual(result["matches"], [])
        self.assertIn("no espn_id", result["note"])


if __name__ == "__main__":
    unittest.main()
