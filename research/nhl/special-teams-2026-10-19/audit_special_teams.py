#!/usr/bin/env python3
"""Step A reproduction audit — no refitting.

Reads forecasts_st.csv and recomputes Brier, log loss, CRPS and the game-clustered
95% CIs using only the CSV. Compares to results_special_teams.json to 1e-9.
Exit code 0 = exact reproduction; 1 = mismatch (which must be reported, not tuned).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SEED = 20261019
N_BOOT = 10_000


def pmf(mu, cap=21):
    mu = max(float(mu), 1e-9)
    ks = np.arange(cap)
    p = np.exp(-mu + ks * math.log(mu) - np.array([math.lgamma(k + 1) for k in ks]))
    return p / p.sum()


def crps(p, y):
    F = np.cumsum(p)
    ks = np.arange(len(p))
    return float(np.sum((F - (ks >= y).astype(float)) ** 2))


def main() -> int:
    rows = list(csv.DictReader(open(HERE / "forecasts_st.csv")))
    published = json.load(open(HERE / "results_special_teams.json"))["metrics"]
    # order by game_id to match the runner's sorted(set(b5) & set(stt))
    rows.sort(key=lambda r: int(r["game_id"]))
    n = len(rows)
    print(f"audit: {n} forecast rows from forecasts_st.csv")

    b5_brier = np.empty(n); st_brier = np.empty(n)
    b5_ll = np.empty(n); st_ll = np.empty(n)
    b5_crps = np.empty(n); st_crps = np.empty(n)
    for i, r in enumerate(rows):
        y = int(r["home_win"])
        p5 = float(r["p_b5"]); ps = float(r["p_st"])
        b5_brier[i] = (p5 - y) ** 2
        st_brier[i] = (ps - y) ** 2
        b5_ll[i] = -(y * math.log(p5) + (1 - y) * math.log(1 - p5))
        st_ll[i] = -(y * math.log(ps) + (1 - y) * math.log(1 - ps))
        hg = int(r["home_goals"]); ag = int(r["away_goals"])
        b5_crps[i] = (crps(pmf(r["mu_h_b5"]), hg) + crps(pmf(r["mu_a_b5"]), ag)) / 2
        st_crps[i] = (crps(pmf(r["mu_h_st"]), hg) + crps(pmf(r["mu_a_st"]), ag)) / 2

    results = {}
    for key, a, b in [("brier", b5_brier, st_brier),
                      ("log_loss", b5_ll, st_ll),
                      ("crps", b5_crps, st_crps)]:
        delta = a - b
        rng = np.random.default_rng(SEED)
        boots = np.empty(N_BOOT)
        for it in range(N_BOOT):
            idx = rng.integers(0, n, n)
            boots[it] = delta[idx].mean()
        results[key] = {
            "b5": float(a.mean()), "st": float(b.mean()),
            "delta_b5_minus_st": float(delta.mean()),
            "ci95_low": float(np.quantile(boots, 0.025)),
            "ci95_high": float(np.quantile(boots, 0.975)),
            "n": n,
        }

    all_match = True
    for key in results:
        r = results[key]; p = published[key]
        fields = ("b5", "st", "delta_b5_minus_st", "ci95_low", "ci95_high")
        diffs = {kk: abs(r[kk] - p[kk]) for kk in fields}
        match = all(d <= 1e-9 for d in diffs.values())
        all_match = all_match and match
        print(f"\n{key}: {'MATCH' if match else 'MISMATCH'}")
        for kk in fields:
            print(f"  {kk:>20}: recomputed={r[kk]:.15f} published={p[kk]:.15f} absdiff={diffs[kk]:.2e}")

    # per-season weighted means reproduce the pooled values (manager's own check)
    by_season = {}
    for r in rows:
        by_season.setdefault(r["season"], []).append(r)
    pooled_b5 = sum(len(v) * np.mean([(float(x["p_b5"]) - int(x["home_win"])) ** 2 for x in v])
                    for v in by_season.values()) / n
    print(f"\nper-season weighted Brier b5 = {pooled_b5:.15f} vs pooled {results['brier']['b5']:.15f} "
          f"absdiff={abs(pooled_b5 - results['brier']['b5']):.2e}")

    print("\nREPRODUCTION:", "PASS" if all_match else "FAIL")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
