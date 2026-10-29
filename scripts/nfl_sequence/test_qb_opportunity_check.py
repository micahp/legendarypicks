"""The QB-opportunity validation check: simulated plays per game against the season's actual, as relative gaps."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qb_opportunity_check as qc  # noqa: E402


class Compare(unittest.TestCase):
    def test_the_gap_is_simulated_over_actual_minus_one(self):
        out = qc.compare({'dropback': 75.0, 'run': 60.0, 'scrimmage': 135.0}, {'dropback': 69.0, 'run': 52.0, 'scrimmage': 121.0})
        self.assertAlmostEqual(out['dropback']['gap'], 75.0 / 69.0 - 1)
        self.assertAlmostEqual(out['scrimmage']['gap'], 135.0 / 121.0 - 1)

    def test_the_pass_share_is_dropbacks_over_scrimmage_plays(self):
        out = qc.compare({'dropback': 75.0, 'run': 60.0, 'scrimmage': 135.0}, {'dropback': 69.0, 'run': 52.0, 'scrimmage': 121.0})
        self.assertAlmostEqual(out['pass_share']['simulated'], 75.0 / 135.0)
        self.assertAlmostEqual(out['pass_share']['actual'], 69.0 / 121.0)

    def test_a_zero_actual_is_not_divided_by_zero(self):
        out = qc.compare({'dropback': 1.0, 'run': 1.0, 'scrimmage': 2.0}, {'dropback': 0.0, 'run': 1.0, 'scrimmage': 1.0})
        self.assertIsNone(out['dropback']['gap'])


if __name__ == '__main__':
    unittest.main()
