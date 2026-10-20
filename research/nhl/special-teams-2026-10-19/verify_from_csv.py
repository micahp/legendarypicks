#!/usr/bin/env python3
"""CSV-only verifier — recompute every reported score from forecasts_all_arms.csv.

No model fit, no DuckDB, no feature build. Reads only:
  forecasts_all_arms.csv  (game_id, season, game_date, home_team, away_team,
                           model_variant, p_home, mu_h, mu_a, home_goals, away_goals)
Compares to the stored results JSONs and prints a reproduction table with the
maximum absolute difference per statistic. Exit 0 iff every stat is <= 1e-9.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SEED = 20261019
N_BOOT = 10_000
CAP = 21
TOL = 1e-9
ARMS = ("b5", "st", "v1", "v2")


def pmf(mu, cap=CAP):
    mu = max(float(mu), 1e-9)
    ks = np.arange(cap)
    p = np.exp(-mu + ks * math.log(mu) - np.array([math.lgamma(k + 1) for k in ks]))
    return p / p.sum()


def crps(p, y):
    F = np.cumsum(p)
    ks = np.arange(len(p))
    return float(np.sum((F - (ks >= y).astype(float)) ** 2))


def pit_ks(mus, obs):
    us = []
    for mu, y in zip(mus, obs):
        p = pmf(mu); F = np.cumsum(p)
        us.append((F[y - 1] if y > 0 else 0.0) + 0.5 * p[y])
    us = np.sort(np.array(us)); n = len(us)
    ks = max(abs((np.arange(1, n + 1) / n) - us).max(), abs(us - (np.arange(0, n) / n)).max())
    return float(ks), float(us.mean())


def main() -> int:
    rows = list(csv.DictReader(open(HERE / "forecasts_all_arms.csv")))
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["model_variant"]].append(r)
    for arm in ARMS:
        by_arm[arm].sort(key=lambda r: int(r["game_id"]))
    n = len(by_arm["st"])
    print(f"CSV-only verifier: {len(rows)} rows, {n} games, arms={list(ARMS)}")

    # per-arm scores
    scores = {}
    for arm in ARMS:
        brier = np.empty(n); ll = np.empty(n); c = np.empty(n); mae = np.empty(n)
        mus_h = []; obs_h = []; mus_a = []; obs_a = []
        for i, r in enumerate(by_arm[arm]):
            y = int(r["home_win"]); p = float(r["p_home"])
            hg = int(r["home_goals"]); ag = int(r["away_goals"])
            brier[i] = (p - y) ** 2
            ll[i] = -(y * math.log(p) + (1 - y) * math.log(1 - p))
            c[i] = (crps(pmf(r["mu_h"]), hg) + crps(pmf(r["mu_a"]), ag)) / 2
            mae[i] = (abs(float(r["mu_h"]) - hg) + abs(float(r["mu_a"]) - ag)) / 2
            mus_h.append(float(r["mu_h"])); obs_h.append(hg)
            mus_a.append(float(r["mu_a"])); obs_a.append(ag)
        kh, uh = pit_ks(mus_h, obs_h)
        ka, ua = pit_ks(mus_a, obs_a)
        scores[arm] = {"brier": float(brier.mean()), "log_loss": float(ll.mean()),
                       "crps": float(c.mean()), "mae": float(mae.mean()),
                       "pit_ks_home": kh, "pit_mean_home": uh,
                       "pit_ks_away": ka, "pit_mean_away": ua,
                       "_brier": brier, "_log_loss": ll, "_crps": c, "_mae": mae}

    # clustered bootstrap deltas vs a reference arm
    def delta_ci(cand, ref):
        out = {}
        for key in ("brier", "log_loss", "crps", "mae"):
            a = scores[ref]["_" + key]; b = scores[cand]["_" + key]
            d = a - b
            rng = np.random.default_rng(SEED)
            boots = np.empty(N_BOOT)
            for it in range(N_BOOT):
                idx = rng.integers(0, n, n)
                boots[it] = d[idx].mean()
            out[key] = {"delta": float(d.mean()),
                        "ci95_low": float(np.quantile(boots, 0.025)),
                        "ci95_high": float(np.quantile(boots, 0.975))}
        return out

    st_vs_b5 = delta_ci("st", "b5")
    v1_vs_st = delta_ci("v1", "st")
    v2_vs_st = delta_ci("v2", "st")

    # reported values
    rs = json.load(open(HERE / "results_special_teams.json"))["metrics"]
    rp = json.load(open(HERE / "results_penalty_volume.json"))

    checks = []
    def chk(name, recomputed, reported):
        d = abs(float(recomputed) - float(reported))
        checks.append((name, recomputed, reported, d))
        return d

    # --- ST experiment: B5 and ST, deltas, CIs ---
    for key in ("brier", "log_loss", "crps", "mae"):
        chk(f"ST: b5 {key}", scores["b5"][key], rs[key]["b5"])
        chk(f"ST: st {key}", scores["st"][key], rs[key]["st"])
        chk(f"ST: delta {key}", st_vs_b5[key]["delta"], rs[key]["delta_b5_minus_st"])
        chk(f"ST: ci_low {key}", st_vs_b5[key]["ci95_low"], rs[key]["ci95_low"])
        chk(f"ST: ci_high {key}", st_vs_b5[key]["ci95_high"], rs[key]["ci95_high"])

    # --- penalty experiment: V1, V2 vs ST ---
    for key in ("brier", "log_loss", "crps", "mae"):
        chk(f"PEN: st {key}", scores["st"][key], rp["v1"][key]["st"])
        chk(f"PEN: v1 {key}", scores["v1"][key], rp["v1"][key]["candidate"])
        chk(f"PEN: v1 delta {key}", v1_vs_st[key]["delta"], rp["v1"][key]["delta_st_minus_candidate"])
        chk(f"PEN: v1 ci_low {key}", v1_vs_st[key]["ci95_low"], rp["v1"][key]["ci95_low"])
        chk(f"PEN: v1 ci_high {key}", v1_vs_st[key]["ci95_high"], rp["v1"][key]["ci95_high"])
        chk(f"PEN: v2 {key}", scores["v2"][key], rp["v2"][key]["candidate"])
        chk(f"PEN: v2 delta {key}", v2_vs_st[key]["delta"], rp["v2"][key]["delta_st_minus_candidate"])
        chk(f"PEN: v2 ci_low {key}", v2_vs_st[key]["ci95_low"], rp["v2"][key]["ci95_low"])
        chk(f"PEN: v2 ci_high {key}", v2_vs_st[key]["ci95_high"], rp["v2"][key]["ci95_high"])

    # --- reported PIT/KS (doc values, 4 dp) ---
    reported_pit = {
        "b5": (0.0514, 0.5105, 0.0705, 0.5213),
        "st": (0.0438, 0.5069, 0.0606, 0.5179),
        "v1": (0.0440, 0.5098, 0.0607, 0.5206),
        "v2": (0.0440, 0.5098, 0.0606, 0.5206),
    }
    for arm, (kh, uh, ka, ua) in reported_pit.items():
        chk(f"PIT {arm} ks_home", scores[arm]["pit_ks_home"], kh)
        chk(f"PIT {arm} mean_home", scores[arm]["pit_mean_home"], uh)
        chk(f"PIT {arm} ks_away", scores[arm]["pit_ks_away"], ka)
        chk(f"PIT {arm} mean_away", scores[arm]["pit_mean_away"], ua)

    # --- print reproduction table ---
    print("\n| statistic | recomputed | reported | absdiff |")
    print("|---|---:|---:|---:|")
    worst = 0.0; worst_name = ""
    for name, r, rep, d in checks:
        flag = "" if d <= TOL else "  <-- MISMATCH"
        if d > worst:
            worst, worst_name = d, name
        # PIT values are reported to 4 dp, so compare at that resolution
        tol_here = 5e-5 if name.startswith("PIT ") else TOL
        print(f"| {name} | {r:.15g} | {rep:.15g} | {d:.2e}{flag if d > tol_here else ''} |")
    print(f"\nmax absdiff = {worst:.3e} ({worst_name})")

    # PIT reported at 4 dp -> tolerance 5e-5; all others 1e-9
    hard = [(nm, d) for nm, r, rep, d in checks if not nm.startswith("PIT ") and d > TOL]
    soft = [(nm, d) for nm, r, rep, d in checks if nm.startswith("PIT ") and d > 5e-5]
    ok = not hard and not soft
    print(f"non-PIT mismatches > 1e-9: {len(hard)}   PIT mismatches > 5e-5: {len(soft)}")
    print("REPRODUCTION:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
