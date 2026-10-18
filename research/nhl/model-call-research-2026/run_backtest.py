#!/usr/bin/env python3
"""Chronological walk-forward evaluation of NHL score distributions and the
tiered model-call policy. Prototype research only: reads the canonical audit
CSVs, writes JSON artifacts under results/, and touches nothing else.

Stages (all graded on every feature-complete evaluation game, matched across
variants):
  load      join canonical games with pregame rolling features
  elo       chronological pregame Elo replay (k=10, home ice 35)
  fit       per-season Poisson refits (B3 elo, B5 xG, B7 elo+xG) on prior
            seasons only; mus cached to results/fit_cache.json
  score     analytical joint distributions plus candidates: NB marginals,
            Dixon-Coles low-score adjustment, empirical tie-mass calibration,
            common-shock bivariate Poisson (when covariance is positive), and
            a period-level simulator with score-state effects and explicit
            OT/SO stages
  mc        Monte Carlo control drawn from the identical Poisson model
  policy    tiered model-call cascade with thresholds tuned on prior seasons
            only; baselines: always-ML and cross-market argmax

Settlement mapping used throughout (documented in the report):
  official total = statistical total + 1{statistical tie} in the regular
  season; identical in playoffs. Puck line +/-1.5 is invariant under both
  targets because a statistical tie always resolves to a 1-goal OT/SO margin,
  which covers both +1.5 sides and neither -1.5 side.
"""
from __future__ import annotations

import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.special import gammaln
from sklearn.linear_model import PoissonRegressor

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent / "kalshi-playoff-audit-2025-26"
CANONICAL = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
RESULTS = HERE / "results"

EVAL_SEASONS = list(range(2019, 2026))
TRAIN_FROM = 2008
ALPHA = 0.01
CAP = 21            # joint matrix goals 0..20
MAX_GOALS = 20
MC_SAMPLE_SEASONS = (2021, 2024)
MC_TRIALS = 200_000
SIM_GAMES = 400     # period-simulator matched subset
SIM_TRIALS = 100_000

MODELS = ("b3_elo", "b5_xg", "b7_elo_xg")
TEAM_ID = {"PHX": "ARI", "T.B": "TBL", "TB": "TBL", "N.J": "NJD", "L.A": "LAK",
           "LA": "LAK", "S.J": "SJS", "ATL": "WPG"}


def team_key(code: str) -> str:
    return TEAM_ID.get(code, code)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def lograte(v) -> float:
    return math.log(max(float(v), 0.05))


# ---------------------------------------------------------------------------
# pmf helpers
# ---------------------------------------------------------------------------

def pmf_rows(mu: np.ndarray, cap: int = CAP) -> np.ndarray:
    mu = np.maximum(np.asarray(mu, float), 1e-9)
    k = np.arange(cap)
    logp = k[None] * np.log(mu[:, None]) - mu[:, None] - gammaln(k + 1)[None]
    out = np.exp(logp)
    out[:, -1] = 1.0 - out[:, :-1].sum(axis=1)
    return np.maximum(out, 0.0)


def nb_rows(mu: np.ndarray, r: float, cap: int = CAP) -> np.ndarray:
    mu = np.maximum(np.asarray(mu, float), 1e-9)
    k = np.arange(cap)
    p = r / (r + mu[:, None])
    logp = gammaln(k + r)[None] - gammaln(r) - gammaln(k + 1)[None] \
        + r * np.log(p) + k[None] * np.log1p(-p)
    out = np.exp(logp)
    out[:, -1] = 1.0 - out[:, :-1].sum(axis=1)
    return np.maximum(out, 0.0)


def fit_nb_dispersion(y: np.ndarray, mu: np.ndarray) -> float:
    """Method-of-moments size r from Pearson dispersion; large r = Poisson."""
    d = np.mean((y - mu) ** 2 / mu)
    if d <= 1.0:
        return 1e6
    return float(mu.mean() / (d - 1.0))


def joint(p_h: np.ndarray, p_a: np.ndarray, adjust: np.ndarray | None = None) -> np.ndarray:
    m = np.outer(p_h, p_a)[:CAP, :CAP]
    if adjust is not None:
        m = m * adjust
        m = m / m.sum()
    return m


def dc_adjust(rho: float, cap: int = CAP) -> np.ndarray:
    a = np.ones((cap, cap))
    a[0, 0] = 1.0 - rho
    a[0, 1] = 1.0 + rho
    a[1, 0] = 1.0 + rho
    a[1, 1] = 1.0 - rho
    return a


