#!/usr/bin/env python3
"""
Active-player cohort analysis for the FBS direct-props baselines.

Read-only on the committed predictions_<market>.csv files. Answers the gating
question the direct-props research left open:

  Does the model's CRPS advantage over the two baselines survive on the
  athletes users actually care about (players who recorded usage / regular
  participants), rather than being carried by the trivially-predictable
  zero-usage rows?

Cohorts (per market, 2025 out-of-sample rows only):
  all          every scored row
  in_game      observed > 0  (player actually recorded the stat)
  zero_usage   observed == 0 (did not record the stat: bench / DNP / no touches)
  regular      athlete active (observed>0) in >= 50% of their own games,
               restricted to in_game rows  (starters / rotation regulars)
  spot         athlete active in < 50% of their games, in_game rows only
  top_volume   in_game rows for athletes in the top quartile of season volume

For every cohort: n, model/baseA/baseB CRPS, paired delta, game_id-clustered
90% bootstrap CI (10k resamples, seed 20261020), cov50/80/90, and whether the
ADOPT_CANDIDATE rule still holds within the cohort.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261020
NBOOT = 10000

MARKETS = {
    "pass_attempts": "passing attempts",
    "passing_yards": "passing yards",
    "rush_attempts": "rushing carries",
    "rushing_yards": "rushing yards",
}


def clustered_delta_ci(df, col_a, col_b, nboot=NBOOT, seed=SEED):
    """Paired delta = a - b, bootstrapped on game_id clusters. Returns (delta, lo, hi)."""
    d = df[["game_id", col_a, col_b]].copy()
    d["delta"] = d[col_a] - d[col_b]
    point = float(d["delta"].mean())
    # per-cluster aggregate: n and sum, so a resample's mean is exact
    g = d.groupby("game_id")["delta"].agg(["sum", "count"])
    sums = g["sum"].values
    counts = g["count"].values
    rng = np.random.default_rng(seed)
    k = len(sums)
    if k < 2:
        return point, float("nan"), float("nan")
    means = np.empty(nboot)
    for i in range(nboot):
        idx = rng.integers(0, k, k)
        means[i] = sums[idx].sum() / counts[idx].sum()
    lo, hi = np.percentile(means, [5, 95])
    return point, float(lo), float(hi)


def cov(df):
    y = df["observed"].values
    return {
        "cov50": float(((df.q25 <= y) & (y <= df.q75)).mean()),
        "cov80": float(((df.q10 <= y) & (y <= df.q90)).mean()),
        "cov90": float(((df.q05 <= y) & (y <= df.q95)).mean()),
    }


def score_cohort(df, name, market):
    n = len(df)
    if n == 0:
        return None
    model = float(df["crps_model"].mean())
    baseA = float(df["crps_baseA"].mean())
    baseB = float(df["crps_baseB"].mean())
    dA, loA, hiA = clustered_delta_ci(df, "crps_model", "crps_baseA")
    dB, loB, hiB = clustered_delta_ci(df, "crps_model", "crps_baseB")
    c = cov(df)
    adopt = (hiA < 0) and (hiB < 0)
    err = df["pred_mean"].values - df["observed"].values
    errA = df["pred_mean_baseA"].values - df["observed"].values
    return {
        "market": market, "cohort": name, "n": n,
        "n_games": int(df["game_id"].nunique()),
        "n_athletes": int(df["athlete_id"].nunique()),
        "crps_model": model, "crps_baseA": baseA, "crps_baseB": baseB,
        "delta_A": dA, "ci90_A_lo": loA, "ci90_A_hi": hiA,
        "delta_B": dB, "ci90_B_lo": loB, "ci90_B_hi": hiB,
        "cov50": c["cov50"], "cov80": c["cov80"], "cov90": c["cov90"],
        "mae_model": float(np.abs(err).mean()),
        "mae_baseA": float(np.abs(errA).mean()),
        "bias_model": float(err.mean()),
        "bias_baseA": float(errA.mean()),
        "adopt_holds": bool(adopt),
    }


def main():
    rows = []
    detail = {}
    for market, label in MARKETS.items():
        path = HERE / f"predictions_{market}.csv"
        df = pd.read_csv(path)
        df["observed"] = df["observed"].astype(float)
        # climate: restrict to 2025 (these files are 2025 out-of-sample)
        df = df[df["season"] == 2025].copy()

        # --- player-level role: active rate across the player's own games ---
        per_ath = df.groupby("athlete_id")["observed"].agg(
            games="count", active=lambda s: int((s > 0).sum()))
        per_ath["active_rate"] = per_ath["active"] / per_ath["games"]
        # season volume for top-quartile cut
        vol = df.groupby("athlete_id")["observed"].sum()
        active_aths = vol[vol > 0]
        if len(active_aths) >= 4:
            q75 = float(active_aths.quantile(0.75))
        else:
            q75 = float("inf")

        df = df.merge(per_ath[["active_rate"]], left_on="athlete_id",
                      right_index=True, how="left")
        df["season_vol"] = df["athlete_id"].map(vol)

        cohorts = {
            "all": df,
            "in_game": df[df["observed"] > 0],
            "zero_usage": df[df["observed"] == 0],
        }
        ingame = df[df["observed"] > 0]
        cohorts["regular"] = ingame[ingame["active_rate"] >= 0.5]
        cohorts["spot"] = ingame[ingame["active_rate"] < 0.5]
        cohorts["top_volume"] = ingame[ingame["season_vol"] >= q75]

        # --- delta contribution: how much of the total CRPS gain is zeros ---
        n_all = len(df)
        dA_row = df["crps_model"] - df["crps_baseA"]
        in_game_mask = df["observed"] > 0
        contrib_ingame = float(dA_row[in_game_mask].sum() / n_all)
        contrib_zero = float(dA_row[~in_game_mask].sum() / n_all)
        detail[market] = {
            "label": label, "q75_volume": q75,
            "active_rate_median": float(per_ath["active_rate"].median()),
            "rows_total": int(n_all),
            "rows_in_game": int(in_game_mask.sum()),
            "frac_in_game": float(in_game_mask.mean()),
            "delta_A_total": float(dA_row.mean()),
            "delta_A_contrib_in_game": contrib_ingame,
            "delta_A_contrib_zero": contrib_zero,
            "delta_A_contrib_in_game_pct": float(contrib_ingame / dA_row.mean() * 100)
                if dA_row.mean() != 0 else float("nan"),
        }
        for cname, cdf in cohorts.items():
            r = score_cohort(cdf, cname, market)
            if r:
                rows.append(r)

    out = pd.DataFrame(rows)
    out.to_csv(HERE / "cohort_2025.csv", index=False)
    with open(HERE / "cohort_detail.json", "w") as f:
        json.dump(detail, f, indent=2)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)
    cols = ["market", "cohort", "n", "n_games", "n_athletes", "crps_model",
            "crps_baseA", "delta_A", "ci90_A_lo", "ci90_A_hi", "cov90",
            "mae_model", "mae_baseA", "bias_model", "adopt_holds"]
    print(out[cols].to_string(index=False))
    print("\nq75 volume / active-rate medians:")
    print(json.dumps(detail, indent=2))


if __name__ == "__main__":
    main()
