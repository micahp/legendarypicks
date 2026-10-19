#!/usr/bin/env python3
"""fbs_phase4b_h0bmc.py -- Phase 4b candidate H0b-MC.

Pre-registered in research/fbs/PREREG-FBS-PHASE4B-20261019.md (commit 680b259a).

H0b-MC re-centres ONLY the frozen H0b total PMF onto t' = a_S + b_S * t, with
(a_S, b_S) from one OLS of obs_total on pred_total over strictly prior seasons.
alpha/gamma/R are read from research/fbs/phase4/block_parameters.csv and are never
refitted. The margin PMF, home/away PMFs and every Phase 4 artifact are untouched.

Read-only against the frozen Phase 4 artifacts; writes only under
research/fbs/phase4b/ and docs/frozen-fbs-phase4b-h0bmc.json.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import kstest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbs_phase4_scores as p4  # noqa: E402

SEED = 20261017
REPS = 2000
MAXS = p4.MAXS
N_M = 2 * MAXS + 1
SUPPORT = np.arange(N_M)
SEASONS = list(range(2015, 2027))
SCORING_SEASONS = (2023, 2024, 2025, 2026)
BUCKETS = [(0, 40, "<40"), (40, 50, "40-50"), (50, 60, "50-60"),
           (60, 70, "60-70"), (70, 10 ** 9, ">70")]
OUT = os.path.join("research", "fbs", "phase4b")
FROZEN_JSON = os.path.join("docs", "frozen-fbs-phase4b-h0bmc.json")


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def sha256_array(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def load_fbs_flags(seasons):
    """The CFBD fbs_game flag from the same cfb_schedules the Phase 4 harness reads."""
    frames = []
    for s in seasons:
        path = os.path.join("research", "fbs", "parquet", "cfb_schedules",
                            "cfb_schedules_%d.parquet" % s)
        if not os.path.exists(path):
            continue
        frames.append(pd.read_parquet(path, columns=["game_id", "fbs_game"]))
    f = pd.concat(frames, ignore_index=True)
    f["game_id"] = f["game_id"].astype(str)
    f["fbs_game"] = f["fbs_game"].fillna(False).astype(bool)
    return f.drop_duplicates("game_id")[["game_id", "fbs_game"]]


def rebuild_predictions(asof, bp):
    """Rebuild mu_h, mu_a and the total-PMF mean for every as-of game with a frozen block row."""
    a = asof.copy()
    a["game_id"] = a["game_id"].astype(str)
    a["block"] = pd.to_datetime(a["date"]).dt.strftime("%Y-%m-%d")
    b = bp[bp["kind"] == "walk_forward"].copy()
    b["block"] = b["block"].astype(str)
    if b["block"].duplicated().any():
        raise SystemExit("duplicate walk_forward block rows in block_parameters.csv")
    m = a.merge(b, on="block", how="left")
    m = m.dropna(subset=["alpha", "home_for", "away_for"]).reset_index(drop=True)
    out = []
    for r in m.itertuples(index=False):
        lh = (r.alpha
              + math.log(max(r.home_for, 1.0) / r.home_for_mean)
              + math.log(max(r.away_against, 1.0) / r.away_against_mean) + r.gamma / 2)
        la = (r.alpha
              + math.log(max(r.away_for, 1.0) / r.away_for_mean)
              + math.log(max(r.home_against, 1.0) / r.home_against_mean) - r.gamma / 2)
        mh, ma = math.exp(lh), math.exp(la)
        _, tt = p4.margin_total(p4.nb_vec(mh, r.R), p4.nb_vec(ma, r.R))
        out.append((r.game_id, r.block, float(r.home_points), float(r.away_points),
                    mh, ma, float(r.R), float(np.dot(SUPPORT, tt))))
    return pd.DataFrame(out, columns=["game_id", "block", "home_points", "away_points",
                                      "mu_h", "mu_a", "R", "pred_total"])


def shift_to_mean(pmf, target, tol=1e-3):
    """Shift a discrete PMF on 0..240 so its mean is target (pre-registered 4.2-4.3)."""
    cdf = p4.cdf_of(np.asarray(pmf, float))
    delta = target - float(np.dot(SUPPORT, pmf))
    p = None
    mean = float("nan")
    renorm = 1.0
    for it in range(3):
        new_cdf = np.interp(SUPPORT - delta, SUPPORT, cdf, left=0.0, right=1.0)
        q = np.diff(new_cdf, prepend=0.0)
        q = np.clip(q, 0.0, None)
        s = float(q.sum())
        renorm = (1.0 / s) if s > 0 else 1.0
        p = q / s if s > 0 else np.asarray(pmf, float)
        mean = float(np.dot(SUPPORT, p))
        if abs(mean - target) <= tol:
            break
        delta += target - mean
    return p, delta, mean, it, renorm


def per_game_brier(frame, metric):
    if metric == "brier_spread":
        vals = [((frame["spread_%s%d" % (side, L)] - frame["spread_hit_%s%d" % (side, L)]) ** 2)
                for L in p4.SPREAD_LINES for side in ("give", "get")]
    else:
        vals = [((frame["over_%d" % L] - frame["over_hit_%d" % L]) ** 2)
                for L in p4.TOTAL_LINES]
    return np.mean(vals, axis=0) if isinstance(vals[0], pd.Series) else float(np.mean(vals))


def main():
    os.makedirs(os.path.join(OUT, "pmf"), exist_ok=True)

    # ---- 1. load games, as-of ratings, frozen parameters, fbs flag
    print("loading games and as-of ratings ...")
    g = p4.load_games(SEASONS)
    asof = p4.build_as_of(g)
    asof["game_id"] = asof["game_id"].astype(str)
    g["game_id"] = g["game_id"].astype(str)
    flags = load_fbs_flags(SEASONS)
    bp = pd.read_csv(os.path.join("research", "fbs", "phase4", "block_parameters.csv"))
    bp["block"] = bp["block"].astype(str)

    # season map
    season_map = g[["game_id", "season"]].drop_duplicates("game_id")
    asof = asof.merge(season_map, on="game_id", how="left")
    asof = asof.merge(flags, on="game_id", how="left")

    # ---- 2. rebuild all prior-season predictions from the frozen block parameters
    print("rebuilding prior-season forecasts from frozen block parameters ...")
    rb = rebuild_predictions(asof, bp)
    rb = rb.merge(season_map, on="game_id", how="left")
    rb = rb.merge(flags, on="game_id", how="left")
    rb["obs_total"] = rb["home_points"] + rb["away_points"]
    print("  rebuilt rows with a frozen block: %d (fbs_game %d)"
          % (len(rb), int(rb["fbs_game"].fillna(False).sum())))

    # ---- 3. reproduction gate: 2023 frozen H0b pred_total at <= 1e-6
    sc = pd.read_csv(os.path.join("research", "fbs", "phase4", "pmf",
                                  "per_observation_scores.csv"), dtype={"game_id": str})
    h0b = sc[sc["model"] == "H0b"].reset_index(drop=True)
    wf23 = h0b[(h0b["period"] == "walk_forward") & (h0b["season"] == 2023)]
    rep = wf23[["game_id", "pred_total"]].merge(
        rb[["game_id", "pred_total"]].rename(columns={"pred_total": "rebuild_total"}),
        on="game_id", how="left")
    if rep["rebuild_total"].isna().any():
        raise SystemExit("reproduction gate: %d 2023 games have no rebuilt forecast"
                         % int(rep["rebuild_total"].isna().sum()))
    rep["abs_diff"] = (rep["rebuild_total"] - rep["pred_total"]).abs()
    repro_max = float(rep["abs_diff"].max())
    repro_mean = float(rep["abs_diff"].mean())
    print("reproduction gate (2023, n=%d): max abs diff = %.3e, mean = %.3e"
          % (len(rep), repro_max, repro_mean))
    if repro_max > 1e-6:
        raise SystemExit("REPRODUCTION GATE FAILED: max abs diff %.3e > 1e-6" % repro_max)

    # ---- 4. calibration sets: rebuilt 2015-2022 + frozen H0b 2023-2025 walk-forward
    prior = rb[rb["fbs_game"].fillna(False)][["game_id", "season", "obs_total", "pred_total"]].copy()
    evalcal = h0b[(h0b["period"] == "walk_forward") &
                  (h0b["season"].isin([2023, 2024, 2025]))][["game_id", "season", "obs_total", "pred_total"]].copy()
    calib = pd.concat([prior, evalcal], ignore_index=True)
    calib = calib.drop_duplicates("game_id")
    print("calibration pool: %d FBS-vs-FBS games, seasons %s"
          % (len(calib), sorted(calib["season"].unique())))

    cal_rows = {}
    for S in SCORING_SEASONS:
        c = calib[calib["season"] < S]
        if len(c) < 250:
            raise SystemExit("calibration set for %d has %d rows (<250)" % (S, len(c)))
        r = stats.linregress(c["pred_total"], c["obs_total"])
        cal_rows[S] = {"season": S, "n": int(len(c)), "slope": float(r.slope),
                       "intercept": float(r.intercept), "r2": float(r.rvalue ** 2),
                       "slope_se": float(r.stderr), "slope_lo": float(r.slope - 1.96 * r.stderr),
                       "slope_hi": float(r.slope + 1.96 * r.stderr),
                       "seasons": sorted(int(s) for s in c["season"].unique())}
        print("  calibration %d: n=%d seasons %d-%d slope=%.4f intercept=%.3f r2=%.4f"
              % (S, len(c), min(cal_rows[S]["seasons"]), max(cal_rows[S]["seasons"]),
                 r.slope, r.intercept, r.rvalue ** 2))
    C = pd.DataFrame(cal_rows.values()).sort_values("season").reset_index(drop=True)
    C.to_csv(os.path.join(OUT, "calibration.csv"), index=False)

    # ---- 5. evaluation frame and frozen PMFs
    z = np.load(os.path.join("research", "fbs", "phase4", "pmf", "margin_total_pmf.npz"),
                allow_pickle=True)
    zids = [str(x) for x in z["game_id"]]
    if zids != h0b["game_id"].tolist():
        raise SystemExit("frozen npz row order does not match the H0b csv rows")
    pmf_frozen = z["H0b_total"].astype(np.float64)
    margin_frozen = z["H0b_margin"].astype(np.float64)

    amap = {int(r.season): (r.intercept, r.slope) for r in C.itertuples(index=False)}
    u_draw = np.random.default_rng(SEED).random(len(h0b))

    rows = []
    shift_rows = []
    for i, r in enumerate(h0b.itertuples(index=False)):
        a_S, b_S = amap[int(r.season)]
        t = float(r.pred_total)
        target = a_S + b_S * t
        delta = target - t
        pmf_new, delta_used, mean_new, iters, renorm = shift_to_mean(pmf_frozen[i], target)
        cdf_new = p4.cdf_of(pmf_new)
        obs_t = float(r.obs_total)
        p0b, p0a = float(pmf_frozen[i][0]), float(pmf_new[0])
        pnb, pna = float(pmf_frozen[i][-1]), float(pmf_new[-1])
        shift_rows.append({"game_id": r.game_id, "season": int(r.season), "period": r.period,
                           "block": r.block, "t": t, "t_prime": target, "delta": delta,
                           "delta_used": delta_used, "mean_after": mean_new,
                           "mean_error": mean_new - target, "iterations": iters,
                           "renorm": renorm, "p0_before": p0b, "p0_after": p0a,
                           "p240_before": pnb, "p240_after": pna,
                           "boundary_change": max(abs(p0a - p0b), abs(pna - pnb)),
                           "failure": bool(abs(mean_new - target) > 1e-3)})
        rec = {"model": "H0b-MC", "game_id": r.game_id, "block": r.block,
               "season": int(r.season), "period": r.period,
               # inherited margin side (unchanged from frozen H0b)
               "crps_margin": float(r.crps_margin), "log_margin": float(r.log_margin),
               "pit_margin": float(r.pit_margin), "pred_margin": float(r.pred_margin),
               "cov50_margin": float(r.cov50_margin), "short50_margin": float(r.short50_margin),
               "cov80_margin": float(r.cov80_margin), "short80_margin": float(r.short80_margin),
               "cov90_margin": float(r.cov90_margin), "short90_margin": float(r.short90_margin),
               "pred_h": float(r.pred_h), "pred_a": float(r.pred_a),
               # corrected total side
               "crps_total": p4.crps_discrete(cdf_new, obs_t, 0),
               "log_total": -math.log(max(float(pmf_new[int(obs_t)]), 1e-12)),
               "pit_total": p4.pit_randomized(cdf_new, pmf_new, obs_t, 0, u_draw[i]),
               "pred_total": mean_new,
               "obs_margin": float(r.obs_margin), "obs_total": obs_t,
               "obs_h": float(r.obs_h), "obs_a": float(r.obs_a)}
        for level in (0.5, 0.8, 0.9):
            lo, hi = p4.central_interval(cdf_new, level, 0)
            slo, shi = p4.shortest_interval(pmf_new, level, 0)
            rec["cov%d_total" % int(level * 100)] = float(lo <= obs_t <= hi)
            rec["short%d_total" % int(level * 100)] = float(slo <= obs_t <= shi)
        for side, L in ((s, L) for L in p4.SPREAD_LINES for s in ("give", "get")):
            rec["spread_%s%d" % (side, L)] = float(getattr(r, "spread_%s%d" % (side, L)))
            rec["spread_hit_%s%d" % (side, L)] = float(getattr(r, "spread_hit_%s%d" % (side, L)))
        for L in p4.TOTAL_LINES:
            rec["over_%d" % L] = float(np.sum(pmf_new[SUPPORT > L]))
            rec["over_hit_%d" % L] = float(obs_t > L)
        rows.append(rec)

    HM = pd.DataFrame(rows)
    SH = pd.DataFrame(shift_rows)
    HM.to_csv(os.path.join(OUT, "pmf", "per_observation_scores.csv"), index=False)
    SH.to_csv(os.path.join(OUT, "per_game_shift.csv"), index=False)

    # ---- 6. persist corrected total PMFs and the unchanged margin PMFs
    new_pmfs = np.zeros_like(pmf_frozen, dtype=np.float32)
    for i, r in enumerate(HM.itertuples(index=False)):
        a_S, b_S = amap[int(r.season)]
        t = float(h0b.iloc[i]["pred_total"])
        target = a_S + b_S * t
        new_pmfs[i] = shift_to_mean(pmf_frozen[i], target)[0].astype(np.float32)
    np.savez_compressed(os.path.join(OUT, "pmf", "h0bmc_pmf.npz"),
                        game_id=h0b["game_id"].to_numpy(),
                        H0bMC_total=new_pmfs,
                        H0bMC_margin=margin_frozen.astype(np.float32))
    margin_hash = sha256_array(margin_frozen.astype(np.float32))
    margin_hash_roundtrip = sha256_array(
        np.load(os.path.join(OUT, "pmf", "h0bmc_pmf.npz"))["H0bMC_margin"])
    if margin_hash != margin_hash_roundtrip:
        raise SystemExit("margin PMF copy is not byte-identical to the frozen H0b margin")
    if margin_hash != sha256_array(z["H0b_margin"]):
        raise SystemExit("margin PMF differs from the frozen Phase 4 artifact")

    # ---- 7. summary, paired comparisons, gates
    periods = {"walk_forward": HM[HM.period == "walk_forward"],
               "holdout": HM[HM.period == "holdout"],
               "dev2026": HM[HM.period == "dev2026"]}
    summary = []
    for pname, d in periods.items():
        row = {"period": pname, "model": "H0b-MC", "n": len(d)}
        for stat, col in (("mae_home", "pred_h"), ("mae_away", "pred_a"),
                          ("mae_margin", "pred_margin"), ("mae_total", "pred_total")):
            obs = {"pred_h": "obs_h", "pred_a": "obs_a",
                   "pred_margin": "obs_margin", "pred_total": "obs_total"}[col]
            diff = (d[col] - d[obs]).to_numpy()
            row[stat] = float(np.mean(np.abs(diff)))
            row[stat.replace("mae", "rmse")] = float(np.sqrt(np.mean(diff ** 2)))
            row[stat.replace("mae", "bias")] = float(np.mean(diff))
        row["crps_margin"] = float(d.crps_margin.mean())
        row["crps_total"] = float(d.crps_total.mean())
        row["log_margin"] = float(d.log_margin.mean())
        row["log_total"] = float(d.log_total.mean())
        for level in (50, 80, 90):
            row["cov%d_margin" % level] = float(d["cov%d_margin" % level].mean())
            row["cov%d_total" % level] = float(d["cov%d_total" % level].mean())
            row["short%d_margin" % level] = float(d["short%d_margin" % level].mean())
            row["short%d_total" % level] = float(d["short%d_total" % level].mean())
        row["pit_margin_ks"] = float(kstest(d.pit_margin, "uniform").pvalue)
        row["pit_total_ks"] = float(kstest(d.pit_total, "uniform").pvalue)
        row["brier_spread"] = float(np.mean([per_game_brier(d, "brier_spread")]))
        row["brier_total"] = float(np.mean([per_game_brier(d, "brier_total")]))
        summary.append(row)
    S = pd.DataFrame(summary)
    S.to_csv(os.path.join(OUT, "summary_by_period.csv"), index=False)

    # combine H0b-MC with the frozen baselines for paired comparisons
    frozen = sc.copy()
    frozen["game_id"] = frozen["game_id"].astype(str)
    h1c = frozen[frozen.model.isin(["H1", "Constant"])].copy()
    # H1/Constant rows keep their frozen margin and total values; H0b-MC is the new row
    allrows = pd.concat([HM, h1c], ignore_index=True)

    pairs = []
    for pname, d in periods.items():
        for base_model in ("H1", "Constant"):
            for model in ("H0b-MC",):
                a_ = d.set_index("game_id").sort_index()
                b_ = h1c[(h1c.period == pname) & (h1c.model == base_model)].set_index("game_id").sort_index()
                common = a_.index.intersection(b_.index)
                if len(common) < 100:
                    continue
                for metric in ("crps_margin", "crps_total", "brier_spread", "brier_total"):
                    av = per_game_brier(a_.loc[common], metric) if metric.startswith("brier") \
                        else a_.loc[common, metric].to_numpy()
                    bv = per_game_brier(b_.loc[common], metric) if metric.startswith("brier") \
                        else b_.loc[common, metric].to_numpy()
                    res = p4.block_bootstrap(np.asarray(av) - np.asarray(bv),
                                             a_.loc[common, "block"].to_numpy(), reps=REPS, seed=SEED)
                    pairs.append({"period": pname, "model": model, "base": base_model,
                                  "metric": metric, **res})
    PR = pd.DataFrame(pairs)
    PR.to_csv(os.path.join(OUT, "paired.csv"), index=False)

    # ---- 8. slope recovery (7.1)
    def slope_check(d):
        r = stats.linregress(d["pred_total"], d["obs_total"])
        return {"slope": float(r.slope), "intercept": float(r.intercept), "r2": float(r.rvalue ** 2),
                "se": float(r.stderr), "lo": float(r.slope - 1.96 * r.stderr),
                "hi": float(r.slope + 1.96 * r.stderr), "n": int(len(d)),
                "contains_1": bool(r.slope - 1.96 * r.stderr <= 1.0 <= r.slope + 1.96 * r.stderr)}
    slope_wf = slope_check(HM[HM.period == "walk_forward"])
    slope_ho = slope_check(HM[HM.period == "holdout"])
    slope_dev = slope_check(HM[HM.period == "dev2026"])
    print("slope recovery WF: %.4f [%.4f, %.4f] contains 1.0 = %s"
          % (slope_wf["slope"], slope_wf["lo"], slope_wf["hi"], slope_wf["contains_1"]))

    # ---- 9. per-bucket total PIT (7.2)
    bucket_rows = []
    for pname in ("walk_forward", "holdout", "dev2026"):
        d = periods[pname]
        for lo, hi, label in BUCKETS:
            s = d[(d["pred_total"] >= lo) & (d["pred_total"] < hi)]
            if len(s) < 10:
                bucket_rows.append({"period": pname, "bucket": label, "n": len(s),
                                    "mean_pit": float("nan"), "ks_p": float("nan")})
                continue
            ks = kstest(s.pit_total, "uniform")
            bucket_rows.append({"period": pname, "bucket": label, "n": int(len(s)),
                                "mean_pit": float(s.pit_total.mean()),
                                "ks_p": float(ks.pvalue)})
    BK = pd.DataFrame(bucket_rows)
    BK.to_csv(os.path.join(OUT, "bucket_pit.csv"), index=False)

    def get(period, metric, base):
        d = PR[(PR.period == period) & (PR.model == "H0b-MC") &
               (PR.metric == metric) & (PR.base == base)]
        return None if d.empty else d.iloc[0]

    wf_row = S[S.period == "walk_forward"].iloc[0]
    ho_row = S[S.period == "holdout"].iloc[0]
    g_dist_m = get("walk_forward", "crps_margin", "H1")
    g_dist_t = get("walk_forward", "crps_total", "H1")
    ho_dist_m = get("holdout", "crps_margin", "H1")
    ho_dist_t = get("holdout", "crps_total", "H1")
    gates = {}
    gates["G-SAMPLE"] = bool(wf_row.n >= 1500 and ho_row.n >= 250)
    gates["G-DIST"] = bool(g_dist_m is not None and g_dist_t is not None
                           and ho_dist_m is not None and ho_dist_t is not None
                           and g_dist_m.hi < 0 and g_dist_t.hi < 0
                           and ho_dist_m["mean"] < 0 and ho_dist_t["mean"] < 0)
    gates["G-CAL"] = bool(wf_row.pit_margin_ks > 0.05 and wf_row.pit_total_ks > 0.05
                          and ho_row.pit_margin_ks > 0.05 and ho_row.pit_total_ks > 0.05
                          and all(abs(wf_row["cov%d_margin" % L] - L / 100) <= 0.05 for L in (50, 80, 90))
                          and all(abs(wf_row["cov%d_total" % L] - L / 100) <= 0.05 for L in (50, 80, 90)))
    sp_c = get("walk_forward", "brier_spread", "Constant")
    sp_h = get("walk_forward", "brier_spread", "H1")
    sp_ho = get("holdout", "brier_spread", "H1")
    gates["G-SPREAD"] = bool(sp_c is not None and sp_h is not None and sp_ho is not None
                             and sp_c.hi < 0 and sp_h.hi < 0 and sp_ho["mean"] < 0)
    tt_c = get("walk_forward", "brier_total", "Constant")
    tt_h = get("walk_forward", "brier_total", "H1")
    tt_ho = get("holdout", "brier_total", "H1")
    gates["G-TOTAL"] = bool(tt_c is not None and tt_h is not None and tt_ho is not None
                            and tt_c.hi < 0 and tt_h.hi < 0 and tt_ho["mean"] < 0)

    # per-bucket reading (7.2): low > 0.55 or high < 0.45, n>=100, KS p<0.05
    bucket_fail = False
    bucket_detail = []
    for pname in ("walk_forward", "holdout"):
        for _, r in BK[BK.period == pname].iterrows():
            if r.n < 100 or not np.isfinite(r.mean_pit):
                continue
            bad = ((r.bucket == "<40" and r.mean_pit > 0.55) or
                   (r.bucket == ">70" and r.mean_pit < 0.45))
            fail = bool(bad and r.ks_p < 0.05)
            bucket_detail.append({"period": pname, "bucket": r.bucket, "n": int(r.n),
                                  "mean_pit": float(r.mean_pit), "ks_p": float(r.ks_p),
                                  "fail": fail})
            bucket_fail = bucket_fail or fail

    verdict = "ADOPTED" if (all(gates.values()) and slope_wf["contains_1"] and not bucket_fail) \
        else "NOT_ADOPTED"

    print("\n== gates (H0b-MC)")
    for k, v in gates.items():
        print("   %-10s %s" % (k, "PASS" if v else "FAIL"))
    print("   slope recovery contains 1.0: %s" % slope_wf["contains_1"])
    print("   per-bucket reading fail: %s" % bucket_fail)
    print("   VERDICT: %s" % verdict)

    # ---- 10. frozen JSON + manifest
    frozen_json = {
        "candidate": "H0b-MC",
        "prereg_commit": "680b259a",
        "run_date": "2026-10-19",
        "reproduction": {"season": 2023, "n": int(len(rep)),
                         "max_abs_diff": repro_max, "mean_abs_diff": repro_mean,
                         "gate_threshold": 1e-6, "passed": bool(repro_max <= 1e-6)},
        "calibration": C.to_dict(orient="records"),
        "population": {"walk_forward": int(len(periods["walk_forward"])),
                       "holdout": int(len(periods["holdout"])),
                       "dev2026": int(len(periods["dev2026"]))},
        "gates": gates,
        "slope_recovery": {"walk_forward": slope_wf, "holdout": slope_ho, "dev2026": slope_dev},
        "bucket_reading": {"fail": bucket_fail, "detail": bucket_detail},
        "verdict": verdict,
        "shift": {"max_abs_mean_error": float(SH["mean_error"].abs().max()),
                  "max_boundary_change": float(SH["boundary_change"].max()),
                  "failures": int(SH["failure"].sum()),
                  "max_iterations": int(SH["iterations"].max())},
        "margin_pmf_sha256": margin_hash,
        "files": {},
    }
    for name in ("calibration.csv", "per_game_shift.csv", "pmf/per_observation_scores.csv",
                 "summary_by_period.csv", "paired.csv", "bucket_pit.csv",
                 "pmf/h0bmc_pmf.npz"):
        path = os.path.join(OUT, name)
        frozen_json["files"][name] = {"sha256": sha256_file(path),
                                      "bytes": os.path.getsize(path)}
    with open(FROZEN_JSON, "w") as fh:
        json.dump(frozen_json, fh, indent=2, sort_keys=True)
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as fh:
        json.dump(frozen_json, fh, indent=2, sort_keys=True)

    print("\nwrote %s and %s" % (OUT, FROZEN_JSON))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