def fit_dc_rho(train_h: np.ndarray, train_a: np.ndarray, mu_h: np.ndarray,
               mu_a: np.ndarray) -> float:
    """Grid-search rho maximizing training likelihood of the observed scores."""
    best, best_ll = None, -np.inf
    i_idx = np.minimum(train_h, MAX_GOALS)
    j_idx = np.minimum(train_a, MAX_GOALS)
    for rho in np.arange(-0.20, 0.21, 0.02):
        adj = dc_adjust(float(rho))
        ll = 0.0
        for i, j, mh, ma in zip(i_idx, j_idx, mu_h, mu_a):
            ph = pmf_rows(np.array([mh]))[0]
            pa = pmf_rows(np.array([ma]))[0]
            m = np.outer(ph, pa) * adj
            m = m / m.sum()
            ll += math.log(max(m[i, j], 1e-15))
        if ll > best_ll:
            best, best_ll = float(rho), ll
    return best


def bivariate_mats(mu_h: np.ndarray, mu_a: np.ndarray, lam12: float) -> np.ndarray:
    """Stack of (n, CAP, CAP) common-shock joint matrices (truncated)."""
    mu_h = np.maximum(np.asarray(mu_h, float), 1e-9)
    mu_a = np.maximum(np.asarray(mu_a, float), 1e-9)
    l1 = np.maximum(mu_h - lam12, 1e-9)
    l2 = np.maximum(mu_a - lam12, 1e-9)
    p1, p2 = pmf_rows(l1), pmf_rows(l2)
    p12 = pmf_rows(np.full(len(mu_h), lam12))[:, :CAP]
    n = len(mu_h)
    out = np.zeros((n, CAP, CAP))
    for kk in range(p12.shape[1]):
        w = p12[:, kk]
        live = w > 1e-12
        if not live.any():
            continue
        # X = X1 + kk, Y = X2 + kk -> cells (i+kk, j+kk)
        block = p1[live, :CAP - kk, None] * p2[live, None, :CAP - kk]
        out[np.flatnonzero(live)[:, None, None],
            np.arange(CAP - kk)[None, :, None] + kk,
            np.arange(CAP - kk)[None, None, :] + kk] += block * w[live][:, None, None]
    s = out.sum(axis=(1, 2), keepdims=True)
    return out / np.maximum(s, 1e-15)


# ---------------------------------------------------------------------------
# Derived probabilities from a joint matrix
# ---------------------------------------------------------------------------

def derive(m: np.ndarray, so_home: float) -> dict:
    i, j = np.indices(m.shape)
    home = float((m * (i > j)).sum())
    away = float((m * (i < j)).sum())
    tie = float(np.trace(m))
    total = i + j
    return {
        "p_home_win": home + tie * so_home,
        "p_away_win": away + tie * (1.0 - so_home),
        # Puck line: home -1.5 wins iff margin >= 2; away +1.5 covers iff margin <= 1
        # (identical to the frozen ledger's p_away_plus_1_5 = 1 - p_home_minus_1_5).
        "p_home_cover": float((m * (i - j >= 2)).sum()),
        "p_away_cover": float((m * (i - j <= 1)).sum()),
        "p_tie": tie,
        "mu_home": float((m * i).sum()),
        "mu_away": float((m * j).sum()),
        "p_over_55": float(m[total >= 6].sum()),
        "p_over_65_official": float(m[(total >= 7) | ((total == 6) & (i == j))].sum()),
        "p_over_65_statistical": float(m[total >= 7].sum()),
        "p_push_6_official": float(m[(total == 6) & (i != j)].sum()),
    }


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_games() -> list[dict]:
    canon = read_csv(CANONICAL)
    feats = read_csv(FEATURES)
    assert len(canon) == len(feats) == 23222
    by_id = {int(x["game_id"]): x for x in feats}
    games = []
    for c in canon:
        gid = int(c["game_id"])
        x = by_id[gid]
        if x["required_features_complete"].lower() != "true":
            continue
        g = {**c, **x}
        g["game_id"] = gid
        g["season"] = int(c["season"])
        g["hw"] = int(c["official_home_winner"])
        g["hg"] = int(c["home_goals_model_target"])
        g["ag"] = int(c["away_goals_model_target"])
        g["ohg"] = int(c["official_home_score"])
        g["oag"] = int(c["official_away_score"])
        g["period"] = c["last_period_type"]
        g["neutral"] = c["neutral_site"].lower() == "true"
        games.append(g)
    games.sort(key=lambda r: (r["game_date"], r["start_time_utc"], r["game_id"]))
    return games


