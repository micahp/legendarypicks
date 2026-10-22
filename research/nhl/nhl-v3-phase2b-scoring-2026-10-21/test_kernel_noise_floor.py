import unittest

import numpy as np
from scipy.stats import betabinom

from kernel_noise_floor import (
    _betabinomial_ppf_recurrence,
    beta_binomial_sog_draws,
    crps_by_game_vectorized,
    fit_beta_binomial_moments,
)
from rule_feasibility import GH_U, GH_WEIGHTS, crps_by_game, mean_preserving_offset


class BetaBinomialMomentFitTests(unittest.TestCase):
    def test_fit_removes_variance_from_varying_attempt_counts(self):
        attempts = np.array([[[5, 10], [10, 10], [15, 10], [20, 10]]])
        sog = np.array([[[1, 5], [5, 5], [9, 5], [15, 5]]])

        fit = fit_beta_binomial_moments(attempts, sog)

        n = attempts[0, :, 0].astype(float)
        y = sog[0, :, 0].astype(float)
        m = y.sum() / n.sum()
        expected_base = (
            m * (1 - m) * n.mean()
            + m * m * (len(n) / (len(n) - 1)) * np.var(n, ddof=0)
        )
        expected_rho = (
            (np.var(y, ddof=1) - expected_base)
            / np.mean(n * (n - 1))
            / (m * (1 - m))
        )
        self.assertAlmostEqual(fit["mean_rate"][0, 0], m)
        self.assertAlmostEqual(fit["binomial_and_attempt_variance"][0, 0], expected_base)
        self.assertAlmostEqual(fit["rho"][0, 0], expected_rho)
        self.assertEqual(fit["rho"][0, 1], 0.0)
        self.assertTrue(np.isinf(fit["concentration"][0, 1]))

    def test_nonpositive_excess_variance_falls_back_to_binomial(self):
        attempts = np.full((1, 4, 2), 10, dtype=np.int64)
        sog = np.array([[[5, 3], [5, 3], [5, 3], [5, 3]]])

        fit = fit_beta_binomial_moments(attempts, sog)

        np.testing.assert_array_equal(fit["rho"], [[0.0, 0.0]])
        self.assertEqual(fit["fallback_count"], 2)


class BetaBinomialDrawTests(unittest.TestCase):
    def test_vectorized_beta_binomial_quantiles_match_scipy(self):
        rng = np.random.default_rng(883)
        attempts = rng.integers(0, 31, size=200)
        alpha = np.exp(rng.uniform(-3.0, 2.0, size=200))
        beta = np.exp(rng.uniform(-3.0, 2.0, size=200))
        uniforms = rng.random(200)
        uniforms[:4] = [0.0, 0.01, 0.5, np.nextafter(1.0, 0.0)]

        actual = _betabinomial_ppf_recurrence(uniforms, attempts, alpha, beta)
        expected = betabinom.ppf(uniforms, attempts, alpha, beta).astype(np.int64)
        # scipy's generic ppf returns -1 for q=0 at n=0; the support contains 0.
        expected[uniforms == 0.0] = 0

        np.testing.assert_array_equal(actual, expected)

    def test_vectorized_crps_matches_reference_helper(self):
        rng = np.random.default_rng(144)
        samples = rng.integers(0, 40, size=(37, 16, 2))
        observed = rng.integers(0, 40, size=(37, 2))

        actual = crps_by_game_vectorized(samples, observed)
        expected = crps_by_game(samples, observed)

        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-14)

    def test_fixed_seed_draws_are_reproducible_and_bounded(self):
        attempts = np.array(
            [[[7, 6], [8, 5], [4, 9]], [[3, 9], [8, 4], [5, 7]]],
            dtype=np.int64,
        )
        means = np.array([[0.42, 0.57], [0.61, 0.31]])
        concentrations = np.array([[12.0, np.inf], [4.0, 18.0]])
        rng = np.random.default_rng(551)
        shared_u = rng.standard_normal((2, 3))
        uniforms = rng.random(attempts.shape)

        first = beta_binomial_sog_draws(
            attempts, means, concentrations, 0.24, shared_u, uniforms
        )
        second = beta_binomial_sog_draws(
            attempts, means, concentrations, 0.24, shared_u, uniforms
        )

        np.testing.assert_array_equal(first, second)
        self.assertTrue(np.issubdtype(first.dtype, np.integer))
        self.assertTrue(np.all(first >= 0))
        self.assertTrue(np.all(first <= attempts))

    def test_sigma_zero_uses_fitted_mean_and_respects_endpoints(self):
        attempts = np.array([[[9, 8], [9, 8]]], dtype=np.int64)
        means = np.array([[0.0, 1.0]])
        concentrations = np.array([[np.inf, np.inf]])
        uniforms = np.array([[[0.1, 0.2], [0.8, 0.9]]])

        output = beta_binomial_sog_draws(
            attempts,
            means,
            concentrations,
            0.0,
            np.zeros((1, 2)),
            uniforms,
        )

        np.testing.assert_array_equal(output[:, :, 0], 0)
        np.testing.assert_array_equal(output[:, :, 1], attempts[:, :, 1])

    def test_mean_preserving_offsets_hold_the_pregame_rate(self):
        rates = np.array([0.03, 0.2, 0.5, 0.83, 0.97])
        sigma = 0.324
        offsets = mean_preserving_offset(rates, sigma)
        logits = np.log(rates) - np.log1p(-rates)
        shifted = 1.0 / (1.0 + np.exp(-(logits[:, None] + offsets[:, None] + sigma * GH_U)))
        expectation = shifted @ GH_WEIGHTS

        np.testing.assert_allclose(expectation, rates, rtol=0.0, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
