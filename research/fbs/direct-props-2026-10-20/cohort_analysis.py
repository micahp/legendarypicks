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

  all                 every scored row
  in_game             observed > 0  (player actually recorded the stat)
  zero_usage          observed == 0 (did not record the stat: bench / DNP / no touches)
  regular_posthoc     POST-HOC / OUTCOME-AWARE. Athlete active (observed>0) in
                      >= 50% of their own 2025 games, restricted to in_game
                      rows. Membership uses full-season information (the target
                      game and later weeks), so it is NOT pregame-definable.
  spot                POST-HOC / OUTCOME-AWARE. Athlete active in < 50% of their
                      2025 games, in_game rows only.
  top_volume_posthoc  POST-HOC / OUTCOME-AWARE. In_game rows for athletes in the
                      top quartile of 2025 season volume (full-season cut).
  pregame_known       PREGAME-DEFINABLE. An athlete qualifies if their 2024
                      season volume for this market was in the top quartile, or
                      -- for athletes with no 2024 volume -- if their strictly-
                      trailing 2025 cumulative volume before this game clears the
                      same threshold. Evaluated over ALL rows for those athletes,
                      zeros included (a user looking a player up does not know
                      whether he will record anything).

## What each cohort can and cannot support

  in_game / zero_usage     A DECOMPOSITION of the aggregate CRPS. Says where the
                           win comes from, not what the model is worth to a user.
  regular_* / top_volume_* Post-hoc, outcome-aware. Directional evidence only.
  pregame_known            The only cohort that can carry a product claim.

For every cohort: n, model/baseA/baseB CRPS, paired delta, game_id-clustered
90% bootstrap CI (10k resamples, seed 20261020), cov50/80/90, MAE, bias, and
whether the ADOPT_CANDIDATE rule still holds within the cohort.
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

# Column + position scope per market, matching run_direct_props.py MARKETS.
MARKET_SPEC = {
    "pass_attempts": dict(col="pass_attempts", positions=["QB"]),
    "passing_yards": dict(col="passing_yards", positions=["QB"]),
    "rush_attempts": dict(col="rush_attempts", positions=["RB", "QB"]),
    "rushing_yards": dict(col="rushing_yards", positions=["RB", "QB"]),
}

# Read-only Phase-5 cache; supplies 2024 season volume for the pregame cut.
DEFAULT_CACHE = "/root/lp-fbs-archive/research/fbs/phase5/cache"


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


def load_prior_season_volume(cache, market, season=2024):
    """Season volume per athlete for one market, position-restricted, from the
    read-only Phase-5 cache. Returns (vol_series, threshold) with threshold the
    75th percentile of season volume among athletes that recorded volume, or
    (None, None) if the cache is unavailable."""
    spec = MARKET_SPEC[market]
    p = Path(cache) / "player_games.parquet"
    if not p.exists():
        return None, None
    pg = pd.read_parquet(p, columns=["athlete_id", "season",
                                     "position_abbreviation", spec["col"]])
    d = pg[(pg.season == season)
           & pg.position_abbreviation.isin(spec["positions"])]
    vol = d.groupby("athlete_id")[spec["col"]].sum()
    active = vol[vol > 0]
    thr = float(active.quantile(0.75)) if len(active) >= 4 else float("inf")
    return vol, thr


def pregame_known_cohort(df, market, cache):
    """Pregame-definable membership (no target-game or future-week data).

    An athlete qualifies for a 2025 row if their 2024 season volume (same market,
    position-restricted) was >= the top-quartile threshold, OR -- if they have no
    2024 volume -- if their strictly-trailing 2025 cumulative volume before this
    game clears the same threshold. Evaluated over ALL rows of qualifying
    athletes, zeros included.
    """
    vol, thr = load_prior_season_volume(cache, market)
    if vol is None:
        return df.iloc[0:0], {
            "prior_season_available": False, "threshold": None,
            "rule": "prior-season cut unavailable (no 2024 player_games); "
                    "pregame_known NOT evaluated",
            "n_member_rows": 0, "n_member_athletes": 0,
            "n_member_games": 0, "frac_member_rows": 0.0,
        }
    d = df.sort_values(["athlete_id", "week", "game_id"]).copy()
    # strictly-trailing: cumulative through prior games only
    trail = d.groupby("athlete_id")["observed"].cumsum() - d["observed"]
    has_prior = d["athlete_id"].isin(vol.index)
    prior_vol = d["athlete_id"].map(vol).fillna(0.0)
    member = np.where(has_prior, prior_vol >= thr, trail >= thr)
    m = pd.Series(member, index=d.index)
    out = d[m]
    info = {
        "prior_season_available": True,
        "threshold": float(thr) if thr is not None else None,
        "rule": "2024 top-quartile season volume; strictly-trailing 2025 volume "
                "for athletes with no 2024 volume",
        "n_member_rows": int(m.sum()),
        "n_member_athletes": int(out["athlete_id"].nunique()),
        "n_member_games": int(out["game_id"].nunique()),
        "n_member_rows_observed_gt0": int((out["observed"] > 0).sum()),
        "frac_member_rows": float(m.mean()),
    }
    return out, info


