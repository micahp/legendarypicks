"""PBV1 package-level sampler (spec: docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md).

A play is a dict with season, game_id, team, family (run or pass), down, distance (HPV1 bucket), red_zone (0 or 1), and
package (the target code, RB+FB for cross-season comparison). A cell is (family, down, distance, red_zone). Its parent is
(family, down). The sampler shrinks the cell's observed package counts toward the parent distribution with K pseudo-counts.
Packages never observed in the parent get no mass.
"""
import collections

import numpy as np

BOOTSTRAP_DRAWS = 10000
BOOTSTRAP_SEED = 20261102


def cell_key(play):
    return (play['family'], play['down'], play['distance'], play['red_zone'])


def parent_key(play):
    return (play['family'], play['down'])


def fit(plays, train_seasons=None):
    model = {'cell': collections.defaultdict(collections.Counter),
             'parent': collections.defaultdict(collections.Counter),
             'marginal': collections.Counter()}
    for play in plays:
        if train_seasons is not None and play['season'] not in train_seasons:
            continue
        model['cell'][cell_key(play)][play['package']] += 1
        model['parent'][parent_key(play)][play['package']] += 1
        model['marginal'][play['package']] += 1
    return model


def sampler_dist(model, cell, K):
    parent = cell[:2]
    parent_counts = model['parent'].get(parent)
    if not parent_counts:
        return {}
    parent_total = sum(parent_counts.values())
    cell_counts = model['cell'].get(cell, collections.Counter())
    cell_total = sum(cell_counts.values())
    return {package: (cell_counts.get(package, 0) + K * count / parent_total) / (cell_total + K)
            for package, count in parent_counts.items()}


def cell_dist(model, cell):
    counts = model['cell'].get(cell)
    if not counts:
        return None
    total = sum(counts.values())
    return {package: count / total for package, count in counts.items()}


def marginal_dist(model):
    total = sum(model['marginal'].values())
    return {package: count / total for package, count in model['marginal'].items()}


def score_play(model, play, K):
    cell = cell_key(play)
    package = play['package']
    sampler = sampler_dist(model, cell, K).get(package)
    b1 = (cell_dist(model, cell) or {}).get(package)
    b0 = marginal_dist(model).get(package)
    return {'sampler': sampler, 'b0': b0, 'b1': b1}


def game_bootstrap_ci(per_game, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    """Paired game-clustered 95% interval for a per-play mean difference.

    per_game holds (sum of per-play differences, number of plays) for each game. Whole games are resampled with
    replacement, so a game with many plays counts as one cluster.
    """
    sums = np.array([s for s, _ in per_game], dtype=float)
    counts = np.array([n for _, n in per_game], dtype=float)
    rng = np.random.RandomState(seed)
    draw = rng.randint(0, len(per_game), size=(draws, len(per_game)))
    stats = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)
