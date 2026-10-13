"""Tests for record_nfl_backtests.py: tuning rows recorded; holdout recorded exactly once."""
import itertools
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import migrate_nfl_model_tables as mg  # noqa: E402
import record_nfl_backtests as rec  # noqa: E402
from test_nfl_ratings_data import TEAMS, points  # noqa: E402


class RecordDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "t.db")
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT,"
                    " week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL,"
                    " away_score REAL, spread_line REAL, total_line REAL, home_moneyline INT,"
                    " away_moneyline INT)")
        for season in (2024, 2025):
            for i, (h, a) in enumerate(itertools.permutations(TEAMS, 2)):
                hp, ap = points(h, a)
                con.execute("INSERT INTO nfl_schedule VALUES (?,?,'REG',?,?,?,'Home',?,?,2.0,44.0,"
                            "-110,-110)", ("%d_%03d" % (season, i), season, i % 6 + 1, h, a, hp, ap))
        con.commit()
        con.close()

    def tearDown(self):
        self._tmp.cleanup()

    def conn(self):
        return sqlite3.connect(self.path)


class Tune(RecordDB):
    def test_one_row_per_grid_configuration(self):
        con = self.conn()
        n = rec.record_tune(con)
        rows = con.execute("SELECT run_id, status, params_json FROM model_runs ORDER BY run_id").fetchall()
        con.close()
        self.assertEqual(n, 36)
        self.assertEqual(len(rows), 36)
        self.assertTrue(all(r[1] == "tuning" for r in rows))
        params = json.loads(rows[0][2])
        self.assertIn("brier", params["results"])
        self.assertIn("half_life", params["config"])

    def test_rerun_replaces_rather_than_duplicates(self):
        con = self.conn()
        rec.record_tune(con)
        rec.record_tune(con)
        n, = con.execute("SELECT COUNT(*) FROM model_runs").fetchone()
        con.close()
        self.assertEqual(n, 36)


class Holdout(RecordDB):
    def test_holdout_recorded_once_with_all_scores(self):
        con = self.conn()
        mg.migrate(con)
        rec.record_holdout(con)
        row = con.execute("SELECT status, params_json FROM model_runs WHERE run_id=?",
                          (rec.HOLDOUT_RUN_ID,)).fetchone()
        con.close()
        self.assertEqual(row[0], "holdout")
        results = json.loads(row[1])["results"]
        self.assertIn("brier", results)
        self.assertIn("brier_diff_ci", results)

    def test_second_holdout_refused(self):
        con = self.conn()
        mg.migrate(con)
        rec.record_holdout(con)
        with self.assertRaises(SystemExit):
            rec.record_holdout(con)
        con.close()


if __name__ == "__main__":
    unittest.main()
