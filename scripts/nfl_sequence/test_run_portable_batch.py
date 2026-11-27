"""Regression tests for the portable batch acceptance boundary."""
import unittest
from copy import deepcopy
from run_portable_batch import validate_run
from roster_preflight import failed


class RunAcceptance(unittest.TestCase):
    def setUp(self):
        self.data = {'game_id': 'game', 'snapshot_sha256': 'snap',
                     'pack': {'model_id': 'model', 'sha256': 'pack'},
                     'simulation': {'requested_games': 2, 'valid_full_games': 2,
                                    'seed_start': 5, 'seed_end_inclusive': 6},
                     'summary': {'valid_full_games': 2, 'outcomes': [
                         {'seed': seed, 'valid_full_game': True, 'complete_game': True,
                          'score_scope': 'valid_final', 'home_points': 21, 'away_points': 17}
                         for seed in (5, 6)]},
                     'player_boxscores_by_seed': [{'seed': seed, 'players': []} for seed in (5, 6)]}

    def check(self, score_only=False):
        return failed(validate_run(self.data, 2, 5, 'game', 'model', 'pack', 'snap', score_only=score_only))

    def test_complete(self):
        self.assertFalse(self.check())

    def test_requested_is_not_valid(self):
        self.data['simulation']['valid_full_games'] = 1
        self.assertTrue(self.check())

    def test_blocked_seed_with_falsely_complete_counts(self):
        self.data['summary']['outcomes'][1]['valid_full_game'] = False
        self.assertTrue(self.check())

    def test_duplicate_seed(self):
        self.data['summary']['outcomes'][1]['seed'] = 5
        self.assertTrue(self.check())

    def test_wrong_snapshot(self):
        self.data['snapshot_sha256'] = 'other'
        self.assertTrue(self.check())

    def test_score_only_is_explicit(self):
        self.data.pop('player_boxscores_by_seed')
        self.assertTrue(self.check())
        self.assertTrue(self.check(score_only=True))
        self.data['player_lines_available'] = False
        self.assertFalse(self.check(score_only=True))


if __name__ == '__main__':
    unittest.main()
