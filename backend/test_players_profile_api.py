#!/usr/bin/env python3

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Keep _core's import-time schema initialization away from every real database.
_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="players-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import players  # noqa: E402


class PlayerProfileApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="players-api-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT
            );
            CREATE TABLE player_game_logs(
              player_id INTEGER, season INTEGER, stats TEXT, game_date TEXT,
              opponent TEXT, home_away TEXT, game_no INTEGER
            );
            CREATE TABLE props(
              player_id INTEGER, market TEXT, side TEXT, line REAL, captured_at TEXT
            );
            CREATE TABLE player_stats(player_id INTEGER, season INTEGER);
            CREATE INDEX idx_test_logs_player ON player_game_logs(player_id);
            CREATE INDEX idx_test_props_player ON props(player_id);
            CREATE INDEX idx_test_stats_player ON player_stats(player_id);
            """
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?)",
            [
                (1, "Alex Ready", "AAA", "nba", "G"),
                (2, "Alex Empty", "BBB", "nfl", "QB"),
                (3, "Alex Stats", "CCC", "nhl", "C"),
                (4, "Alex Prop", "DDD", "ufc", None),
            ],
        )
        con.execute(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?)",
            (1, 2026, json.dumps({"PTS": 24}), "2026-07-20", "OPP", "home", 1),
        )
        con.execute("INSERT INTO player_stats VALUES(3, 2026)")
        con.execute(
            "INSERT INTO props VALUES(?,?,?,?,?)",
            (4, "points", "over", 20.5, "2026-07-21T12:00:00Z"),
        )
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = mock.patch.object(players, "_db", side_effect=connection)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_search_omits_unrenderable_identity_and_reports_coverage(self):
        result = players.search_players("Alex")

        self.assertEqual([4, 1, 3], [row["id"] for row in result])
        self.assertNotIn(2, [row["id"] for row in result])
        by_id = {row["id"]: row for row in result}
        self.assertEqual(
            {"game_logs": True, "props": False, "season_stats": False},
            by_id[1]["coverage"],
        )

    def test_profile_includes_existing_season_stats_contract(self):
        stats = {
            "window": "2026",
            "games": 82,
            "stats": {"pts": 25.2, "reb": 7.1},
            "source": "fixture",
        }
        with mock.patch.object(players, "_season_stats_for_profile", return_value=stats):
            result = players.player_profile(1)

        self.assertEqual(stats, result["season_stats"])
        self.assertEqual("ready", result["data_status"])
        self.assertTrue(result["coverage"]["game_logs"])
        self.assertTrue(result["coverage"]["season_stats"])
        self.assertEqual(24, result["recent_games"][0]["stats"]["PTS"])

    def test_direct_blank_identity_is_explicit_not_silently_ready(self):
        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual("unavailable", result["data_status"])
        self.assertEqual(
            {"game_logs": False, "props": False, "season_stats": False},
            result["coverage"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
