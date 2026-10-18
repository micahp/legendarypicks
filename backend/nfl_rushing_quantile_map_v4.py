#!/usr/bin/env python3
"""nfl_rushing_quantile_map_v4.py -- fit the carry quantiles directly instead of assuming a family.

Pre-registered in docs/SPEC-nfl-rushing-participation-v4.md (2026-10-18, before any v4 code).

    B0    NB(m, R0)                                incumbent, unchanged
    Zf    v2's ZINB, single R                      reference, for continuity
    V4    empirical quantile map by tier + v2's pi  <- CANDIDATE
    V4u   the same anchors fitted unconditionally, no mixture   diagnostic reference, cannot be adopted

V4 assumes no distributional family. Seven anchors (5/10/25/50/75/90/95%) are fitted per usage tier on
training candidates who appeared, interpolated linearly in m between tier centres, monotone-clipped, and
turned into a discrete PMF through a piecewise-linear CDF. v2's participation probability supplies the zero
mass unchanged: P(0) = pi + (1-pi) P_app(0).

Gate: AGGREGATE coverage at 50/80/90, all six comparisons against B0 (unchanged from v1-v3). Per-tier
coverage is reported as a diagnostic and carries no adoption weight.

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 nfl_rushing_quantile_map_v4.py --eval-seasons 2025 2026 \
            --json ../docs/frozen-nfl-rushing-participation-v4.json
"""
import argparse
import json
import math
import os
import sqlite3
from collections import Counter

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2

LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
MAXK = v2.MAXK
P_FLOOR = v2.P_FLOOR
MIN_TIER_N = 30


# -- anchors ---------------------------------------------------------------------------------

def empirical_anchors(values, levels=LEVELS):
    xs = sorted(values)
    n = len(xs)
    out = []
    for q in levels:
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(n - 1, lo + 1)
        frac = pos - lo
        out.append(xs[lo] * (1 - frac) + xs[hi] * frac)
    return out


def fit_anchors(items, appeared_only=True):
    """Per tier: anchors, centre (mean m), n. Thin tiers fall back to the pooled anchors."""
    def pick(subset):
        return [i["y"] for i in subset if (i["appeared"] or not appeared_only)]

    pooled_vals = pick(items)
    pooled = {"anchors": empirical_anchors(pooled_vals), "n": len(pooled_vals)}
    table = {}
    for t in v2.TIERS:
        sub = [i for i in items if v2.tier_of(i["m"]) == t]
        vals = pick(sub)
        if len(vals) < MIN_TIER_N:
            table[t] = {"anchors": list(pooled["anchors"]), "centre": _centre(sub),
                        "n": len(vals), "fallback": True}
        else:
            table[t] = {"anchors": empirical_anchors(vals), "centre": _centre(sub),
                        "n": len(vals), "fallback": False}
    return table, pooled


def _centre(subset):
    ms = [i["m"] for i in subset]
    return sum(ms) / len(ms) if ms else 0.0


def anchors_for(m, table):
    """Linear interpolation in m between neighbouring tier centres; constant outside."""
    tiers = list(v2.TIERS)
    centres = [table[t]["centre"] for t in tiers]
    if m <= centres[0]:
        out = list(table[tiers[0]]["anchors"])
    elif m >= centres[-1]:
        out = list(table[tiers[-1]]["anchors"])
    else:
        out = None
        for a, b in zip(tiers, tiers[1:]):
            ca, cb = table[a]["centre"], table[b]["centre"]
            if ca <= m <= cb:
                w = (m - ca) / (cb - ca) if cb > ca else 0.0
                out = [x + w * (y - x) for x, y in
                       zip(table[a]["anchors"], table[b]["anchors"])]
                break
        if out is None:
            out = list(table[tiers[-1]]["anchors"])
    # monotone clip: the CDF must be non-decreasing
    clipped = []
    running = -1e9
    for v in out:
        running = max(running, v)
        clipped.append(running)
    return clipped


