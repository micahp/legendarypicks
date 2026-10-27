from __future__ import annotations

import unittest

from evidence_core import (binary_scores, decode_situation_code, parse_clock,
                           score_state, shrink_binary_rate, strength_for_side,
                           time_remaining_bucket)


class EvidenceCoreTests(unittest.TestCase):
    def test_period_clock_is_strict(self):
        self.assertEqual(parse_clock("19:59"), 1199)
        for value in ("20:60", "1:2", None):
            with self.assertRaises(ValueError):
                parse_clock(value)

    def test_situation_code_decodes_expected_fields_and_quarantines_bad_values(self):
        self.assertEqual(decode_situation_code("1451"), {
            "away_goalie": 1, "away_skaters": 4,
            "home_skaters": 5, "home_goalie": 1,
        })
        self.assertIsNone(decode_situation_code("155"))
        self.assertIsNone(decode_situation_code("2551"))

    def test_team_perspective_strength_and_game_state_bins(self):
        self.assertEqual(strength_for_side(5, 4, "home"), "5v4")
        self.assertEqual(strength_for_side(5, 4, "away"), "4v5")
        self.assertEqual(score_state(2, 1), "leading")
        self.assertEqual(score_state(1, 2), "trailing")
        self.assertEqual(time_remaining_bucket("REG", 1200, 1141), "<=1m")

    def test_beta_binomial_shrinkage_falls_back_to_parent(self):
        self.assertAlmostEqual(shrink_binary_rate(0, 0, 0.25), 0.25)
        self.assertAlmostEqual(shrink_binary_rate(9, 10, 0.5), 19 / 30)

    def test_binary_scores(self):
        scores = binary_scores([1, 0], [0.75, 0.25])
        self.assertEqual(scores["n"], 2)
        self.assertAlmostEqual(scores["brier"], 0.0625)


if __name__ == "__main__":
    unittest.main()
