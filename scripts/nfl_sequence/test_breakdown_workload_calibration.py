import unittest

import numpy as np

import breakdown_workload_calibration as breakdown
import fit_adaptive_workload_concentration as adaptive


class WorkloadBreakdownTests(unittest.TestCase):
    def test_predictive_interval_includes_finite_count_variation(self):
        lo, hi = breakdown.predictive_interval(10, 500000, 500000, np.random.default_rng(1))
        self.assertLess(lo, 5)
        self.assertGreater(hi, 5)

    def test_concentration_fit_reports_boundary_and_count(self):
        row = ({'a': 8, 'b': 2}, ['a', 'b'], ['a', 'b'], {'a': .8, 'b': .2},
               {'a': 'RB', 'b': 'RB'}, ('RB',))
        result = adaptive.fit({'RB': [row]})['RB']
        self.assertEqual(result['team_games'], 1)
        self.assertGreater(result['phi'], 0)
        self.assertIsInstance(result['grid_boundary'], bool)

    def test_within_group_nll_detects_wrong_player_allocation(self):
        counts = {'a': 9, 'b': 1, 'new': 1}
        positions = {'a': 'WR', 'b': 'WR', 'new': 'WR'}
        good = breakdown.within_group_nll(counts, ['a', 'b'], ['a', 'b'],
                                          {'a': .9, 'b': .1}, 10, positions, ('WR',))
        bad = breakdown.within_group_nll(counts, ['a', 'b'], ['a', 'b'],
                                         {'a': .1, 'b': .9}, 10, positions, ('WR',))
        self.assertLess(good, bad)


if __name__ == '__main__':
    unittest.main()
