"""Regression tests for the retired destructive NFL weekly writer."""
import json
import os
import runpy
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nfl_logs as mod


class _FakeColumn:
    def __eq__(self, _other):
        return [True]


class _FakeWeekly:
    """Enough of the old nfl_data_py frame contract to trigger its write."""

    columns = ("season_type", "passing_yards")

    def __getitem__(self, key):
        if isinstance(key, str):
            return _FakeColumn()
        return self

    def __len__(self):
        return 1

    def iterrows(self):
        yield 0, {
            "player_id": "00-0000001",
            "week": 1,
            "recent_team": "NEW",
            "opponent_team": "NEW",
            "passing_yards": 999,
        }


class RetiredIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.con = sqlite3.connect(self.db)
        self.con.execute(
            """CREATE TABLE players (
                   id INTEGER PRIMARY KEY,
                   league TEXT,
                   nfl_gsis_id TEXT
               )"""
        )
        self.con.execute(
            "INSERT INTO players VALUES (1, 'nfl', '00-0000001')"
        )
        mod.ensure_table(self.con)
        self.con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (1, 'nfl', 2024, '1', '2024_01_A_B', '2024-09-08',
                       'A', 'B', 'home', ?, 'nflverse_weekly', '00-0000001')""",
            (json.dumps({
                "pass_yds": 25,
                "off_snaps": 42,
                "off_pct": 0.8,
                "adot": 12.3,
            }),),
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _stored_row(self):
        return self.con.execute(
            """SELECT id, player_id, league, season, game_no, game_id, game_date,
                      team, opponent, home_away, stats, source, source_player_key,
                      ingested_at
               FROM player_game_logs
               WHERE league='nfl' AND season=2024
                 AND source_player_key='00-0000001' AND game_no='1'"""
        ).fetchone()

    def test_executing_retired_module_cannot_replace_existing_log(self):
        before = self._stored_row()
        fake_nfl = types.ModuleType("nfl_data_py")
        fake_nfl.import_weekly_data = lambda _years: _FakeWeekly()
        fake_service = types.ModuleType("sports_service")
        fake_service._normalize_name = lambda value: value

        with patch.dict(os.environ, {"LP_DB_PATH": self.db}), patch.dict(
            sys.modules,
            {"nfl_data_py": fake_nfl, "sports_service": fake_service},
        ), patch.object(sys, "argv", [mod.__file__, "--year", "2024"]):
            runpy.run_path(mod.__file__, run_name="__main__")

        self.assertEqual(before, self._stored_row())
        self.assertFalse(hasattr(mod, "ingest_nfl_logs"))

    def test_schema_setup_is_still_idempotent(self):
        mod.ensure_table(self.con)

        indexes = {
            row[0]
            for row in self.con.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='index' AND tbl_name='player_game_logs'"""
            )
        }
        self.assertTrue({
            "idx_pgl_player",
            "idx_pgl_league_date",
            "idx_pgl_team_game",
            "idx_pgl_team_season_game",
        }.issubset(indexes))


if __name__ == "__main__":
    unittest.main()
