"""Research V1.7 mechanical completion must not be advertised as a valid forecast."""
import unittest

import pregame_batch


class ResearchPenaltyAggregationTests(unittest.TestCase):
    def test_calibrated_and_mechanically_complete_population_are_separate(self):
        rows = [
            {'seed': 1, 'status': 'complete_regulation',
             'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True,
             'home_points': 24, 'away_points': 20},
            {'seed': 2, 'status': 'complete_regulation',
             'valid_full_game': False, 'complete_game': True,
             'regulation_end_reached': True,
             'home_points': 26, 'away_points': 17},
            {'seed': 3, 'status': 'blocked', 'blocker': 'safety_return_geometry',
             'valid_full_game': False, 'complete_game': False,
             'regulation_end_reached': False,
             'home_points': 7, 'away_points': 3},
        ]
        summary = pregame_batch.summarize_outcomes(rows, requested=3)
        self.assertEqual(summary['valid_full_games'], 1)
        self.assertEqual(summary['mechanically_complete_games'], 2)
        self.assertEqual(summary['research_only_complete_games'], 1)
        self.assertEqual(summary['blocked_before_regulation_end'], 1)
        self.assertEqual(summary['valid_full_game_distribution']['sample_games'], 1)
        self.assertEqual(summary['mechanically_complete_distribution']['sample_games'], 2)
        self.assertEqual(
            summary['mechanically_complete_distribution_status'],
            'research_diagnostic_not_a_validated_forecast')
        self.assertEqual(summary['mechanically_complete_distribution']['market_settlement'], None)
        self.assertEqual(summary['valid_full_game_distribution']['scores']['home']['mean'], 24)

    def test_partial_and_validation_error_games_do_not_leak_into_final_scores(self):
        rows = [
            {'seed': 4, 'status': 'validation_error',
             'valid_full_game': True, 'complete_game': True,
             'home_points': 99, 'away_points': 0},
            {'seed': 5, 'status': 'blocked', 'blocker': 'unresolved_ruling',
             'valid_full_game': False, 'complete_game': False,
             'home_points': 31, 'away_points': 0},
        ]
        summary = pregame_batch.summarize_outcomes(rows, requested=2)
        self.assertEqual(summary['valid_full_games'], 0)
        self.assertEqual(summary['mechanically_complete_games'], 0)
        self.assertEqual(summary['research_only_complete_games'], 0)
        self.assertEqual(summary['simulation_or_validation_errors'], 1)
        self.assertEqual(summary['mechanically_complete_distribution']['sample_games'], 0)


if __name__ == '__main__':
    unittest.main()