def pmf_from_anchors(anchors, maxk=MAXK):
    """Piecewise-linear CDF through (value, level) anchors, differenced into a PMF on 0..maxk."""
    a, lv = list(anchors), list(LEVELS)

    def F(x):
        if x < a[0]:
            return 0.0
        if x >= a[-1]:
            return 1.0
        for i in range(len(a) - 1):
            if a[i] <= x < a[i + 1]:
                span = a[i + 1] - a[i]
                frac = (x - a[i]) / span if span > 0 else 0.0
                return lv[i] + frac * (lv[i + 1] - lv[i])
        return 1.0

    pmf, prev = [], 0.0
    for k in range(maxk + 1):
        cur = F(float(k))
        pmf.append(max(0.0, cur - prev))
        prev = cur
    pmf[-1] += max(0.0, 1.0 - sum(pmf))
    total = sum(pmf)
    return [v / total for v in pmf] if total > 0 else pmf


def mix_zero(pmf_cond, p):
    """v2's zero layer: pi at zero, (1-pi) * conditional elsewhere."""
    p = min(max(p, P_FLOOR), 1.0)
    pi = 1.0 - p
    out = [v * p for v in pmf_cond]
    out[0] += pi
    return out


# -- models ----------------------------------------------------------------------------------

def pmf_for(model, item, fit):
    m = item["m"]
    if model == "B0":
        return v2.nb_pmf(m, fit["R0"])
    if model == "Zf":
        return v2.zinb_pmf(m, fit["R"], v2.p_of(item, fit["p_cross"], None))
    if model == "V4":
        cond = pmf_from_anchors(anchors_for(m, fit["anchors"]))
        return mix_zero(cond, v2.p_of(item, fit["p_cross"], None))
    if model == "V4u":
        return pmf_from_anchors(anchors_for(m, fit["anchors_uncond"]))
    raise ValueError(model)


def score(items, fit, models):
    rows = {}
    for i in items:
        for model in models:
            pmf = pmf_for(model, i, fit)
            cdf = v2.cdf_of(pmf)
            mu = v2.mean_of(pmf)
            pan = 1.0 - cdf[0]
            y = int(i["y"])
            rows[(model, i["game_id"], i["pid"])] = {
                "crps": v2.crps_discrete(cdf, i["y"]),
                "logloss": -math.log(max(pmf[y] if y < len(pmf) else 1e-12, 1e-12)),
                "cov50": v2.covered(cdf, i["y"], 0.5),
                "cov80": v2.covered(cdf, i["y"], 0.8),
                "cov90": v2.covered(cdf, i["y"], 0.9),
                "ae": abs(mu - i["y"]),
                "bias": mu - i["y"],
                "sd_pred": math.sqrt(sum((k - mu) ** 2 * v for k, v in enumerate(pmf))),
                "brier_any": (pan - (1.0 if i["y"] >= 1 else 0.0)) ** 2,
                "pan": pan, "y": i["y"], "pos": i["pos"], "week": i["week"],
                "appeared": i["appeared"],
            }
    return rows


def aggregate(rows, model, keys):
    n = len(keys)
    if not n:
        return None
    return {
        "n": n,
        "crps": sum(rows[(model,) + k]["crps"] for k in keys) / n,
        "logloss": sum(rows[(model,) + k]["logloss"] for k in keys) / n,
        "cov50": sum(rows[(model,) + k]["cov50"] for k in keys) / n,
        "cov80": sum(rows[(model,) + k]["cov80"] for k in keys) / n,
        "cov90": sum(rows[(model,) + k]["cov90"] for k in keys) / n,
        "mae": sum(rows[(model,) + k]["ae"] for k in keys) / n,
        "bias": sum(rows[(model,) + k]["bias"] for k in keys) / n,
        "sd_pred": sum(rows[(model,) + k]["sd_pred"] for k in keys) / n,
        "sd_obs": v2._sd([rows[(model,) + k]["y"] for k in keys]),
        "brier_any": sum(rows[(model,) + k]["brier_any"] for k in keys) / n,
        "auc_any": v2.auc([(rows[(model,) + k]["pan"], 1 if rows[(model,) + k]["y"] >= 1 else 0)
                           for k in keys]),
    }


