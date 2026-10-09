"""Tests for nfl_backtest.py. Planted-truth season in a temp DB, no network.

The leakage tests are the ones that matter: a walk-forward backtest that sees its own week
is a backtest that grades itself.
"""
import itertools
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_backtest as nb  # noqa: E402
import nfl_ratings as nr  # noqa: E402
from test_nfl_ratings_data import TEAMS, points  # noqa: E402


class BtDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, "
            "week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL, "
            "away_score REAL, spread_line REAL, total_line REAL, home_moneyline INT, "
            "away_moneyline INT)")
        # One planted season: every ordered pair once, 6 weeks, scores from the planted truth.
        for i, (h, a) in enumerate(itertools.permutations(TEAMS, 2)):
            hp, ap = points(h, a)
            self.con.execute("INSERT INTO nfl_schedule VALUES (?,2025,'REG',?,?,?,'Home',?,?,"
                             "2.0,44.0,-110,-110)", ("g%03d" % i, i % 6 + 1, h, a, hp, ap))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def projections(self, week):
        return {r["game_id"]: r["proj_margin"]
                for r in nb.backtest_season(self.con, 2025) if r["week"] == week}


class Walkforward(BtDB):
    def test_row_count_is_games_in_weeks_two_onward(self):
        rows = nb.backtest_season(self.con, 2025)
        self.assertEqual(len(rows), 25)                  # 30 games, minus the 5 in week 1
        self.assertEqual(min(r["week"] for r in rows), 2)

    def test_projecting_week_w_does_not_see_week_w_scores(self):
        before = self.projections(4)
        self.con.execute("UPDATE nfl_schedule SET home_score = home_score + 40 WHERE week = 4")
        self.con.commit()
        after = self.projections(4)
        self.assertTrue(before)
        for gid in before:
            self.assertAlmostEqual(before[gid], after[gid], places=9, msg=gid)

    def test_projecting_week_w_does_not_see_later_weeks(self):
        before = self.projections(3)
        self.con.execute("UPDATE nfl_schedule SET away_score = away_score + 40 WHERE week >= 4")
        self.con.commit()
        after = self.projections(3)
        for gid in before:
            self.assertAlmostEqual(before[gid], after[gid], places=9, msg=gid)

    def test_first_season_has_no_prior_and_says_so(self):
        rows = nb.backtest_season(self.con, 2025)
        self.assertFalse(rows[0]["prior_used"])

    def test_market_probability_is_devigged_moneyline(self):
        r = nb.backtest_season(self.con, 2025)[0]
        self.assertAlmostEqual(r["p_market"], 0.5, places=12)


class CapPoints(unittest.TestCase):
    def scored(self):
        # (week, home, away, hs, as, loc): 4 games, one huge score, mean is pulled by it.
        return [(1, "AAA", "BBB", 60.0, 10.0, "Home"),
                (1, "CCC", "DDD", 20.0, 22.0, "Home"),
                (2, "AAA", "CCC", 18.0, 21.0, "Home"),
                (2, "BBB", "DDD", 24.0, 17.0, "Home")]

    def test_no_cap_leaves_scores_untouched(self):
        g = nb.training_games(self.scored(), 3, None)
        self.assertEqual(max(x.home_pts for x in g), 60.0)

    def test_cap_clips_each_score_to_mean_plus_minus_cap(self):
        scores = [s for r in self.scored() for s in (float(r[3]), float(r[4]))]
        center = sum(scores) / len(scores)
        g = nb.training_games(self.scored(), 3, 5.0)
        for x in g:
            self.assertLessEqual(x.home_pts, center + 5.0 + 1e-9)
            self.assertGreaterEqual(x.away_pts, center - 5.0 - 1e-9)
        self.assertAlmostEqual(max(x.home_pts for x in g), center + 5.0, places=9)

    def test_cap_mean_uses_training_weeks_only(self):
        # Changing week 2 must not move the cap centre used to fit week 2.
        base = self.scored()
        g1 = nb.training_games(base, 2, 5.0)
        changed = [r if r[0] != 2 else (r[0], r[1], r[2], 999.0, 999.0, r[5]) for r in base]
        g2 = nb.training_games(changed, 2, 5.0)
        self.assertEqual([(x.home_pts, x.away_pts) for x in g1],
                         [(x.home_pts, x.away_pts) for x in g2])


class Params(unittest.TestCase):
    def test_unknown_parameter_is_refused(self):
        with self.assertRaises(ValueError):
            nb._params({"half_lfie": 6})

    def test_bad_sigma_and_cap_points_refused(self):
        with self.assertRaises(ValueError):
            nb._params({"sigma": 0.0})
        with self.assertRaises(ValueError):
            nb._params({"cap_points": 0.0})

    def test_defaults_are_the_spec_values(self):
        p = nb._params({})
        self.assertEqual((p["half_life"], p["cap"], p["prior_games"], p["sigma"]),
                         (6.0, 21.0, 4.0, 13.4))
        self.assertIsNone(p["cap_points"])


if __name__ == "__main__":
    unittest.main()
