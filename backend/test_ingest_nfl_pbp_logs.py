"""Tests for additive NFL play-by-play retention.

No network: nfl_data_py.import_pbp_data is replaced with a synthetic frame.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nfl_pbp_logs as mod


def _play(play_id, **overrides):
    row = {column: None for column in mod._PLAY_COLS}
    row.update({
        "game_id": "2025_01_ARI_SEA",
        "play_id": play_id,
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "posteam": "SEA",
        "defteam": "ARI",
        "home_team": "SEA",
        "away_team": "ARI",
        "game_date": "2025-09-07",
        "qtr": 1,
        "down": 1,
        "ydstogo": 10,
        "yardline_100": 75,
        "game_seconds_remaining": 3600,
        "play_type": "pass",
        "epa": 0.5,
        "wpa": 0.02,
        "qb_epa": 0.5,
        "air_yards": 12.0,
        "yards_gained": 12,
        "cpoe": 3.1,
        "passer_player_id": "00-0000001",
        "receiver_player_id": "00-0000002",
        "pass_location": "left",
        "complete_pass": 1,
        "touchdown": 0,
        "series": 1,
        "series_result": "First down",
        "drive": 1,
        "success": 1,
        "shotgun": 1,
        "sack": 0,
        "two_point_attempt": 0,
        "pass_attempt": 1,
        "rush_attempt": 0,
        "passing_yards": 12.0,
        "rushing_yards": 0.0,
        "receiving_yards": 12.0,
        "pass_touchdown": 0,
        "rush_touchdown": 0,
        "interception": 0,
    })
    row.update(overrides)
    return row


def _frame():
    import pandas as pd

    return pd.DataFrame([
        _play(1),
        _play(
            2,
            play_type="run",
            epa=-0.2,
            wpa=-0.01,
            qb_epa=0.0,
            air_yards=None,
            yards_gained=3,
            cpoe=None,
            passer_player_id=None,
            rusher_player_id="00-0000003",
            receiver_player_id=None,
            pass_location=None,
            run_location="middle",
            run_gap="guard",
            complete_pass=0,
            success=0,
            shotgun=0,
            pass_attempt=0,
            rush_attempt=1,
            passing_yards=0.0,
            rushing_yards=3.0,
            receiving_yards=0.0,
        ),
        _play(
            3,
            posteam="ARI",
            defteam="SEA",
            passer_player_id="00-0000004",
            receiver_player_id="00-0000005",
            air_yards=5.0,
            yards_gained=8,
            passing_yards=8.0,
            receiving_yards=8.0,
        ),
        _play(4, season_type="POST"),
    ])


class PbpRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.original_db = mod.DB
        mod.DB = self.db

        import nfl_data_py

        self.original_import = nfl_data_py.import_pbp_data
        nfl_data_py.import_pbp_data = lambda years: _frame()

    def tearDown(self):
        import nfl_data_py

        nfl_data_py.import_pbp_data = self.original_import
        mod.DB = self.original_db
        self.tmp.cleanup()

    def _run(self):
        retained = mod.ingest(2025)
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return retained, con

    def test_plays_are_retained_and_regular_season_only(self):
        retained, con = self._run()
        self.assertEqual(3, retained)
        self.assertEqual(3, con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0])
        self.assertEqual(
            [2025],
            [row[0] for row in con.execute("SELECT DISTINCT season FROM nfl_pbp")],
        )
        con.close()

    def test_retained_table_has_the_curated_fifty_columns(self):
        _, con = self._run()
        columns = [
            row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)").fetchall()
        ]
        con.close()
        self.assertEqual(50, len(columns))
        self.assertEqual(mod._PLAY_COLS, columns)

    def test_retained_play_keeps_chart_fields(self):
        _, con = self._run()
        row = con.execute("SELECT * FROM nfl_pbp WHERE play_id=1").fetchone()
        con.close()
        self.assertEqual(0.5, row["epa"])
        self.assertEqual(12.0, row["air_yards"])
        self.assertEqual(1, row["down"])
        self.assertEqual(10, row["ydstogo"])
        self.assertIsNone(row["run_gap"])
        self.assertEqual("00-0000002", row["receiver_player_id"])
        self.assertEqual("First down", row["series_result"])

    def test_missing_source_column_fails_loud(self):
        import nfl_data_py

        nfl_data_py.import_pbp_data = lambda years: _frame().drop(
            columns=["run_gap"]
        )
        with self.assertRaises(RuntimeError) as ctx:
            mod.ingest(2025)
        self.assertIn("run_gap", str(ctx.exception))

    def test_rerunning_does_not_duplicate_plays(self):
        mod.ingest(2025)
        retained = mod.ingest(2025)
        self.assertEqual(3, retained)
        con = sqlite3.connect(self.db)
        self.assertEqual(3, con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0])
        con.close()

    def test_ingest_does_not_create_player_game_logs(self):
        _, con = self._run()
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        con.close()
        self.assertNotIn("player_game_logs", tables)


if __name__ == "__main__":
    unittest.main()
