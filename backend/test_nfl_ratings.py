"""Tests for nfl_ratings.py. Synthetic leagues with KNOWN ratings, no database.

A fit that recovers planted truth is the only evidence that the design matrix is right;
each test below also names the broken version it would catch.
"""
import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_ratings as nr  # noqa: E402

TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
# Truth with zero mean in both o and d. The tiny prior pins the mean, so this is recoverable.
O_TRUE = {"AAA": 4.0, "BBB": 2.0, "CCC": 0.5, "DDD": -0.5, "EEE": -2.0, "FFF": -4.0}
D_TRUE = {"AAA": -3.0, "BBB": -1.0, "CCC": 0.0, "DDD": 1.0, "EEE": 2.0, "FFF": 1.0}
MU_TRUE, H_TRUE = 22.0, 2.5


def true_points(home, away, neutral=False):
    h = 0.0 if neutral else H_TRUE
    return (MU_TRUE + O_TRUE[home] - D_TRUE[away] + h / 2.0,
            MU_TRUE + O_TRUE[away] - D_TRUE[home] - h / 2.0)


def round_robin(neutral=False, weeks_ago=0.0):
    games = []
    for a, b in itertools.permutations(TEAMS, 2):
        hp, ap = true_points(a, b, neutral)
        games.append(nr.Game(weeks_ago, a, b, round(hp, 6), round(ap, 6), neutral))
    return games


class Recovery(unittest.TestCase):
    def test_noiseless_round_robin_recovers_truth(self):
        # Points are noiseless and every margin is under 21, so cap is irrelevant.
        f = nr.fit(round_robin(), TEAMS, cap=None, prior_games=1e-6)
        for t in TEAMS:
            self.assertAlmostEqual(f.o[t], O_TRUE[t], places=3, msg="o " + t)
            self.assertAlmostEqual(f.d[t], D_TRUE[t], places=3, msg="d " + t)
        self.assertAlmostEqual(f.mu, MU_TRUE, places=3)
        self.assertAlmostEqual(f.h, H_TRUE, places=3)

    def test_neutral_games_do_not_carry_home_field(self):
        # Mutation check: applying h to neutral games would bias h toward zero here.
        games = round_robin(neutral=False) + round_robin(neutral=True)
        f = nr.fit(games, TEAMS, cap=None, prior_games=1e-6)
        self.assertAlmostEqual(f.h, H_TRUE, places=2)
        # Neutral-only data has no home-field signal, so h must fall back to 0.
        f0 = nr.fit(round_robin(neutral=True), TEAMS, cap=None, prior_games=1e-6)
        self.assertAlmostEqual(f0.h, 0.0, places=3)


class Prior(unittest.TestCase):
    def test_team_with_no_games_sits_at_its_prior(self):
        games = [g for g in round_robin() if "NEW" not in (g.home, g.away)]
        teams = TEAMS + ["NEW"]
        f = nr.fit(games, teams, cap=None, prior={"NEW": (1.5, -0.5)}, prior_games=4.0)
        self.assertAlmostEqual(f.o["NEW"], 1.5, places=9)
        self.assertAlmostEqual(f.d["NEW"], -0.5, places=9)

    def test_prior_pulls_thin_team_toward_prior(self):
        # One game for NEW. A large prior weight must keep it near the prior, a small one must not.
        games = round_robin() + [nr.Game(0.0, "NEW", "AAA", 30.0, 3.0)]
        teams = TEAMS + ["NEW"]
        strong = nr.fit(games, teams, cap=None, prior={"NEW": (-5.0, 0.0)}, prior_games=50.0)
        weak = nr.fit(games, teams, cap=None, prior={"NEW": (-5.0, 0.0)}, prior_games=0.01)
        self.assertLess(abs(strong.o["NEW"] - (-5.0)), abs(weak.o["NEW"] - (-5.0)))


