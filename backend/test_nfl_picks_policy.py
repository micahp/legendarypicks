"""Tests for nfl_picks_policy: prediction, lean and wager must not collapse into each other."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_picks_policy as p  # noqa: E402

KICK = "2026-10-11T17:00:00Z"


def lock(**over):
    base = {
        "proj_home": 24.0, "proj_away": 20.0, "margin": 4.0, "total": 46.0, "p_home_win": 0.62,
        "line": {"spread": -1.5, "total": 44.5, "home_moneyline": -150.0,
                 "away_moneyline": 130.0, "captured_at": "2026-10-11T16:00:00Z"},
    }
    if "line" in over:
        over = {**over, "line": {**base["line"], **over["line"]}}
    base.update(over)
    return base


class Devig(unittest.TestCase):
    def test_two_sided_price_normalises_to_one(self):
        home, away = p.devig(-150, 130)
        self.assertAlmostEqual(home + away, 1.0)
        self.assertGreater(home, away)

    def test_missing_or_impossible_price_is_none(self):
        self.assertIsNone(p.devig(None, 130))
        self.assertIsNone(p.devig(0, 130))


class Lean(unittest.TestCase):
    def test_sides_follow_the_model(self):
        out = p.lean(lock())
        self.assertEqual((out["ml"]["side"], out["spread"]["side"], out["total"]["side"]),
                         ("home", "home", "over"))

    def test_exactly_on_the_line_is_no_lean_not_away(self):
        # The old page resolved this to the away side; the grader called it no_pick.
        out = p.lean(lock(margin=-1.5))
        self.assertEqual(out["spread"]["side"], "none")
        self.assertEqual(out["spread"]["reason"], "level_with_line")
        self.assertEqual(out["spread"]["edge_pts"], 0.0)

    def test_level_win_probability_is_no_lean(self):
        out = p.lean(lock(p_home_win=0.5))
        self.assertEqual(out["ml"]["side"], "none")
        self.assertEqual(out["ml"]["reason"], "level_at_50")

    def test_level_total_is_no_lean(self):
        out = p.lean(lock(total=44.5))
        self.assertEqual(out["total"]["side"], "none")

    def test_missing_line_has_no_lean(self):
        out = p.lean(lock(line={"spread": None, "total": None}))
        self.assertEqual(out["spread"]["reason"], "no_line")
        self.assertEqual(out["total"]["reason"], "no_line")

    def test_edge_against_price_is_measured_only_when_priced(self):
        priced = p.lean(lock())["ml"]["edge_pp"]
        self.assertIsNotNone(priced)
        self.assertIsNone(p.lean(lock(line={"home_moneyline": None}))["ml"]["edge_pp"])


class PriceStatus(unittest.TestCase):
    def test_pregame(self):
        self.assertEqual(p.price_status(lock(), KICK), "pregame")

    def test_post_kickoff_is_not_a_pregame_price(self):
        self.assertEqual(p.price_status(lock(line={"captured_at": "2026-10-11T18:00:00Z"}), KICK),
                         "post_kickoff")

    def test_missing_moneyline_is_no_price(self):
        self.assertEqual(p.price_status(lock(line={"home_moneyline": None}), KICK), "no_price")

    def test_missing_time_is_unknown_not_pregame(self):
        self.assertEqual(p.price_status(lock(line={"captured_at": None}), KICK), "unknown_time")


class Wager(unittest.TestCase):
    def test_priced_market_is_declined_by_the_observe_only_policy(self):
        w = p.wager(lock(), KICK)
        self.assertEqual((w["status"], w["reason"]), ("no_qualifying_wager", p.POLICY_STATUS))
        self.assertEqual(w["markets"]["ml"]["status"], "no_qualifying_wager")

    def test_unpriced_market_is_not_reported_as_a_failed_wager(self):
        w = p.wager(lock(line={"home_moneyline": None, "away_moneyline": None}), KICK)
        self.assertEqual(w["status"], "insufficient_price_data")
        self.assertEqual(w["markets"]["ml"]["status"], "insufficient_price_data")

    def test_spread_and_total_are_never_priced_without_juice(self):
        w = p.wager(lock(), KICK)
        for market in ("spread", "total"):
            self.assertEqual(w["markets"][market]["status"], "insufficient_price_data")
            self.assertEqual(w["markets"][market]["reason"], "no_price")

    def test_policy_issues_nothing(self):
        w = p.wager(lock(), KICK)
        self.assertFalse(any(m["status"] == "qualifying_wager" for m in w["markets"].values()))


class TotalLean(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(p.total_lean_result(46.0, 44.5, 51.0), "win")
        self.assertEqual(p.total_lean_result(46.0, 44.5, 40.0), "loss")
        self.assertEqual(p.total_lean_result(46.0, 44.5, 44.5), "push")
        self.assertEqual(p.total_lean_result(44.5, 44.5, 51.0), "no_pick")
        self.assertEqual(p.total_lean_result(None, 44.5, 51.0), "no_line")
        self.assertIsNone(p.total_lean_result(46.0, 44.5, None))


if __name__ == "__main__":
    unittest.main()
