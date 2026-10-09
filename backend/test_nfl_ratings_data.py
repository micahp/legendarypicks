"""Tests for nfl_ratings_data.py: schedule rows -> Game lists, season fits and priors.

Temp DB with a planted-truth season, so the fit has a known answer to recover.
"""
import itertools
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_ratings as nr  # noqa: E402
import nfl_ratings_data as nrd  # noqa: E402

TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
O_TRUE = {"AAA": 4.0, "BBB": 2.0, "CCC": 0.5, "DDD": -0.5, "EEE": -2.0, "FFF": -4.0}
D_TRUE = {"AAA": -3.0, "BBB": -1.0, "CCC": 0.0, "DDD": 1.0, "EEE": 2.0, "FFF": 1.0}
MU, H = 22.0, 2.5


def points(home, away):
    return (MU + O_TRUE[home] - D_TRUE[away] + H / 2, MU + O_TRUE[away] - D_TRUE[home] - H / 2)


class SchedDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, "
            "week INT, home_team TEXT, away_team TEXT, home_score REAL, away_score REAL, "
            "location TEXT)")

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def add(self, gid, season, gtype, week, home, away, hs, as_, loc="Home"):
        self.con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?)",
                         (gid, season, gtype, week, home, away, hs, as_, loc))

    def planted_season(self, season=2025):
        """Every ordered pair once: 30 games over 6 weeks, scores from the planted truth."""
        pairs = list(itertools.permutations(TEAMS, 2))
        for i, (h, a) in enumerate(pairs):
            hp, ap = points(h, a)
            self.add("%d_%03d" % (season, i), season, "REG", i % 6 + 1, h, a, hp, ap)


class LoadGames(SchedDB):
    def test_playoffs_and_unscored_are_excluded_and_counted(self):
        self.planted_season()
        self.add("p1", 2025, "WC", 19, "AAA", "BBB", 20.0, 17.0)
        self.add("u1", 2025, "REG", 6, "CCC", "DDD", None, None)
        games, unscored, anchor = nrd.load_games(self.con, 2025)
        self.assertEqual(len(games), 30)
        self.assertEqual(unscored, 1)
        self.assertEqual(anchor, 6)

    def test_weeks_ago_is_measured_from_anchor(self):
        self.planted_season()
        games, _, anchor = nrd.load_games(self.con, 2025)
        by_week = {}
        for g in games:
            by_week.setdefault(anchor - g.weeks_ago, []).append(g)
        self.assertEqual(sorted(by_week), [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(g.weeks_ago == 0.0 for g in by_week[6]))

    def test_neutral_location_is_parsed(self):
        self.add("n1", 2025, "REG", 1, "AAA", "BBB", 10.0, 7.0, loc="Neutral")
        self.add("h1", 2025, "REG", 1, "CCC", "DDD", 10.0, 7.0, loc="Home")
        games, _, _ = nrd.load_games(self.con, 2025)
        flags = {(g.home, g.away): g.neutral for g in games}
        self.assertTrue(flags[("AAA", "BBB")])
        self.assertFalse(flags[("CCC", "DDD")])


class SeasonFitAndPrior(SchedDB):
    def test_season_fit_recovers_planted_truth(self):
        self.planted_season()
        f, info = nrd.season_fit(self.con, 2025, cap=None, prior_games=1e-6)
        self.assertEqual(info["games"], 30)
        for t in TEAMS:
            self.assertAlmostEqual(f.o[t], O_TRUE[t], places=3, msg="o " + t)
            self.assertAlmostEqual(f.d[t], D_TRUE[t], places=3, msg="d " + t)
        self.assertAlmostEqual(f.h, H, places=3)

    def test_prior_is_two_thirds_of_final_rating(self):
        self.planted_season()
        f, _ = nrd.season_fit(self.con, 2025, cap=None, prior_games=1e-6)
        prior = nrd.prior_from_fit(f)
        for t in TEAMS:
            self.assertAlmostEqual(prior[t][0], f.o[t] * 2.0 / 3.0, places=12)
            self.assertAlmostEqual(prior[t][1], f.d[t] * 2.0 / 3.0, places=12)

    def test_prior_shrink_bounds(self):
        self.planted_season()
        f, _ = nrd.season_fit(self.con, 2025, cap=None, prior_games=1e-6)
        with self.assertRaises(ValueError):
            nrd.prior_from_fit(f, shrink=1.0)
        with self.assertRaises(ValueError):
            nrd.prior_from_fit(f, shrink=-0.1)

    def test_season_with_no_scores_is_rejected(self):
        self.add("u", 2026, "REG", 1, "AAA", "BBB", None, None)
        with self.assertRaises(ValueError):
            nrd.season_fit(self.con, 2026)


class RealDataSmoke(unittest.TestCase):
    """Runs against the dev DB when present. Skipped on a machine without it."""

    DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")

    def test_2025_fit_and_prior_on_real_schedule(self):
        if not os.path.isfile(self.DB):
            self.skipTest("dev DB not present")
        con = sqlite3.connect("file:%s?mode=ro" % self.DB, uri=True)
        try:
            f, info = nrd.season_fit(con, 2025)
        finally:
            con.close()
        self.assertEqual(info["games"], 272)
        self.assertEqual(info["unscored"], 0)
        self.assertEqual(len(f.o), 32)
        self.assertGreater(f.mu, 15.0)
        self.assertLess(f.mu, 30.0)


if __name__ == "__main__":
    unittest.main()