def elo_replay(games: list[dict], k: float = 10.0, hfa: float = 35.0) -> dict[int, dict]:
    ratings = defaultdict(lambda: 1500.0)
    out = {}
    by_date = defaultdict(list)
    for r in games:
        by_date[r["game_date"]].append(r)
    for date in sorted(by_date):
        updates = []
        for r in by_date[date]:
            home, away = team_key(r["home_team"]), team_key(r["away_team"])
            venue = 0.0 if r["neutral"] else hfa
            rh, ra = ratings[home], ratings[away]
            d = (rh - ra) / 400.0
            out[r["game_id"]] = {"diff": d, "venue": float(venue > 0)}
            updates.append((home, away, float(r["hw"] - 1 / (1 + 10 ** (-((rh - ra + venue) / 400))))))
        for home, away, res in updates:
            ch = k * res
            ratings[home] += ch
            ratings[away] -= ch
    return out


def so_rate(games: list[dict]) -> float:
    so = [g for g in games if g["period"] == "SO"]
    return sum(g["hw"] for g in so) / len(so) if so else 0.5


# ---------------------------------------------------------------------------
# Features and refits
# ---------------------------------------------------------------------------

def side_rows(games: list[dict], model: str, elo: dict[int, dict]):
    X, y = [], []
    for r in games:
        hx, hxga = lograte(r["home_rolling10_5v5_score_venue_xgf"]), lograte(r["home_rolling10_5v5_score_venue_xga"])
        ax, axga = lograte(r["away_rolling10_5v5_score_venue_xgf"]), lograte(r["away_rolling10_5v5_score_venue_xga"])
        d = elo[r["game_id"]]["diff"]
        if model == "b3_elo":
            X.extend([[elo[r["game_id"]]["venue"], d], [0.0, -d]])
        elif model == "b5_xg":
            X.extend([[1.0, hx, axga], [0.0, ax, hxga]])
        elif model == "b7_elo_xg":
            X.extend([[1.0, hx, axga, d], [0.0, ax, hxga, -d]])
        else:
            raise ValueError(model)
        y.extend([r["hg"], r["ag"]])
    return np.asarray(X, float), np.asarray(y, float)


def predict_mus(games: list[dict], model: str, elo: dict, beta: np.ndarray) -> dict[int, tuple]:
    out = {}
    for r in games:
        hx, hxga = lograte(r["home_rolling10_5v5_score_venue_xgf"]), lograte(r["home_rolling10_5v5_score_venue_xga"])
        ax, axga = lograte(r["away_rolling10_5v5_score_venue_xgf"]), lograte(r["away_rolling10_5v5_score_venue_xga"])
        d = elo[r["game_id"]]["diff"]
        if model == "b3_elo":
            xh, xa = [elo[r["game_id"]]["venue"], d], [0.0, -d]
        elif model == "b5_xg":
            xh, xa = [1.0, hx, axga], [0.0, ax, hxga]
        else:
            xh, xa = [1.0, hx, axga, d], [0.0, ax, hxga, -d]
        out[r["game_id"]] = (math.exp(float(np.dot(xh, beta))), math.exp(float(np.dot(xa, beta))))
    return out


# ---------------------------------------------------------------------------
# Monte Carlo control and period simulator
# ---------------------------------------------------------------------------

def mc_control(games: list[dict], preds_mus: dict[int, tuple], so_home: float,
               trials: int = MC_TRIALS, seed: int = 20261017) -> dict:
    rng = np.random.default_rng(seed)
    ids = [g["game_id"] for g in games]
    mu = np.array([preds_mus[gid] for gid in ids])
    t0 = time.time()
    ph = pmf_rows(mu[:, 0]); pa = pmf_rows(mu[:, 1])
    analytic = []
    for a, b in zip(ph, pa):
        analytic.append(derive(np.outer(a, b)[:CAP, :CAP], so_home))
    sample = rng.choice(len(ids), size=min(600, len(ids)), replace=False)
    diffs = defaultdict(list)
    conv = {}
    for n in (10_000, 25_000, 50_000, 100_000, trials):
        t = time.time()
        d_cur = defaultdict(list)
        for ix in sample:
            h = rng.poisson(mu[ix, 0], n)
            a = rng.poisson(mu[ix, 1], n)
            emp = {"p_home_win": float((h > a).mean()) + float((h == a).mean()) * so_home,
                   "p_away_cover": float((h - a <= 1).mean()),
                   "p_over_55": float((h + a >= 6).mean()),
                   "p_over_65_official": float(((h + a >= 7) | ((h + a == 6) & (h == a))).mean())}
            for key, ev in emp.items():
                d_cur[key].append(abs(ev - analytic[ix][key]))
        conv[n] = {"mean_abs_diff": {k: float(np.mean(v)) for k, v in d_cur.items()},
                   "max_abs_diff": {k: float(np.max(v)) for k, v in d_cur.items()},
                   "seconds": round(time.time() - t, 2)}
        for k, v in d_cur.items():
            diffs[k].extend(v)
    return {"n_games": len(sample), "trials_max": trials,
            "convergence": conv,
            "mean_abs_diff_all": {k: float(np.mean(v)) for k, v in diffs.items()},
            "max_abs_diff_all": {k: float(np.max(v)) for k, v in diffs.items()},
            "mc_seconds_total": round(time.time() - t0, 1)}


