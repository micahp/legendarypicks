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
