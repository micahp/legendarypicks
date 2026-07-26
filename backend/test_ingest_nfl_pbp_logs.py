"""Tests for NFL play retention and the game_date/home_away fix.

This ingest had no coverage at all while being the sole writer of the 2025 NFL
season. Every assertion below was checked against a deliberately broken
implementation, not just a passing one -- an assertion that cannot fail is not a
test.

No network: nfl_data_py.import_pbp_data is replaced with a synthetic frame.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _frame():
    import pandas as pd
    import ingest_nfl_pbp_logs as mod
    # Two teams, one game, four plays. SEA is home, so a SEA row must resolve to
    # 'home' and the ARI row to 'away' -- the pair is what makes the assertion
    # meaningful rather than a coin flip that passes half the time.
    rows = []
    common = dict(game_id="2025_01_ARI_SEA", season=2025, week=1,
                  home_team="SEA", away_team="ARI", game_date="2025-09-07",
                  season_type="REG")
    rows.append(dict(common, play_id=1, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=75, game_seconds_remaining=3600,
                     play_type="pass", epa=0.5, wpa=0.02, qb_epa=0.5, air_yards=12.0,
                     yards_gained=12, cpoe=3.1, passer_player_id="00-0000001",
                     rusher_player_id=None, receiver_player_id="00-0000002",
                     pass_location="left", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=1, series_result="First down",
                     drive=1, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=12.0, rushing_yards=0.0, receiving_yards=12.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB One", rusher_player_name=None,
                     receiver_player_name="WR Two"))
    rows.append(dict(common, play_id=2, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=63, game_seconds_remaining=3560,
                     play_type="run", epa=-0.2, wpa=-0.01, qb_epa=0.0, air_yards=None,
                     yards_gained=3, cpoe=None, passer_player_id=None,
                     rusher_player_id="00-0000003", receiver_player_id=None,
                     pass_location=None, run_location="middle", run_gap="guard",
                     complete_pass=0, touchdown=0, series=1, series_result="First down",
                     drive=1, success=0, shotgun=0, pass_attempt=0, rush_attempt=1,
                     passing_yards=0.0, rushing_yards=3.0, receiving_yards=0.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name=None, rusher_player_name="RB Three",
                     receiver_player_name=None))
    rows.append(dict(common, play_id=3, posteam="ARI", defteam="SEA", qtr=2, down=3,
                     ydstogo=2, yardline_100=40, game_seconds_remaining=1800,
                     play_type="pass", epa=0.9, wpa=0.04, qb_epa=0.9, air_yards=5.0,
                     yards_gained=8, cpoe=1.0, passer_player_id="00-0000004",
                     rusher_player_id=None, receiver_player_id="00-0000005",
                     pass_location="right", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=2, series_result="First down",
                     drive=2, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=8.0, rushing_yards=0.0, receiving_yards=8.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB Four", rusher_player_name=None,
                     receiver_player_name="WR Five"))
    # A postseason play, to prove the REG filter still applies to retention.
    rows.append(dict(common, play_id=4, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=75, game_seconds_remaining=3600,
                     play_type="pass", epa=0.1, wpa=0.0, qb_epa=0.1, air_yards=4.0,
                     yards_gained=4, cpoe=0.0, passer_player_id="00-0000001",
                     rusher_player_id=None, receiver_player_id="00-0000002",
                     pass_location="left", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=1, series_result="First down",
                     drive=1, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=4.0, rushing_yards=0.0, receiving_yards=4.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB One", rusher_player_name=None,
                     receiver_player_name="WR Two"))
    rows[-1]["season_type"] = "POST"
    return pd.DataFrame(rows)


class PbpRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("""CREATE TABLE players (id INTEGER PRIMARY KEY, league TEXT,
                       name TEXT, nfl_gsis_id TEXT)""")
        for pid, gsis in ((1, "00-0000001"), (2, "00-0000002"), (3, "00-0000003"),
                          (4, "00-0000004"), (5, "00-0000005")):
            con.execute("INSERT INTO players VALUES (?,'nfl',?,?)", (pid, f"p{pid}", gsis))
        con.commit(); con.close()

        import nfl_data_py
        import ingest_nfl_pbp_logs as mod
        self.mod = mod
        mod.DB = self.db
        self._orig = nfl_data_py.import_pbp_data
        nfl_data_py.import_pbp_data = lambda years: _frame()

    def tearDown(self):
        import nfl_data_py
        nfl_data_py.import_pbp_data = self._orig

    def _run(self):
        self.mod.ingest(2025)
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def test_plays_are_retained_and_regular_season_only(self):
        con = self._run()
        n = con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0]
        # 3 REG plays retained, the POST play dropped by the existing filter.
        self.assertEqual(n, 3)
        seasons = [r[0] for r in con.execute("SELECT DISTINCT season FROM nfl_pbp")]
        self.assertEqual(seasons, [2025])

    def test_retained_play_keeps_the_columns_charts_need(self):
        con = self._run()
        row = con.execute("SELECT * FROM nfl_pbp WHERE play_id=1").fetchone()
        self.assertEqual(row["epa"], 0.5)
        self.assertEqual(row["air_yards"], 12.0)
        self.assertEqual(row["down"], 1)
        self.assertEqual(row["ydstogo"], 10)
        self.assertEqual(row["run_gap"], None)
        self.assertEqual(row["receiver_player_id"], "00-0000002")
        self.assertEqual(row["series_result"], "First down")

    def test_game_date_and_home_away_are_populated(self):
        """The bug this fixes left both NULL on all 10,717 NFL rows."""
        con = self._run()
        rows = con.execute(
            "SELECT team, game_date, home_away FROM player_game_logs WHERE league='nfl'"
        ).fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["game_date"], "2025-09-07")
            self.assertIsNotNone(r["home_away"])
        sides = {r["team"]: r["home_away"] for r in rows}
        # SEA is home_team, ARI is not. Both directions asserted so a constant
        # would fail.
        self.assertEqual(sides["SEA"], "home")
        self.assertEqual(sides["ARI"], "away")

    def test_missing_source_column_fails_loud(self):
        """Silent narrowing is the drift that went unnoticed between 2024/2025."""
        import nfl_data_py
        nfl_data_py.import_pbp_data = lambda years: _frame().drop(columns=["run_gap"])
        with self.assertRaises(RuntimeError) as ctx:
            self.mod.ingest(2025)
        self.assertIn("run_gap", str(ctx.exception))

    def test_rerunning_does_not_duplicate_plays(self):
        self.mod.ingest(2025)
        self.mod.ingest(2025)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