def simulate_period_games(mu_h: float, mu_a: float, state_eff: float, ot_rate: float,
                          so_home: float, trials: int, rng) -> dict:
    """Score-state period simulator with explicit OT (3v3 pace) and SO stage.

    Trailing team attack rate x(1+state_eff), leading team x(1-state_eff);
    state_eff is calibrated on training tie rates. Statistical score = goals
    through regulation+OT (shootout decider excluded, matching the target).
    """
    base_h, base_a = mu_h / 3.0, mu_a / 3.0
    hs = np.zeros(trials, dtype=np.int8)
    as_ = np.zeros(trials, dtype=np.int8)
    for _ in range(3):
        lead = hs - as_
        rate_h = np.where(lead > 0, base_h * (1 - state_eff),
                          np.where(lead < 0, base_h * (1 + state_eff), base_h))
        rate_a = np.where(lead < 0, base_a * (1 - state_eff),
                          np.where(lead > 0, base_a * (1 + state_eff), base_a))
        hs += rng.poisson(rate_h).astype(np.int8)
        as_ += rng.poisson(rate_a).astype(np.int8)
    # OT: 5 minutes at 3v3 pace (~3x per-minute 5v5)
    ot_rate_h, ot_rate_a = mu_h / 12.0 * 3.0, mu_a / 12.0 * 3.0
    ot_h = rng.poisson(np.where(hs == as_, ot_rate_h, 0.0))
    ot_a = rng.poisson(np.where(hs == as_, ot_rate_a, 0.0))
    hs += ot_h.astype(np.int8)
    as_ += ot_a.astype(np.int8)
    went_so = (hs == as_)
    so_home_win = rng.random(trials) < so_home
    home_win = np.where(hs > as_, True, np.where(hs < as_, False, so_home_win))
    total_stat = hs + as_                     # statistical target
    total_off = total_stat + went_so          # official adds the SO decider
    return {
        "p_home_win": float(home_win.mean()),
        "p_away_cover": float((hs - as_ <= 1).mean()),
        "p_over_55": float((total_stat >= 6).mean()),
        "p_over_65_official": float((total_off >= 7).mean()),
        "p_tie": float(went_so.mean()),
    }


def calibrate_state_eff(train_games: list[dict], elo: dict, model: str, beta: np.ndarray,
                        so_home: float, rng, target_tie: float) -> float:
    """Bisect state_eff so simulated regulation-tie share matches training."""
    sample = train_games[-1500:]
    mus = np.array([predict_mus([g], model, elo, beta)[g["game_id"]] for g in sample])
    lo, hi = 0.0, 0.6
    for _ in range(7):
        mid = (lo + hi) / 2
        ties = np.mean([simulate_period_games(mh, ma, mid, 0.0, so_home, 8000, rng)["p_tie"]
                        for (mh, ma) in mus[:40]])
        if ties < target_tie:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def summarize(rows: list[dict]) -> dict:
    p_hw = np.array([r["p_home_win"] for r in rows])
    y_hw = np.array([r["y_home_win"] for r in rows])
    p_hc = np.array([r["p_home_cover"] for r in rows])
    y_hc = np.array([r["y_home_cover"] for r in rows])
    p_ac = np.array([r["p_away_cover"] for r in rows])
    y_ac = np.array([r["y_away_cover"] for r in rows])
    p_o5 = np.array([r["p_over_55"] for r in rows])
    y_o5 = np.array([r["y_over55"] for r in rows])
    p_o6 = np.array([r["p_over_65_official"] for r in rows])
    y_o6 = np.array([r["y_over65"] for r in rows])

    def br(p, y):
        return float(np.mean((p - y) ** 2))

    def ll(p, y):
        p = np.clip(p, 1e-15, 1 - 1e-15)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    # calibration: observed vs predicted in 10 bins
    def calib(p, y):
        bins = np.clip((p * 10).astype(int), 0, 9)
        obs = [float(y[bins == b].mean()) if (bins == b).any() else None for b in range(10)]
        cnt = [int((bins == b).sum()) for b in range(10)]
        slope = float(np.polyfit(p, y, 1)[0]) if len(p) > 2 else None
        return {"bins_pred": [float(p[bins == b].mean()) if (bins == b).any() else None for b in range(10)],
                "bins_obs": obs, "bins_n": cnt, "slope": slope}

    out = {"n": len(rows),
           "ml_brier": br(p_hw, y_hw), "ml_logloss": ll(p_hw, y_hw),
           "ml_calibration": calib(p_hw, y_hw),
           "home_cover_brier": br(p_hc, y_hc), "away_cover_brier": br(p_ac, y_ac),
           "over55_brier": br(p_o5, y_o5), "over65_brier": br(p_o6, y_o6),
           "over55_base": br(np.full(len(y_o5), y_o5.mean()), y_o5),
           "over65_base": br(np.full(len(y_o6), y_o6.mean()), y_o6),
           "goal_mae_home": float(np.mean([r["goal_mae_home"] for r in rows])),
           "goal_mae_away": float(np.mean([r["goal_mae_away"] for r in rows]))}
    nll = [r["score_nll"] for r in rows if r["score_nll"] is not None]
    if nll:
        out["score_nll_mean"] = float(np.mean(nll))
    return out


