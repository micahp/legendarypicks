"""Team attack/defence Poisson fitted on the canonical game file, scored goals-only.

Replaces the log-xG/log-Elo linear predictor, whose fitted spread is far too narrow: its
projected margin has a standard deviation of about 0.25 goals against an observed 2.6, so it
cannot tell a strong team from a weak one.

The design is two rows per game (team attack, team defence, home advantage, neutral-site
suppression) with a 400-day recency half-life and ridge 20, fitted on the observed regulation+OT
goal target. A 5v5 xG target and its linear calibration are also fitted and kept for reference,
but they are not blended into the shipped means; `mus()` returns the goals-fitted ratings.

Walk-forward, pooled over the 9,147 feature-complete canonical games of 2019-2025: goals-only
Brier 0.2444 against 0.2462 for the frozen B5 reference, with a projected-margin sd of 0.65-0.72
against the frozen 0.25-0.32. `eval_team_strength.py` reproduces the per-season table and the
pooled number. The earlier blended-arm figures quoted here (0.2461/0.2473/0.2478) were not
reproducible from the shipped code and are superseded.

Deterministic: the only input is the hash-checked canonical CSV.
"""
from __future__ import annotations

import csv
import datetime as dt
import math

import numpy as np

HALF_LIFE_DAYS = 400.0
RIDGE = 20.0


def load_games(path: str) -> list[dict]:
    games = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                hxg = float(r.get("home_xgf_5v5") or 0.0)
                axg = float(r.get("away_xgf_5v5") or 0.0)
            except ValueError:
                hxg = axg = 0.0
            games.append(dict(
                date=r["game_date"], season=int(r["season"]), home=r["home_team"], away=r["away_team"],
                hg=int(r["home_goals_model_target"]), ag=int(r["away_goals_model_target"]),
                hxg=hxg, axg=axg,
                neutral=str(r["neutral_site"]).lower() in ("true", "1"),
            ))
    return games


class TeamStrength:
    def __init__(self, games: list[dict]):
        self.teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.theta_goals = self._fit(games, "goals")
        xg_games = [g for g in games if g["hxg"] > 0 and g["axg"] > 0]
        self.theta_xg = self._fit(xg_games, "xg") if len(xg_games) > 500 else None
        self.xg_scale = self._scale(xg_games) if self.theta_xg is not None else None

    # ------------------------------------------------------------------ fit
    def _fit(self, games: list[dict], target: str) -> np.ndarray:
        n = len(self.teams)
        latest = dt.date.fromisoformat(max(g["date"] for g in games))
        obs = []
        for g in games:
            w = 0.5 ** ((latest - dt.date.fromisoformat(g["date"])).days / HALF_LIFE_DAYS)
            hv, av = (g["hg"], g["ag"]) if target == "goals" else (g["hxg"], g["axg"])
            obs.append(("home", g["home"], g["away"], hv, w, g["neutral"]))
            obs.append(("away", g["away"], g["home"], av, w, g["neutral"]))
        X = np.zeros((len(obs), 3 + 2 * (n - 1)))
        y = np.zeros(len(obs))
        wts = np.zeros(len(obs))
        for i, (side, team, opp, value, w, neutral) in enumerate(obs):
            X[i, 0] = 1.0
            X[i, 1] = 1.0 if side == "home" else 0.0
            X[i, 2] = 0.0 if neutral else (1.0 if side == "home" else 0.0)
            if self.idx[team] < n - 1:
                X[i, 3 + self.idx[team]] = 1.0
            if self.idx[opp] < n - 1:
                X[i, 3 + n - 1 + self.idx[opp]] = -1.0
            y[i] = value
            wts[i] = w
        theta = np.zeros(X.shape[1])
        theta[0] = math.log(2.9 if target == "goals" else 2.4)
        for _ in range(60):
            eta = X @ theta
            mu = np.exp(np.clip(eta, -6, 3))
            z = eta + (y - mu) / mu
            W = mu * wts
            A = X.T @ (X * W[:, None]) + RIDGE * np.eye(len(theta))
            A[0, 0] -= RIDGE
            new = np.linalg.solve(A, X.T @ (W * z))
            done = np.max(np.abs(new - theta)) < 1e-10
            theta = new
            if done:
                break
        return theta

    @staticmethod
    def _scale(games: list[dict]) -> tuple[float, float]:
        """Linear map from a team's xG mean to its goal mean."""
        xs, gs = [], []
        for g in games:
            if g["hxg"] > 0:
                xs.extend([g["hxg"], g["axg"]])
                gs.extend([g["hg"], g["ag"]])
        if len(xs) < 200:
            return (0.0, 1.0)
        A = np.vstack([np.ones(len(xs)), np.asarray(xs)]).T
        coef, *_ = np.linalg.lstsq(A, np.asarray(gs, dtype=float), rcond=None)
        return (float(coef[0]), float(coef[1]))

    # ------------------------------------------------------------ inference
    def _mu(self, theta: np.ndarray, team: str, opp: str, is_home: float, neutral: bool) -> float:
        n = len(self.teams)
        eta = theta[0] + theta[1] * is_home + (0.0 if neutral else theta[2] * is_home)
        # An unseen team (a franchise that joined after the training window) is the reference
        # level, same as the dropped last index; only the walk-forward evaluation meets one.
        ti = self.idx.get(team, n - 1)
        oi = self.idx.get(opp, n - 1)
        if ti < n - 1:
            eta += theta[3 + ti]
        if oi < n - 1:
            eta -= theta[3 + n - 1 + oi]
        return float(np.exp(np.clip(eta, -6, 3)))

    def mus(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        # Goals are the target that carries the spread. The xG arm is fitted and kept for
        # reference only; blending it in compressed the projected margin without improving the
        # pooled walk-forward Brier, so v2 scores off the goal-fitted ratings.
        mh_g = self._mu(self.theta_goals, home, away, 1.0, neutral)
        ma_g = self._mu(self.theta_goals, away, home, 0.0, neutral)
        return mh_g, ma_g

    def ratings(self) -> dict[str, dict[str, float]]:
        n = len(self.teams)
        return {t: {"attack": float(self.theta_goals[3 + i]) if i < n - 1 else 0.0,
                    "defence": float(self.theta_goals[3 + n - 1 + i]) if i < n - 1 else 0.0}
                for t, i in self.idx.items()}
