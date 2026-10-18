#!/usr/bin/env python3
"""Unit checks for the increment (b) feature builder.

Covers the claims the ladder makes about leakage control and the EPA construction:
  * the allow-list passes and any banned or unknown column raises;
  * the EP design matrix has the pre-registered shape;
  * a scoring play is worth its points plus the change in expectation.

Run: /root/legendarypicks/backend/venv/bin/python -m unittest backend/test_fbs_phase3_features.py
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbs_phase3_features as f  # noqa: E402


class AllowListTest(unittest.TestCase):
    def test_allow_list_passes(self):
        f.assert_allowed(f.ALLOWED_COLUMNS)

    def test_banned_columns_raise(self):
        for column in ("EPA", "wpa", "ep_before", "ep_after", "ppa", "success_rate", "fpi",
                       "home_spread", "win_probability"):
            with self.assertRaises(ValueError, msg=column):
                f.assert_allowed([column])

    def test_unknown_column_raises(self):
        with self.assertRaises(ValueError):
            f.assert_allowed(["not_a_real_column"])

    def test_allow_list_contains_no_banned_name(self):
        self.assertEqual([c for c in f.ALLOWED_COLUMNS if f.BANNED.search(c)], [])


class DesignTest(unittest.TestCase):
    def test_design_shape(self):
        df = pd.DataFrame({"down": [1, 3, 4], "distance": [10, 2, 7], "yards_to_goal": [75, 20, 50]})
        X = f.state_design(df)
        self.assertEqual(X.shape, (3, len(f.EP_FEATURES)))
        self.assertTrue(np.isfinite(X).all())

    def test_missing_state_defaults(self):
        df = pd.DataFrame({"down": [None], "distance": [None], "yards_to_goal": [None]})
        X = f.state_design(df)
        self.assertTrue(np.isfinite(X).all())


class EpaConstructionTest(unittest.TestCase):
    def test_scoring_play_is_points_plus_change(self):
        plays = pd.DataFrame({
            "game_id": [1, 1],
            "pos_team": ["A", "B"],
            "def_pos_team": ["B", "A"],
            "down": [1, 1], "distance": [10, 10], "yards_to_goal": [80, 20],
            "down_end": [1, 1], "distance_end": [10, 10], "yards_to_goal_end": [20, 80],
            "pass": [True, False], "rush": [False, True],
            "change_of_pos_team": [True, False],
            "pts_scored": [7.0, 0.0],
        })
        coef = np.zeros(len(f.EP_FEATURES))
        coef[f.EP_FEATURES.index("field")] = 0.5      # EP rises with field position
        out = f.attach_epa(f.add_states(plays), coef)
        cur = 0.5 * (80 / 9.9)
        nxt = 0.5 * (20 / 9.9)
        self.assertAlmostEqual(out.loc[0, "epa"], 7.0 + nxt - cur, places=6)
        self.assertEqual(out.loc[0, "success"], 1.0)


if __name__ == "__main__":
    unittest.main()
