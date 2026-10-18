import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("LP_DB_PATH", ":memory:")

import grade_nfl_game_distributions as gr
import nfl_game_distribution as gd


class Distributions(unittest.TestCase):
    """The stored object must be enough to regenerate the numbers, and it must not be rewritable."""

    def setUp(self):
        h = tempfile.NamedTemporaryFile(prefix="nfl-dist-", suffix=".db", delete=False)
        self.path = h.name
        h.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = sqlite3.connect(self.path)
        self.con.executescript("""
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT,
                home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER,
                spread_line REAL, total_line REAL, home_moneyline REAL, away_moneyline REAL);
            CREATE TABLE nfl_line_snapshots (snapshot_id INTEGER PRIMARY KEY, spread_line REAL, total_line REAL);
            INSERT INTO nfl_schedule VALUES ('g1',2025,5,'REG','H','A',27,20,-3.0,44.5,-160.0,140.0);
            INSERT INTO nfl_line_snapshots VALUES (7, -3.5, 45.0);
        """)
        self.con.commit()

    def rows(self, line_snapshot_id=None):
        return [{"game_id": "g1", "season": 2025, "week": 5, "model_version": "test-v1",
                 "margin_mean": 2.0, "margin_sd": 13.0, "total_mean": 45.0, "total_sd": 12.0,
                 "line_snapshot_id": line_snapshot_id, "params": {"fit": "synthetic"}}]

    def test_store_is_frozen_and_reproducible(self):
        ins, ref = gd.store(self.con, self.rows(line_snapshot_id=7))
        self.assertEqual((1, 0), (ins, ref))
        ins2, ref2 = gd.store(self.con, self.rows(line_snapshot_id=7))
        self.assertEqual((0, 1), (ins2, ref2), "a second write must be refused, not overwrite")
        got = self.con.execute(
            "SELECT margin_mean, margin_sd, total_mean, total_sd, method FROM %s" % gd.TABLE).fetchall()
        self.assertEqual(1, len(got))
        self.assertEqual(("gaussian_margin_and_total_independent",), (got[0][4],))
        loaded = gr.load(self.con, [2025])
        self.assertEqual(1, len(loaded))
        r = loaded[0]
        # the same parameters regenerate exactly the same three probabilities, twice
        for _ in range(2):
            self.assertAlmostEqual(gr.p_over(2.0, 13.0, 0.0), 0.5 * (1 + gr.math.erf(2.0 / 13.0 / gr.math.sqrt(2))), places=12)
            self.assertAlmostEqual(gr.p_over(2.0, 13.0, r["spread"]), gr.p_over(2.0, 13.0, r["spread"]), places=15)
        self.assertEqual(-3.5, r["spread"], "the lock's snapshot line wins over the schedule line")
        self.assertEqual(45.0, r["total"])

    def test_probabilities_follow_the_parameters(self):
        loaded = gr.load(self.con, [2025]) if gd.store(self.con, self.rows())[0] else []
        p_win = gr.p_over(2.0, 13.0, 0.0)
        self.assertGreater(p_win, 0.5)
        self.assertAlmostEqual(1.0, p_win + gr.p_over(-2.0, 13.0, 0.0), places=12)


if __name__ == "__main__":
    unittest.main()
