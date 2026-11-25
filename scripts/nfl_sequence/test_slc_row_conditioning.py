import unittest

import slc_row_conditioning as conditioning


class RowConditioningTests(unittest.TestCase):
    def test_support_aware_relaxes_optional_conditions_to_minimum(self):
        rows = [
            {'formation': 'a', 'coverage': 'man'} for _ in range(12)
        ] + [
            {'formation': 'b', 'coverage': 'zone'} for _ in range(18)
        ]
        conditions = [
            ('formation', lambda row: row['formation'] == 'a'),
            ('coverage', lambda row: row['coverage'] == 'man'),
        ]

        selected, audit = conditioning.support_aware(rows, conditions, [1.0] * len(rows))

        self.assertEqual(len(selected), 30)
        self.assertEqual(audit['optional_conditions_retained'], [])
        self.assertFalse(audit['below_minimum_after_relaxation'])

    def test_support_aware_reports_base_pool_below_minimum(self):
        rows = [{'formation': 'a'} for _ in range(4)]
        selected, audit = conditioning.support_aware(
            rows, [('formation', lambda row: row['formation'] == 'missing')], [1.0] * len(rows))

        self.assertEqual(selected, rows)
        self.assertTrue(audit['below_minimum_after_relaxation'])
        self.assertEqual(audit['optional_conditions_retained'], [])

    def test_support_aware_uses_final_weighted_support(self):
        rows = [{'formation': 'target'} for _ in range(10)] + [{'formation': 'other'} for _ in range(20)]
        final_weights = [1.0] + [0.001] * 9 + [1.0] * 20
        selected, audit = conditioning.support_aware(
            rows, [('formation', lambda row: row['formation'] == 'target')], final_weights,
            min_candidates=10, min_ess=5.0)

        self.assertEqual(selected, rows)
        self.assertEqual(audit['optional_conditions_retained'], [])
        self.assertLess(audit['initial_support']['effective_sample_size'], 5.0)
        self.assertFalse(audit['below_minimum_after_relaxation'])

    def test_final_sampling_weights_combine_transition_and_row_weights(self):
        self.assertEqual([2.0, 0.25], conditioning.final_sampling_weights([1.0, 0.5], [2.0, 0.5]))

    def test_final_sampling_weights_reject_misaligned_factors(self):
        with self.assertRaisesRegex(ValueError, 'align'):
            conditioning.final_sampling_weights([1.0], [1.0, 2.0])

    def test_soft_conditioning_is_bounded_and_keeps_shrunk_outside_support(self):
        rows = [{'label': 'target'} for _ in range(5)] + [{'label': 'other'} for _ in range(95)]
        weights, audit = conditioning.soft_weights(
            rows, [('label', lambda row: row['label'] == 'target')], [1.0] * len(rows),
            max_condition_weight=4.0, shrinkage_prior_n=25.0)

        self.assertEqual(len(weights), len(rows))
        self.assertTrue(all(weight > 0 for weight in weights))
        self.assertLessEqual(audit['context_weight_max'], 4.0)
        self.assertLess(audit['effective_sample_size'], len(rows))
        self.assertIn('filter_order_dependence', audit)

    def test_soft_shrinkage_uses_each_conditions_matched_support(self):
        rows = [{'label': 'rare'} for _ in range(5)] + [{'label': 'common'} for _ in range(95)]
        _weights, audit = conditioning.soft_weights(
            rows, [('label', lambda row: row['label'] == 'rare')], [1.0] * len(rows),
            condition_support_weights=[1.0] * len(rows), shrinkage_prior_n=25.0)

        record = audit['optional_conditions_weighted'][0]
        self.assertEqual(record['matched_effective_sample_size'], 5.0)
        self.assertAlmostEqual(record['shrinkage'], 5.0 / 30.0)

    def test_filter_order_audit_exposes_noncommuting_fallbacks(self):
        rows = [
            {'formation': 'a', 'coverage': 'man'},
            {'formation': 'b', 'coverage': 'zone'},
            {'formation': 'b', 'coverage': 'zone'},
        ]
        conditions = [
            ('formation', lambda row: row['formation'] == 'a'),
            ('coverage', lambda row: row['coverage'] == 'zone'),
        ]

        audit = conditioning.filter_order_dependence(rows, conditions)

        self.assertEqual(audit['canonical_final_candidates'], 1)
        self.assertEqual(audit['reverse_final_candidates'], 2)
        self.assertEqual(audit['symmetric_difference_candidates'], 3)


if __name__ == '__main__':
    unittest.main()
