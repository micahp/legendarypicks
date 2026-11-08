import unittest

import summarize_workload_experiment as summary


class WorkloadExperimentSummary(unittest.TestCase):
    def test_distribution_uses_central_eighty_percent(self):
        result = summary.distribution([0, 1, 2, 3, 4])
        self.assertEqual(result['n'], 5)
        self.assertEqual(result['median'], 2)
        self.assertAlmostEqual(result['p10'], .4)
        self.assertAlmostEqual(result['p90'], 3.6)

    def test_empty_distribution_is_unknown(self):
        self.assertIsNone(summary.distribution([]))

if __name__ == '__main__':
    unittest.main()