def run_season(hist, eval_season, fit_seasons, weeks):
    train = []
    for s in fit_seasons:
        train.extend(v2.build_items(hist, s, weeks=weeks))
    items = v2.build_items(hist, eval_season, weeks=weeks)

    p_cross, _ = v2.fit_p_cross(train)
    R0, n0 = v2.fit_r(train, lambda i: 1.0)
    R_pooled, _ = v2.fit_r(train, lambda i: v2.p_of(i, p_cross, None))
    anchors, pooled = fit_anchors(train, appeared_only=True)
    anchors_u, pooled_u = fit_anchors(train, appeared_only=False)

    fit = {"R0": R0, "R": R_pooled, "p_cross": p_cross, "anchors": anchors,
           "anchors_uncond": anchors_u}
    models = ("B0", "Zf", "V4", "V4u")
    rows = score(items, fit, models)

    subsets = {
        "all (pregame candidates)": [(i["game_id"], i["pid"]) for i in items],
        "RB": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "RB"],
        "QB (not gated)": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "QB"],
    }
    report = {"eval_season": eval_season, "fit_seasons": fit_seasons,
              "weeks": [min(weeks), max(weeks)],
              "counts": {"train": len(train), "eval": len(items),
                         "eval_appeared": sum(1 for i in items if i["appeared"]),
                         "eval_status": dict(Counter(i["status"] or "none" for i in items))},
              "fit": {"R0": R0, "n_R0": n0, "R_pooled": R_pooled,
                      "anchors": {v2.TIER_LABEL[t]: {"anchors": [round(x, 3) for x in
                                                                  anchors[t]["anchors"]],
                                                     "centre": round(anchors[t]["centre"], 3),
                                                     "n": anchors[t]["n"],
                                                     "fallback": anchors[t]["fallback"]}
                                  for t in v2.TIERS},
                      "pooled_anchors": [round(x, 3) for x in pooled["anchors"]],
                      "uncond_anchors": {v2.TIER_LABEL[t]: [round(x, 3) for x in
                                                            anchors_u[t]["anchors"]]
                                         for t in v2.TIERS}},
              "tables": {}, "paired": {}, "tier_diagnostic": {}}
    for name, keys in subsets.items():
        for model in models:
            agg = aggregate(rows, model, keys)
            if agg:
                report["tables"]["%s|%s" % (name, model)] = agg
        if keys:
            report["tables"]["%s|obs" % name] = {"n": len(keys),
                                                 "sd_obs": aggregate(rows, "B0", keys)["sd_obs"]}
        for model in ("Zf", "V4", "V4u"):
            report["paired"]["%s|%s|B0" % (name, model)] = v2.paired_rows(rows, model, "B0", keys)

    # per-tier coverage: DIAGNOSTIC ONLY (the gate is aggregate)
    for t in v2.TIERS:
        keys = [(i["game_id"], i["pid"]) for i in items if v2.tier_of(i["m"]) == t]
        if not keys:
            continue
        report["tier_diagnostic"][v2.TIER_LABEL[t]] = {
            model: {k: round(aggregate(rows, model, keys)[k], 4)
                    for k in ("n", "cov50", "cov80", "cov90", "crps")}
            for model in models if aggregate(rows, model, keys)}
    return report


