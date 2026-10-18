#!/usr/bin/env python3
"""fbs_phase3_increment_e.py -- test increment (e) against C2 and G2, exactly as pre-registered.

Spec: RESULT-FBS-PHASE3-B-20261018.md §15. Same population, embargo, walk-forward, frozen 2025
holdout, metrics and week-block bootstrap as (b)–(d). Models on the identical game set:

    C2   G2 + seven drive splits                                  (standing model, refit here)
    E1   G2 + intercept                                           (recalibration control)
    E2   G2 + coach tenure, off/def returning production          (primary)
    E2+  E2 + talent composite, net transfer talent               (secondary, reported only)

Primary comparison is E2 - C2.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_e.py
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/root/lp-fbs-audit/backend")
import fbs_game_winner_baseline as base  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_increment import (  # noqa: E402
    frozen_holdout, metrics, paired_bootstrap, walk_forward)

FEATURES_C = feat_c.FEATURE_NAMES_C
FEATURES_E = ["coach_tenure_diff", "off_returning_diff", "def_returning_diff"]
FEATURES_EP = FEATURES_E + ["talent_diff", "transfer_talent_diff"]


def fit_models(frame, feature_cols, label):
    wf = walk_forward(frame, feature_cols)
    return wf.rename(columns={"p_b2": "p_" + label, "p_b1": "p_" + label + "_ctl"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet")
    ap.add_argument("--features-b", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--features-c", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    ap.add_argument("--features-e", default=os.path.join("research", "fbs", "phase3", "game_features_e.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3-e"))
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
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
    fe = pd.read_csv(a.features_e, dtype={"game_id": str}).drop(columns=["season"], errors="ignore")
    frame = frame.merge(fb[["game_id", "epa_diff"]], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + FEATURES_C], on="game_id", how="left")
    frame = frame.merge(fe, on="game_id", how="left")

    complete_c = frame[FEATURES_C].notna().all(axis=1)
    frame["has_drive_data"] = complete_c
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)
    # identical population to (b)-(d): the one game without CFBD play-by-play stays out
    population = frame["epa_diff"].notna()
    frame = frame[population].drop(columns=["epa_diff"]).reset_index(drop=True)

    for col in FEATURES_EP:
        if col not in frame.columns:
            frame[col] = 0.0
    frame[FEATURES_EP] = frame[FEATURES_EP].fillna(0.0)
    for flag in ("coach_tenure_known", "off_returning_known", "def_returning_known",
                 "talent_known", "transfer_talent_known"):
        if flag not in frame.columns:
            frame[flag] = False
        frame[flag] = frame[flag].fillna(False).astype(bool)

    eval_pop = frame[frame.season.between(2023, 2025)]
    print("population: %d games (2023-25 %d)" % (len(frame), len(eval_pop)))
    for flag in ("coach_tenure_known", "off_returning_known", "def_returning_known",
                 "talent_known", "transfer_talent_known"):
        print("  %-22s known %.3f" % (flag, eval_pop[flag].mean()))

    print("walk-forward fits ...")
    wf_c = fit_models(frame, FEATURES_C, "c2")
    wf_e2 = fit_models(frame, FEATURES_E, "e2")
    wf_ep = fit_models(frame, FEATURES_EP, "ep")
    wf = wf_e2.merge(wf_c[["game_id", "p_c2"]], on="game_id", how="inner").merge(
        wf_ep[["game_id", "p_ep"]], on="game_id", how="inner")
    wf["block"] = wf["season"].astype(str) + "-" + wf["week_start"].astype(str)

    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
    ledger["game_id"] = ledger["game_id"].astype(str)
    hold_c, _ = frozen_holdout(frame, FEATURES_C, holdout_ledger=ledger, holdout_season=2025)
    hold_e, params_e = frozen_holdout(frame, FEATURES_E, holdout_ledger=ledger, holdout_season=2025)
    hold_ep, _ = frozen_holdout(frame, FEATURES_EP, holdout_ledger=ledger, holdout_season=2025)
    hold_c = hold_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})
    hold_e = hold_e.rename(columns={"p_b2": "p_e2", "p_b1": "p_e2_ctl"})
    hold_ep = hold_ep.rename(columns={"p_b2": "p_ep", "p_b1": "p_ep_ctl"})
    for df in (hold_c, hold_e, hold_ep):
        df["game_id"] = df["game_id"].astype(str)
    hold = hold_e.merge(hold_c[["game_id", "p_c2"]], on="game_id", how="inner").merge(
        hold_ep[["game_id", "p_ep"]], on="game_id", how="inner")
    hold["block"] = hold["season"].astype(str) + "-" + hold["week_start"].astype(str)
    print("frozen holdout trained on %d games; E2 coefficients: %s"
          % (params_e["n_train"], np.round(params_e["b2"], 4).tolist()))

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": hold,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    model_cols = (("G2", "p_g2"), ("C2 G2+drive splits", "p_c2"), ("E1 G2+intercept", "p_e2_ctl"),
                  ("E2 G2+coach/returning", "p_e2"), ("E2+ +talent/portal", "p_ep"))
    for name, data in periods.items():
        for model, col in model_cols:
            if col in data:
                rows.append({"period": name, "model": model, **metrics(data, col)})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    comparisons = (("E2 - C2", "p_e2", "p_c2"), ("E2 - G2", "p_e2", "p_g2"),
                   ("E2 - E1", "p_e2", "p_e2_ctl"), ("E2+ - C2", "p_ep", "p_c2"),
                   ("C2 - G2", "p_c2", "p_g2"))
    paired_rows = []
    for name, data in periods.items():
        for label, a_col, b_col in comparisons:
            if a_col in data and b_col in data:
                paired_rows.append({"period": name, "comparison": label,
                                    **paired_bootstrap(data, a_col, b_col)})
    paired_df = pd.DataFrame(paired_rows)
    paired_df.to_csv(os.path.join(a.out_dir, "paired.csv"), index=False)
    wf.to_csv(os.path.join(a.out_dir, "forecasts_walk_forward.csv"), index=False)
    hold.to_csv(os.path.join(a.out_dir, "forecasts_holdout_2025.csv"), index=False)

    print("\nmetrics")
    print(metrics_df.to_string(index=False, float_format=lambda v: "%.4f" % v))
    print("\npaired differences (Brier; negative favours the first model)")
    print(paired_df.to_string(index=False, float_format=lambda v: "%.5f" % v))

    def get(period, label):
        row = paired_df[(paired_df.period == period) & (paired_df.comparison == label)]
        return None if row.empty else row.iloc[0]

    m_wf = metrics_df[metrics_df.period == "walk-forward 2023-2025"].set_index("model")
    m_h = metrics_df[metrics_df.period == "2025 frozen holdout"].set_index("model")
    primary = get("walk-forward 2023-2025", "E2 - C2")
    info = get("walk-forward 2023-2025", "E2 - E1")
    hold_cmp = get("2025 frozen holdout", "E2 - C2")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["E2 G2+coach/returning", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["E2 G2+coach/returning", "games"] >= 250),
        "primary_e2_beats_c2": bool(primary is not None and primary.hi < 0),
        "information_e2_beats_e1": bool(info is not None and info.hi < 0),
        "holdout_e2_not_worse_than_+0.002": bool(hold_cmp is not None and hold_cmp["diff"] <= 0.002),
        "holdout_e2_point_negative": bool(hold_cmp is not None and hold_cmp["diff"] < 0),
        "logloss_pooled_vs_c2": bool(m_wf.loc["E2 G2+coach/returning", "log_loss"]
                                     <= m_wf.loc["C2 G2+drive splits", "log_loss"]),
        "logloss_holdout_vs_c2": bool(m_h.loc["E2 G2+coach/returning", "log_loss"]
                                      <= m_h.loc["C2 G2+drive splits", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["E2 G2+coach/returning", "reliability_10bin"]
            <= m_wf.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["E2 G2+coach/returning", "reliability_10bin"]
            <= m_h.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\nVERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
