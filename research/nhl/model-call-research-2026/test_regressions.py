#!/usr/bin/env python3
"""Regression tests for the research prototype.

1. Prototype expected goals must equal the fitted PoissonRegressor's own
   .predict(X) on the same rows — this catches a missing intercept
   (the original bug: fit saved only .coef_, predict used exp(x . beta)).
2. League-average projected goals must be plausible NHL scoring (~2.5-3.4
   goals per team per game; total 5.5-6.5), checked on the actual cache.
3. Cover-probability base-rate sanity: mean projected p_away_cover must not
   sit far above the empirical base rate (~0.67 for away +1.5).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_backtest as rb

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name} {detail}")
    if not cond:
        failures.append(name)


def main() -> None:
    games = rb.load_games()
    elo = rb.elo_replay(games)
    cache_path = HERE / "results" / "fit_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    # --- 1. intercept + coef must reproduce PoissonRegressor.predict ---
    train = [g for g in games if rb.TRAIN_FROM <= g["season"] < rb.EVAL_SEASONS[0]]
    for model in rb.MODELS:
        X, y = rb.side_rows(train, model, elo)
        fitted = PoissonRegressor(alpha=rb.ALPHA, max_iter=500, tol=1e-9).fit(X, y)
        params = {"intercept": float(fitted.intercept_), "coef": [float(b) for b in fitted.coef_]}
        sample = train[:300]
        mus = rb.predict_mus(sample, model, elo, params)
        proto = [mus[g["game_id"]] for g in sample]
        expect = []
        for g in sample:
            hx, hxga = rb.lograte(g["home_rolling10_5v5_score_venue_xgf"]), rb.lograte(g["home_rolling10_5v5_score_venue_xga"])
            ax, axga = rb.lograte(g["away_rolling10_5v5_score_venue_xgf"]), rb.lograte(g["away_rolling10_5v5_score_venue_xga"])
            d = elo[g["game_id"]]["diff"]
            if model == "b3_elo":
                xh, xa = [elo[g["game_id"]]["venue"], d], [0.0, -d]
            elif model == "b5_xg":
                xh, xa = [1.0, hx, axga], [0.0, ax, hxga]
            else:
                xh, xa = [1.0, hx, axga, d], [0.0, ax, hxga, -d]
            expect.append((fitted.predict([xh])[0], fitted.predict([xa])[0]))
        err = max(abs(a - b) for (a, _), (b, _) in zip(proto, expect))
        check(f"predict_mus matches .predict ({model})", err < 1e-6, f"max_err={err:.2e}")

        # cached params, if present, must include the intercept
        cached = cache.get(str(rb.EVAL_SEASONS[-1]), {}).get(model)
        if cached is not None:
            check(f"fit_cache stores intercept ({model})",
                  isinstance(cached, dict) and "intercept" in cached and "coef" in cached,
                  f"keys={list(cached) if isinstance(cached, dict) else cached}")

    # --- 2. league-average projected goals must be plausible ---
    if cache:
        season = str(rb.EVAL_SEASONS[-1])
        evalg = [g for g in games if g["season"] == rb.EVAL_SEASONS[-1]]
        for model in rb.MODELS:
            if model not in cache.get(season, {}):
                continue
            mus = rb.predict_mus(evalg, model, elo, cache[season][model])
            mh = np.array([m[0] for m in mus.values()])
            ma = np.array([m[1] for m in mus.values()])
            total = (mh.mean() + ma.mean())
            check(f"league-mean goals plausible ({model}, season {season})",
                  5.0 < total < 7.0, f"home={mh.mean():.2f} away={ma.mean():.2f} total={total:.2f}")
            check(f"no implausibly low team goals ({model})",
                  mh.min() > 1.5 and ma.min() > 1.5,
                  f"min_home={mh.min():.2f} min_away={ma.min():.2f}")

    # --- 3. mean projected p_away_cover vs empirical base rate ---
    if cache:
        season = str(rb.EVAL_SEASONS[-1])
        evalg = [g for g in games if g["season"] == rb.EVAL_SEASONS[-1]]
        train_so = rb.so_rate([g for g in games if g["season"] < rb.EVAL_SEASONS[-1]])
        for model in rb.MODELS:
            if model not in cache.get(season, {}):
                continue
            mus = rb.predict_mus(evalg, model, elo, cache[season][model])
            pcov = []
            for g in evalg:
                mh, ma = mus[g["game_id"]]
                m = rb.joint(rb.pmf_rows(np.array([mh])), rb.pmf_rows(np.array([ma])))
                pcov.append(rb.derive(m, train_so)["p_away_cover"])
            mean_pcov = float(np.mean(pcov))
            # empirical away+1.5 cover rate on the same season
            y = np.array([int(g["hg"] - g["ag"] <= 1) for g in evalg], float)
            base = float(y.mean())
            # raw Poisson is expected to sit somewhat above base, but not 10+ points
            check(f"raw p_away_cover not wildly inflated ({model}, season {season})",
                  mean_pcov < base + 0.06, f"mean_p={mean_pcov:.3f} base={base:.3f}")

    print()
    if failures:
        print(f"{len(failures)} regression check(s) FAILED: {failures}")
        sys.exit(1)
    print("all regression checks passed")


if __name__ == "__main__":
    main()
