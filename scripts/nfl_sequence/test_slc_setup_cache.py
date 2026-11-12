"""Fast build-cache regression tests that need no NFL database."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slc_setup_cache as cache  # noqa: E402


class ConditionalFitCache(unittest.TestCase):
    @staticmethod
    def pool():
        return {
            (1, '10+', 'other'): [
                ('pass_complete', {'season': 2024, 'penalty': 0,
                                   'labels': {'A': 'WR', 'D': 'deep', 'E': 'left'},
                                   'yards_gained': 8}, 12, None),
                ('sack', {'season': 2024, 'penalty': 0, 'labels': {}}, 10, None),
            ],
        }

    def test_identical_training_inputs_use_one_fit_across_model_snapshots(self):
        first = self.pool()
        other = copy.deepcopy(first)
        other[(1, '10+', 'other')][0][1]['yards_gained'] = 99  # unused by the conditional fit
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {'SLC_FIT_CACHE_DIR': folder}), \
                mock.patch.object(cache.pass_label_outcomes.PassLabelOutcomeModel, 'fit',
                                  side_effect=[{'fit_number': 1}, {'fit_number': 2}]) as fit:
            self.assertEqual(cache.fit_pass_label_outcomes(first), {'fit_number': 1})
            self.assertEqual(cache.fit_pass_label_outcomes(other), {'fit_number': 1})
            self.assertEqual(fit.call_count, 1)
            other[(1, '10+', 'other')][0][1]['labels']['D'] = 'short'
            self.assertEqual(cache.fit_pass_label_outcomes(other), {'fit_number': 2})
            self.assertEqual(fit.call_count, 2)

    def test_disabled_cache_always_uses_original_fit(self):
        with mock.patch.dict(os.environ, {'SLC_FIT_CACHE_DIR': ''}), \
                mock.patch.object(cache.pass_label_outcomes.PassLabelOutcomeModel, 'fit',
                                  return_value='uncached') as fit:
            self.assertEqual(cache.fit_pass_label_outcomes(self.pool()), 'uncached')
            self.assertEqual(cache.fit_pass_label_outcomes(self.pool()), 'uncached')
            self.assertEqual(fit.call_count, 2)

    def test_penalty_order_season_and_event_are_part_of_cache_identity(self):
        original = self.pool()
        reference_hash = cache.pass_label_input_sha256(original)
        variants = []
        for field, replacement in [('season', 2023), ('penalty', None)]:
            altered = copy.deepcopy(original)
            altered[(1, '10+', 'other')][0][1][field] = replacement
            variants.append(altered)
        swapped = copy.deepcopy(original)
        swapped[(1, '10+', 'other')].reverse()
        variants.append(swapped)
        changed_event = copy.deepcopy(original)
        first_event, first_row, first_runoff, first_spot = changed_event[(1, '10+', 'other')][0]
        changed_event[(1, '10+', 'other')][0] = ('pass_incomplete', first_row, first_runoff, first_spot)
        variants.append(changed_event)
        for variant in variants:
            self.assertNotEqual(cache.pass_label_input_sha256(variant), reference_hash)

    def test_fumble_source_play_type_and_scramble_change_fit_cache_identity(self):
        original = {(1, '3-5', '30-49'): [
            ('fumble_lost', {'season': 2024, 'penalty': 0, 'play_type': 'pass',
                             'qb_scramble': 0,
                             'labels': {'A': 'WR', 'D': 'short', 'E': 'left'}}, 0, None)]}
        baseline = cache.pass_label_input_sha256(original)
        changed_type = copy.deepcopy(original)
        changed_type[(1, '3-5', '30-49')][0][1]['play_type'] = 'run'
        self.assertNotEqual(cache.pass_label_input_sha256(changed_type), baseline)
        changed_scramble = copy.deepcopy(original)
        changed_scramble[(1, '3-5', '30-49')][0][1]['qb_scramble'] = 1
        self.assertNotEqual(cache.pass_label_input_sha256(changed_scramble), baseline)

    def test_unrelated_yardage_does_not_invalidate_fit(self):
        original = self.pool()
        altered = copy.deepcopy(original)
        altered[(1, '10+', 'other')][0][1]['yards_gained'] += 100
        self.assertEqual(cache.pass_label_input_sha256(altered),
                         cache.pass_label_input_sha256(original))


if __name__ == '__main__':
    unittest.main()
