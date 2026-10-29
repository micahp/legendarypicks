import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import run_slc_archival_comparison as comparison  # noqa: E402
import slc_config  # noqa: E402


class ArchivalComparisonContract(unittest.TestCase):
    def test_primary_population_is_exactly_the_28_locked_week5_to_week7_games(self):
        matrix = REPO / 'docs/research/slc-week1-7-readiness-2026-10-29/readiness_matrix.csv'
        candidates, classes = comparison._primary_candidates(matrix)
        self.assertEqual(classes, {'cutoff-valid': 28, 'exploratory reconstruction': 51, 'refused': 28})
        self.assertEqual(len(candidates), 28)
        self.assertEqual({row['week'] for row in candidates}, {'5', '6', '7'})
        self.assertTrue(all(row['readiness_class'] == 'cutoff-valid' for row in candidates))
        self.assertTrue(all(row['cutoff_basis'] == 'recorded LP lock' for row in candidates))

    def test_smoke_gate_compares_every_profile_layer_including_disabled_fixed_shares(self):
        expected = comparison._required_full_stack_layers()
        self.assertEqual(set(expected), set(slc_config.ENGINE_LAYER_KEYS))
        self.assertEqual(len(comparison.RUNTIME_FIELDS), len(slc_config.ENGINE_LAYER_KEYS) - 1)
        self.assertFalse(expected['fixed_player_target_carry_shares'])
        self.assertTrue(all(expected[name] for name in comparison.RUNTIME_FIELDS))


if __name__ == '__main__':
    unittest.main()
