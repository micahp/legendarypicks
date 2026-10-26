import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_batch  # noqa: E402
import simulate_pregame_batch as batch  # noqa: E402


class BatchAggregation(unittest.TestCase):
    def test_player_template_keeps_full_depth_backup_roles(self):
        snapshot = {
            'rosters': {
                'home': {'team': 'SEA', 'players': [
                    {'gsis_id': 'sea-rb1', 'player_name': 'RB One', 'pos_abb': 'RB', 'pos_rank': 1,
                     'group': '3WR 1TE', 'starter': True},
                    {'gsis_id': 'sea-rb2', 'player_name': 'RB Two', 'pos_abb': 'RB', 'pos_rank': 2,
                     'group': '3WR 1TE', 'starter': False},
                    {'gsis_id': 'sea-rb1', 'player_name': 'RB One', 'pos_abb': 'KR', 'pos_rank': 1,
                     'group': 'Special Teams', 'starter': False},
                ]},
                'away': {'team': 'KC', 'players': []},
            },
        }
        players = batch._player_template(snapshot)
        self.assertFalse(players['sea-rb2']['starter'])
        self.assertEqual(players['sea-rb2']['position'], 'RB')
        self.assertEqual(players['sea-rb1']['position'], 'RB')
        self.assertEqual(len(players['sea-rb1']['roster_roles']), 2)
        self.assertEqual(len(players), 2)

    def test_all_seeds_are_retained_and_ties_are_in_regulation_distribution(self):
        rows = [
            {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 10, 'away_points': 7},
            {'seed': 2, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 7, 'away_points': 10},
            {'seed': 3, 'status': 'blocked', 'blocker': 'overtime_not_modelled', 'valid_full_game': False,
             'complete_game': False, 'regulation_end_reached': True, 'tied_at_regulation_end': True,
             'home_points': 14, 'away_points': 14},
            {'seed': 4, 'status': 'blocked', 'blocker': 'thin_pool_cell', 'valid_full_game': False,
             'complete_game': False, 'regulation_end_reached': False, 'tied_at_regulation_end': False,
             'home_points': 3, 'away_points': 3},
        ]
        report = pregame_batch.summarize_outcomes(rows, 4, home_market_margin=0, market_total=17)
        self.assertEqual(report['requested_games'], 4)
        self.assertEqual(len(report['outcomes']), 4)
        self.assertEqual(report['valid_full_games'], 2)
        self.assertEqual(report['tied_at_regulation_end'], 1)
        self.assertEqual(report['blocked_before_regulation_end'], 1)
        self.assertEqual(report['valid_full_game_distribution']['scores']['home']['mean'], 8.5)
        self.assertEqual(report['valid_full_game_distribution']['home_minus_away']['mean'], 0)
        self.assertEqual(report['regulation_end_reached_distribution']['sample_games'], 3)
        self.assertAlmostEqual(report['regulation_end_reached_distribution']['win_probability']['tie'], 1 / 3, places=4)
        self.assertEqual(report['blocker_counts'], {'overtime_not_modelled': 1, 'thin_pool_cell': 1})

    def test_market_pushes_and_missing_valid_samples_are_explicit(self):
        rows = [
            {'seed': 10, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 20, 'away_points': 17},
            {'seed': 11, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 20, 'away_points': 17},
        ]
        report = pregame_batch.summarize_outcomes(rows, 2, home_market_margin=3, market_total=37)
        settlement = report['valid_full_game_distribution']['market_settlement']
        self.assertEqual(settlement['spread_push_probability'], 1)
        self.assertEqual(settlement['total_push_probability'], 1)
        self.assertEqual(report['valid_full_game_distribution']['most_frequent_exact_score']['probability'], 1)

        blocked = [{'seed': 4, 'status': 'blocked', 'blocker': 'missing_pool', 'valid_full_game': False,
                    'complete_game': False, 'regulation_end_reached': False,
                    'tied_at_regulation_end': False, 'home_points': 0, 'away_points': 0}]
        report = pregame_batch.summarize_outcomes(blocked, 1)
        self.assertEqual(report['valid_full_game_distribution']['sample_games'], 0)
        self.assertEqual(report['valid_full_game_distribution']['scores'], None)

    def test_refuses_missing_or_duplicate_seed_rows(self):
        with self.assertRaisesRegex(ValueError, 'explicit seed outcomes'):
            pregame_batch.summarize_outcomes([], 1)
        with self.assertRaisesRegex(ValueError, 'unique integer seed'):
            pregame_batch.summarize_outcomes([{'seed': 3}, {'seed': 3}], 2)

    def test_regulation_tie_is_not_misreported_as_a_partial_game(self):
        result = batch._record_outcome(12, {
            'status': 'blocked', 'blocker': 'overtime_not_modelled', 'tied': True,
            'regulation_end_reached': False, 'final_quarter': 4, 'final_clock_seconds': 0,
            'complete_game': False, 'valid_full_game': False, 'points': {'A': 24, 'B': 24},
        })
        self.assertTrue(result['regulation_end_reached'])
        self.assertTrue(result['tied_at_regulation_end'])
        self.assertEqual(result['score_scope'], 'regulation_end_only')


if __name__ == '__main__':
    unittest.main()
