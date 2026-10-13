"""Tests for the 2024 tuning grid: the ranking rule and the holdout guard."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_tune_2024 as tune  # noqa: E402


class Ranking(unittest.TestCase):
    def test_lower_brier_wins(self):
        a = {"brier": 0.22, "log_loss": 0.6, "nondefault": 2}
        b = {"brier": 0.23, "log_loss": 0.5, "nondefault": 0}
        self.assertIs(tune.rank([b, a])[0], a)

    def test_tie_to_three_decimals_prefers_fewer_nondefault(self):
        a = {"brier": 0.2231, "log_loss": 0.6, "nondefault": 2}
        b = {"brier": 0.2229, "log_loss": 0.6, "nondefault": 0}
        self.assertIs(tune.rank([a, b])[0], b)


    def test_log_loss_does_not_override_the_tie_rule(self):
        # Same Brier to three decimals. The config with fewer non-defaults wins even though its
        # log loss is worse.
        simple = {"brier": 0.2229, "log_loss": 0.9, "nondefault": 0}
        fancy = {"brier": 0.2231, "log_loss": 0.5, "nondefault": 2}
        self.assertIs(tune.rank([fancy, simple])[0], simple)


class HoldoutGuard(unittest.TestCase):
    def test_only_2024_is_tuned(self):
        self.assertEqual(tune.SEASON, 2024)
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "nfl_tune_2024.py")).read()
        self.assertNotIn("2025", src)


if __name__ == "__main__":
    unittest.main()
