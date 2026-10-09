"""Tests for nfl_metrics.py. Every expected value is worked out by hand, not read from the code.

Each convention (sign of the spread, de-vig normalisation, push handling) is checked against
a broken alternative that would give a different number.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_metrics as m  # noqa: E402


class Scores(unittest.TestCase):
    def test_brier(self):
        self.assertAlmostEqual(m.brier([0.5, 0.5], [1, 0]), 0.25, places=12)
        self.assertAlmostEqual(m.brier([1.0, 0.0], [1, 0]), 0.0, places=12)
        self.assertAlmostEqual(m.brier([0.8], [1]), 0.04, places=12)

    def test_log_loss(self):
        self.assertAlmostEqual(m.log_loss([0.5, 0.5], [1, 0]), math.log(2), places=12)
        # A confident wrong answer is finite after clipping, and large.
        self.assertGreater(m.log_loss([0.0], [1]), 20.0)
        self.assertTrue(math.isfinite(m.log_loss([0.0], [1])))

    def test_mae(self):
        self.assertAlmostEqual(m.mae([1.0, -3.0], [2.0, -1.0]), 1.5, places=12)

    def test_length_mismatch_is_refused(self):
        for fn in (m.brier, m.log_loss):
            with self.assertRaises(ValueError):
                fn([0.5], [1, 0])
        with self.assertRaises(ValueError):
            m.mae([1.0], [])

    def test_empty_is_refused(self):
        with self.assertRaises(ValueError):
            m.brier([], [])


class Market(unittest.TestCase):
    def test_american_to_prob(self):
        self.assertAlmostEqual(m.american_to_prob(-110), 110.0 / 210.0, places=12)
        self.assertAlmostEqual(m.american_to_prob(150), 0.4, places=12)

    def test_zero_odds_refused(self):
        with self.assertRaises(ValueError):
            m.american_to_prob(0)

    def test_even_market_devigs_to_half(self):
        self.assertAlmostEqual(m.devig_home_prob(-110, -110), 0.5, places=12)

    def test_devig_matches_hand_calc_on_real_line(self):
        # 2025 week 1 PHI (home) -425 / DAL +330. Implied 425/525 and 100/430 (exact fractions);
        # fair home = (425/525) / (425/525 + 100/430) = 731/941. Dividing by the sum is the choice.
        self.assertAlmostEqual(m.devig_home_prob(-425, 330), 731.0 / 941.0, places=12)

    def test_devig_is_not_raw_implied(self):
        raw = m.american_to_prob(-425)
        self.assertNotAlmostEqual(m.devig_home_prob(-425, 330), raw, places=3)


class Calibration(unittest.TestCase):
    def test_bins_count_and_flag(self):
        rows = m.calibration_bins([0.05, 0.15, 0.95, 1.0], [0, 1, 1, 1])
        self.assertEqual(len(rows), 10)
        by_lo = {round(r[0], 2): r for r in rows}
        self.assertEqual((by_lo[0.0][2], by_lo[0.0][3]), (1, 0))
        self.assertEqual((by_lo[0.1][2], by_lo[0.1][3]), (1, 1))
        # 0.95 and 1.0 both land in the top bin.
        self.assertEqual((by_lo[0.9][2], by_lo[0.9][3]), (2, 2))
        self.assertTrue(all(r[5] for r in rows))  # every bin here is under 20 games

    def test_bad_width_refused(self):
        with self.assertRaises(ValueError):
            m.calibration_bins([0.5], [1], width=0.0)


class AtsRules(unittest.TestCase):
    def test_home_covers_when_margin_beats_the_line(self):
        # Positive line = home favored by that much. Home must win by MORE than the line.
        self.assertEqual(m.ats_result(4, 3.0), "cover")
        self.assertEqual(m.ats_result(2, 3.0), "miss")

    def test_exact_margin_is_a_push(self):
        self.assertEqual(m.ats_result(3, 3.0), "push")

    def test_negative_line_home_underdog(self):
        # Home is +3 underdog (line -3). It covers if it loses by less than 3 or wins outright.
        self.assertEqual(m.ats_result(-1, -3.0), "cover")
        self.assertEqual(m.ats_result(-4, -3.0), "miss")

    def test_record_excludes_pushes_from_the_rate(self):
        rec = m.ats_record([4, 2, 3, 6], [3.0, 3.0, 3.0, 3.0])
        self.assertEqual((rec["cover"], rec["miss"], rec["push"]), (2, 1, 1))
        self.assertAlmostEqual(rec["cover_rate"], 2.0 / 3.0, places=12)

    def test_record_with_only_pushes_has_no_rate(self):
        self.assertIsNone(m.ats_record([3], [3.0])["cover_rate"])


class Bootstrap(unittest.TestCase):
    def test_identical_losses_have_zero_interval_around_zero(self):
        point, lo, hi = m.bootstrap_mean_diff_ci([0.2, 0.3, 0.1], [0.2, 0.3, 0.1], reps=500)
        self.assertEqual(point, 0.0)
        self.assertLessEqual(lo, 0.0)
        self.assertGreaterEqual(hi, 0.0)

    def test_constant_gap_gives_interval_away_from_zero(self):
        point, lo, hi = m.bootstrap_mean_diff_ci([0.3] * 40, [0.2] * 40, reps=500)
        self.assertAlmostEqual(point, 0.1, places=12)
        self.assertAlmostEqual(lo, 0.1, places=12)
        self.assertAlmostEqual(hi, 0.1, places=12)

    def test_seeded_so_reruns_match(self):
        a = m.bootstrap_mean_diff_ci([0.3, 0.1, 0.5, 0.2], [0.2, 0.2, 0.2, 0.2], reps=300)
        b = m.bootstrap_mean_diff_ci([0.3, 0.1, 0.5, 0.2], [0.2, 0.2, 0.2, 0.2], reps=300)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
