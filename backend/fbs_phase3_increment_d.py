#!/usr/bin/env python3
"""fbs_phase3_increment_d.py -- test increment (d) against C2 and G2, exactly as pre-registered.

Spec: RESULT-FBS-PHASE3-B-20261018.md §13. Same population, embargo, walk-forward, frozen 2025
holdout, metrics and week-block bootstrap as (b)/(c). Models on the identical game set:

    C2         G2 + seven drive splits            (the standing model, refit here)
    D1         G2 + intercept                     (recalibration control for (d))
    D2         G2 + rest_diff, away_travel_km, lon_shift        (primary)
    D2-weather D2 + temperature_c, wind_kph                     (secondary, reported only)

Primary comparison is D2 - C2.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_d.py
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
FEATURES_D = ["rest_diff", "away_travel_km", "lon_shift"]
FEATURES_DW = FEATURES_D + ["temperature_c", "wind_kph"]


def fit_models(frame, feature_cols, label):
    wf = walk_forward(frame, feature_cols)
    return wf.rename(columns={"p_b2": "p_" + label, "p_b1": "p_" + label + "_ctl"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet")
    ap.add_argument("--features-b", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--features-c", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    ap.add_argument("--features-d", default=os.path.join("research", "fbs", "phase3", "game_features_d.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3-d"))
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
    fd = pd.read_csv(a.features_d, dtype={"game_id": str}).drop(columns=["season"], errors="ignore")
    frame = frame.merge(fb[["game_id", "epa_diff"]], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + FEATURES_C], on="game_id", how="left")
    frame = frame.merge(fd, on="game_id", how="left")
    complete_c = frame[FEATURES_C].notna().all(axis=1)
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)
    frame["has_drive_data"] = complete_c
    # identical population to (b) and (c): the one game with no cfbfastR play-by-play stays out
    population = frame["epa_diff"].notna()
    frame = frame[population].drop(columns=["epa_diff"]).reset_index(drop=True)
    for col in FEATURES_DW:
        if col not in frame.columns:
            frame[col] = 0.0
    frame[FEATURES_DW] = frame[FEATURES_DW].fillna(0.0)
    for flag in ("travel_known", "weather_known"):
        if flag not in frame.columns:
            frame[flag] = False
        frame[flag] = frame[flag].fillna(False).astype(bool)
    print("population: %d games; travel known %.3f, weather known %.3f"
          % (len(frame), frame.travel_known.mean(), frame.weather_known.mean()))

    print("walk-forward fits ...")
    wf_c = fit_models(frame, FEATURES_C, "c2")
    wf_d2 = fit_models(frame, FEATURES_D, "d2")
    wf_dw = fit_models(frame, FEATURES_DW, "dw")
    wf = wf_d2.merge(
        wf_c[["game_id", "p_c2"]], on="game_id", how="inner").merge(
        wf_dw[["game_id", "p_dw"]], on="game_id", how="inner")
    wf["block"] = wf["season"].astype(str) + "-" + wf["week_start"].astype(str)

    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
    ledger["game_id"] = ledger["game_id"].astype(str)
    hold_c, _ = frozen_holdout(frame, FEATURES_C, holdout_ledger=ledger, holdout_season=2025)
    hold_d, params_d = frozen_holdout(frame, FEATURES_D, holdout_ledger=ledger, holdout_season=2025)
    hold_dw, _ = frozen_holdout(frame, FEATURES_DW, holdout_ledger=ledger, holdout_season=2025)
    hold_c = hold_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c2_ctl"})
    hold_d = hold_d.rename(columns={"p_b2": "p_d2", "p_b1": "p_d2_ctl"})
    hold_dw = hold_dw.rename(columns={"p_b2": "p_dw", "p_b1": "p_dw_ctl"})
    for df in (hold_c, hold_d, hold_dw):
        df["game_id"] = df["game_id"].astype(str)
    hold = hold_d.merge(hold_c[["game_id", "p_c2"]], on="game_id", how="inner").merge(
        hold_dw[["game_id", "p_dw"]], on="game_id", how="inner")
    hold["block"] = hold["season"].astype(str) + "-" + hold["week_start"].astype(str)
    print("frozen holdout trained on %d games; D2 coefficients: %s"
          % (params_d["n_train"], np.round(params_d["b2"], 4).tolist()))

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": hold,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    model_cols = (("G2", "p_g2"), ("C2 G2+drive splits", "p_c2"), ("D1 G2+intercept", "p_d2_ctl"),
                  ("D2 G2+rest/travel/lon", "p_d2"), ("D2w +weather", "p_dw"))
    for name, data in periods.items():
        for model, col in model_cols:
            if col in data:
                rows.append({"period": name, "model": model, **metrics(data, col)})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    comparisons = (("D2 - C2", "p_d2", "p_c2"), ("D2 - G2", "p_d2", "p_g2"),
                   ("D2 - D1", "p_d2", "p_d2_ctl"), ("D2w - C2", "p_dw", "p_c2"),
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
    primary = get("walk-forward 2023-2025", "D2 - C2")
    info = get("walk-forward 2023-2025", "D2 - D1")
    hold_cmp = get("2025 frozen holdout", "D2 - C2")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["D2 G2+rest/travel/lon", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["D2 G2+rest/travel/lon", "games"] >= 250),
        "primary_d2_beats_c2": bool(primary is not None and primary.hi < 0),
        "information_d2_beats_d1": bool(info is not None and info.hi < 0),
        "holdout_d2_not_worse_than_+0.002": bool(hold_cmp is not None and hold_cmp["diff"] <= 0.002),
        "holdout_d2_point_negative": bool(hold_cmp is not None and hold_cmp["diff"] < 0),
        "logloss_pooled_vs_c2": bool(m_wf.loc["D2 G2+rest/travel/lon", "log_loss"]
                                     <= m_wf.loc["C2 G2+drive splits", "log_loss"]),
        "logloss_holdout_vs_c2": bool(m_h.loc["D2 G2+rest/travel/lon", "log_loss"]
                                      <= m_h.loc["C2 G2+drive splits", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["D2 G2+rest/travel/lon", "reliability_10bin"]
            <= m_wf.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["D2 G2+rest/travel/lon", "reliability_10bin"]
            <= m_h.loc["C2 G2+drive splits", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\nVERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
