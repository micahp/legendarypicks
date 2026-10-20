#!/usr/bin/env python3
"""fbs_phase3_increment.py -- test increment (b) against the G2 baseline, exactly as pre-registered.

Protocol (see research/fbs/PHASE3-LADDER-20261018.md):
  * population, embargo and walk-forward are the Phase 1 harness's own (imported read-only);
  * B1 = G2 + intercept (recalibration control), B2 = G2 + intercept + four differences;
  * logistic fit with the G2 logit as a fixed offset, ridge 1.0 on the coefficients;
  * headlines: paired Brier on the 2023-2025 walk-forward, the 2025 frozen holdout, and 2026 as
    development evidence, with 95% season-stratified UTC-week block bootstrap intervals.

The harness is never modified: this script imports it from /root/lp-fbs-audit/backend.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment.py
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/lp-fbs-audit/backend")
import fbs_game_winner_baseline as base  # noqa: E402  (read-only import of the Phase 1 harness)

FEATURES = ["epa_diff", "success_diff", "explosive_diff", "tempo_diff"]
RIDGE = 1.0
MIN_TRAIN_GAMES = 200
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261017


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def fit_offset_logistic(X, y, offset, ridge=RIDGE):
    """Minimise penalised NLL for sigmoid(offset + X b). Column 0 of X is the intercept."""
    from scipy.optimize import minimize

    def nll(b):
        eta = offset + X @ b
        p = sigmoid(eta)
        eps = 1e-9
        loss = -np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        penalty = ridge * np.sum(b[1:] ** 2)
        grad = X.T @ (p - y)
        grad[1:] += 2 * ridge * b[1:]
        return loss + penalty, grad

    res = minimize(nll, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B")
    return res.x


def walk_forward(frame, feature_cols, start_season=2023, min_train=MIN_TRAIN_GAMES):
    """Refit at every date block on strictly earlier games; return per-game predictions."""
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)
    frame["block"] = frame["season"].astype(str) + "-" + frame["utc_date"].astype(str)
    preds = np.full(len(frame), np.nan)
    preds_b1 = np.full(len(frame), np.nan)
    n_train_used = np.zeros(len(frame), dtype=int)
    for block_start, idx in frame.groupby("block", sort=True).groups.items():
        block_idx = np.asarray(idx)
        cutoff = frame.loc[block_idx, "utc_date"].min()
        past = frame["utc_date"] < cutoff
        train = frame[past].dropna(subset=["p_g2", "y"] + feature_cols)
        if len(train) < min_train:
            preds[block_idx] = frame.loc[block_idx, "p_g2"].to_numpy()
            preds_b1[block_idx] = frame.loc[block_idx, "p_g2"].to_numpy()
            continue
        mu = train[feature_cols].mean()
        sd = train[feature_cols].std().replace(0, 1.0)
        X_train = np.column_stack([np.ones(len(train))] +
                                  [((train[c] - mu[c]) / sd[c]).to_numpy() for c in feature_cols])
        y_train = train["y"].to_numpy(dtype=float)
        offset_train = logit(train["p_g2"].to_numpy())
        b2 = fit_offset_logistic(X_train, y_train, offset_train)
        b1 = fit_offset_logistic(X_train[:, :1], y_train, offset_train)
        block = frame.loc[block_idx]
        X_block = np.column_stack([np.ones(len(block))] +
                                  [((block[c] - mu[c]) / sd[c]).to_numpy() for c in feature_cols])
        offset_block = logit(block["p_g2"].to_numpy())
        preds[block_idx] = sigmoid(offset_block + X_block @ b2)
        preds_b1[block_idx] = sigmoid(offset_block + X_block[:, :1] @ b1)
        n_train_used[block_idx] = len(train)
    frame["p_b2"] = preds
    frame["p_b1"] = preds_b1
    frame["n_train"] = n_train_used
    return frame


def frozen_holdout(frame, feature_cols, holdout_ledger=None, holdout_season=2025):
    """Fit through the end of the prior season only, forecast the holdout season.

    The holdout baseline must be the harness's FROZEN G2 (Elo not updated inside 2025), otherwise
    the baseline would be scored with same-season information that B1/B2 never see.
    """
    train = frame[(frame.season < holdout_season)].dropna(subset=["p_g2", "y"] + feature_cols)
    test = frame[frame.season == holdout_season].copy()
    if holdout_ledger is not None:
        test = test.drop(columns=[c for c in ("p_g2", "elo_home_prob") if c in test.columns])
        test = test.merge(holdout_ledger, on="game_id", how="inner")
        test = test.rename(columns={"elo_home_prob": "p_g2"})
    mu = train[feature_cols].mean()
    sd = train[feature_cols].std().replace(0, 1.0)
    X_train = np.column_stack([np.ones(len(train))] +
                              [((train[c] - mu[c]) / sd[c]).to_numpy() for c in feature_cols])
    y_train = train["y"].to_numpy(dtype=float)
    offset_train = logit(train["p_g2"].to_numpy())
    b2 = fit_offset_logistic(X_train, y_train, offset_train)
    b1 = fit_offset_logistic(X_train[:, :1], y_train, offset_train)
    X_test = np.column_stack([np.ones(len(test))] +
                             [((test[c] - mu[c]) / sd[c]).to_numpy() for c in feature_cols])
    offset_test = logit(test["p_g2"].to_numpy())
    test["p_b2"] = sigmoid(offset_test + X_test @ b2)
    test["p_b1"] = sigmoid(offset_test + X_test[:, :1] @ b1)
    return test, {"b2": b2, "b1": b1, "n_train": len(train)}


def metrics(df, column, target="y"):
    d = df.dropna(subset=[column, target])
    p = d[column].to_numpy(dtype=float)
    y = d[target].to_numpy(dtype=float)
    eps = 1e-9
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
    bins = np.clip((p * 10).astype(int), 0, 9)
    rel = res = 0.0
    base_rate = float(y.mean())
    for b in range(10):
        m = bins == b
        if not m.any():
            continue
        rel += m.mean() * (p[m].mean() - y[m].mean()) ** 2
        res += m.mean() * (y[m].mean() - base_rate) ** 2
    return {"games": int(len(d)), "brier": brier, "brier_skill_vs_coinflip": 1 - brier / 0.25,
            "log_loss": logloss, "reliability_10bin": rel, "resolution_10bin": res,
            "accuracy": float(np.mean((p > 0.5) == (y > 0.5)))}


def paired_bootstrap(df, col_a, col_b, target="y", reps=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED):
    """95% percentile interval for mean(sq_err_a - sq_err_b), season-stratified week blocks."""
    d = df.dropna(subset=[col_a, col_b, target]).copy()
    d["diff"] = (d[col_a] - d[target]) ** 2 - (d[col_b] - d[target]) ** 2
    d["block"] = d["season"].astype(str) + "-" + d["week_start"].astype(str)
    rng = np.random.default_rng(seed)
    per_season = []
    for season, season_df in d.groupby("season"):
        blocks = [g["diff"].to_numpy() for _, g in season_df.groupby("block")]
        per_season.append((season, blocks))
    stats = np.empty(reps)
    for r in range(reps):
        pooled = []
        for season, blocks in per_season:
            pick = rng.integers(0, len(blocks), len(blocks))
            pooled.append(np.concatenate([blocks[i] for i in pick]))
        stats[r] = np.concatenate(pooled).mean()
    point = float(d["diff"].mean())
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return {"diff": point, "lo": float(lo), "hi": float(hi), "n": int(len(d)),
            "blocks": int(d["block"].nunique())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet",
                    help="Phase 1 inputs (read-only)")
    ap.add_argument("--features", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3"))
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    seasons = [int(s) for s in a.seasons.split(",")]

    print("loading Phase 1 events and reproducing G2 ...")
    events, coverage, _, _ = base.load_events(a.data_dir, seasons)
    forecasts = base.make_predictions(events, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)

    reference_path = os.path.join("research", "fbs", "phase3-baseline",
                                  "fbs_game_winner_predictions_20261018.csv")
    if os.path.exists(reference_path):
        ref = pd.read_csv(reference_path, usecols=["game_id", "elo_home_prob"])
        ref["game_id"] = ref["game_id"].astype(str)
        check = forecasts.merge(ref, on="game_id", suffixes=("", "_ref"))
        gap = float((check["elo_home_prob"] - check["elo_home_prob_ref"]).abs().max())
        print("  max |G2 - reference G2| on %d shared games: %.2e" % (len(check), gap))
        if gap > 1e-9:
            raise SystemExit("reproduced G2 does not match the Phase 1 ledger")

    frame = forecasts.rename(columns={"home_win": "y"})
    frame["y"] = frame["y"].astype(float)
    frame["p_g2"] = frame["elo_home_prob"]
    frame["utc_date"] = pd.to_datetime(frame["utc_date"])
    if "week_start_utc" in frame.columns:
        frame["week_start"] = pd.to_datetime(frame["week_start_utc"]).dt.date
    else:
        frame["week_start"] = (frame["utc_date"] - pd.to_timedelta(
            frame["utc_date"].dt.weekday, unit="D")).dt.date
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)

    feats = pd.read_csv(a.features, dtype={"game_id": str})
    before = len(frame)
    frame = frame.merge(feats, on="game_id", how="left")
    joined = frame[FEATURES].notna().all(axis=1).sum()
    print("features joined: %d of %d games (%.1f%%)" % (joined, before, 100 * joined / before))
    frame = frame[frame[FEATURES].notna().all(axis=1)].reset_index(drop=True)

    print("walk-forward fit ...")
    wf = walk_forward(frame, FEATURES, start_season=2023)
    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = None
    if os.path.exists(ledger_path):
        ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
        ledger["game_id"] = ledger["game_id"].astype(str)
    holdout, holdout_params = frozen_holdout(frame, FEATURES, holdout_ledger=ledger, holdout_season=2025)
    print("  frozen holdout trained on %d games" % holdout_params["n_train"])
    print("  B2 coefficients (intercept + %s): %s" % (", ".join(FEATURES),
                                                       np.round(holdout_params["b2"], 4).tolist()))

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": holdout,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    for name, data in periods.items():
        for model, col in (("G2", "p_g2"), ("B1 G2+intercept", "p_b1"), ("B2 G2+features", "p_b2")):
            if col not in data:
                continue
            m = metrics(data, col)
            rows.append({"period": name, "model": model, **m})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    paired_rows = []
    for name, data in periods.items():
        for label, a_col, b_col in (("B1 - G2", "p_b1", "p_g2"), ("B2 - G2", "p_b2", "p_g2"),
                                    ("B2 - B1", "p_b2", "p_b1")):
            if a_col not in data or b_col not in data:
                continue
            r = paired_bootstrap(data, a_col, b_col)
            paired_rows.append({"period": name, "comparison": label, **r})
    paired_df = pd.DataFrame(paired_rows)
    paired_df.to_csv(os.path.join(a.out_dir, "paired.csv"), index=False)

    wf.to_csv(os.path.join(a.out_dir, "forecasts_walk_forward.csv"), index=False)
    holdout.to_csv(os.path.join(a.out_dir, "forecasts_holdout_2025.csv"), index=False)

    print("\nmetrics")
    print(metrics_df.to_string(index=False, float_format=lambda v: "%.4f" % v))
    print("\npaired differences (Brier; negative favours the first model)")
    print(paired_df.to_string(index=False, float_format=lambda v: "%.5f" % v))

    # gates
    pooled = paired_df[(paired_df.period == "walk-forward 2023-2025")]
    hold = paired_df[(paired_df.period == "2025 frozen holdout")]
    def get(df, label):
        row = df[df.comparison == label]
        return None if row.empty else row.iloc[0]
    g_b2 = get(pooled, "B2 - G2")
    g_b1 = get(pooled, "B2 - B1")
    h_b2 = get(hold, "B2 - G2")
    m_wf = metrics_df[metrics_df.period == "walk-forward 2023-2025"].set_index("model")
    m_h = metrics_df[metrics_df.period == "2025 frozen holdout"].set_index("model")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["B2 G2+features", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["B2 G2+features", "games"] >= 250),
        "primary_b2_beats_g2": bool(g_b2 is not None and g_b2.hi < 0),
        "information_b2_beats_b1": bool(g_b1 is not None and g_b1.hi < 0),
        "holdout_not_worse_than_+0.002": bool(h_b2 is not None and h_b2["diff"] <= 0.002),
        "holdout_point_negative": bool(h_b2 is not None and h_b2["diff"] < 0),
        "logloss_same_sign_pooled": bool(
            m_wf.loc["B2 G2+features", "log_loss"] <= m_wf.loc["G2", "log_loss"]),
        "logloss_same_sign_holdout": bool(
            m_h.loc["B2 G2+features", "log_loss"] <= m_h.loc["G2", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["B2 G2+features", "reliability_10bin"]
            <= m_wf.loc["G2", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["B2 G2+features", "reliability_10bin"]
            <= m_h.loc["G2", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\nVERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
