#!/usr/bin/env python3
"""The prop-page soccer form is read-only and FotMob-backed."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="soccer-form-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers.games import soccer_form  # noqa: E402


class FotMobFormRead(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="sf-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT,team TEXT,league TEXT);
            CREATE TABLE player_game_logs_fotmob(
              id INTEGER PRIMARY KEY AUTOINCREMENT,player_id INTEGER,league TEXT,
              game_date TEXT,game_id TEXT,opponent TEXT,home_away TEXT,stats TEXT
            );
        """)
        con.executemany("INSERT INTO players VALUES(?,?,?,?)", [
            (1, "Liga MX Player", "AME", "ligamx"),
            (2, "MLS Player", "CLB", "mls"),
            (3, "Other Player", "X", "epl"),
        ])
        con.executemany(
            "INSERT INTO player_game_logs_fotmob"
            "(player_id,league,game_date,game_id,opponent,home_away,stats) VALUES(?,?,?,?,?,?,?)",
            [
                (1, "ligamx", "2026-08-22", "mx-1", "JUA", "away",
                 json.dumps({"minutes": 90, "shots": 3, "passes": 48,
                             "passes_attempted": None})),
                (1, "lcup", "2026-08-26", "lc-1", "SEA", "home",
                 json.dumps({"minutes": 80, "shots": 2})),
                (2, "mls", "2026-08-24", "mls-1", "CIN", "home",
                 json.dumps({"minutes": 75, "tackles": 4})),
            ],
        )
        con.commit()
        con.close()

        def connection():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            return db

        patch = mock.patch.object(soccer_form, "_db", side_effect=connection)
        patch.start()
        self.addCleanup(patch.stop)

    def test_liga_mx_form_combines_its_league_and_leagues_cup(self):
        result = soccer_form.soccer_player_form(1)
        self.assertEqual(result["source"], "fotmob")
        self.assertEqual([row["event_id"] for row in result["matches"]], ["lc-1", "mx-1"])
        self.assertEqual(result["matches"][0]["matchup"], "vs SEA")
        self.assertEqual(result["stored"], 0)

    def test_fotmob_passes_are_not_invented_as_pass_attempts(self):
        result = soccer_form.soccer_player_form(1)
        mx = next(row for row in result["matches"] if row["event_id"] == "mx-1")
        self.assertIsNone(mx["passes_attempted"])

    def test_mls_form_is_supported_and_unrelated_league_is_explicit(self):
        self.assertEqual(soccer_form.soccer_player_form(2)["matches"][0]["event_id"], "mls-1")
        other = soccer_form.soccer_player_form(3)
        self.assertEqual(other["matches"], [])
        self.assertIn("not available", other["note"])

    def test_malformed_publisher_row_fails_loudly(self):
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO player_game_logs_fotmob"
            "(player_id,league,game_date,game_id,stats) VALUES(1,'ligamx','2026-09-01','bad','[]')"
        )
        con.commit()
        con.close()
        with self.assertRaisesRegex(Exception, "malformed"):
            soccer_form.soccer_player_form(1)


if __name__ == "__main__":
    unittest.main()
