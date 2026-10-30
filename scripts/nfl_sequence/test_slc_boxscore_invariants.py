"""Negative box-score mutations and the mandatory per-seed SLC accounting gate."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import simulate_pregame_batch as batch  # noqa: E402
import slc_outputs as outputs  # noqa: E402
from test_slc_outputs import PROFILE, SNAPSHOT, game_record  # noqa: E402


def build(record, seed=17):
    outcome = {'seed': seed, 'status': 'complete', 'valid_full_game': True,
               'complete_game': True, 'tied_at_regulation_end': False}
    return outputs.build_boxscore(seed, outcome, record, SNAPSHOT, PROFILE)


class BoxscoreHardInvariants(unittest.TestCase):
    def test_mutation_completions_over_attempts_and_receptions_over_targets_fails(self):
        record = game_record()
        record['stats']['team']['A']['pass_comp'] = 2
        record['stats']['player'][0]['passing']['comp'] = 2
        record['stats']['player'][1]['receiving']['rec'] = 2

        box = build(record)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertEqual(box['reconciliation']['failure_class'], 'STAT_ACCOUNTING')
        home = next(row for row in box['reconciliation']['teams'] if row['side'] == 'A')
        self.assertIn('completions_exceed_attempts', home['mismatches'])
        self.assertIn('receptions_exceed_targets', home['mismatches'])

    def test_mutation_turnover_and_game_points_mismatches_fail(self):
        record = game_record()
        record['stats']['team']['A']['points'] = 23
        record['stats']['team']['A']['interceptions'] = 1
        record['stats']['player'][0]['passing']['int'] = 1

        box = build(record)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertEqual(box['reconciliation']['failure_class'], 'STAT_ACCOUNTING')
        home = next(row for row in box['reconciliation']['teams'] if row['side'] == 'A')
        self.assertIn('team_points_vs_game_points', home['mismatches'])
        self.assertEqual(home['mismatches']['turnovers'], {'players': 1, 'team': 0})

    def test_valid_complete_slc_seed_is_checked_even_without_boxscore_export(self):
        record = game_record()
        valid = {'seed': 17, 'status': 'complete', 'valid_full_game': True,
                 'complete_game': True, 'tied_at_regulation_end': False}
        with patch.object(batch.slc_engine, 'is_slc', return_value=True), \
                patch.object(batch.slc_engine, 'play', return_value=(record, [])), \
                patch.object(batch.gs, 'validate_game'), \
                patch.object(batch, '_record_outcome', return_value=valid.copy()), \
                patch.object(batch.slc_outputs, 'build_boxscore', return_value={
                    'reconciliation': {'status': 'passed'}}) as build_boxscore:
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        build_boxscore.assert_called_once()
        self.assertTrue(outcome['valid_full_game'])
        self.assertNotIn('boxscore', outcome)
        self.assertIsNotNone(contribution)

    def test_failed_per_seed_reconciliation_marks_seed_invalid_and_excludes_it(self):
        record = game_record()
        good = {'seed': 17, 'status': 'complete', 'valid_full_game': True,
                'complete_game': True, 'tied_at_regulation_end': False}
        failed = {'seed': 17, 'status': 'validation_error', 'valid_full_game': False,
                  'complete_game': False, 'tied_at_regulation_end': False}
        with patch.object(batch.slc_engine, 'is_slc', return_value=True), \
                patch.object(batch.slc_engine, 'play', return_value=(record, [])), \
                patch.object(batch.gs, 'validate_game'), \
                patch.object(batch, '_record_outcome', side_effect=[good, failed]), \
                patch.object(batch.slc_outputs, 'build_boxscore', return_value={
                    'reconciliation': {'status': 'failed', 'failure_class': 'STAT_ACCOUNTING'}}) as build_boxscore:
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        build_boxscore.assert_called_once()
        self.assertFalse(outcome['valid_full_game'])
        self.assertIn('STAT_ACCOUNTING', outcome['boxscore_error'])
        self.assertIsNone(contribution)


if __name__ == '__main__':
    unittest.main()
