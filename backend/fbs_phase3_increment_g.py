#!/usr/bin/env python3
"""fbs_phase3_increment_g.py -- test increment (g) against C2, exactly as pre-registered.

Spec: RESULT-FBS-PHASE3-B-20261018.md §19. Same population, embargo, walk-forward, frozen 2025
holdout, metrics and week-block bootstrap as (b)–(f). Models on the identical game set:

    C2   flat ridge logistic on G2 + seven drive splits      (standing model, refit here)
    G1   hierarchy on the G2 offset only                     (no-features control)
    G2h  hierarchy + the seven drive splits                  (primary)

Primary comparison is G2h - C2; information gate is G2h - G1.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_g.py
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_g.py \
      --lam-team 4.0 --out-dir research/fbs/phase3-g/lam4
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/root/lp-fbs-audit/backend")
import fbs_game_winner_baseline as base  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_hierarchical import HierarchicalLogistic  # noqa: E402
from fbs_phase3_increment import (  # noqa: E402
    MIN_TRAIN_GAMES, frozen_holdout, logit, metrics, paired_bootstrap, sigmoid, walk_forward)

FEATURES_C = feat_c.FEATURE_NAMES_C
LAM_TEAM = 9.0
LAM_CONF = 156.0
RIDGE = 1.0


def hierarchical_walk_forward(frame, feature_cols, lam_team, lam_conf, start_season=2023,
                              min_train=MIN_TRAIN_GAMES):
    """Refit at every date block on strictly earlier games, exactly like walk_forward()."""
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)
    frame["block"] = frame["season"].astype(str) + "-" + frame["utc_date"].astype(str)
    preds = np.full(len(frame), np.nan)
    diags = []
    for block_start, idx in frame.groupby("block", sort=True).groups.items():
        block_idx = np.asarray(idx)
        cutoff = frame.loc[block_idx, "utc_date"].min()
        train = frame[frame["utc_date"] < cutoff].dropna(subset=["p_g2", "y"] + feature_cols)
        if len(train) < min_train:
            preds[block_idx] = frame.loc[block_idx, "p_g2"].to_numpy()
            continue
        model = HierarchicalLogistic(lam_team=lam_team, lam_conf=lam_conf, ridge=RIDGE)
        model.fit(train, feature_cols)
        if not model.converged:
            raise RuntimeError("hierarchical fit failed to converge: block %s, grad %.3e, iter %d"
                               % (block_start, model.grad_norm, model.n_iter))
        preds[block_idx] = model.predict(frame.loc[block_idx])
        d = model.diagnostics()
        d["block"] = block_start
        d["n_train"] = len(train)
        d["n_test"] = len(block_idx)
        diags.append(d)
    frame["p_h"] = preds
    frame["n_train"] = np.nan
    return frame, diags


def hierarchical_holdout(frame, feature_cols, lam_team, lam_conf, holdout_ledger, holdout_season=2025):
    train = frame[frame.season < holdout_season].dropna(subset=["p_g2", "y"] + feature_cols)
    test = frame[frame.season == holdout_season].copy()
    test = test.drop(columns=[c for c in ("p_g2", "elo_home_prob") if c in test.columns])
    test = test.merge(holdout_ledger, on="game_id", how="inner")
    test = test.rename(columns={"elo_home_prob": "p_g2"})
    model = HierarchicalLogistic(lam_team=lam_team, lam_conf=lam_conf, ridge=RIDGE)
    model.fit(train, feature_cols)
    if not model.converged:
        raise RuntimeError("holdout fit failed to converge: grad %.3e" % model.grad_norm)
    test["p_h"] = model.predict(test)
    return test, model, {"n_train": len(train), **model.diagnostics()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet")
    ap.add_argument("--features-b", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--features-c", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3-g"))
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    ap.add_argument("--lam-team", type=float, default=LAM_TEAM)
    ap.add_argument("--lam-conf", type=float, default=LAM_CONF)
    ap.add_argument("--primary", action="store_true", help="score the gate table (frozen run only)")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    seasons = [int(s) for s in a.seasons.split(",")]

    print("loading Phase 1 events and reproducing G2 ...")
    events, _, _, _ = base.load_events(a.data_dir, seasons)
    forecasts = base.make_predictions(events, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    frame = forecasts.rename(columns={"home_win": "y"})
    frame["y"] = frame["y"].astype(float)
    frame["p_g2"] = frame["elo_home_prob"]
    frame["utc_date"] = pd.to_datetime(frame["utc_date"])
    frame["week_start"] = (frame["utc_date"] - pd.to_timedelta(
        frame["utc_date"].dt.weekday, unit="D")).dt.date
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)

    fb = pd.read_csv(a.features_b, dtype={"game_id": str})
    fc = pd.read_csv(a.features_c, dtype={"game_id": str})
    frame = frame.merge(fb[["game_id", "epa_diff"]], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + FEATURES_C], on="game_id", how="left")

    frame["has_drive_data"] = frame[FEATURES_C].notna().all(axis=1)
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)          # league-mean-difference fill + flag
    frame = frame[frame["epa_diff"].notna()].drop(columns=["epa_diff"]).reset_index(drop=True)
    frame["home_team_id"] = frame["home_team_id"].astype(str)
    frame["away_team_id"] = frame["away_team_id"].astype(str)

    eval_pop = frame[frame.season.between(2023, 2025)]
    print("population: %d games (2023-25 %d); has_drive_data %.3f"
          % (len(frame), len(eval_pop), eval_pop["has_drive_data"].mean()))
    if a.seasons == "2022,2023,2024,2025,2026":
        assert len(frame) == 3523 and len(eval_pop) == 2397, (len(frame), len(eval_pop))

    print("flat C2 walk-forward ...")
    wf_c = walk_forward(frame.copy(), FEATURES_C)
    wf_c = wf_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})

    print("hierarchy-only (G1) walk-forward, lam_team=%.1f lam_conf=%.0f ..." % (a.lam_team, a.lam_conf))
    wf_g1, diags_g1 = hierarchical_walk_forward(frame.copy(), [], a.lam_team, a.lam_conf)
    wf_g1 = wf_g1.rename(columns={"p_h": "p_g1"})

    print("hierarchy + drive splits (G2h) walk-forward ...")
    wf_g2h, diags_g2h = hierarchical_walk_forward(frame.copy(), FEATURES_C, a.lam_team, a.lam_conf)
    wf_g2h = wf_g2h.rename(columns={"p_h": "p_g2h"})

    wf = wf_c[["game_id", "season", "week_start", "y", "p_g2", "p_c2", "p_c2_ctl"]].merge(
        wf_g1[["game_id", "p_g1"]], on="game_id", how="inner").merge(
        wf_g2h[["game_id", "p_g2h"]], on="game_id", how="inner")
    wf["block"] = wf["season"].astype(str) + "-" + wf["week_start"].astype(str)

    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
    ledger["game_id"] = ledger["game_id"].astype(str)

    hold_c, _ = frozen_holdout(frame.copy(), FEATURES_C, holdout_ledger=ledger, holdout_season=2025)
    hold_c = hold_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})
    hold_g1, _, d_h1 = hierarchical_holdout(frame.copy(), [], a.lam_team, a.lam_conf, ledger)
    hold_g1 = hold_g1.rename(columns={"p_h": "p_g1"})
    hold_g2h, model_g2h, d_h2 = hierarchical_holdout(frame.copy(), FEATURES_C, a.lam_team,
                                                     a.lam_conf, ledger)
    hold_g2h = hold_g2h.rename(columns={"p_h": "p_g2h"})
    for df in (hold_c, hold_g1, hold_g2h):
        df["game_id"] = df["game_id"].astype(str)
    hold = hold_g2h[["game_id", "season", "week_start", "y", "p_g2", "p_g2h"]].merge(
        hold_c[["game_id", "p_c2"]], on="game_id", how="inner").merge(
        hold_g1[["game_id", "p_g1"]], on="game_id", how="inner")
    hold["block"] = hold["season"].astype(str) + "-" + hold["week_start"].astype(str)

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": hold,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    model_cols = (("G2", "p_g2"), ("C2 G2+drive splits", "p_c2"), ("G1 hierarchy only", "p_g1"),
                  ("G2h hierarchy+drives", "p_g2h"))
    for name, data in periods.items():
        for model, col in model_cols:
            if col in data:
                rows.append({"period": name, "model": model, **metrics(data, col)})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    comparisons = (("G2h - C2", "p_g2h", "p_c2"), ("G2h - G1", "p_g2h", "p_g1"),
                   ("G2h - G2", "p_g2h", "p_g2"), ("G1 - G2", "p_g1", "p_g2"),
                   ("C2 - G2", "p_c2", "p_g2"))
    paired_rows = []
    for name, data in periods.items():
        for label, x, y in comparisons:
            if x in data and y in data:
                paired_rows.append({"period": name, "comparison": label,
                                    **paired_bootstrap(data, x, y)})
    paired_df = pd.DataFrame(paired_rows)
    paired_df.to_csv(os.path.join(a.out_dir, "paired.csv"), index=False)
    wf.to_csv(os.path.join(a.out_dir, "forecasts_walk_forward.csv"), index=False)
    hold.to_csv(os.path.join(a.out_dir, "forecasts_holdout_2025.csv"), index=False)

    diags = {"lam_team": a.lam_team, "lam_conf": a.lam_conf, "ridge": RIDGE,
             "folds_g1": len(diags_g1), "folds_g2h": len(diags_g2h),
             "max_grad_g1": max(d["grad_norm"] for d in diags_g1),
             "max_grad_g2h": max(d["grad_norm"] for d in diags_g2h),
             "median_sd_u_g2h": float(np.median([d["sd_u"] for d in diags_g2h])),
             "median_sd_m_g2h": float(np.median([d["sd_m"] for d in diags_g2h])),
             "holdout_g2h": {k: v for k, v in d_h2.items() if k != "b"},
             "holdout_g1": {k: v for k, v in d_h1.items() if k != "b"},
             "holdout_condition_number": model_g2h.hessian_condition(
                 frame[frame.season < 2025].dropna(subset=["p_g2", "y"] + FEATURES_C)),
             "holdout_b": dict(zip(["intercept"] + FEATURES_C, [model_g2h.b0] + list(model_g2h.b)))}
    with open(os.path.join(a.out_dir, "diagnostics.json"), "w") as fh:
        json.dump(diags, fh, indent=2, default=float)

    print("\nmetrics")
    print(metrics_df.to_string(index=False, float_format=lambda v: "%.4f" % v))
    print("\npaired differences (Brier; negative favours the first model)")
    print(paired_df.to_string(index=False, float_format=lambda v: "%.5f" % v))
    print("\ndiagnostics: folds %d/%d, max|grad| %.2e/%.2e, median sd(u) %.3f, sd(m) %.3f, cond %.1e"
          % (diags["folds_g2h"], diags["folds_g1"], diags["max_grad_g2h"], diags["max_grad_g1"],
             diags["median_sd_u_g2h"], diags["median_sd_m_g2h"], diags["holdout_condition_number"]))

    if not a.primary:
        return

    def get(period, label):
        row = paired_df[(paired_df.period == period) & (paired_df.comparison == label)]
        return None if row.empty else row.iloc[0]

    m_wf = metrics_df[metrics_df.period == "walk-forward 2023-2025"].set_index("model")
    m_h = metrics_df[metrics_df.period == "2025 frozen holdout"].set_index("model")
    primary = get("walk-forward 2023-2025", "G2h - C2")
    info = get("walk-forward 2023-2025", "G2h - G1")
    hold_cmp = get("2025 frozen holdout", "G2h - C2")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["G2h hierarchy+drives", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["G2h hierarchy+drives", "games"] >= 250),
        "primary_g2h_beats_c2": bool(primary is not None and primary.hi < 0),
        "information_g2h_beats_g1": bool(info is not None and info.hi < 0),
        "holdout_not_worse_than_+0.002": bool(hold_cmp is not None and hold_cmp["diff"] <= 0.002),
        "holdout_point_negative": bool(hold_cmp is not None and hold_cmp["diff"] < 0),
        "logloss_pooled_vs_c2": bool(m_wf.loc["G2h hierarchy+drives", "log_loss"]
                                     <= m_wf.loc["C2 G2+drive splits", "log_loss"]),
        "logloss_holdout_vs_c2": bool(m_h.loc["G2h hierarchy+drives", "log_loss"]
                                      <= m_h.loc["C2 G2+drive splits", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["G2h hierarchy+drives", "reliability_10bin"]
            <= m_wf.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["G2h hierarchy+drives", "reliability_10bin"]
            <= m_h.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\npassed %d/%d" % (int(gates_df.passed.sum()), len(gates_df)))
    print("VERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
