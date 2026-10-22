import unittest

import numpy as np

from kernel_fix import (
    baseline_conversion_rates,
    conditional_conversion_probabilities,
    conditional_sog_draws,
)
from rule_feasibility import (
    GH_U,
    GH_WEIGHTS,
    _expit,
    mean_preserving_offset,
    paired_margin_variance_bootstrap,
)


class ConditionalSOGKernelTests(unittest.TestCase):
    def test_sigma_zero_rates_are_phase2a_rates_and_expected_counts_reconcile(self):
        attempts = np.asarray([[[0, 0], [5, 3]], [[4, 7], [2, 6]]], dtype=np.int64)
        sog = np.asarray([[[0, 0], [2, 1]], [[1, 3], [1, 2]]], dtype=np.int64)
        rates = baseline_conversion_rates(attempts, sog)
        probabilities = conditional_conversion_probabilities(rates, 0.0, np.zeros((2, 2)))
        self.assertTrue(np.array_equal(probabilities, rates))
        expected_counts = attempts * probabilities
        self.assertLessEqual(float(np.max(np.abs(expected_counts - sog))), 1e-12)

    def test_mean_preserving_offsets_and_opposite_shared_latent(self):
        p0 = np.asarray([0.2, 0.5, 0.8], dtype=float)
        for sigma in (0.0, 0.10, 0.16, 0.24, 0.324, 0.45):
            for p in p0:
                offset = mean_preserving_offset(float(p), sigma)
                expected = float(np.dot(
                    _expit(np.log(p / (1.0 - p)) + offset + sigma * GH_U), GH_WEIGHTS
                ))
                self.assertLess(abs(expected - float(p)), 1e-12)

            rate_grid = np.broadcast_to(p0[None, None, :2], (1, len(GH_U), 2)).copy()
            u_grid = np.broadcast_to(GH_U[None, :], (1, len(GH_U)))
            adjusted = conditional_conversion_probabilities(rate_grid, sigma, u_grid)
            means = adjusted[0].T @ GH_WEIGHTS
            np.testing.assert_allclose(means, p0[:2], atol=1e-12, rtol=0.0)

    def test_probabilities_are_continuous_at_zero_for_fixed_latents(self):
        p0 = np.asarray([[[0.12, 0.31], [0.62, 0.85]]], dtype=float)
        latent = np.asarray([[2.0, -3.0]])
        adjusted = conditional_conversion_probabilities(p0, 1e-9, latent)
        self.assertLess(float(np.max(np.abs(adjusted - p0))), 1e-7)

    def test_binomial_kernel_is_reproducible_and_never_exceeds_attempts(self):
        attempts = np.asarray([[[0, 0], [5, 3]], [[4, 7], [2, 6]]], dtype=np.int64)
        sog = np.asarray([[[0, 0], [2, 1]], [[1, 3], [1, 2]]], dtype=np.int64)
        rng = np.random.default_rng(732)
        shared_u = rng.standard_normal(attempts.shape[:2])
        uniforms = rng.random(attempts.shape)
        first = conditional_sog_draws(attempts, sog, 0.324, shared_u, uniforms)
        second = conditional_sog_draws(attempts, sog, 0.324, shared_u, uniforms)
        self.assertTrue(np.array_equal(first, second))
        self.assertTrue(np.all(first >= 0))
        self.assertTrue(np.all(first <= attempts))
        self.assertTrue(np.array_equal(attempts[0, 0], np.asarray([0, 0])))

    def test_paired_attempt_bootstrap_is_degenerate_for_fixed_trace(self):
        attempts = np.asarray([[[3, 5], [4, 4]], [[6, 2], [5, 3]]], dtype=np.int64)
        indices = np.asarray([[0, 1], [1, 0], [1, 1]], dtype=np.int32)
        interval = paired_margin_variance_bootstrap(attempts, attempts.copy(), indices)
        self.assertEqual(interval["lower_95"], 0.0)
        self.assertEqual(interval["upper_95"], 0.0)
        self.assertFalse(interval["interval_wholly_above_zero"])


if __name__ == "__main__":
    unittest.main()
