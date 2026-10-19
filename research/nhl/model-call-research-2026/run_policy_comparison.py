#!/usr/bin/env python3
"""Tiered policy comparison: recalibrated tiered cascade vs baselines.

Research-stack only. Compares, on matched chronological evaluation windows:

  A. raw tiered cascade (the current run_backtest.py tier_of with raw probabilities)
  B. recalibrated tiered cascade (same thresholds, recalibrated cover probabilities)
  C. always-moneyline baseline (pick the higher-probability side)
  D. ev-max-1 style baseline (approximated: always pick the highest raw
     probability market, which is what an EV-max rule collapses to when the
     no-vig market probability is the same for all candidates on a slate)

All comparisons are expanding-window: thresholds (and the recalibration map)
are fit on prior seasons only, then applied to the held-out season. The
deliverable is a per-season accuracy table with sample sizes and hit rates by
tier, demonstrating whether the tiered hierarchy improves user-facing call
accuracy without giving up meaningful betting opportunities.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

import run_backtest as rb

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def fit_logistic_map(p: np.ndarray, y: np.ndarray):
    mdl = LogisticRegression(C=1e6).fit(p.reshape(-1, 1), y)
    return mdl


def apply_logistic(mdl, p: np.ndarray) -> np.ndarray:
    return mdl.predict_proba(p.reshape(-1, 1))[:, 1]


def evaluate_policy(rows: list[dict], tau1: float, tau2: float, tau3: float,
                    cover_overrides: dict | None = None) -> dict:
    """Run the corrected tiered cascade (run_backtest.tier_of) on rows.

    tier_of picks a confident +1.5 prediction on the UNDERDOG (away +1.5 when
    the model favours home, home +1.5 when it favours away). Reporting is by
    SELECTION FREQUENCY per tier, with hit rate / Brier / n per tier, never by
    won/lost counts alone.
    """
    sel = Counter()
    hit = Counter()
    tier_p = defaultdict(list)
    tier_y = defaultdict(list)
    for r in rows:
        p = dict(r)
        p["p_away_win"] = 1.0 - r["p_home_win"]
        if cover_overrides:
            p.update(cover_overrides(r))
        tier, side, prob, _market = rb.tier_of(
            p, tau1, tau2, tau3, r["mu_home"] + r["mu_away"])
        sel[tier] += 1
        if tier == "fallback":
            continue
        if tier == "ml":
            y = r["y_home_win"] if side == "home" else 1 - r["y_home_win"]
        elif tier == "cover":
            y = r["y_away_cover"] if side == "away" else r["y_home_cover_plus"]
        else:  # total
            line = 5.5 if (r["mu_home"] + r["mu_away"]) <= 6.0 else 6.5
            y = r["y_over55"] if line == 5.5 else r["y_over65"]
            if side == "under":
                y = 1 - y
        hit[tier] += int(y)
        tier_p[tier].append(float(prob))
        tier_y[tier].append(int(y))

    n = sum(sel.values())
    decided = n - sel["fallback"]
    tiers = {}
    for t in ("ml", "cover", "total"):
        k = sel[t]
        if not k:
            continue
        tiers[t] = {
            "frequency": k / n if n else None,
            "n_games": k,
            "hit_rate": hit[t] / k,
            "brier": brier(np.array(tier_p[t]), np.array(tier_y[t])),
            "mean_prob": float(np.mean(tier_p[t])),
        }
    return {
        "n": n,
        "tier_usage": {t: (sel[t] / n if n else None)
                       for t in ("ml", "cover", "total", "fallback")},
        "tier_counts": {t: sel[t] for t in ("ml", "cover", "total", "fallback")},
        "tiers": tiers,
        "acc": (hit["ml"] + hit["cover"] + hit["total"]) / decided if decided else None,
        "coverage": decided / n if n else None,
        "fallback_rate": sel["fallback"] / n if n else None,
    }


def tune_cascade(rows: list[dict], cover_overrides: dict | None = None) -> tuple[float, float, float]:
    """Grid search for tau1/tau2/tau3 on tuning rows (maximize accuracy, <=5% fallback)."""
    best = None
    for tau1 in np.arange(0.55, 0.801, 0.025):
        for tau2 in np.arange(0.55, 0.801, 0.025):
            for tau3 in np.arange(0.55, 0.801, 0.025):
                out = evaluate_policy(rows, float(tau1), float(tau2), float(tau3), cover_overrides)
                if out["fallback_rate"] is None or out["fallback_rate"] > 0.05:
                    continue
                if best is None or out["acc"] > best[0]:
                    best = (out["acc"], (float(tau1), float(tau2), float(tau3)))
    return best[1] if best else (0.60, 0.55, 0.55)


def main() -> None:
    t0 = time.time()
    RESULTS.mkdir(exist_ok=True)
    games = rb.load_games()
    elo = rb.elo_replay(games)
    cache = json.load(open(RESULTS / "fit_cache.json"))
    print(f"loaded {len(games)} games at {time.time()-t0:.0f}s", flush=True)

    # Build evaluation rows per model (raw probabilities only; recalibration
    # is applied season-by-season from prior seasons).
    rows_by_model = {}
    for model in rb.MODELS:
        rows = []
        for season in rb.EVAL_SEASONS:
            evalg = [g for g in games if g["season"] == season]
            mus = rb.predict_mus(evalg, model, elo, cache[str(season)][model])
            train_so = rb.so_rate([g for g in games if g["season"] < season])
            for g in evalg:
                mh, ma = mus[g["game_id"]]
                m = rb.joint(rb.pmf_rows(np.array([mh])), rb.pmf_rows(np.array([ma])))
                d = rb.derive(m, train_so)
                rows.append({
                    "game_id": g["game_id"], "season": season,
                    "p_home_win": d["p_home_win"],
                    "p_away_cover": d["p_away_cover"],
                    "p_home_cover": d["p_home_cover"],
                    "p_home_cover_plus": d["p_home_cover_plus"],
                    "p_over_55": d["p_over_55"],
                    "p_over_65_official": d["p_over_65_official"],
                    "y_home_win": g["hw"],
                    "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                    "y_home_cover": int(g["hg"] - g["ag"] >= 2),
                    "y_home_cover_plus": int(g["hg"] - g["ag"] >= -1),
                    "y_over55": int(g["ohg"] + g["oag"] > 5.5),
                    "y_over65": int(g["ohg"] + g["oag"] > 6.5),
                    "mu_home": mh, "mu_away": ma,
                })
        rows_by_model[model] = rows
        print(f"  built raw rows {model} at {time.time()-t0:.0f}s", flush=True)

    # expanding-window: for each season, fit recalibration + tune thresholds on
    # prior seasons, then evaluate on the held-out season.
    out = {}
    for model, rows in rows_by_model.items():
        per_season = {}
        for season in rb.EVAL_SEASONS:
            past = [r for r in rows if r["season"] < season]
            cur = [r for r in rows if r["season"] == season]
            if len(past) < 300:
                continue
            # fit a recalibration map on prior seasons' away-cover probability
            # Recalibrate BOTH underdog-cover events on prior seasons only.
            map_away = fit_logistic_map(np.array([r["p_away_cover"] for r in past]),
                                        np.array([r["y_away_cover"] for r in past]))
            map_home = fit_logistic_map(np.array([r["p_home_cover_plus"] for r in past]),
                                        np.array([r["y_home_cover_plus"] for r in past]))

            def rec_rows(rs):
                """Copy rows with both cover probabilities recalibrated."""
                pa = apply_logistic(map_away, np.array([r["p_away_cover"] for r in rs]))
                ph = apply_logistic(map_home, np.array([r["p_home_cover_plus"] for r in rs]))
                return [{**r, "p_away_cover": float(a), "p_home_cover_plus": float(h)}
                        for r, a, h in zip(rs, pa, ph)]

            t_raw = tune_cascade(past)
            t_rec = tune_cascade(rec_rows(past))
            # --- simple predictive/selection baselines (prior-season prevalence) ---
            y_fit = np.array([r["y_away_cover"] for r in past])
            base_pred = float(np.mean(y_fit))
            y_cur = np.array([r["y_away_cover"] for r in cur])
            y_hw = np.array([r["y_home_win"] for r in cur])
            p_ml = np.array([max(r["p_home_win"], 1 - r["p_home_win"]) for r in cur])
            per_season[season] = {
                "n": len(cur),
                "raw_cascade": evaluate_policy(cur, *t_raw),
                "recalibrated_cascade": evaluate_policy(rec_rows(cur), *t_rec),
                "always_ml": evaluate_policy(cur, 0.0, 2.0, 2.0),
                # requested simple rules:
                # 1. always select away +1.5 (hit rate + constant-pred Brier)
                "always_away_cover_hit_rate": float(y_cur.mean()),
                "always_away_cover_brier": brier(np.full(len(y_cur), base_pred), y_cur),
                # 2. prior-season constant cover rate as a predictive baseline
                "base_constant_cover_pred": base_pred,
                "base_constant_cover_brier": brier(np.full(len(y_cur), base_pred), y_cur),
                # 3. always select the higher-probability moneyline side
                "always_ml_hit_rate": float(np.mean([r["y_home_win"] if r["p_home_win"] >= 0.5
                                                     else 1 - r["y_home_win"] for r in cur])),
                "always_ml_brier": brier(p_ml, y_hw),
                "thresholds_raw": t_raw, "thresholds_rec": t_rec,
            }
        out[model] = per_season
        print(f"  policy comparison {model} done at {time.time()-t0:.0f}s", flush=True)

    (RESULTS / "policy_comparison.json").write_text(json.dumps(out, indent=1))
    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
