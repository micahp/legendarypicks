"""Held-out validation of per-game opportunity shares: the metrics, written before share_validation.py.

The fixed-share adapter predicts each team-game's counts multinomially with the season shares. The Dirichlet-multinomial predicts them
with per-game shares drawn around those shares. On games withheld from fitting, the comparison is the held-out log-likelihood per
team-game (a proper score), the zero-opportunity rate, the count mean and variance per player, and the count quantiles.
"""
import math
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import share_validation as sv  # noqa: E402


class Scores(unittest.TestCase):
    def test_the_fixed_share_log_likelihood_is_the_multinomial(self):
        ll = sv.multinomial_loglik({'A': 3, 'B': 1}, 4, {'A': 0.6, 'B': 0.4})
        self.assertAlmostEqual(ll, math.log(math.comb(4, 1) * 0.6 ** 3 * 0.4), places=9)

    def test_the_dirichlet_log_likelihood_is_larger_when_the_truth_is_overdispersed(self):
        rng = random.Random(3)
        counts = [{'A': 0, 'B': 12} if rng.random() < 0.5 else {'A': 12, 'B': 0} for _ in range(200)]
        totals = [12] * 200
        fixed = sum(sv.multinomial_loglik(c, t, {'A': 0.5, 'B': 0.5}) for c, t in zip(counts, totals))
        overdispersed = sum(sv.dirichlet_loglik(c, t, {'A': 0.5, 'B': 0.5}, phi=2.0) for c, t in zip(counts, totals))
        self.assertGreater(overdispersed, fixed)


class Summaries(unittest.TestCase):
    def test_zero_rate_mean_variance_and_quantiles_come_from_the_counts(self):
        counts = [{'A': 0}, {'A': 2}, {'A': 4}, {'A': 6}]
        out = sv.summarise(counts, 'A')
        self.assertAlmostEqual(out['mean'], 3.0)
        self.assertAlmostEqual(out['zero_rate'], 0.25)
        self.assertAlmostEqual(out['variance'], 20.0 / 3.0)
        self.assertEqual(out['quantiles']['50'], 3.0)

    def test_fixed_share_prediction_quantiles_mix_the_games_opportunity_totals(self):
        self.assertEqual(sv.predictive_quantiles([2, 2], 0.5), {'10': 0, '50': 1, '90': 2})

    def test_dirichlet_marginal_prediction_quantiles_use_the_beta_binomial(self):
        self.assertEqual(sv.predictive_quantiles([4], 0.5, phi=2.0), {'10': 0, '50': 2, '90': 4})

    def test_empirical_count_quantiles_use_the_same_discrete_inverse_cdf_convention(self):
        self.assertEqual(sv.empirical_count_quantiles([0, 2, 4, 6]), {'10': 0, '50': 2, '90': 6})

    def test_predicted_variance_includes_between_game_opportunity_volume(self):
        self.assertAlmostEqual(sv.predictive_sample_variance([(0.5, 0.25), (1.5, 0.75)]), 1.0)


class Uncertainty(unittest.TestCase):
    def test_the_bootstrap_interval_over_games_brackets_a_known_difference(self):
        rng = random.Random(7)
        diffs = [1.0 + rng.gauss(0, 0.5) for _ in range(400)]
        low, high = sv.bootstrap_mean_interval(diffs, reps=500, seed=1)
        self.assertLess(low, 1.0)
        self.assertGreater(high, 1.0)

    def test_the_cluster_bootstrap_keeps_both_team_rows_from_each_game_together(self):
        low, high = sv.bootstrap_cluster_mean_interval({'G1': [0.0, 0.0], 'G2': [10.0, 10.0]}, reps=1000, seed=1)
        self.assertEqual(low, 0.0)
        self.assertEqual(high, 10.0)


if __name__ == '__main__':
    unittest.main()


class DirichletMultinomialPmf(unittest.TestCase):
    """The Dirichlet-multinomial log-likelihood must be a proper pmf: over every count vector of a small game it sums to one."""

    def test_the_dirichlet_multinomial_pmf_sums_to_one_over_all_count_vectors(self):
        total = 4
        base = {'A': 0.5, 'B': 0.3, 'C': 0.2}
        phi = 3.0
        mass = 0.0
        for a in range(total + 1):
            for b in range(total + 1 - a):
                c = total - a - b
                mass += math.exp(sv.dirichlet_loglik({'A': a, 'B': b, 'C': c}, total, base, phi))
        self.assertAlmostEqual(mass, 1.0, places=9)

    def test_with_huge_concentration_the_dirichlet_multinomial_matches_the_multinomial(self):
        counts = {'A': 3, 'B': 1}
        base = {'A': 0.6, 'B': 0.4}
        self.assertAlmostEqual(sv.dirichlet_loglik(counts, 4, base, phi=1e7), sv.multinomial_loglik(counts, 4, base), places=3)
