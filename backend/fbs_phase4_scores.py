#!/usr/bin/env python3
"""fbs_phase4_scores.py -- final-score distributions for FBS, pre-registered in §21.

Models, all producing a joint distribution over (home points, away points) and therefore a margin PMF and
a total PMF per game:

    Constant   league-average independent Poisson, no tilt
    PriorMean  prior-season team means, no opponent adjustment
    H1         league-average shape tilted to G2h's win probability   (the control that matters)
    H0a        independent Poisson on decayed points ratings           (alpha, gamma by MLE)
    H0b        independent NegBin2 on the same means                   (PRIMARY: + R by moments)
    H0c        bivariate Poisson with a shared component               (marginals unchanged)

Ratings are as-of: decayed points scored/allowed, snapshotted at each UTC date block before any game in it
is played. Every parameter is fitted on games strictly earlier than the block being forecast.

Read-only. Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase4_scores.py --out research/fbs/phase4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import kstest

sys.path.insert(0, "/root/lp-fbs-audit/backend")
import fbs_game_winner_baseline as base  # noqa: E402

MAXS = 120                     # score support 0..MAXS
HL = 6.0                       # rating half-life in team-games
LAM = 0.5 ** (1.0 / HL)
SEED = 20261017
REPS = 2000
SPREAD_LINES = (3, 7, 10, 14)
TOTAL_LINES = (45, 48, 52, 56, 60)
MODELS = ("Constant", "PriorMean", "H1", "H0a", "H0b", "H0c")


# -- distributions ---------------------------------------------------------------------------

def poisson_vec(mu, n=MAXS):
    k = np.arange(n + 1)
    mu = max(float(mu), 1e-9)
    out = np.exp(-mu + k * math.log(mu) - gammaln(k + 1))
    return out / out.sum()


def nb_vec(mu, R, n=MAXS):
    """NegBin2 with mean mu and dispersion R: var = mu + mu^2/R."""
    k = np.arange(n + 1)
    mu = max(float(mu), 1e-9)
    r = max(float(R), 0.5)
    p = r / (r + mu)
    logp = (gammaln(k + r) - gammaln(r) - gammaln(k + 1)
            + r * math.log(p) + k * math.log1p(-p))
    out = np.exp(logp - logp.max())
    return out / out.sum()


def margin_total(ph, pa):
    """Independent (or shared-component-reduced) score vectors -> margin and total PMFs.

    Both live on a 2*MAXS+1 support: margin index i means margin i - MAXS, total index i means i points.
    A full linear convolution is 4*MAXS+1 long but the tail is exactly zero (scores are bounded at MAXS),
    so it is truncated rather than allowed to change the declared support.
    """
    n = 2 * MAXS + 1
    margin = np.convolve(ph, pa[::-1])[:n]
    total = np.convolve(ph, pa)[:n]
    return margin / margin.sum(), total / total.sum()


def bivariate_margin_total(mu_h, mu_a, lam3):
    """X_h = Y1 + Z, X_a = Y2 + Z. Margin = Y1 - Y2 (Z cancels); total = (Y1+Y2) + 2Z."""
    lam3 = max(0.0, min(lam3, 0.8 * min(mu_h, mu_a)))
    y1 = poisson_vec(max(mu_h - lam3, 1e-9))
    y2 = poisson_vec(max(mu_a - lam3, 1e-9))
    margin, w = margin_total(y1, y2)
    z = poisson_vec(lam3)
    two_z = np.zeros(2 * MAXS + 1)
    two_z[0::2] = z[:MAXS + 1]
    total = np.convolve(w, two_z)[:2 * MAXS + 1]
    return margin / margin.sum(), total / total.sum()


def tilted_league(ph0, pa0, p_win):
    """League-average joint tilted by exp(theta) on home wins so P(home win) = p_win.

    The tilt is a step function on sign(margin), so both margin and total PMFs come out in closed form.
    Returns (margin_pmf, total_pmf, theta).
    """
    joint = np.outer(ph0, pa0)
    idx = np.arange(MAXS + 1)
    home_win = idx[:, None] > idx[None, :]
    margin_idx = idx[:, None] - idx[None, :] + MAXS
    total_idx = idx[:, None] + idx[None, :]
    a_plus = np.bincount(margin_idx[home_win], weights=joint[home_win],
                         minlength=2 * MAXS + 1)
    a_rest = np.bincount(margin_idx[~home_win], weights=joint[~home_win],
                         minlength=2 * MAXS + 1)
    t_plus = np.bincount(total_idx[home_win], weights=joint[home_win],
                         minlength=2 * MAXS + 1)
    t_rest = np.bincount(total_idx[~home_win], weights=joint[~home_win],
                         minlength=2 * MAXS + 1)
    s_plus, s_rest = a_plus.sum(), a_rest.sum()
    if s_plus <= 0 or s_rest <= 0:
        return margin_total(ph0, pa0)[0], margin_total(ph0, pa0)[1], 0.0
    p_win = min(max(p_win, 1e-4), 1 - 1e-4)
    # P(win) = e^t S+ / (S0 + e^t S+)  ->  e^t = p S0 / ((1-p) S+)
    e_t = (p_win * s_rest) / ((1 - p_win) * s_plus)
    denom = s_rest + e_t * s_plus
    return ((a_rest + e_t * a_plus) / denom, (t_rest + e_t * t_plus) / denom, math.log(e_t))


# -- metrics ---------------------------------------------------------------------------------

def cdf_of(pmf):
    c = np.cumsum(pmf)
    c[-1] = 1.0
    return c


def crps_discrete(cdf, y, offset=0):
    """CRPS on an integer support whose index i corresponds to value i + offset."""
    k = np.arange(len(cdf)) + offset
    return float(np.sum((cdf - (k >= y).astype(float)) ** 2))


def central_interval(cdf, level, offset=0):
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    n = len(cdf)
    lo = int(np.searchsorted(cdf, lo_q))
    hi = int(np.searchsorted(cdf, hi_q))
    return min(lo, n - 1) + offset, min(hi, n - 1) + offset


def shortest_interval(pmf, level, offset=0):
    """Shortest contiguous interval whose mass is >= level."""
    n = len(pmf)
    c = np.concatenate([[0.0], np.cumsum(pmf)])
    best, best_w = (0, n - 1), n
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j < n and c[j + 1] - c[i] < level - 1e-12:
            j += 1
        if j >= n:
            break
        if j - i < best_w:
            best, best_w = (i, j), j - i
    return best[0] + offset, best[1] + offset


def pit_randomized(cdf, pmf, y, offset, u):
    """Randomized PIT for a discrete predictive distribution."""
    idx = int(y) - offset
    below = cdf[idx - 1] if idx > 0 else 0.0
    return float(below + u * pmf[idx])


def point_stats(pred, obs):
    d = np.asarray(pred, float) - np.asarray(obs, float)
    return {"n": int(len(d)), "mae": float(np.mean(np.abs(d))),
            "rmse": float(np.sqrt(np.mean(d ** 2))), "bias": float(np.mean(d))}


def block_bootstrap(diffs, blocks, reps=REPS, seed=SEED):
    """Paired mean difference with a UTC-week-block bootstrap interval."""
    d = np.asarray(diffs, float)
    blocks = np.asarray(blocks)
    uniq = np.unique(blocks)
    if len(uniq) < 2:
        return {"mean": float(d.mean()), "lo": float("nan"), "hi": float("nan"),
                "blocks": int(len(uniq)), "n": int(len(d))}
    sums = {b: d[blocks == b].sum() for b in uniq}
    counts = {b: int((blocks == b).sum()) for b in uniq}
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for r in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        tot = sum(sums[b] for b in pick)
        cnt = sum(counts[b] for b in pick)
        means[r] = tot / cnt
    return {"mean": float(d.mean()), "lo": float(np.percentile(means, 2.5)),
            "hi": float(np.percentile(means, 97.5)), "blocks": int(len(uniq)), "n": int(len(d))}


# -- data ------------------------------------------------------------------------------------

def load_games(seasons):
    """Every FBS game with a final score from cfb_schedules, plus as-of decayed points ratings."""
    frames = []
    for s in seasons:
        path = "research/fbs/parquet/cfb_schedules/cfb_schedules_%d.parquet" % s
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path, columns=["game_id", "season", "week", "start_date", "home_id",
                                            "away_id", "home_team", "away_team", "home_points",
                                            "away_points", "home_conference", "away_conference",
                                            "neutral_site", "completed"])
        frames.append(df)
    g = pd.concat(frames, ignore_index=True)
    g["start_date"] = pd.to_datetime(g["start_date"], errors="coerce", utc=True)
    g = g.dropna(subset=["start_date", "home_points", "away_points"])
    g = g[g["completed"].fillna(True).astype(bool)]
    g["home_points"] = pd.to_numeric(g["home_points"], errors="coerce")
    g["away_points"] = pd.to_numeric(g["away_points"], errors="coerce")
    g = g.dropna(subset=["home_points", "away_points"])
    return g.sort_values(["start_date", "game_id"]).reset_index(drop=True)


def build_as_of(g):
    """Decayed points ratings, snapshotted before each date block. Returns per-game as-of ratings."""
    state = {}
    out = []
    for date, block in g.groupby(g["start_date"].dt.date, sort=True):
        snap = {t: (s["f"], s["a"], s["w"]) for t, s in state.items()}
        for r in block.itertuples(index=False):
            def rating(team):
                f, a, w = snap.get(team, (0.0, 0.0, 0.0))
                return (f / w, a / w, w) if w > 0 else (None, None, 0.0)
            rf, ra, rw = rating(r.home_id)
            af, aa, aw = rating(r.away_id)
            out.append({"game_id": str(r.game_id), "date": date, "home_id": r.home_id,
                        "away_id": r.away_id, "home_points": r.home_points,
                        "away_points": r.away_points,
                        "home_for": rf, "home_against": ra, "home_w": rw,
                        "away_for": af, "away_against": aa, "away_w": aw})
        for r in block.itertuples(index=False):
            for team, pts, opp in ((r.home_id, r.home_points, r.away_points),
                                   (r.away_id, r.away_points, r.home_points)):
                s = state.get(team, {"f": 0.0, "a": 0.0, "w": 0.0})
                state[team] = {"f": s["f"] * LAM + float(pts), "a": s["a"] * LAM + float(opp),
                               "w": s["w"] * LAM + 1.0}
    return pd.DataFrame(out)


def prior_season_means(g):
    """Mean points scored per team in the previous season, no adjustment."""
    out = {}
    for season in sorted(g["season"].unique()):
        prev = g[g["season"] == season - 1]
        if prev.empty:
            continue
        scored = pd.concat([
            prev[["home_id", "home_points"]].rename(columns={"home_id": "team", "home_points": "pts"}),
            prev[["away_id", "away_points"]].rename(columns={"away_id": "team", "away_points": "pts"}),
        ])
        means = scored.groupby("team")["pts"].mean()
        for team, m in means.items():
            out[(season, team)] = float(m)
    return out


# -- models ----------------------------------------------------------------------------------

def fit_poisson(train):
    """alpha, gamma by Poisson MLE on games with ratings available."""
    t = train.dropna(subset=["home_for", "away_for"])
    if len(t) < 50:
        return None
    off_h = np.log(np.maximum(t.home_for.to_numpy(), 1.0) / t.home_for.mean())
    def_h = np.log(np.maximum(t.home_against.to_numpy(), 1.0) / t.home_against.mean())
    off_a = np.log(np.maximum(t.away_for.to_numpy(), 1.0) / t.away_for.mean())
    def_a = np.log(np.maximum(t.away_against.to_numpy(), 1.0) / t.away_against.mean())
    yh = t.home_points.to_numpy(float)
    ya = t.away_points.to_numpy(float)

    def nll(p):
        a, gm = p
        lh = a + off_h + def_a + gm / 2
        la = a + off_a + def_h - gm / 2
        mh, ma = np.exp(lh), np.exp(la)
        val = np.sum(mh - yh * lh) + np.sum(ma - ya * la)
        grad = np.array([np.sum(mh + ma - yh - ya),
                         0.5 * np.sum(mh - ma - yh + ya)])
        return val, grad

    res = minimize(nll, np.array([math.log(max(t.home_points.mean(), 1.0)), 0.0]), jac=True,
                   method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1]), (off_h, def_h, off_a, def_a, yh, ya)


def fit_dispersion(alpha, gamma, mats):
    off_h, def_h, off_a, def_a, yh, ya = mats
    mh = np.exp(alpha + off_h + def_a + gamma / 2)
    ma = np.exp(alpha + off_a + def_h - gamma / 2)
    num = np.sum(mh ** 2) + np.sum(ma ** 2)
    den = (np.sum((yh - mh) ** 2 - mh) + np.sum((ya - ma) ** 2 - ma))
    return max(0.5, num / den) if den > 0 else 50.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join("research", "fbs", "phase4"))
    ap.add_argument("--seasons", default="2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026")
    a = ap.parse_args(argv)
    os.makedirs(os.path.join(a.out, "pmf"), exist_ok=True)
    seasons = [int(s) for s in a.seasons.split(",")]

    print("loading schedules and building as-of ratings ...")
    g = load_games(seasons)
    asof = build_as_of(g)
    prior = prior_season_means(g)
    print("  %d games with scores, %d as-of rows" % (len(g), len(asof)))

    # evaluation population: identical to Phase 3 (same harness, same games, same exclusion)
    data_dir = "/root/lp-fbs-audit/research/fbs/parquet"
    events, _, _, _ = base.load_events(data_dir, [s for s in seasons if s >= 2022])
    forecasts = base.make_predictions(events, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    forecasts["utc_date"] = pd.to_datetime(forecasts["utc_date"])
    forecasts["week_start"] = (forecasts["utc_date"] - pd.to_timedelta(
        forecasts["utc_date"].dt.weekday, unit="D")).dt.date
    fc = pd.read_csv("research/fbs/phase3-g/forecasts_walk_forward.csv", dtype={"game_id": str})
    hold = pd.read_csv("research/fbs/phase3-baseline/fbs_game_winner_holdout_2025_20261018.csv",
                       dtype={"game_id": str})
    base_cols = ["game_id", "season", "week_start", "home_team_id", "away_team_id",
                 "home_team", "away_team", "home_score", "away_score"]
    pop = forecasts[base_cols].copy()
    pop = pop.merge(fc[["game_id", "p_g2h"]], on="game_id", how="inner")
    pop = pop[pop["season"] >= 2023]
    pop["period"] = np.where(pop["season"] >= 2026, "dev2026", "walk_forward")
    pop["h1_prob"] = pop["p_g2h"]

    # frozen holdout, built straight from the ledger so no game can be lost in a join
    ho = forecasts[base_cols].copy()
    ho = ho[ho["game_id"].isin(set(hold["game_id"]))]
    ho = ho.merge(hold[["game_id", "elo_home_prob"]], on="game_id", how="left")
    ho["period"] = "holdout"
    ho["h1_prob"] = ho["elo_home_prob"]
    lost = sorted(set(hold["game_id"]) - set(ho["game_id"]))
    print("holdout ledger %d games; %d present in the harness frame; absent %d %s"
          % (len(hold), len(ho), len(lost), lost[:5]))
    pop = pd.concat([pop, ho], ignore_index=True)
    pop = pop.rename(columns={"home_team_id": "home_id", "away_team_id": "away_id"})
    pop["home_points"] = pd.to_numeric(pop["home_score"], errors="coerce")
    pop["away_points"] = pd.to_numeric(pop["away_score"], errors="coerce")
    pop = pop.dropna(subset=["home_points", "away_points"])
    asof["game_id"] = asof["game_id"].astype(str)
    pop = pop.merge(asof[["game_id", "date", "home_for", "home_against", "away_for", "away_against"]],
                    on="game_id", how="left")
    pop["game_date"] = pd.to_datetime(pop["date"])
    for per, d in pop.groupby("period"):
        print("  %-12s %4d games, %4d with as-of ratings" % (per, len(d), d.home_for.notna().sum()))
    dropped = pop[pop["home_for"].isna()]
    if len(dropped):
        print("  dropped for missing ratings: %d %s"
              % (len(dropped), sorted(dropped.game_id)[:5]))
    # the pre-registration keeps game 401778314 out (no CFBD play-by-play); it is excluded here too so the
    # population is identical to Phase 3 even though a score distribution does not need PBP
    pop = pop[pop["game_id"] != "401778314"]
    pop = pop.dropna(subset=["home_for", "away_for"]).reset_index(drop=True)
    weeks = sorted(pop["week_start"].unique())
    print("population %d games over %d week blocks (wf %d, holdout %d)"
          % (len(pop), len(weeks), (pop.period == "walk_forward").sum(), (pop.period == "holdout").sum()))

    # ---- forecast: walk-forward per block, plus a FROZEN holdout fitted through 2024 only
    games = asof.copy()
    games["date"] = pd.to_datetime(games["date"])
    games["block"] = games["date"].dt.date
    blocks = sorted(games["block"].unique())

    def model_params(train):
        fit = fit_poisson(train)
        if fit is None:
            return None
        alpha, gamma, mats = fit
        R = fit_dispersion(alpha, gamma, mats)
        cov = float(np.cov(mats[4], mats[5])[0, 1]) if len(mats[4]) > 2 else 0.0
        return {"alpha": alpha, "gamma": gamma, "R": R, "lam3": max(0.0, cov),
                "mu_h0": float(np.mean(mats[4])), "mu_a0": float(np.mean(mats[5])),
                "home_for_mean": float(train.home_for.mean()),
                "home_against_mean": float(train.home_against.mean()),
                "away_for_mean": float(train.away_for.mean()),
                "away_against_mean": float(train.away_against.mean()),
                "n_train": int(len(train))}

    def predict_rows(r, par, period):
        lh = (par["alpha"]
              + math.log(max(r.home_for, 1.0) / par["home_for_mean"])
              + math.log(max(r.away_against, 1.0) / par["away_against_mean"]) + par["gamma"] / 2)
        la = (par["alpha"]
              + math.log(max(r.away_for, 1.0) / par["away_for_mean"])
              + math.log(max(r.home_against, 1.0) / par["home_against_mean"]) - par["gamma"] / 2)
        p_win = float(r.h1_prob) if pd.notna(r.h1_prob) else 0.5
        return {"game_id": r.game_id, "block": str(r.week_start), "season": int(r.season),
                "period": period, "mu_h": math.exp(lh), "mu_a": math.exp(la),
                "R": par["R"], "lam3": par["lam3"], "mu_h0": par["mu_h0"],
                "mu_a0": par["mu_a0"],
                "prior_h": prior.get((r.season, r.home_id), par["mu_h0"]),
                "prior_a": prior.get((r.season, r.away_id), par["mu_a0"]), "p_h1": p_win,
                "obs_h": float(r.home_points), "obs_a": float(r.away_points)}

    preds, params = [], []
    for block in blocks:
        train = games[games["date"].dt.date < block]
        if len(train) < 200:
            continue
        par = model_params(train)
        if par is None:
            continue
        params.append({"block": str(block), "kind": "walk_forward", **par})
        for r in pop[(pop["game_date"].dt.date == block) & (pop.period != "holdout")].itertuples(
                index=False):
            if pd.isna(r.home_for) or pd.isna(r.away_for) or pd.isna(r.h1_prob):
                continue
            preds.append(predict_rows(r, par, r.period))

    # frozen holdout: every fitted parameter from games strictly before 2025-01-01
    frozen_train = games[games["date"] < pd.Timestamp("2025-01-01")]
    frozen = model_params(frozen_train)
    if frozen is None:
        raise SystemExit("holdout fit failed: not enough frozen training games")
    params.append({"block": "frozen_2025", "kind": "holdout", **frozen})
    for r in pop[pop.period == "holdout"].itertuples(index=False):
        if pd.isna(r.home_for) or pd.isna(r.away_for) or pd.isna(r.h1_prob):
            continue
        preds.append(predict_rows(r, frozen, "holdout"))
    print("frozen holdout parameters fitted on %d games before 2025-01-01" % frozen["n_train"])
    P = pd.DataFrame(preds)
    print("forecasts: %d rows (%d walk-forward, %d holdout) over %d blocks"
          % (len(P), (P.period == "walk_forward").sum(), (P.period == "holdout").sum(),
             P.block.nunique()))

    # ---- PMFs per model
    n_m = 2 * MAXS + 1
    store = {m: {"margin": np.zeros((len(P), n_m), np.float32),
                 "total": np.zeros((len(P), n_m), np.float32),
                 "mean_margin": np.zeros(len(P)), "mean_total": np.zeros(len(P))}
             for m in MODELS}
    cache = {}
    for i, r in enumerate(P.itertuples(index=False)):
        key = (round(r.mu_h0, 4), round(r.mu_a0, 4), round(r.p_h1, 4))
        if key not in cache:
            ph0, pa0 = poisson_vec(r.mu_h0), poisson_vec(r.mu_a0)
            m_con, t_con = margin_total(ph0, pa0)
            m_h1, t_h1, _ = tilted_league(ph0, pa0, r.p_h1)
            cache[key] = (m_con, t_con, m_h1, t_h1)
        m_con, t_con, m_h1, t_h1 = cache[key]
        m_a, t_a = margin_total(poisson_vec(r.mu_h), poisson_vec(r.mu_a))
        m_b, t_b = margin_total(nb_vec(r.mu_h, r.R), nb_vec(r.mu_a, r.R))
        m_c, t_c = bivariate_margin_total(r.mu_h, r.mu_a, r.lam3)
        m_p, t_p = margin_total(poisson_vec(r.prior_h), poisson_vec(r.prior_a))
        for model, (mm, tt) in (("Constant", (m_con, t_con)), ("PriorMean", (m_p, t_p)),
                                ("H1", (m_h1, t_h1)), ("H0a", (m_a, t_a)),
                                ("H0b", (m_b, t_b)), ("H0c", (m_c, t_c))):
            store[model]["margin"][i] = mm.astype(np.float32)
            store[model]["total"][i] = tt.astype(np.float32)
            store[model]["mean_margin"][i] = float(np.dot(np.arange(n_m) - MAXS, mm))
            store[model]["mean_total"][i] = float(np.dot(np.arange(n_m), tt))

    # ---- metrics
    rng = np.random.default_rng(SEED)
    u_draw = rng.random(len(P))
    obs_margin = (P.obs_h - P.obs_a).to_numpy(float)
    obs_total = (P.obs_h + P.obs_a).to_numpy(float)
    rows = []
    per_game = []
    for model in MODELS:
        ms, ts = store[model]["margin"], store[model]["total"]
        mm_mean, tt_mean = store[model]["mean_margin"], store[model]["mean_total"]
        for i in range(len(P)):
            mm, tt = ms[i].astype(float), ts[i].astype(float)
            cm, ct = cdf_of(mm / mm.sum()), cdf_of(tt / tt.sum())
            mm = mm / mm.sum()
            tt = tt / tt.sum()
            rec = {"model": model, "game_id": P.game_id.iloc[i], "block": P.block.iloc[i],
                   "season": P.season.iloc[i], "period": P.period.iloc[i],
                   "crps_margin": crps_discrete(cm, obs_margin[i], -MAXS),
                   "crps_total": crps_discrete(ct, obs_total[i], 0),
                   "log_margin": -math.log(max(mm[int(obs_margin[i]) + MAXS], 1e-12)),
                   "log_total": -math.log(max(tt[int(obs_total[i])], 1e-12)),
                   "pit_margin": pit_randomized(cm, mm, obs_margin[i], -MAXS, u_draw[i]),
                   "pit_total": pit_randomized(ct, tt, obs_total[i], 0, u_draw[i]),
                   "pred_margin": mm_mean[i], "pred_total": tt_mean[i],
                   "pred_h": (tt_mean[i] + mm_mean[i]) / 2, "pred_a": (tt_mean[i] - mm_mean[i]) / 2,
                   "obs_margin": obs_margin[i], "obs_total": obs_total[i],
                   "obs_h": P.obs_h.iloc[i], "obs_a": P.obs_a.iloc[i]}
            for level in (0.5, 0.8, 0.9):
                lo, hi = central_interval(cm, level, -MAXS)
                slo, shi = shortest_interval(mm, level, -MAXS)
                rec["cov%d_margin" % int(level * 100)] = float(lo <= obs_margin[i] <= hi)
                rec["short%d_margin" % int(level * 100)] = float(slo <= obs_margin[i] <= shi)
                lo, hi = central_interval(ct, level, 0)
                slo, shi = shortest_interval(tt, level, 0)
                rec["cov%d_total" % int(level * 100)] = float(lo <= obs_total[i] <= hi)
                rec["short%d_total" % int(level * 100)] = float(slo <= obs_total[i] <= shi)
            for L in SPREAD_LINES:
                for side in ("give", "get"):
                    line = L if side == "give" else -L
                    p = float(np.sum(mm[np.arange(n_m) - MAXS > line]))
                    rec["spread_%s%d" % (side, L)] = p
                    rec["spread_hit_%s%d" % (side, L)] = float(obs_margin[i] > line)
            for line in TOTAL_LINES:
                p = float(np.sum(tt[np.arange(n_m) > line]))
                rec["over_%d" % line] = p
                rec["over_hit_%d" % line] = float(obs_total[i] > line)
            per_game.append(rec)
    G = pd.DataFrame(per_game)
    G.to_csv(os.path.join(a.out, "pmf", "per_observation_scores.csv"), index=False)
    np.savez_compressed(os.path.join(a.out, "pmf", "margin_total_pmf.npz"),
                        game_id=P.game_id.to_numpy(),
                        **{"%s_margin" % m: store[m]["margin"] for m in MODELS},
                        **{"%s_total" % m: store[m]["total"] for m in MODELS})
    P.to_csv(os.path.join(a.out, "per_game_parameters.csv"), index=False)
    pd.DataFrame(params).to_csv(os.path.join(a.out, "block_parameters.csv"), index=False)

    # ---- summaries and gates
    periods = {"walk_forward": G[G.period == "walk_forward"],
               "holdout": G[G.period == "holdout"],
               "dev2026": G[G.period == "dev2026"]}
    summary = []
    for pname, d in periods.items():
        for model in MODELS:
            s = d[d.model == model]
            if s.empty:
                continue
            row = {"period": pname, "model": model, "n": len(s)}
            for stat, col in (("mae_home", "pred_h"), ("mae_away", "pred_a"),
                              ("mae_margin", "pred_margin"), ("mae_total", "pred_total")):
                obs = {"pred_h": "obs_h", "pred_a": "obs_a",
                       "pred_margin": "obs_margin", "pred_total": "obs_total"}[col]
                row[stat] = float(np.mean(np.abs(s[col] - s[obs])))
                if stat.startswith("mae"):
                    d_ = (s[col] - s[obs]).to_numpy()
                    row[stat.replace("mae", "rmse")] = float(np.sqrt(np.mean(d_ ** 2)))
                    row[stat.replace("mae", "bias")] = float(np.mean(d_))
            row["crps_margin"] = float(s.crps_margin.mean())
            row["crps_total"] = float(s.crps_total.mean())
            row["log_margin"] = float(s.log_margin.mean())
            row["log_total"] = float(s.log_total.mean())
            for level in (50, 80, 90):
                row["cov%d_margin" % level] = float(s["cov%d_margin" % level].mean())
                row["cov%d_total" % level] = float(s["cov%d_total" % level].mean())
                row["short%d_margin" % level] = float(s["short%d_margin" % level].mean())
                row["short%d_total" % level] = float(s["short%d_total" % level].mean())
            row["pit_margin_ks"] = float(kstest(s.pit_margin, "uniform").pvalue)
            row["pit_total_ks"] = float(kstest(s.pit_total, "uniform").pvalue)
            row["brier_spread"] = float(np.mean([
                (s["spread_%s%d" % (side, L)] - s["spread_hit_%s%d" % (side, L)]).pow(2).mean()
                for L in SPREAD_LINES for side in ("give", "get")]))
            row["brier_total"] = float(np.mean([
                (s["over_%d" % L] - s["over_hit_%d" % L]).pow(2).mean() for L in TOTAL_LINES]))
            summary.append(row)
    S = pd.DataFrame(summary)
    S.to_csv(os.path.join(a.out, "summary_by_period.csv"), index=False)

    # paired comparisons by week block
    pairs = []
    for pname, d in periods.items():
        for base_model in ("H1", "Constant"):
            for model in MODELS:
                if model == base_model:
                    continue
                a_ = d[d.model == model].set_index("game_id").sort_index()
                b_ = d[d.model == base_model].set_index("game_id").sort_index()
                common = a_.index.intersection(b_.index)
                if len(common) < 100:
                    continue
                def brier_vec(frame, metric, games):
                    out = []
                    for g in games:
                        if metric == "brier_spread":
                            vals = [(frame.loc[g, "spread_%s%d" % (s_, L)]
                                     - frame.loc[g, "spread_hit_%s%d" % (s_, L)]) ** 2
                                    for L in SPREAD_LINES for s_ in ("give", "get")]
                        else:
                            vals = [(frame.loc[g, "over_%d" % L]
                                     - frame.loc[g, "over_hit_%d" % L]) ** 2
                                    for L in TOTAL_LINES]
                        out.append(sum(vals) / len(vals))
                    return np.array(out)

                for metric in ("crps_margin", "crps_total", "brier_spread", "brier_total"):
                    if metric.startswith("brier"):
                        av = brier_vec(a_, metric, common)
                        bv = brier_vec(b_, metric, common)
                    else:
                        av = a_.loc[common, metric].to_numpy()
                        bv = b_.loc[common, metric].to_numpy()
                    res = block_bootstrap(av - bv, a_.loc[common, "block"].to_numpy())
                    pairs.append({"period": pname, "model": model, "base": base_model,
                                  "metric": metric, **res})
    PR = pd.DataFrame(pairs)
    PR.to_csv(os.path.join(a.out, "paired.csv"), index=False)

    print("\n== summary (walk-forward 2023-25)")
    wf = S[S.period == "walk_forward"]
    cols = ["model", "n", "mae_margin", "mae_total", "crps_margin", "crps_total",
            "log_margin", "log_total", "pit_margin_ks", "pit_total_ks",
            "cov50_margin", "cov80_margin", "cov90_margin", "brier_spread", "brier_total"]
    print(wf[cols].to_string(index=False, float_format=lambda v: "%.4f" % v))
    print("\n== paired vs H1 (walk-forward)")
    print(PR[(PR.period == "walk_forward") & (PR.base == "H1")][
        ["model", "metric", "mean", "lo", "hi", "blocks"]]
        .to_string(index=False, float_format=lambda v: "%.4f" % v))

    # ---- gates
    def get(period, model, metric, base=None):
        d = PR[(PR.period == period) & (PR.model == model) & (PR.metric == metric)]
        if base:
            d = d[d.base == base]
        return None if d.empty else d.iloc[0]

    primary = "H0b"
    gates = {}
    wf_row = S[(S.period == "walk_forward") & (S.model == primary)].iloc[0]
    ho_row = S[(S.period == "holdout") & (S.model == primary)].iloc[0]
    g_dist_m = get("walk_forward", primary, "crps_margin", "H1")
    g_dist_t = get("walk_forward", primary, "crps_total", "H1")
    gates["G-SAMPLE"] = bool(wf_row.n >= 1500 and ho_row.n >= 250)
    gates["G-DIST"] = bool(g_dist_m is not None and g_dist_t is not None
                           and g_dist_m.hi < 0 and g_dist_t.hi < 0
                           and get("holdout", primary, "crps_margin", "H1")["mean"] < 0
                           and get("holdout", primary, "crps_total", "H1")["mean"] < 0)
    gates["G-CAL"] = bool(wf_row.pit_margin_ks > 0.05 and wf_row.pit_total_ks > 0.05
                          and ho_row.pit_margin_ks > 0.05 and ho_row.pit_total_ks > 0.05
                          and all(abs(wf_row["cov%d_margin" % L] - L / 100) <= 0.05
                                  for L in (50, 80, 90))
                          and all(abs(wf_row["cov%d_total" % L] - L / 100) <= 0.05
                                  for L in (50, 80, 90)))
    sp_c, sp_h = get("walk_forward", primary, "brier_spread", "Constant"), \
        get("walk_forward", primary, "brier_spread", "H1")
    gates["G-SPREAD"] = bool(sp_c is not None and sp_h is not None
                             and sp_c.hi < 0 and sp_h.hi < 0
                             and get("holdout", primary, "brier_spread", "H1")["mean"] < 0)
    tt_c, tt_h = get("walk_forward", primary, "brier_total", "Constant"), \
        get("walk_forward", primary, "brier_total", "H1")
    gates["G-TOTAL"] = bool(tt_c is not None and tt_h is not None
                            and tt_c.hi < 0 and tt_h.hi < 0
                            and get("holdout", primary, "brier_total", "H1")["mean"] < 0)
    verdict = "ADOPTED" if all(gates.values()) else "NOT_ADOPTED"

    print("\n== gates (%s)" % primary)
    for k, v in gates.items():
        print("   %-10s %s" % (k, "PASS" if v else "FAIL"))
    print("   VERDICT: %s" % verdict)

    manifest = {"models": list(MODELS), "primary": primary, "gates": gates, "verdict": verdict,
                "population": {"total": int(len(P)),
                               "walk_forward": int((P.period == "walk_forward").sum()),
                               "holdout": int((P.period == "holdout").sum())},
                "blocks": int(P.block.nunique()), "seed": SEED, "reps": REPS,
                "support": {"margin": [-MAXS, MAXS], "total": [0, MAXS]},
                "files": {}}
    for name in ("pmf/margin_total_pmf.npz", "pmf/per_observation_scores.csv",
                 "per_game_parameters.csv", "block_parameters.csv", "summary_by_period.csv",
                 "paired.csv"):
        path = os.path.join(a.out, name)
        if os.path.exists(path):
            manifest["files"][name] = {"sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
                                       "bytes": os.path.getsize(path)}
    with open(os.path.join(a.out, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print("\nwrote %s" % a.out)


if __name__ == "__main__":
    main()