class Recency(unittest.TestCase):
    def test_short_half_life_favours_recent_games(self):
        # AAA was dominant 8 weeks ago and poor this week. Short half-life must rate it lower.
        old = [nr.Game(8.0, "AAA", "BBB", 30.0, 10.0), nr.Game(8.0, "AAA", "CCC", 30.0, 10.0),
               nr.Game(8.0, "BBB", "AAA", 10.0, 30.0), nr.Game(8.0, "CCC", "AAA", 10.0, 30.0)]
        new = [nr.Game(0.0, "AAA", "BBB", 10.0, 30.0), nr.Game(0.0, "AAA", "CCC", 10.0, 30.0),
               nr.Game(0.0, "BBB", "AAA", 30.0, 10.0), nr.Game(0.0, "CCC", "AAA", 30.0, 10.0)]
        teams = ["AAA", "BBB", "CCC"]
        short = nr.fit(old + new, teams, half_life=1.0, cap=None, prior_games=1e-3)
        long_ = nr.fit(old + new, teams, half_life=100.0, cap=None, prior_games=1e-3)
        # Sign convention (spec 4.1): margin = (o_A - d_B) - (o_B - d_A) + h, so a team's net
        # strength is o + d. The long fit is near zero (old and new results cancel); the short
        # fit must be clearly negative.
        self.assertLess(short.o["AAA"] + short.d["AAA"], long_.o["AAA"] + long_.d["AAA"] - 1.0)

    def test_negative_weeks_ago_is_rejected(self):
        with self.assertRaises(ValueError):
            nr.fit([nr.Game(-1.0, "AAA", "BBB", 1.0, 2.0)], ["AAA", "BBB"], prior_games=1.0)


class Blowout(unittest.TestCase):
    def test_cap_changes_fit_only_when_margins_exceed_it(self):
        # No margin is over 21, so cap=21 and cap=None must agree exactly.
        base = round_robin()
        a = nr.fit(base, TEAMS, cap=21.0, prior_games=1e-6)
        b = nr.fit(base, TEAMS, cap=None, prior_games=1e-6)
        for t in TEAMS:
            self.assertAlmostEqual(a.o[t], b.o[t], places=9)
        # With a 50-point blowout, the cap must move the ratings by a clear amount (measured:
        # about 0.67 points on o and d). Raw points are still fitted, so the dampening is partial.
        blow = base + [nr.Game(0.0, "AAA", "FFF", 50.0, 0.0)]
        capped = nr.fit(blow, TEAMS, cap=21.0, prior_games=1e-6)
        uncapped = nr.fit(blow, TEAMS, cap=None, prior_games=1e-6)
        moved = max(abs(capped.o[t] - uncapped.o[t]) for t in TEAMS)
        self.assertGreater(moved, 0.1)


class Validation(unittest.TestCase):
    def test_zero_prior_games_is_rejected(self):
        with self.assertRaises(ValueError):
            nr.fit(round_robin(), TEAMS, prior_games=0.0)

    def test_unknown_team_is_rejected(self):
        with self.assertRaises(KeyError):
            nr.fit([nr.Game(0.0, "AAA", "ZZZ", 1.0, 2.0)], ["AAA", "BBB"], prior_games=1.0)

    def test_expected_points_matches_formula(self):
        f = nr.fit(round_robin(), TEAMS, cap=None, prior_games=1e-6)
        ph, pa = nr.expected_points(f, "AAA", "BBB")
        self.assertAlmostEqual(ph - pa, (f.o["AAA"] - f.d["BBB"]) - (f.o["BBB"] - f.d["AAA"]) + f.h,
                               places=9)
        ph_n, pa_n = nr.expected_points(f, "AAA", "BBB", neutral=True)
        self.assertAlmostEqual(ph_n - pa_n, (f.o["AAA"] - f.d["BBB"]) - (f.o["BBB"] - f.d["AAA"]),
                               places=9)


if __name__ == "__main__":
    unittest.main()
