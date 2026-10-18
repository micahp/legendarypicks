#!/usr/bin/env python3
"""fbs_phase3_increment_c.py -- test increment (c) against B2 and G2, exactly as pre-registered.

Spec: RESULT-FBS-PHASE3-B-20261018.md §11. Same population, embargo, walk-forward, frozen 2025
holdout, metrics and week-block bootstrap as (b). Three models on the identical game set:

    B2  G2 + four prior-play differences          (the standing model)
    C1  G2 + intercept                            (recalibration control for (c))
    C2  G2 + seven drive/box-score differences    (the increment)

Primary comparison is C2 - B2. C2 - G2 is reported for continuity.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_increment_c.py
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
    frozen_holdout, logit, metrics, paired_bootstrap, sigmoid, walk_forward)
from fbs_phase3_increment import FEATURES as FEATURES_B  # noqa: E402

FEATURES_C = feat_c.FEATURE_NAMES_C


def walk_forward_c(frame, feature_cols, min_train=200):
    """Same walk-forward as (b) but labels its outputs c2/c1."""
    out = walk_forward(frame, feature_cols, min_train=min_train)
    return out.rename(columns={"p_b2": "p_c2", "p_b1": "p_c1"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default="/root/lp-fbs-audit/research/fbs/parquet")
    ap.add_argument("--features-b", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--features-c", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    ap.add_argument("--out-dir", default=os.path.join("research", "fbs", "phase3-c"))
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
    frame = frame.merge(fb[["game_id"] + FEATURES_B], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + FEATURES_C], on="game_id", how="left")
    complete_b = frame[FEATURES_B].notna().all(axis=1)
    complete_c = frame[FEATURES_C].notna().all(axis=1)
    print("features: b %d, c %d, both %d of %d games"
          % (complete_b.sum(), complete_c.sum(), (complete_b & complete_c).sum(), len(frame)))
    # Games with no ESPN drive table get the league-mean difference (0.0, because a league-average
    # offence against a league-average defence cancels) and a flag. Zero here is the league mean, not
    # a missing value imputed as zero; it keeps the population identical to (b).
    frame["has_drive_data"] = complete_c
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)
    print("games with no drive data, filled at the league mean: %d" % int((~complete_c).sum()))
    frame = frame[complete_b].reset_index(drop=True)

    print("walk-forward fits ...")
    wf_b = walk_forward(frame, FEATURES_B)
    wf_c = walk_forward_c(frame, FEATURES_C)
    wf = wf_c.drop(columns=["p_b2", "p_b1"], errors="ignore").merge(
        wf_b[["game_id", "p_b2", "p_b1"]], on="game_id", how="inner")
    wf["block"] = wf["season"].astype(str) + "-" + wf["week_start"].astype(str)

    ledger_path = os.path.join("research", "fbs", "phase3-baseline",
                               "fbs_game_winner_holdout_2025_20261018.csv")
    ledger = pd.read_csv(ledger_path, usecols=["game_id", "elo_home_prob"])
    ledger["game_id"] = ledger["game_id"].astype(str)
    hold_b, params_b = frozen_holdout(frame, FEATURES_B, holdout_ledger=ledger, holdout_season=2025)
    hold_c, params_c = frozen_holdout(frame, FEATURES_C, holdout_ledger=ledger, holdout_season=2025)
    hold_c = hold_c.rename(columns={"p_b2": "p_c2", "p_b1": "p_c1"})
    hold_b["game_id"] = hold_b["game_id"].astype(str)
    hold_c["game_id"] = hold_c["game_id"].astype(str)
    hold = hold_c.merge(hold_b[["game_id", "p_b2", "p_b1"]], on="game_id", how="inner")
    hold["block"] = hold["season"].astype(str) + "-" + hold["week_start"].astype(str)
    print("frozen holdout trained on %d games; C2 coefficients: %s"
          % (params_c["n_train"], np.round(params_c["b2"], 4).tolist()))

    periods = {
        "walk-forward 2023-2025": wf[wf.season.between(2023, 2025)],
        "2025 frozen holdout": hold,
        "2026 development": wf[wf.season == 2026],
    }
    rows = []
    for name, data in periods.items():
        for model, col in (("G2", "p_g2"), ("B2 G2+prior-play", "p_b2"),
                           ("C1 G2+intercept", "p_c1"), ("C2 G2+drive splits", "p_c2")):
            if col in data:
                rows.append({"period": name, "model": model, **metrics(data, col)})
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(os.path.join(a.out_dir, "metrics.csv"), index=False)

    comparisons = (("C2 - B2", "p_c2", "p_b2"), ("C2 - G2", "p_c2", "p_g2"),
                   ("C2 - C1", "p_c2", "p_c1"), ("B2 - G2", "p_b2", "p_g2"))
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
    primary = get("walk-forward 2023-2025", "C2 - B2")
    info = get("walk-forward 2023-2025", "C2 - C1")
    hold_cmp = get("2025 frozen holdout", "C2 - B2")
    gates = {
        "sample_pooled_ge_1500": bool(m_wf.loc["C2 G2+drive splits", "games"] >= 1500),
        "sample_holdout_ge_250": bool(m_h.loc["C2 G2+drive splits", "games"] >= 250),
        "primary_c2_beats_b2": bool(primary is not None and primary.hi < 0),
        "information_c2_beats_c1": bool(info is not None and info.hi < 0),
        "holdout_c2_not_worse_than_+0.002": bool(hold_cmp is not None and hold_cmp["diff"] <= 0.002),
        "holdout_c2_point_negative": bool(hold_cmp is not None and hold_cmp["diff"] < 0),
        "logloss_pooled_vs_b2": bool(m_wf.loc["C2 G2+drive splits", "log_loss"]
                                     <= m_wf.loc["B2 G2+prior-play", "log_loss"]),
        "logloss_holdout_vs_b2": bool(m_h.loc["C2 G2+drive splits", "log_loss"]
                                      <= m_h.loc["B2 G2+prior-play", "log_loss"]),
        "calibration_pooled_within_0.005": bool(
            m_wf.loc["C2 G2+drive splits", "reliability_10bin"]
            <= m_wf.loc["B2 G2+prior-play", "reliability_10bin"] + 0.005),
        "calibration_holdout_within_0.005": bool(
            m_h.loc["C2 G2+drive splits", "reliability_10bin"]
            <= m_h.loc["B2 G2+prior-play", "reliability_10bin"] + 0.005),
    }
    gates_df = pd.DataFrame([{"gate": k, "passed": v} for k, v in gates.items()])
    gates_df.to_csv(os.path.join(a.out_dir, "gates.csv"), index=False)
    print("\ngates")
    print(gates_df.to_string(index=False))
    print("\nVERDICT:", "ADOPTED" if all(gates.values()) else "DISCARDED")


if __name__ == "__main__":
    main()
