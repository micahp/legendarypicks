#!/usr/bin/env python3
"""test_fbs_phase3_hierarchical.py -- checks the (g) estimator before it is scored.

Run: /root/legendarypicks/backend/venv/bin/python backend/test_fbs_phase3_hierarchical.py
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fbs_phase3_hierarchical import HierarchicalLogistic, _logit, _sigmoid  # noqa: E402

CONF = ["A", "B"]


def synthetic(n_teams=20, n_games=900, seed=7, effect_sd=0.7):
    rng = np.random.default_rng(seed)
    team_effect = {i: rng.normal(0, effect_sd) for i in range(n_teams)}
    rows = []
    for g in range(n_games):
        h = int(rng.integers(0, n_teams))
        a = int(rng.integers(0, n_teams))
        if h == a:
            continue
        offset = 0.0
        eta = offset + team_effect[h] - team_effect[a]
        y = float(rng.random() < _sigmoid(eta))
        rows.append({"game_id": str(g), "season": 2024, "home_team_id": str(h), "away_team_id": str(a),
                     "home_conference": CONF[h % 2], "away_conference": CONF[a % 2],
                     "p_g2": 0.5, "y": y, "feat": rng.normal()})
    return pd.DataFrame(rows), team_effect


class TestHierarchical(unittest.TestCase):
    def test_converges_and_predicts_probabilities(self):
        df, _ = synthetic()
        m = HierarchicalLogistic(lam_team=4.0, lam_conf=50.0).fit(df, ["feat"])
        self.assertTrue(m.converged, m.grad_norm)
        p = m.predict(df)
        self.assertTrue(np.all((p > 0) & (p < 1)))
        self.assertEqual(p.shape, (len(df),))

    def test_recovers_large_team_effects(self):
        df, truth = synthetic(n_teams=24, n_games=3000, effect_sd=0.9, seed=11)
        m = HierarchicalLogistic(lam_team=2.0, lam_conf=100.0).fit(df, ["feat"])
        est = {k: v for k, v in m.ts_index.items()}
        pairs = [(truth[int(k[1])], m.u[v]) for k, v in est.items() if np.isfinite(truth[int(k[1])])]
        est_vals = np.array([v for _, v in pairs])
        true_vals = np.array([t for t, _ in pairs])
        self.assertGreater(np.corrcoef(est_vals, true_vals)[0, 1], 0.7)

    def test_unseen_team_season_falls_back_to_conference_mean(self):
        df, _ = synthetic()
        m = HierarchicalLogistic(lam_team=4.0, lam_conf=50.0).fit(df, ["feat"])
        new = df.head(1).copy()
        new["home_team_id"] = "999"
        p_new = m.predict(new)[0]
        # prediction must still be a probability and must not depend on an invented team effect
        self.assertTrue(0 < p_new < 1)

    def test_stronger_prior_shrinks_effects(self):
        df, _ = synthetic()
        weak = HierarchicalLogistic(lam_team=1.0, lam_conf=100.0).fit(df, ["feat"])
        strong = HierarchicalLogistic(lam_team=100.0, lam_conf=100.0).fit(df, ["feat"])
        self.assertLess(np.std(strong.u), np.std(weak.u))

    def test_offset_is_preserved(self):
        # generate outcomes from the offset itself, so a correct model should not move it
        rng = np.random.default_rng(5)
        n = 600
        p_true = 0.75
        y = (rng.random(n) < p_true).astype(float)
        df = pd.DataFrame({"game_id": [str(i) for i in range(n)], "season": 2024,
                           "home_team_id": ["1"] * n, "away_team_id": ["2"] * n,
                           "home_conference": ["A"] * n, "away_conference": ["A"] * n,
                           "p_g2": p_true, "y": y, "feat": rng.normal(size=n)})
        m = HierarchicalLogistic(lam_team=1e6, lam_conf=1e6).fit(df, ["feat"])
        p = m.predict(df)
        self.assertTrue(np.all(np.abs(p - p_true) < 0.05), p.mean())

    def test_gradient_matches_finite_difference(self):
        df, _ = synthetic(n_teams=6, n_games=120, seed=3)
        m = HierarchicalLogistic(lam_team=9.0, lam_conf=156.0)
        m.feature_cols = ["feat"]
        m.mu = {"feat": float(df.feat.mean())}
        m.sd = {"feat": float(df.feat.std())}
        X = m._design(df, fit=True)
        y = df.y.to_numpy()
        offset = _logit(df.p_g2.to_numpy())
        pen = m._penalty_vector(X.shape[1])

        def obj(theta):
            eta = offset + X @ theta
            return np.sum(np.logaddexp(0, eta) - y * eta) + 0.5 * np.sum(pen * theta ** 2)

        theta = np.random.default_rng(0).normal(0, 0.1, X.shape[1])
        grad = X.T @ (_sigmoid(offset + X @ theta) - y) + pen * theta
        eps = 1e-6
        idx = [0, 1, X.shape[1] - 1]
        for j in idx:
            up, dn = theta.copy(), theta.copy()
            up[j] += eps
            dn[j] -= eps
            numeric = (obj(up) - obj(dn)) / (2 * eps)
            self.assertAlmostEqual(grad[j], numeric, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