def main():
    rows = []
    detail = {}
    for market, label in MARKETS.items():
        path = HERE / f"predictions_{market}.csv"
        df = pd.read_csv(path)
        df["observed"] = df["observed"].astype(float)
        df = df[df["season"] == 2025].copy()

        # --- player-level role: active rate across the player's own games ---
        # NOTE: full 2025 season (target + later weeks) -> these cuts are
        # POST-HOC / outcome-aware, not pregame-definable.
        per_ath = df.groupby("athlete_id")["observed"].agg(
            games="count", active=lambda s: int((s > 0).sum()))
        per_ath["active_rate"] = per_ath["active"] / per_ath["games"]
        # season volume for the post-hoc top-quartile cut
        vol = df.groupby("athlete_id")["observed"].sum()
        active_aths = vol[vol > 0]
        if len(active_aths) >= 4:
            q75 = float(active_aths.quantile(0.75))
        else:
            q75 = float("inf")

        df = df.merge(per_ath[["active_rate"]], left_on="athlete_id",
                      right_index=True, how="left")
        df["season_vol"] = df["athlete_id"].map(vol)

        in_game_mask = df["observed"] > 0
        # zero usage is strictly observed==0; negative-yard rows (college sacks
        # and losses) are recorded usage, counted separately, never "zeros".
        zero_mask = df["observed"] == 0
        neg_mask = df["observed"] < 0
        cohorts = {
            "all": df,
            "in_game": df[in_game_mask],
            "zero_usage": df[zero_mask],
        }
        ingame = df[in_game_mask]
        # POST-HOC / OUTCOME-AWARE (full-season membership): directional only.
        cohorts["regular_posthoc"] = ingame[ingame["active_rate"] >= 0.5]
        cohorts["spot"] = ingame[ingame["active_rate"] < 0.5]
        cohorts["top_volume_posthoc"] = ingame[ingame["season_vol"] >= q75]

        # PREGAME-DEFINABLE cut (2024 top-quartile volume, else trailing).
        pk_df, pk_info = pregame_known_cohort(df, market, DEFAULT_CACHE)
        cohorts["pregame_known"] = pk_df

        # --- delta contribution / zero share ---
        n_all = len(df)
        dA_row = df["crps_model"] - df["crps_baseA"]
        contrib_ingame = float(dA_row[in_game_mask].sum() / n_all)
        contrib_zero = float(dA_row[zero_mask].sum() / n_all)
        detail[market] = {
            "label": label, "q75_volume": q75,
            "active_rate_median": float(per_ath["active_rate"].median()),
            "rows_total": int(n_all),
            "rows_in_game": int(in_game_mask.sum()),
            "rows_zero": int(zero_mask.sum()),
            "rows_negative": int(neg_mask.sum()),
            "frac_in_game": float(in_game_mask.mean()),
            "frac_zero": float(zero_mask.mean()),
            "delta_A_total": float(dA_row.mean()),
            "delta_A_contrib_in_game": contrib_ingame,
            "delta_A_contrib_zero": contrib_zero,
            "delta_A_contrib_in_game_pct": float(contrib_ingame / dA_row.mean() * 100)
                if dA_row.mean() != 0 else float("nan"),
            "pregame_known": pk_info,
        }
        for cname, cdf in cohorts.items():
            r = score_cohort(cdf, cname, market)
            if r:
                rows.append(r)

    out = pd.DataFrame(rows)
    out.to_csv(HERE / "cohort_2025.csv", index=False)
    with open(HERE / "cohort_detail.json", "w") as f:
        json.dump(detail, f, indent=2)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    cols = ["market", "cohort", "n", "n_games", "n_athletes", "crps_model",
            "crps_baseA", "delta_A", "ci90_A_lo", "ci90_A_hi", "cov90",
            "mae_model", "mae_baseA", "bias_model", "adopt_holds"]
    print(out[cols].to_string(index=False))
    print("\nzero share of scored rows (frac_zero):")
    for m in MARKETS:
        print(f"  {m:16s} rows={detail[m]['rows_total']:6d}  "
              f"frac_zero={detail[m]['frac_zero']:.4f}")
    print("\npregame_known membership:")
    for m in MARKETS:
        print(f"  {m:16s} " + json.dumps(detail[m]["pregame_known"]))
    print("\nfull detail:")
    print(json.dumps(detail, indent=2))


if __name__ == "__main__":
    main()
