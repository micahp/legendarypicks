import unittest

import numpy as np

from rule_feasibility import (
    GH_U,
    GH_WEIGHTS,
    _expit,
    crps_ensemble,
    mean_preserving_offset,
    moments,
    resplit_counts,
)


class RuleFeasibilityTests(unittest.TestCase):
    def test_mean_preserving_offsets_across_preregistered_points(self):
        for p0 in (0.2, 0.5, 0.8):
            for sigma in (0.1, 0.324, 0.45):
                offset = mean_preserving_offset(p0, sigma)
                expectation = float(
                    np.dot(_expit(np.log(p0 / (1.0 - p0)) + offset + sigma * GH_U), GH_WEIGHTS)
                )
                self.assertLess(abs(expectation - p0), 1e-10)

    def test_sigma_zero_resplit_is_exact_identity_and_preserves_moments(self):
        pairs = np.asarray([[[3, 7], [5, 5]], [[0, 8], [8, 0]]], dtype=np.int64)
        rng = np.random.default_rng(91)
        output = resplit_counts(pairs, 0.0, np.zeros((2, 2)), rng)
        self.assertEqual(output.tobytes(), pairs.tobytes())
        self.assertEqual(moments(output), moments(pairs))

    def test_crps_on_hand_computable_two_point_ensemble(self):
        self.assertAlmostEqual(crps_ensemble([0, 2], 1), 0.5, places=12)


if __name__ == "__main__":
    unittest.main()