def bootstrap_delta(rows_a: list[dict], rows_b: list[dict], key_a: str, key_b: str,
                    iters: int = 2000, seed: int = 7) -> dict:
    """Paired bootstrap for Brier delta (a - b) with 95% CI."""
    rng = np.random.default_rng(seed)

    def sq(rows, pkey):
        ykey = {"p_home_win": "y_home_win", "p_home_cover": "y_home_cover",
                "p_away_cover": "y_away_cover", "p_over_55": "y_over55",
                "p_over_65_official": "y_over65"}[pkey]
        return np.array([(r[pkey] - r[ykey]) ** 2 for r in rows])
    ea, eb = sq(rows_a, key_a), sq(rows_b, key_b)
    n = min(len(ea), len(eb))
    idx = np.arange(n)
    deltas = []
    for _ in range(iters):
        s = rng.choice(idx, n, replace=True)
        deltas.append(float(ea[s].mean() - eb[s].mean()))
    deltas = np.array(deltas)
    point = float(ea.mean() - eb.mean())
    return {"point_delta": point, "ci95": [float(np.percentile(deltas, 2.5)),
                                           float(np.percentile(deltas, 97.5))]}


# ---------------------------------------------------------------------------
# Tiered policy
# ---------------------------------------------------------------------------

def tier_of(p: dict, tau1: float, tau2: float, tau3: float, ref_total: float) -> tuple:
    """Return (tier, side, probability). ref_total: projected total for line choice."""
    line = 5.5 if ref_total <= 6.0 else 6.5
    p_over = p["p_over_55"] if line == 5.5 else p["p_over_65_official"]
    p_ml = max(p["p_home_win"], p["p_away_win"])
    ml_side = "home" if p["p_home_win"] >= p["p_away_win"] else "away"
    p_cover = max(p["p_home_cover"], p["p_away_cover"])
    cover_side = "home" if p["p_home_cover"] >= p["p_away_cover"] else "away"
    if p_ml >= tau1:
        return ("ml", ml_side, p_ml, "home_win" if ml_side == "home" else "away_win")
    if p_cover >= tau2:
        return ("cover", cover_side, p_cover, "home_cover" if cover_side == "home" else "away_cover")
    if max(p_over, 1 - p_over) >= tau3:
        side = "over" if p_over >= 0.5 else "under"
        return ("total", side, max(p_over, 1 - p_over),
                "over55" if line == 5.5 else "over65")
    return ("fallback", None, None, None)


def outcome_of(tier, side, g: dict, ref_line: float) -> str:
    if tier == "ml":
        if side == "home":
            return "won" if g["hw"] else "lost"
        return "won" if not g["hw"] else "lost"
    if tier == "cover":
        # home -1.5 covers iff margin >= 2; away +1.5 covers iff margin <= 1
        margin = g["hg"] - g["ag"]
        return "won" if (margin >= 2 if side == "home" else margin <= 1) else "lost"
    if tier == "total":
        total = g["ohg"] + g["oag"]
        line = ref_line
        if side == "over":
            return "won" if total > line else "lost"
        return "won" if total < line else "lost"
    return "fallback"


