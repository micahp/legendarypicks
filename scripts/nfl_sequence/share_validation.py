"""Held-out validation metrics for per-game opportunity shares (research). See test_share_validation.py for what each one is."""
import math
import random
import statistics

import share_distributions as sdm


def multinomial_loglik(counts, total, shares):
    """Log-likelihood of one team-game's counts under the fixed season shares (the adapter's implied model)."""
    value = math.lgamma(total + 1)
    for player, p in shares.items():
        n = counts.get(player, 0)
        value -= math.lgamma(n + 1)
        if n:
            value += n * math.log(p)
    return value


def dirichlet_loglik(counts, total, base_shares, phi):
    """Log-likelihood of one team-game's counts under the Dirichlet-multinomial with concentration phi around the base shares."""
    return sdm._dm_loglik(counts, total, {player: phi * b for player, b in base_shares.items()})


def _quantile(sorted_values, q):
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def summarise(count_dicts, player):
    """Mean, sample variance, zero-opportunity rate and quantiles of one player's counts over games (zeros included)."""
    values = sorted(c.get(player, 0) for c in count_dicts)
    return {'games': len(values), 'mean': statistics.fmean(values),
            'variance': statistics.variance(values) if len(values) > 1 else 0.0,
            'zero_rate': sum(1 for v in values if v == 0) / len(values),
            'quantiles': {str(int(q * 100)): _quantile(values, q) for q in (0.1, 0.5, 0.9)}}


def bootstrap_mean_interval(values, reps=2000, seed=0, level=0.95):
    """A percentile interval for the mean of per-game differences, resampling games."""
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choice(values) for _ in range(n)) for _ in range(reps))
    tail = (1.0 - level) / 2.0
    return means[int(tail * (reps - 1))], means[int((1.0 - tail) * (reps - 1))]
