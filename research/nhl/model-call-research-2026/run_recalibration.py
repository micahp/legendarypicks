#!/usr/bin/env python3
"""Cover-probability recalibration prototype.

Addresses the urgent audit finding (report section 1.7): every frozen model
variant overestimates +1.5 cover probability by 11-14 percentage points and
loses to a constant base-rate predictor on cover Brier. This script fits
leak-safe recalibration maps (logistic and isotonic) on prior seasons only and
evaluates the recalibrated probabilities against:
  - the raw (uncalibrated) model probabilities,
  - a constant base-rate predictor,
  - the tiered policy with the new calibrated cover gate (replacing the
    legacy S > 1.0 spread-gap trigger, which is retired per section 1.5).

Everything is chronological: the recalibration map for a given evaluation
season is fit only on strictly earlier seasons. Frozen model forecasts, ledgers,
and grading provenance are untouched; this is research-stack only.

Outputs (results/):
  recalibration_metrics.json  per-season Brier/log-loss/calibration for raw vs
                              recalibrated vs base-rate cover probabilities
  recalibration_gate.json     tiered-policy accuracy with the calibrated gate
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

import run_backtest as rb

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_table(p: np.ndarray, y: np.ndarray, bins=10) -> list[dict]:
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append({"bin": b / bins, "n": int(m.sum()),
                        "mean_pred": float(p[m].mean()),
                        "mean_obs": float(y[m].mean())})
    return out


def raw_eval_rows(model: str, games: list[dict], elo: dict, cache: dict) -> list[dict]:
    """Per-game raw cover probabilities from the per-season frozen betas.

    The recalibration target is the *puck-line* market: y_away_cover = 1 when
    the away side covers +1.5 (statistical margin <= 1), which equals the
    standard book convention because a statistical tie covers +1.5 and never
    covers -1.5.
    """
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
                "p_away_cover": d["p_away_cover"],
                "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                "p_home_cover": d["p_home_cover"],
                "y_home_cover": int(g["hg"] - g["ag"] >= 2),
                "p_home_win": d["p_home_win"], "y_home_win": g["hw"],
                "mu_home": mh, "mu_away": ma,
            })
    return rows


def fit_maps(rows: list[dict], method: str) -> object:
    """Fit a recalibration map on (raw cover prob, actual outcome) pairs."""
    p = np.array([r["p_away_cover"] for r in rows])
    y = np.array([r["y_away_cover"] for r in rows])
    if method == "logistic":
        # 2-feature logistic with an intercept: maps raw p monotonically.
        mdl = LogisticRegression(C=1e6).fit(p.reshape(-1, 1), y)
        return ("logistic", mdl)
    if method == "isotonic":
        mdl = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98)
        mdl.fit(p, y)
        return ("isotonic", mdl)
    raise ValueError(method)


def apply_map(map_obj, p: np.ndarray) -> np.ndarray:
    kind, mdl = map_obj
    if kind == "logistic":
        return mdl.predict_proba(p.reshape(-1, 1))[:, 1]
    return mdl.predict(p)


def main() -> None:
    t0 = time.time()
    RESULTS.mkdir(exist_ok=True)
    games = rb.load_games()
    elo = rb.elo_replay(games)
    cache = json.load(open(RESULTS / "fit_cache.json"))
    print(f"loaded {len(games)} games at {time.time()-t0:.0f}s", flush=True)

    all_rows = {m: raw_eval_rows(m, games, elo, cache) for m in rb.MODELS}
    print(f"raw eval rows done at {time.time()-t0:.0f}s", flush=True)

    # --- chronological recalibration, expanding window ---
    metrics = {}
    for model, rows in all_rows.items():
        # both sides: recalibrate away-cover and (1 - away-cover) for home cover
        per_season = {}
        for season in rb.EVAL_SEASONS:
            past = [r for r in rows if r["season"] < season]
            cur = [r for r in rows if r["season"] == season]
            if len(past) < 300:
                per_season[season] = {"n": len(cur), "method": "none"}
                continue
            # fit both maps on prior seasons only
            maps = {meth: fit_maps(past, meth) for meth in ("logistic", "isotonic")}
            p_raw = np.array([r["p_away_cover"] for r in cur])
            y = np.array([r["y_away_cover"] for r in cur])
            p_lr = apply_map(maps["logistic"], p_raw)
            p_iso = apply_map(maps["isotonic"], p_raw)
            base = float(np.mean([r["y_away_cover"] for r in past]))
            per_season[season] = {
                "n": len(cur), "method": "both",
                "train_n": len(past),
                "base_rate_train": base,
                "raw_brier": brier(p_raw, y), "raw_logloss": logloss(p_raw, y),
                "logistic_brier": brier(p_lr, y), "logistic_logloss": logloss(p_lr, y),
                "isotonic_brier": brier(p_iso, y), "isotonic_logloss": logloss(p_iso, y),
                "base_brier": brier(np.full(len(y), base), y),
                "raw_calibration": calibration_table(p_raw, y, 5),
                "logistic_calibration": calibration_table(p_lr, y, 5),
            }
        metrics[model] = {
            "aggregate_n": sum(s.get("n", 0) for s in per_season.values()),
            "per_season": {str(k): v for k, v in sorted(per_season.items())},
            "mean_raw_brier": float(np.mean([s["raw_brier"] for s in per_season.values() if "raw_brier" in s])),
            "mean_logistic_brier": float(np.mean([s["logistic_brier"] for s in per_season.values() if "logistic_brier" in s])),
            "mean_isotonic_brier": float(np.mean([s["isotonic_brier"] for s in per_season.values() if "isotonic_brier" in s])),
            "mean_base_brier": float(np.mean([s["base_brier"] for s in per_season.values() if "base_brier" in s])),
        }
        print(f"  recalibration {model} done at {time.time()-t0:.0f}s", flush=True)
    (RESULTS / "recalibration_metrics.json").write_text(json.dumps(metrics, indent=1))

    # --- tiered policy with the calibrated cover gate ---
    # replaces the legacy S > 1.0 spread-gap trigger: a game's puck-line call is
    # made only when the recalibrated cover probability exceeds tau2.
    gate = {}
    for model, rows in all_rows.items():
        # expanding window: fit recalibration + choose tau2 on prior seasons only
        per_season = {}
        for season in rb.EVAL_SEASONS:
            past = [r for r in rows if r["season"] < season]
            cur = [r for r in rows if r["season"] == season]
            if len(past) < 300:
                per_season[season] = {"n": len(cur), "tau2": None, "note": "insufficient history"}
                continue
            # choose tau2 on the prior seasons: maximize accuracy with >= 10% fire rate
            p_fit = apply_map(fit_maps(past, "isotonic"),
                              np.array([r["p_away_cover"] for r in past]))
            y_fit = np.array([r["y_away_cover"] for r in past])
            best_tau, best_acc = None, -1.0
            for tau in np.arange(0.55, 0.80, 0.01):
                fired = p_fit >= tau
                if fired.mean() < 0.10:
                    break
                acc = float((p_fit >= tau).mean() and y_fit[fired].mean())
                if acc > best_acc:
                    best_acc, best_tau = y_fit[fired].mean(), float(tau)
            # apply on current season with the frozen map from prior seasons
            map_obj = fit_maps(past, "isotonic")
            p_cur = apply_map(map_obj, np.array([r["p_away_cover"] for r in cur]))
            y_cur = np.array([r["y_away_cover"] for r in cur])
            fired = p_cur >= best_tau
            per_season[season] = {
                "n": len(cur), "tau2": best_tau,
                "fire_rate": float(fired.mean()),
                "hit_rate_when_fired": float(y_cur[fired].mean()) if fired.any() else None,
                "n_fired": int(fired.sum()),
                "brier_all_games_isotonic": brier(p_cur, y_cur),
            }
        gate[model] = per_season
    (RESULTS / "recalibration_gate.json").write_text(json.dumps(gate, indent=1))
    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