def tune_thresholds(tuning_rows: list[dict], game_lookup: dict[int, dict]) -> dict:
    """Grid search maximizing cascade accuracy with usage constraints."""
    best = None
    ref_totals = {gid: game_lookup[gid]["_ref_total"] for gid in game_lookup}
    for tau1 in np.arange(0.55, 0.801, 0.025):
        for tau2 in np.arange(0.55, 0.701, 0.025):
            for tau3 in np.arange(0.55, 0.701, 0.025):
                res = defaultdict(int)
                for r in tuning_rows:
                    # A game without a complete model call must not be treated as having
                    # one; count it as an explicit fallback rather than manufacturing a
                    # call from partial data.
                    if not all(r.get(k) is not None for k in
                               ("p_home_win", "p_home_cover", "p_away_cover", "p_over_55", "p_over_65_official")):
                        res["fallback"] += 1
                        continue
                    p = {"p_home_win": r["p_home_win"], "p_away_win": 1 - r["p_home_win"],
                         "p_home_cover": r["p_home_cover"], "p_away_cover": r["p_away_cover"],
                         "p_over_55": r["p_over_55"], "p_over_65_official": r["p_over_65_official"]}
                    tier, side, _prob, _k = tier_of(p, float(tau1), float(tau2), float(tau3), ref_totals[r["game_id"]])
                    line = 5.5 if ref_totals[r["game_id"]] <= 6.0 else 6.5
                    res[outcome_of(tier, side, game_lookup[r["game_id"]], line)] += 1
                n = sum(res.values())
                acc = res["won"] / n
                fallback = res["fallback"] / n
                if fallback > 0.05:
                    continue
                if best is None or acc > best["acc"] or (acc == best["acc"] and (tau1, tau2, tau3) < best["taus"]):
                    best = {"acc": acc, "taus": (float(tau1), float(tau2), float(tau3)),
                            "fallback": fallback, "n": n,
                            "tier_usage": {k: v / n for k, v in res.items()}}
    return best


