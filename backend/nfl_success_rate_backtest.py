#!/usr/bin/env python3
"""nfl_success_rate_backtest.py -- does success rate help the game model, over raw EPA?

Micah's framing, 2026-10-18: success rate IS the consistency measure -- how often a play succeeds --
so there is one candidate feature, not a success feature plus an SD-of-EPA feature.

Two models, identical construction, same pool, same targets, same games:

  M0  control   margin ~ EPA per play differentials (pass, rush) + home
                total  ~ EPA per play sum-differentials (pass, rush)
  M1  treatment M0 + success-rate differentials (pass, rush), and for the total the success-rate
                sum-differentials.

Each game is predicted from a regression fitted on every game BEFORE its week (chronological, no
shuffling, no future season). Ratings for a game come from plays before its week only
(`nfl_team_quality.ratings_for`). P(home win) = Normal(margin_hat, sigma) with sigma the residual SD
of the fit pool, population form.

Reported: Brier, log loss, MAE (margin and total), reliability and resolution on the winner
probability, and every M1 - M0 difference paired per game and clustered by week (games in the same
week share ratings, lines and conditions).

Read-only. Usage:
  LP_DB_PATH=... python3 nfl_success_rate_backtest.py [--test-seasons 2023 2024 2025]
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
from collections import defaultdict

import numpy as np

import nfl_team_quality as tq

WEEKS = range(3, 19)
MIN_POOL = 200
EPS = 1e-9


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def games(con, season, week):
    return con.execute(
        "SELECT game_id, home_team, away_team, home_score, away_score, spread_line, total_line "
        "FROM nfl_schedule WHERE season=? AND week=? AND game_type='REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL", (season, week)).fetchall()


def features(rat, home, away, mode):
    """Margin features (home minus away) and total features (both offenses versus both defenses).

    mode: 'epa' (control), 'succ' (success only, a diagnostic), 'both' (the treatment).
    """
    m, t = [], []
    for measure in (("epa",) if mode == "epa" else ("succ",) if mode == "succ" else ("epa", "succ")):
        for typ in ("pass", "rush"):
            m.append((rat.get(home, "%s_%s_off" % (measure, typ)) - rat.get(home, "%s_%s_def" % (measure, typ)))
                     - (rat.get(away, "%s_%s_off" % (measure, typ)) - rat.get(away, "%s_%s_def" % (measure, typ))))
            t.append(rat.get(home, "%s_%s_off" % (measure, typ)) + rat.get(away, "%s_%s_off" % (measure, typ))
                     - rat.get(home, "%s_%s_def" % (measure, typ)) - rat.get(away, "%s_%s_def" % (measure, typ)))
    return m, t


def design(rows, mode, target):
    """Design matrix and outcome for 'margin' or 'total'."""
    X, y = [], []
    for r in rows:
        m, t = features(r["rat"], r["home"], r["away"], mode)
        cols = m if target == "margin" else t
        X.append([1.0] + cols + ([1.0] if target == "margin" else []))   # home indicator, margin only
        y.append(r["margin"] if target == "margin" else r["total"])
    return np.array(X), np.array(y)


def fit_predict(pool, target, mode, pred_rows):
    X, y = design(pool, mode, target)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sigma = float(np.sqrt(np.mean(resid ** 2)))          # population form, stated in the report
    Xp, _ = design(pred_rows, mode, target)
    return Xp @ beta, sigma, beta


def metrics(rows, pm, pt, sigma):
    out = {"n": 0, "ties": 0, "brier": 0.0, "ll": 0.0, "mae_m": 0.0, "mae_t": 0.0,
           "bins": defaultdict(lambda: [0, 0.0, 0.0])}
    brier = ll = am = at = 0.0
    n = ties = 0
    for r, m, t in zip(rows, pm, pt):
        p = norm_cdf(m / sigma) if sigma > 0 else 0.5
        y = 1.0 if r["margin"] > 0 else 0.0
        am += abs(m - r["margin"])
        at += abs(t - r["total"])
        n += 1
        if r["margin"] == 0:
            ties += 1
        else:
            brier += (p - y) ** 2
            ll += -(y * math.log(min(max(p, EPS), 1 - EPS)) + (1 - y) * math.log(max(1 - p, EPS)))
            b = out["bins"][min(int(p * 10), 9)]
            b[0] += 1
            b[1] += p
            b[2] += y
    out.update(n=n, ties=ties, brier=brier / max(n - ties, 1), ll=ll / max(n - ties, 1),
               mae_m=am / n, mae_t=at / n)
    obs = sum(b[2] for b in out["bins"].values()) / max(sum(b[0] for b in out["bins"].values()), 1)
    rel = res = 0.0
    for cnt, sp, sy in out["bins"].values():
        if not cnt:
            continue
        rel += cnt * (sp / cnt - sy / cnt) ** 2
        res += cnt * (sy / cnt - obs) ** 2
    out["reliability"] = rel / max(n - ties, 1)
    out["resolution"] = res / max(n - ties, 1)
    return out


def bootstrap_week(diffs_by_week, reps=2000, seed=20261018):
    """Mean of per-game paired differences, clustered by week."""
    rng = np.random.default_rng(seed)
    weeks = list(diffs_by_week)
    allv = np.array([x for w in weeks for x in diffs_by_week[w]])
    point = float(allv.mean())
    means = []
    for _ in range(reps):
        pick = rng.choice(len(weeks), size=len(weeks), replace=True)
        vals = np.concatenate([diffs_by_week[weeks[i]] for i in pick])
        means.append(vals.mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return point, float(lo), float(hi), len(allv), len(weeks)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test-seasons", type=int, nargs="+", default=[2023, 2024, 2025])
    ap.add_argument("--k-succ", type=float, nargs="+", default=[150.0, 300.0, 600.0],
                    help="success-rate shrink values; 300 is the pre-registered value, the rest is a "
                         "sensitivity reported as-is")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)

    first, last = min(a.test_seasons) - 13, max(a.test_seasons)
    print("play filter, seasons %d-%d:" % (first, last))
    for k, v in tq.filters_report(con, first, last).items():
        print("  %-22s %8d" % (k, v))
    agg, n_read = tq.load_plays(con, first, last)
    print("  plays entering the ratings: %d" % n_read)

    results = {}
    for k_succ in a.k_succ:
        rows, preds = [], []
        neff_succ = []
        for season in range(first + 1, last + 1):
            for week in WEEKS:
                gs = games(con, season, week)
                if not gs:
                    continue
                rat = tq.ratings_for(agg, season, week, k_succ=k_succ)
                for team in {g[1] for g in gs} | {g[2] for g in gs}:
                    neff_succ.append(rat.n_eff.get((team, "succ_pass_off"), 0.0))
                for gid, home, away, hs, as_, spread, total in gs:
                    rows.append({"season": season, "week": week, "game_id": gid, "home": home,
                                 "away": away, "margin": hs - as_, "total": hs + as_, "rat": rat})
                if season not in a.test_seasons:
                    continue
                pool = [r for r in rows if (r["season"], r["week"]) < (season, week)]
                if len(pool) < MIN_POOL:
                    continue
                tgt = [r for r in rows if r["season"] == season and r["week"] == week]
                for name, mode in (("M0", "epa"), ("M1", "both"), ("S", "succ")):
                    pm, sig_m, _ = fit_predict(pool, "margin", mode, tgt)
                    pt, sig_t, _ = fit_predict(pool, "total", mode, tgt)
                    preds.append({"season": season, "week": week, "model": name,
                                  "rows": tgt, "pm": pm, "pt": pt, "sigma": sig_m,
                                  "sigma_t": sig_t})
        # score the two models on the identical games
        keyed = defaultdict(dict)
        for p in preds:
            for r, m, t in zip(p["rows"], p["pm"], p["pt"]):
                keyed[(p["season"], p["week"], p["model"])][r["game_id"]] = (r, float(m), float(t), p["sigma"])
        out = {}
        for name in ("M0", "M1", "S"):
            allkeys = sorted({k for (s, w, m) in keyed if m == name for k in keyed[(s, w, m)]})
            sub = [keyed[(s, w, name)][k] for (s, w, m) in sorted(keyed) if m == name for k in keyed[(s, w, m)]]
            out[name] = metrics([x[0] for x in sub], [x[1] for x in sub], [x[2] for x in sub], sub[0][3])
        # paired, by week
        diffs = {"brier": defaultdict(list), "ll": defaultdict(list), "mae_m": defaultdict(list),
                 "mae_t": defaultdict(list)}
        for arm in ("M1", "S"):
            dd = {k: defaultdict(list) for k in ("brier", "ll", "mae_m", "mae_t")}
            for (s, w, m) in list(keyed):
                if m != arm:
                    continue
                for gid, (r, m1, t1, sig) in keyed[(s, w, arm)].items():
                    if (s, w, "M0") not in keyed or gid not in keyed[(s, w, "M0")]:
                        continue
                    r0, m0, t0, _ = keyed[(s, w, "M0")][gid]
                    if r["margin"] == 0:
                        continue
                    p1 = norm_cdf(m1 / sig)
                    p0 = norm_cdf(m0 / sig)
                    y = 1.0 if r["margin"] > 0 else 0.0
                    dd["brier"][(s, w)].append((p1 - y) ** 2 - (p0 - y) ** 2)
                    e1, e0 = min(max(p1, EPS), 1 - EPS), min(max(p0, EPS), 1 - EPS)
                    dd["ll"][(s, w)].append(-(y * math.log(e1) + (1 - y) * math.log(1 - e1))
                                            + (y * math.log(e0) + (1 - y) * math.log(1 - e0)))
                    dd["mae_m"][(s, w)].append(abs(m1 - r["margin"]) - abs(m0 - r["margin"]))
                    dd["mae_t"][(s, w)].append(abs(t1 - r["total"]) - abs(t0 - r["total"]))
            diffs[arm] = dd
        results[k_succ] = (out, {arm: {k: bootstrap_week(v) for k, v in dd.items()}
                                 for arm, dd in diffs.items()},
                           float(np.median(neff_succ)) if neff_succ else 0.0)

    for k_succ, (out, bs, neff) in results.items():
        print("\n== success-rate shrink K = %.0f (median effective plays per team-week %.0f) ==" % (k_succ, neff))
        print("  %-4s %6s %5s %8s %8s %9s %9s %9s %9s" % (
            "model", "games", "ties", "Brier", "logloss", "MAE margin", "MAE total",
            "reliab", "resol"))
        for name in ("M0", "M1", "S"):
            m = out[name]
            print("  %-4s %6d %5d %8.4f %8.4f %9.3f %9.3f %9.5f %9.5f" % (
                name, m["n"], m["ties"], m["brier"], m["ll"], m["mae_m"], m["mae_t"],
                m["reliability"], m["resolution"]))
        for arm, label in (("M1", "M1 (EPA+success)"), ("S", "S (success only)")):
            print("  %s - M0, paired per game, clustered by week (negative = %s better):" % (label, arm))
            for k, lab in (("brier", "Brier winner"), ("ll", "logloss winner"), ("mae_m", "MAE margin"),
                           ("mae_t", "MAE total")):
                pt, lo, hi, n, g = bs[arm][k]
                print("    %-15s %+.5f  [%+.5f, %+.5f]  (n=%d, %d weeks)%s" % (
                    lab, pt, lo, hi, n, g, "" if lo * hi > 0 else "  spans zero"))


if __name__ == "__main__":
    main()
