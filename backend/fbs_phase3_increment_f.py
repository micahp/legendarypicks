#!/usr/bin/env python3
"""fbs_phase3_increment_f.py -- test increment (f) against C2 and G2, exactly as pre-registered.

Spec: RESULT-FBS-PHASE3-B-20261018.md §17. Same population, embargo, walk-forward, frozen 2025
holdout, metrics and week-block bootstrap as (b)–(e). Models on the identical game set:

    C2  G2 + seven drive splits                        (standing model, refit here)
    F1  G2 + intercept                                 (recalibration control)
    F2  G2 + four form differences                     (primary)

Primary comparison is F2 - C2. Run with --features-f pointing at the half-life 6 table for the primary
result, and at the half-life 3 / 10 tables for the pre-registered robustness check.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_f.py
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_f.py \
      --features-f research/fbs/phase3/game_features_f_hl3.csv --out-dir research/fbs/phase3-f/hl3
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
FEATURES_F = ["off_epa_form_diff", "def_epa_form_diff", "off_success_form_diff",
              "def_success_form_diff"]


def fit_models(frame, feature_cols, label):
    wf = walk_forward(frame, feature_cols)
    return wf.rename(columns={"p_b2": "p_" + label, "p_b1": "p_" + label + "_ctl"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet")
    ap.add_argument("--features-b", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--features-c", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    ap.add_argument("--features-f", default=os.path.join("research", "fbs", "phase3", "game_features_f_hl6.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3-f"))
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    ap.add_argument("--primary", action="store_true", help="score the gate table (half-life 6 run only)")
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
    ff = pd.read_csv(a.features_f, dtype={"game_id": str})
    frame = frame.merge(fb[["game_id", "epa_diff"]], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + FEATURES_C], on="game_id", how="left")
    frame = frame.merge(ff[["game_id"] + FEATURES_F + ["form_known"]], on="game_id", how="left")

    complete_c = frame[FEATURES_C].notna().all(axis=1)
    frame["has_drive_data"] = complete_c
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)
    population = frame["epa_diff"].notna()
    frame = frame[population].drop(columns=["epa_diff"]).reset_index(drop=True)
    for col in FEATURES_F:
        frame[col] = frame[col].fillna(0.0)
    frame["form_known"] = frame["form_known"].fillna(False).astype(bool)

    eval_pop = frame[frame.season.between(2023, 2025)]
    print("population: %d games (2023-25 %d); form known %.3f"
          % (len(frame), len(eval_pop), eval_pop["form_known"].mean()))

    print("walk-forward fits (%s) ..." % os.path.basename(a.features_f))
    wf_c = fit_models(frame, FEATURES_C, "c2")
    wf_f = fit_models(frame, FEATURES_F, "f2")
    wf = wf_f.merge(wf_c[["game_id", "p_c2"]], on="game_id", how="inner")
    wf["block"] = wf["season"].astype(str) + "-" + wf["week_start"].astype(str)

    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
    ledger["game_id"] = ledger["game_id"].astype(str)
    hold_c, _ = frozen_holdout(frame, FEATURES_C, holdout_ledger=ledger, holdout_season=2025)
    hold_f, params_f = frozen_holdout(frame, FEATURES_F, holdout_ledger=ledger, holdout_season=2025)
    hold_c = hold_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})
    hold_f = hold_f.rename(columns={"p_b2": "p_f2", "p_b1": "p_f2_ctl"})
    hold_c["game_id"] = hold_c["game_id"].astype(str)
    hold_f["game_id"] = hold_f["game_id"].astype(str)
    hold = hold_f.merge(hold_c[["game_id", "p_c2"]], on="game_id", how="inner")
    hold["block"] = hold["season"].astype(str) + "-" + hold["week_start"].astype(str)
    print("frozen holdout trained on %d games; F2 coefficients: %s"
          % (params_f["n_train"], np.round(params_f["b2"], 4).tolist()))

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": hold,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    model_cols = (("G2", "p_g2"), ("C2 G2+drive splits", "p_c2"), ("F1 G2+intercept", "p_f2_ctl"),
                  ("F2 G2+form", "p_f2"))
    for name, data in periods.items():
        for model, col in model_cols:
            if col in data:
                rows.append({"period": name, "model": model, **metrics(data, col)})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    comparisons = (("F2 - C2", "p_f2", "p_c2"), ("F2 - G2", "p_f2", "p_g2"),
                   ("F2 - F1", "p_f2", "p_f2_ctl"), ("C2 - G2", "p_c2", "p_g2"))
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

    if not a.primary:
        return

    def get(period, label):
        row = paired_df[(paired_df.period == period) & (paired_df.comparison == label)]
        return None if row.empty else row.iloc[0]

    m_wf = metrics_df[metrics_df.period == "walk-forward 2023-2025"].set_index("model")
    m_h = metrics_df[metrics_df.period == "2025 frozen holdout"].set_index("model")
    primary = get("walk-forward 2023-2025", "F2 - C2")
    info = get("walk-forward 2023-2025", "F2 - F1")
    hold_cmp = get("2025 frozen holdout", "F2 - C2")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["F2 G2+form", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["F2 G2+form", "games"] >= 250),
        "primary_f2_beats_c2": bool(primary is not None and primary.hi < 0),
        "information_f2_beats_f1": bool(info is not None and info.hi < 0),
        "holdout_f2_not_worse_than_+0.002": bool(hold_cmp is not None and hold_cmp["diff"] <= 0.002),
        "holdout_f2_point_negative": bool(hold_cmp is not None and hold_cmp["diff"] < 0),
        "logloss_pooled_vs_c2": bool(m_wf.loc["F2 G2+form", "log_loss"]
                                     <= m_wf.loc["C2 G2+drive splits", "log_loss"]),
        "logloss_holdout_vs_c2": bool(m_h.loc["F2 G2+form", "log_loss"]
                                      <= m_h.loc["C2 G2+drive splits", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["F2 G2+form", "reliability_10bin"]
            <= m_wf.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["F2 G2+form", "reliability_10bin"]
            <= m_h.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\nVERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
