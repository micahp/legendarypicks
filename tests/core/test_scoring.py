# tests/core/test_scoring.py
import unittest
import sys
import os

# Adjust the Python path to include the src directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from core.scoring import calculate_fantasy_points, SCORING_RULES
# from core.nba_data import MOCK_BOX_SCORES # Using local samples as per example

# Sample box scores for testing (as provided in the prompt example)
NIKOLA_JOKIC_TD_EXAMPLE = { # Triple-Double example
    "player_id": 203999, "player_name": "Nikola Jokic", "game_id": "0022300001", 
    "team_abbreviation": "DEN", "PTS": 30, "REB": 15, "AST": 12, "STL": 2, "BLK": 1, "TOV": 3
}
# Expected: (30*1.0) + (15*1.2) + (12*1.5) + (2*3.0) + (1*3.0) + (3*-1.0) + 3.0 (TD bonus)
#         = 30 + 18 + 18 + 6 + 3 - 3 + 3.0 = 75.0

PLAYER_DD_EXAMPLE = { # Double-Double example
    "player_id": 1628369, "player_name": "Jayson Tatum", "game_id": "0022300003",
    "team_abbreviation": "BOS", "PTS": 28, "REB": 10, "AST": 4, "STL": 1, "BLK": 0, "TOV": 2
}
# Expected: (28*1.0) + (10*1.2) + (4*1.5) + (1*3.0) + (0*3.0) + (2*-1.0) + 1.5 (DD bonus)
#         = 28 + 12 + 6 + 3 + 0 - 2 + 1.5 = 48.5

PLAYER_NO_BONUS_EXAMPLE = {
    "player_id": 201939, "player_name": "Stephen Curry", "game_id": "0022300004",
    "team_abbreviation": "GSW", "PTS": 33, "REB": 5, "AST": 5, "STL": 1, "BLK": 0, "TOV": 3
}
# Expected: (33*1.0) + (5*1.2) + (5*1.5) + (1*3.0) + (0*3.0) + (3*-1.0)
#         = 33 + 6 + 7.5 + 3 + 0 - 3 = 46.5

class TestScoring(unittest.TestCase):

    def test_triple_double(self):
        points = calculate_fantasy_points(NIKOLA_JOKIC_TD_EXAMPLE, SCORING_RULES)
        self.assertEqual(points, 75.0)

    def test_double_double(self):
        points = calculate_fantasy_points(PLAYER_DD_EXAMPLE, SCORING_RULES)
        self.assertEqual(points, 48.5)

    def test_no_bonus(self):
        points = calculate_fantasy_points(PLAYER_NO_BONUS_EXAMPLE, SCORING_RULES)
        self.assertEqual(points, 46.5)

    def test_zero_stats_negative_turnovers(self):
        zero_stats = {"PTS": 0, "REB": 0, "AST": 0, "STL": 0, "BLK": 0, "TOV": 2}
        points = calculate_fantasy_points(zero_stats, SCORING_RULES) # (2 * -1.0) = -2.0
        self.assertEqual(points, -2.0)
            
    def test_empty_box_score(self):
        points = calculate_fantasy_points({}, SCORING_RULES)
        self.assertEqual(points, 0.0)

    def test_all_zero_values_no_bonus(self):
        # Player has stats but none are >= 10, and TOV is 0
        all_zeros = {"PTS": 5, "REB": 5, "AST": 5, "STL": 0, "BLK": 0, "TOV": 0}
        # Expected: (5*1.0) + (5*1.2) + (5*1.5) = 5 + 6 + 7.5 = 18.5
        points = calculate_fantasy_points(all_zeros, SCORING_RULES)
        self.assertEqual(points, 18.5)

    def test_single_stat_category_double_digit_no_bonus(self):
        single_double_digit = {"PTS": 15, "REB": 5, "AST": 3, "STL": 1, "BLK": 1, "TOV": 1}
        # Expected: (15*1) + (5*1.2) + (3*1.5) + (1*3) + (1*3) + (1*-1)
        #         = 15 + 6 + 4.5 + 3 + 3 - 1 = 30.5
        points = calculate_fantasy_points(single_double_digit, SCORING_RULES)
        self.assertEqual(points, 30.5)
        
    def test_exact_double_double_threshold(self):
        exact_dd = {"PTS": 10, "REB": 10, "AST": 1, "STL": 0, "BLK": 0, "TOV": 0}
        # Expected: (10*1) + (10*1.2) + (1*1.5) + 1.5 (DD)
        #         = 10 + 12 + 1.5 + 1.5 = 25.0
        points = calculate_fantasy_points(exact_dd, SCORING_RULES)
        self.assertEqual(points, 25.0)

    def test_exact_triple_double_threshold(self):
        exact_td = {"PTS": 10, "REB": 10, "AST": 10, "STL": 0, "BLK": 0, "TOV": 0}
        # Expected: (10*1) + (10*1.2) + (10*1.5) + 3.0 (TD)
        #         = 10 + 12 + 15 + 3.0 = 40.0
        points = calculate_fantasy_points(exact_td, SCORING_RULES)
        self.assertEqual(points, 40.0)

    def test_quadruple_double_gets_td_bonus(self): # Four stats >= 10 should still get TD bonus
        quad_double = {"PTS": 10, "REB": 10, "AST": 10, "STL": 10, "BLK": 0, "TOV": 0}
        # Expected: (10*1) + (10*1.2) + (10*1.5) + (10*3.0) + 3.0 (TD)
        #         = 10 + 12 + 15 + 30 + 3.0 = 70.0
        points = calculate_fantasy_points(quad_double, SCORING_RULES)
        self.assertEqual(points, 70.0)

if __name__ == '__main__':
    # Adding a simple way to run tests from this file directly
    # This is helpful for development and debugging.
    # To make this runnable:
    # 1. Ensure current directory is the root of the project when running.
    # 2. Or, ensure src is in PYTHONPATH.
    # The sys.path manipulation at the top helps with discovery if run from tests/core.
    unittest.main()