def _jsonable(obj):
    if isinstance(obj, dict):
        return {("%s" % (k if not isinstance(k, tuple) else "|".join(str(x) for x in k))):
                _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--eval-seasons", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--weeks", type=int, nargs=2, default=[3, 18])
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    weeks = set(range(a.weeks[0], a.weeks[1] + 1))
    seasons = list(range(2024, max(a.eval_seasons) + 1))
    hist = eng.History.load(con, seasons)
    print("loaded %d log rows, seasons %s" % (len(hist.rows), seasons))

    out = {"seasons": {}, "gates": {}}
    for eval_season in a.eval_seasons:
        fit_seasons = [s for s in seasons if s < eval_season]
        rep = run_season(hist, eval_season, fit_seasons, weeks)
        out["seasons"][str(eval_season)] = rep
        print("\n== %d (fit %s): %d candidates, %d appeared"
              % (eval_season, fit_seasons, rep["counts"]["eval"], rep["counts"]["eval_appeared"]))
        for label, d in rep["fit"]["anchors"].items():
            print("   %-9s n=%4d centre %5.2f anchors %s%s"
                  % (label, d["n"], d["centre"],
                     " ".join("%5.1f" % x for x in d["anchors"]),
                     "  (FALLBACK)" if d["fallback"] else ""))
        for name in ("all (pregame candidates)", "RB", "QB (not gated)"):
            print("\n   %s (n=%d)" % (name, rep["tables"]["%s|B0" % name]["n"]))
            print("     %-5s %8s %8s %6s %6s %6s %7s %7s %7s %8s %6s"
                  % ("model", "CRPS", "logloss", "cov50", "cov80", "cov90", "MAE", "sdP",
                     "sdObs", "Brier", "AUC"))
            for model in ("B0", "Zf", "V4", "V4u"):
                t = rep["tables"].get("%s|%s" % (name, model))
                if not t:
                    continue
                print("     %-5s %8.4f %8.4f %6.3f %6.3f %6.3f %7.4f %7.2f %7.2f %8.4f %6s"
                      % (model, t["crps"], t["logloss"], t["cov50"], t["cov80"], t["cov90"],
                         t["mae"], t["sd_pred"], t["sd_obs"], t["brier_any"],
                         ("%.4f" % t["auc_any"]) if t["auc_any"] is not None else "n/a"))
            for model in ("Zf", "V4", "V4u"):
                pr = rep["paired"].get("%s|%s|B0" % (name, model))
                if pr:
                    print("     paired %-4s - B0: %+.4f +/- %.4f (n=%d, %d games)"
                          % (model, pr["mean"], pr["ci"], pr["n"], pr["clusters"]))
        print("\n   per-tier coverage at 50/80/90 (DIAGNOSTIC, not gated):")
        for tier, d in rep["tier_diagnostic"].items():
            print("     %-9s %s" % (tier, "  ".join(
                "%s %.3f/%.3f/%.3f" % (m, d[m]["cov50"], d[m]["cov80"], d[m]["cov90"])
                for m in ("B0", "V4"))))

    print("\n== pre-registered gate: AGGREGATE coverage, all six comparisons")
    checks = {}
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        for level in ("cov50", "cov80", "cov90"):
            nominal = float(level[3:]) / 100.0
            v4v, b0 = t["all (pregame candidates)|V4"][level], t["all (pregame candidates)|B0"][level]
            ok = abs(v4v - nominal) < abs(b0 - nominal)
            checks["%d|%s" % (season, level)] = {"nominal": nominal, "B0": b0, "V4": v4v, "pass": ok}
            print("   %d %s: B0 %.3f  V4 %.3f  |err| %.3f vs %.3f  %s"
                  % (season, level, b0, v4v, abs(b0 - nominal), abs(v4v - nominal),
                     "PASS" if ok else "FAIL"))
    mae_ok = True
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        v4m, b0m = t["all (pregame candidates)|V4"]["mae"], t["all (pregame candidates)|B0"]["mae"]
        ok = v4m <= b0m + 0.02
        mae_ok = mae_ok and ok
        print("   %d MAE: B0 %.4f  V4 %.4f  %s" % (season, b0m, v4m, "PASS" if ok else "FAIL"))
    cov_ok = all(c["pass"] for c in checks.values())
    out["gates"] = {"coverage": checks, "coverage_pass": cov_ok, "mae_pass": mae_ok,
                    "verdict": "ADOPTED" if (cov_ok and mae_ok) else "NOT_ADOPTED"}
    print("\n   VERDICT: %s" % out["gates"]["verdict"])

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(_jsonable(out), fh, indent=2, sort_keys=True)
        print("\nwrote %s" % a.json)


if __name__ == "__main__":
    main()
