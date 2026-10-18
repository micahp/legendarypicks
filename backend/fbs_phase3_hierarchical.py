#!/usr/bin/env python3
"""fbs_phase3_hierarchical.py -- two-level random-intercept logistic, fitted by penalised MLE.

The estimator behind increment (g), pre-registered in RESULT-FBS-PHASE3-B-20261018.md §19:

    eta_i = offset_i + b0 + x_i'b + (a_home(i) - a_away(i))
    a_t   = m_conf(t) + u_t,   u_t ~ N(0, 1/lambda_team),  m_c ~ N(0, 1/lambda_conf)

Gaussian priors are exactly ridge penalties, so the objective is strictly convex and the optimum is unique.
Fitting is L-BFGS-B with the analytic gradient; every fit is checked for convergence and the caller is
expected to assert on it. No sampler, no seed.

A team-season never seen in training predicts u = 0 and keeps its conference mean.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

GTOL = 1e-6
MAXITER = 500
CONVERGENCE_GRAD = 1e-5


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class HierarchicalLogistic:
    """Random intercepts for team-season, nested in conference means, on top of a fixed offset."""

    def __init__(self, lam_team=9.0, lam_conf=156.0, ridge=1.0):
        self.lam_team = float(lam_team)
        self.lam_conf = float(lam_conf)
        self.ridge = float(ridge)

    # -- design ---------------------------------------------------------------
    @staticmethod
    def _keys(df):
        home = list(zip(df["season"].to_numpy(), df["home_team_id"].astype(str).to_numpy()))
        away = list(zip(df["season"].to_numpy(), df["away_team_id"].astype(str).to_numpy()))
        return home, away

    def _design(self, df, fit=False):
        home_ts, away_ts = self._keys(df)
        home_cf = df["home_conference"].fillna("").astype(str).to_numpy()
        away_cf = df["away_conference"].fillna("").astype(str).to_numpy()
        if fit:
            self.ts_index = {k: i for i, k in enumerate(sorted(set(home_ts) | set(away_ts)))}
            self.conf_index = {c: i for i, c in enumerate(sorted(set(home_cf) | set(away_cf)))}
        n = len(df)
        p = 1 + len(self.feature_cols)
        k_ts, k_cf = len(self.ts_index), len(self.conf_index)
        X = np.zeros((n, p + k_cf + k_ts))
        X[:, 0] = 1.0
        for j, col in enumerate(self.feature_cols, start=1):
            X[:, j] = (df[col].to_numpy(dtype=float) - self.mu[col]) / self.sd[col]
        for i, (h, a) in enumerate(zip(home_ts, away_ts)):
            j = self.ts_index.get(h)
            if j is not None:
                X[i, p + k_cf + j] += 1.0
            j = self.ts_index.get(a)
            if j is not None:
                X[i, p + k_cf + j] -= 1.0
        for i, (h, a) in enumerate(zip(home_cf, away_cf)):
            j = self.conf_index.get(h)
            if j is not None:
                X[i, p + j] += 1.0
            j = self.conf_index.get(a)
            if j is not None:
                X[i, p + j] -= 1.0
        return X

    def _penalty_vector(self, n_params):
        p = 1 + len(self.feature_cols)
        k_cf = len(self.conf_index)
        pen = np.zeros(n_params)
        pen[1:p] = 2.0 * self.ridge
        pen[p:p + k_cf] = 2.0 * self.lam_conf
        pen[p + k_cf:] = 2.0 * self.lam_team
        return pen

    # -- fit / predict --------------------------------------------------------
    def fit(self, df, feature_cols):
        self.feature_cols = list(feature_cols)
        self.mu = {c: float(df[c].mean()) for c in self.feature_cols}
        self.sd = {}
        for c in self.feature_cols:
            s = float(df[c].std())
            self.sd[c] = s if s > 0 else 1.0
        X = self._design(df, fit=True)
        y = df["y"].to_numpy(dtype=float)
        offset = _logit(df["p_g2"].to_numpy())
        pen = self._penalty_vector(X.shape[1])

        def objective(theta):
            eta = offset + X @ theta
            # stable log-likelihood
            loss = np.sum(np.logaddexp(0.0, eta) - y * eta) + 0.5 * np.sum(pen * theta ** 2)
            grad = X.T @ (_sigmoid(eta) - y) + pen * theta
            return loss, grad

        theta = np.zeros(X.shape[1])
        grad_norm = np.inf
        restarts = 0
        for _ in range(3):
            res = minimize(objective, theta, jac=True, method="L-BFGS-B",
                           options={"maxiter": 4000, "gtol": 1e-10, "ftol": 1e-16, "maxls": 80})
            theta = res.x
            grad_norm = float(np.max(np.abs(res.jac)))
            if grad_norm < CONVERGENCE_GRAD:
                break
            # L-BFGS-B can stop on line-search precision rather than the gradient; restarting from
            # the stopped point with the identical objective and settings resumes the descent.
            restarts += 1
        self.theta = theta
        self.grad_norm = grad_norm
        self.restarts = restarts
        self.converged = grad_norm < CONVERGENCE_GRAD
        self.n_iter = int(res.nit)
        p = 1 + len(self.feature_cols)
        k_cf = len(self.conf_index)
        self.b0 = float(self.theta[0])
        self.b = self.theta[1:p].copy()
        self.m = self.theta[p:p + k_cf].copy()
        self.u = self.theta[p + k_cf:].copy()
        return self

    def hessian_condition(self, df):
        """Condition number of the penalised Hessian at the fitted solution (identification check)."""
        X = self._design(df, fit=False)
        eta = _logit(df["p_g2"].to_numpy()) + X @ self.theta
        w = _sigmoid(eta) * (1 - _sigmoid(eta))
        pen = self._penalty_vector(X.shape[1])
        hess = (X.T * w) @ X + np.diag(pen)
        return float(np.linalg.cond(hess))

    def predict(self, df):
        X = self._design(df, fit=False)
        eta = _logit(df["p_g2"].to_numpy()) + X @ self.theta
        return _sigmoid(eta)

    def diagnostics(self, feature_cols=None):
        return {
            "converged": self.converged,
            "grad_norm": self.grad_norm,
            "n_iter": self.n_iter,
            "n_team_seasons": int(len(self.ts_index)),
            "sd_u": float(np.std(self.u)) if len(self.u) else 0.0,
            "sd_m": float(np.std(self.m)) if len(self.m) else 0.0,
            "b": self.b.tolist(),
            "b0": self.b0,
        }
