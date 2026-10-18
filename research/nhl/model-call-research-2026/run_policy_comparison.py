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
                    cover_prob_key: str) -> dict:
    """Run the tiered cascade on rows; return per-tier counts and hit rates."""
    res = {"ml": {"won": 0, "lost": 0}, "cover": {"won": 0, "lost": 0},
           "total": {"won": 0, "lost": 0}, "fallback": 0}
    for r in rows:
        p_ml = max(r["p_home_win"], 1 - r["p_home_win"])
        ml_side = "home" if r["p_home_win"] >= 0.5 else "away"
        p_cover = r[cover_prob_key]
        cover_side = "away" if cover_prob_key == "p_away_cover_rec" else "home"
        ref_total = r["mu_home"] + r["mu_away"]
        line = 5.5 if ref_total <= 6.0 else 6.5
        p_over = r["p_over_55"] if line == 5.5 else r["p_over_65_official"]

        if p_ml >= tau1:
            tier, side = "ml", ml_side
        elif p_cover >= tau2:
            tier, side = "cover", cover_side
        elif max(p_over, 1 - p_over) >= tau3:
            tier, side = "total", ("over" if p_over >= 0.5 else "under")
        else:
            res["fallback"] += 1
            continue
        if tier == "ml":
            won = (r["y_home_win"] == 1) if side == "home" else (r["y_home_win"] == 0)
        elif tier == "cover":
            if side == "away":
                won = r["y_away_cover"] == 1
            else:
                won = r["y_home_cover"] == 1
        else:  # total
            total = r["y_over55"] if line == 5.5 else r["y_over65"]
            won = (total == 1) if side == "over" else (total == 0)
        res[tier]["won" if won else "lost"] += 1
    n = sum(v if isinstance(v, int) else v["won"] + v["lost"] for v in res.values())
    return {
        "n": n, "res": res,
        "acc": (res["ml"]["won"] + res["cover"]["won"] + res["total"]["won"]) / n if n else None,
        "fallback_rate": res["fallback"] / n if n else None,
        "tier_accuracy": {
            t: res[t]["won"] / (res[t]["won"] + res[t]["lost"])
            for t in ("ml", "cover", "total")
            if (res[t]["won"] + res[t]["lost"]) > 0},
        "tier_n": {t: res[t]["won"] + res[t]["lost"] for t in ("ml", "cover", "total")},
    }


def tune_cascade(rows: list[dict], cover_prob_key: str) -> tuple[float, float, float]:
    """Grid search for tau1/tau2/tau3 on tuning rows (maximize accuracy, <=5% fallback)."""
    best = None
    for tau1 in np.arange(0.55, 0.801, 0.025):
        for tau2 in np.arange(0.55, 0.801, 0.025):
            for tau3 in np.arange(0.55, 0.801, 0.025):
                out = evaluate_policy(rows, float(tau1), float(tau2), float(tau3), cover_prob_key)
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
                    "p_over_55": d["p_over_55"],
                    "p_over_65_official": d["p_over_65_official"],
                    "y_home_win": g["hw"],
                    "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                    "y_home_cover": int(g["hg"] - g["ag"] >= 2),
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
            p_fit = np.array([r["p_away_cover"] for r in past])
            y_fit = np.array([r["y_away_cover"] for r in past])
            map_obj = fit_logistic_map(p_fit, y_fit)
            # apply to current season
            p_cur_raw = np.array([r["p_away_cover"] for r in cur])
            p_cur_rec = apply_logistic(map_obj, p_cur_raw)
            cur_rec = []
            for r, p_rec in zip(cur, p_cur_rec):
                cur_rec.append({**r, "p_away_cover_rec": float(p_rec)})
            # tune thresholds separately for raw and recalibrated on prior seasons
            past_rec = []
            p_past_rec = apply_logistic(map_obj, p_fit)
            for r, p_rec in zip(past, p_past_rec):
                past_rec.append({**r, "p_away_cover_rec": float(p_rec)})
            t_raw = tune_cascade(past, "p_away_cover")
            t_rec = tune_cascade(past_rec, "p_away_cover_rec")
            # --- simple predictive/selection baselines (prior-season prevalence) ---
            p_fit_raw = np.array([r["p_away_cover"] for r in past])
            y_fit = np.array([r["y_away_cover"] for r in past])
            base_pred = float(np.mean(y_fit))
            y_cur = np.array([r["y_away_cover"] for r in cur])
            y_hw = np.array([r["y_home_win"] for r in cur])
            p_ml = np.array([max(r["p_home_win"], 1 - r["p_home_win"]) for r in cur])
            per_season[season] = {
                "n": len(cur),
                "raw_cascade": evaluate_policy(cur, *t_raw, "p_away_cover"),
                "recalibrated_cascade": evaluate_policy(cur_rec, *t_rec, "p_away_cover_rec"),
                "always_ml": evaluate_policy(cur, 0.0, 2.0, 2.0, "p_away_cover"),
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