def main() -> None:
    t0 = time.time()
    RESULTS.mkdir(exist_ok=True)
    games = load_games()
    print(f"loaded {len(games)} games", flush=True)
    elo = elo_replay(games)
    fit_cache_path = RESULTS / "fit_cache.json"
    cache = json.loads(fit_cache_path.read_text()) if fit_cache_path.exists() else {}

    diag_train = [g for g in games if TRAIN_FROM <= g["season"] <= 2018]
    hg = np.array([g["hg"] for g in diag_train], float)
    ag = np.array([g["ag"] for g in diag_train], float)
    diag = {"train": "2008-2018", "n": len(diag_train),
            "mean_goals": [float(hg.mean()), float(ag.mean())],
            "var_goals": [float(hg.var()), float(ag.var())],
            "corr": float(np.corrcoef(hg, ag)[0, 1]),
            "tie_rate": float((hg == ag).mean()),
            "home_so_rate": so_rate(diag_train)}
    (RESULTS / "dispersion_diagnostics.json").write_text(json.dumps(diag, indent=1))
    print(f"diagnostics: tie_rate={diag['tie_rate']:.4f} corr={diag['corr']:.4f}", flush=True)

    # --- fit per season (cached) ---
    betas = {}
    for season in EVAL_SEASONS:
        train = [g for g in games if TRAIN_FROM <= g["season"] < season]
        key = str(season)
        cache.setdefault(key, {})
        for model in MODELS:
            if model in cache[key]:
                continue
            X, y = side_rows(train, model, elo)
            beta = PoissonRegressor(alpha=ALPHA, max_iter=500, tol=1e-9).fit(X, y).coef_
            cache[key][model] = [float(b) for b in beta]
            print(f"  fit {model} through {season - 1} at {time.time()-t0:.0f}s", flush=True)
    fit_cache_path.write_text(json.dumps(cache, indent=1))

    # --- score stage: analytical + candidates, all seasons ---
    all_rows = defaultdict(list)   # (model, variant) -> rows
    game_lookup = {}
    for season in EVAL_SEASONS:
        evalg = [g for g in games if g["season"] == season]
        train = [g for g in games if TRAIN_FROM <= g["season"] < season]
        so_home = so_rate(train)
        # empirical regulation-tie share for state-eff calibration
        t_tr = np.array([g["hg"] for g in train], float)
        a_tr = np.array([g["ag"] for g in train], float)
        tie_rate_train = float((t_tr == a_tr).mean())
        mu_h_tr = np.array([g["hg"] for g in train[-4000:]], float)
        for model in MODELS:
            beta = np.array(cache[str(season)][model])
            mus = predict_mus(evalg, model, elo, beta)
            mu_h = np.array([mus[g["game_id"]][0] for g in evalg])
            mu_a = np.array([mus[g["game_id"]][1] for g in evalg])
            ph = pmf_rows(mu_h); pa = pmf_rows(mu_a)
            # dispersion fit on training residuals for NB
            X_tr, y_tr = side_rows(train[-8000:], model, elo)
            mu_tr = np.exp(X_tr @ beta)
            r_nb = fit_nb_dispersion(y_tr, mu_tr)
            ph_nb = nb_rows(mu_h, r_nb); pa_nb = nb_rows(mu_a, r_nb)
            # DC rho fit on a training subsample
            sub = train[-1500:]
            mus_sub = predict_mus(sub, model, elo, beta)
            rho = fit_dc_rho(np.array([g["hg"] for g in sub]), np.array([g["ag"] for g in sub]),
                             np.array([mus_sub[g["game_id"]][0] for g in sub]),
                             np.array([mus_sub[g["game_id"]][1] for g in sub]))
            # training covariance for common shock
            cov = float(np.cov(np.array([g["hg"] for g in train[-8000:]], float),
                               np.array([g["ag"] for g in train[-8000:]], float))[0, 1])
            lam12 = max(cov, 0.0) if cov > 0 else 0.0

            for variant, (PH, PA, adj) in {
                "poisson": (ph, pa, None),
                "nb": (ph_nb, pa_nb, None),
                "dixon_coles": (ph, pa, dc_adjust(rho)),
                "tie_calibrated": (None, None, None),   # built below
                "bivariate": (None, None, None),
            }.items():
                if variant == "tie_calibrated":
                    # scale non-tie mass so tie share matches empirical training rate
                    mats = []
                    for a, b in zip(ph, pa):
                        m = np.outer(a, b)[:CAP, :CAP]
                        i, j = np.indices(m.shape)
                        tie_m = float(np.trace(m))
                        s = tie_rate_train / tie_m if tie_m > 1e-9 else 0.0
                        m2 = m.copy()
                        m2[i == j] = m[i == j] * s
                        non_tie = m2.sum() - np.trace(m2)
                        m2[i != j] = m[i != j] * ((1 - tie_rate_train) / max(non_tie, 1e-9))
                        mats.append(m2)
                    per_game = mats
                elif variant == "bivariate":
                    per_game = list(bivariate_mats(mu_h, mu_a, lam12))
                else:
                    per_game = [np.outer(a, b)[:CAP, :CAP] * (adj if adj is not None else 1.0)
                                for a, b in zip(PH, PA)]
                    per_game = [m / m.sum() for m in per_game]
                for g, m in zip(evalg, per_game):
                    d = derive(m, so_home)
                    d["score_nll"] = -math.log(max(m[min(g["hg"], MAX_GOALS), min(g["ag"], MAX_GOALS)], 1e-15))
                    all_rows[(model, variant)].append({
                        "game_id": g["game_id"], "season": season, "model": model, "variant": variant,
                        **{k: v for k, v in d.items()},
                        "y_home_win": g["hw"], "y_home_cover": int(g["hg"] - g["ag"] >= 2),
                        "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                        "y_over55": int(g["ohg"] + g["oag"] > 5.5),
                        "y_over65": int(g["ohg"] + g["oag"] > 6.5),
                        "goal_mae_home": abs(d["mu_home"] - g["hg"]),
                        "goal_mae_away": abs(d["mu_away"] - g["ag"]),
                        "score_nll": d["score_nll"],
                    })
            print(f"  scored {model} {season} at {time.time()-t0:.0f}s", flush=True)
        for g in evalg:
            game_lookup[g["game_id"]] = g

    # --- MC control on matched sample ---
    season_2021 = [g for g in games if g["season"] in MC_SAMPLE_SEASONS]
    mus_2021 = {}
    for season in MC_SAMPLE_SEASONS:
        beta = np.array(cache[str(season)]["b7_elo_xg"])
        mus_2021.update(predict_mus([g for g in games if g["season"] == season], "b7_elo_xg", elo, beta))
    so21 = so_rate([g for g in games if TRAIN_FROM <= g["season"] < min(MC_SAMPLE_SEASONS)])
    mc = mc_control(season_2021, mus_2021, so21)
    (RESULTS / "mc_control.json").write_text(json.dumps(mc, indent=1))
    print(f"MC control done: mean|diff|={mc['mean_abs_diff_all']} at {time.time()-t0:.0f}s", flush=True)

    # --- period simulator on matched subset (B7 model, state-eff calibrated) ---
    sim_ids = [g for g in season_2021 if g["game_id"] in mus_2021][:SIM_GAMES]
    beta = np.array(cache[str(max(MC_SAMPLE_SEASONS))]["b7_elo_xg"])
    rng = np.random.default_rng(42)
    state_eff = calibrate_state_eff([g for g in games if TRAIN_FROM <= g["season"] < min(MC_SAMPLE_SEASONS)],
                                    elo, "b7_elo_xg", beta, so21, rng,
                                    float(np.mean([(g["hg"] == g["ag"]) for g in games if TRAIN_FROM <= g["season"] < min(MC_SAMPLE_SEASONS)])))
    sim_rows = []
    t_sim = time.time()
    for g in sim_ids:
        mh, ma = mus_2021[g["game_id"]]
        r = simulate_period_games(mh, ma, state_eff, 0.0, so21, SIM_TRIALS, rng)
        sim_rows.append({"game_id": g["game_id"],
                         "p_home_win": r["p_home_win"], "p_away_cover": r["p_away_cover"],
                         "p_over55": r["p_over_55"], "p_over65": r["p_over_65_official"],
                         "p_tie_sim": r["p_tie"],
                         "y_home_win": g["hw"], "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                         "y_over55": int(g["ohg"] + g["oag"] > 5.5),
                         "y_over65": int(g["ohg"] + g["oag"] > 6.5)})
    sim_summary = {"n_games": len(sim_rows), "trials": SIM_TRIALS, "state_eff": state_eff,
                   "seconds": round(time.time() - t_sim, 1),
                   "brier": {"ml": float(np.mean([(r["p_home_win"] - r["y_home_win"]) ** 2 for r in sim_rows])),
                             "away_cover": float(np.mean([(r["p_away_cover"] - r["y_away_cover"]) ** 2 for r in sim_rows])),
                             "over55": float(np.mean([(r["p_over55"] - r["y_over55"]) ** 2 for r in sim_rows])),
                             "over65": float(np.mean([(r["p_over65"] - r["y_over65"]) ** 2 for r in sim_rows]))}}
    (RESULTS / "period_simulator.json").write_text(json.dumps(sim_summary, indent=1))
    print(f"period simulator done: {sim_summary['brier']} at {time.time()-t0:.0f}s", flush=True)

    # --- summarize variants ---
    summary = {}
    for (model, variant), rows in all_rows.items():
        summary[f"{model}|{variant}"] = summarize(rows)
    (RESULTS / "season_metrics.json").write_text(json.dumps(summary, indent=1))

    # --- policy stage with expanding-window threshold tuning ---
    policy = {}
    for model in MODELS:
        rows = all_rows[(model, "poisson")]
        for season in EVAL_SEASONS:
            past = [r for r in rows if r["season"] < season]
            cur = [r for r in rows if r["season"] == season]
            # outcome fields need real game data: rebuild from games
            game_by_id = {g["game_id"]: g for g in games}
            if len(past) < 300:
                tuned = {"taus": (0.60, 0.60, 0.60), "acc": None, "n": 0, "tier_usage": {}}
            else:
                lookup = {}
                for r in past:
                    lookup[r["game_id"]] = {**r, "_ref_total": r["mu_home"] + r["mu_away"]}
                for gid in lookup:
                    lookup[gid].update({k: game_by_id[gid][k] for k in ("hw", "hg", "ag", "ohg", "oag")})
                tuned = tune_thresholds(list(lookup.values()), lookup) or {"taus": (0.60, 0.60, 0.60), "n": 0}
            tau1, tau2, tau3 = tuned["taus"]
            res = defaultdict(int)
            for r in cur:
                p = {"p_home_win": r["p_home_win"], "p_away_win": 1 - r["p_home_win"],
                     "p_home_cover": r["p_home_cover"], "p_away_cover": r["p_away_cover"],
                     "p_over_55": r["p_over_55"], "p_over_65_official": r["p_over_65_official"]}
                tier, side, _prob, _k = tier_of(p, tau1, tau2, tau3, r["mu_home"] + r["mu_away"])
                line = 5.5 if (r["mu_home"] + r["mu_away"]) <= 6.0 else 6.5
                res[outcome_of(tier, side, game_by_id[r["game_id"]], line)] += 1
            n = sum(res.values())
            policy[f"{model}|{season}"] = {
                "taus": [tau1, tau2, tau3], "tuning_n": tuned.get("n"),
                "tuning_acc": tuned.get("acc"),
                "eval_n": n, "eval_acc": res["won"] / n,
                "fallback_rate": res["fallback"] / n,
                "tier_usage": {k: v / n for k, v in res.items()},
                "won": res["won"], "lost": res["lost"], "fallback": res["fallback"]}
    (RESULTS / "policy_results.json").write_text(json.dumps(policy, indent=1))
    print(f"policy done at {time.time()-t0:.0f}s", flush=True)

    # paired bootstrap: tie_calibrated vs poisson on key markets (B7)
    boot = {}
    for market in ("p_away_cover", "p_over_65_official"):
        boot[market] = bootstrap_delta(all_rows[("b7_elo_xg", "tie_calibrated")],
                                       all_rows[("b7_elo_xg", "poisson")], market, market)
    (RESULTS / "bootstrap_deltas.json").write_text(json.dumps(boot, indent=1))

    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
