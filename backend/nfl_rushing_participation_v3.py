#!/usr/bin/env python3
"""nfl_rushing_participation_v3.py -- does tiered dispersion fix v2's calibration?

Pre-registered in docs/SPEC-nfl-rushing-participation-v3.md (2026-10-18, before any v3 fit).

    B0      NB(m, R0)                            incumbent, unchanged
    Zd      pi[0] + (1-pi) NB(m/(1-pi), R)       v2 reference, designation-only p
    Zf      pi[0] + (1-pi) NB(m/(1-pi), R)       v2's candidate, single R (the thing being fixed)
    V3      pi[0] + (1-pi) NB(m/(1-pi), R_tier)  ONE change: R per usage tier   <- candidate
    B2ref   (1-pq)[0] + pq ZTNB(m/q, R_t)        v1's hurdle, reference

Everything except the dispersion is v2's, imported rather than rewritten: the participation cross, the
untruncated count component, mu = m/(1-pi), the CRPS/coverage/quantile code and the game-clustered paired
interval. Coverage at 50/80/90 is the primary gate, exactly as in v2.

Read-only on the DB. One command reproduces the result:

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 nfl_rushing_participation_v3.py --eval-seasons 2025 2026 \
            --json ../docs/frozen-nfl-rushing-participation-v3.json
"""
import argparse
import json
import math
import os
import sqlite3
from collections import Counter

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2

TIERS = v2.TIERS
TIER_LABEL = v2.TIER_LABEL
KAPPA = v2.KAPPA
P_FLOOR = v2.P_FLOOR
MIN_TIER_N = 30


def fit_r_tiered(items, p_fn):
    """Moment dispersion per usage tier, each floored at 0.5; thin tiers fall back to the pooled value."""
    pooled_R, _ = v2.fit_r(items, p_fn)
    out, counts = {}, {}
    for t in TIERS:
        num = den = 0.0
        n = 0
        for i in items:
            if not i["appeared"] or v2.tier_of(i["m"]) != t:
                continue
            p = min(max(p_fn(i), P_FLOOR), 1.0)
            mu = i["m"] / p
            num += mu ** 2
            den += (i["y"] - mu) ** 2 - mu
            n += 1
        counts[t] = n
        if n < MIN_TIER_N or den <= 0 or num <= 0:
            out[t] = pooled_R
            counts[t] = -n          # negative marks a fallback
        else:
            out[t] = max(0.5, num / den)
    return out, counts, pooled_R


def pmf_for(model, item, fit):
    m = item["m"]
    if model == "B0":
        return v2.nb_pmf(m, fit["R0"])
    if model == "Zd":
        return v2.zinb_pmf(m, fit["R"], v2.p_status_of(item, fit["p_status"]))
    if model == "Zf":
        return v2.zinb_pmf(m, fit["R"], v2.p_of(item, fit["p_cross"], None))
    if model == "V3":
        R = fit["R_tier"][v2.tier_of(m)]
        return v2.zinb_pmf(m, R, v2.p_of(item, fit["p_cross"], None))
    if model == "B2ref":
        q = max(fit["q"][v2.tier_of(m)], v2.Q_FLOOR)
        p = v2.p_status_of(item, fit["p_status"])
        return v2._hurdle(m, q, p, fit["R_t"])
    raise ValueError(model)


def score(items, fit, models):
    rows = {}
    for i in items:
        for model in models:
            pmf = pmf_for(model, i, fit)
            cdf = v2.cdf_of(pmf)
            mu = v2.mean_of(pmf)
            pan = 1.0 - cdf[0]
            rows[(model, i["game_id"], i["pid"])] = {
                "crps": v2.crps_discrete(cdf, i["y"]),
                "logloss": -math.log(max(pmf[int(i["y"])] if int(i["y"]) < len(pmf) else 1e-12,
                                        1e-12)),
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
    p_status, _ = v2.fit_p_status(train)
    p_fn = lambda i: v2.p_of(i, p_cross, None)  # noqa: E731
    R_tier, tier_n, pooled_R = fit_r_tiered(train, p_fn)
    R0, n0 = v2.fit_r(train, lambda i: 1.0)
    q, tier_q_n = v2.fit_q(train)
    R_t, rt_crps, n_rt = v2.fit_rt(train, q)

    fit = {"R0": R0, "R": pooled_R, "R_tier": R_tier, "p_cross": p_cross,
           "p_status": p_status, "q": q, "R_t": R_t}
    models = ("B0", "Zd", "Zf", "V3", "B2ref")
    rows = score(items, fit, models)

    subsets = {
        "all (pregame candidates)": [(i["game_id"], i["pid"]) for i in items],
        "RB": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "RB"],
        "QB (not gated)": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "QB"],
        "appeared only": [(i["game_id"], i["pid"]) for i in items if i["appeared"]],
    }
    report = {"eval_season": eval_season, "fit_seasons": fit_seasons,
              "weeks": [min(weeks), max(weeks)],
              "counts": {"train": len(train), "eval": len(items),
                         "eval_appeared": sum(1 for i in items if i["appeared"]),
                         "eval_status": dict(Counter(i["status"] or "none" for i in items))},
              "fit": {"R0": R0, "n_R0": n0, "R_pooled": pooled_R,
                      "R_tier": {TIER_LABEL[t]: R_tier[t] for t in TIERS},
                      "tier_n": {TIER_LABEL[t]: tier_n[t] for t in TIERS},
                      "R_t": R_t, "rt_crps": rt_crps, "n_rt": n_rt,
                      "q": {TIER_LABEL[t]: q[t] for t in TIERS},
                      "p_status": {k: round(v, 4) for k, v in p_status.items()}},
              "tables": {}, "paired": {}}
    for name, keys in subsets.items():
        for model in models:
            agg = aggregate(rows, model, keys)
            if agg:
                report["tables"]["%s|%s" % (name, model)] = agg
        if keys:
            report["tables"]["%s|obs" % name] = {"n": len(keys),
                                                 "sd_obs": aggregate(rows, "V3", keys)["sd_obs"]}
        for model in ("Zd", "Zf", "V3", "B2ref"):
            report["paired"]["%s|%s|B0" % (name, model)] = v2.paired_rows(rows, model, "B0", keys)
        report["paired"]["%s|V3|Zf" % name] = v2.paired_rows(rows, "V3", "Zf", keys)
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
        d = rep["fit"]
        print("\n== %d (fit %s): %d candidates, %d appeared"
              % (eval_season, fit_seasons, rep["counts"]["eval"], rep["counts"]["eval_appeared"]))
        print("   R0 %.3f | pooled R %.3f | R by tier %s | R_t %.2f"
              % (d["R0"], d["R_pooled"],
                 {k: round(v, 3) for k, v in d["R_tier"].items()}, d["R_t"]))
        print("   tier n %s" % d["tier_n"])
        for name in ("all (pregame candidates)", "RB", "QB (not gated)"):
            print("\n   %s (n=%d)" % (name, rep["tables"]["%s|B0" % name]["n"]))
            print("     %-6s %8s %8s %6s %6s %6s %7s %7s %8s %6s"
                  % ("model", "CRPS", "logloss", "cov50", "cov80", "cov90", "MAE", "sdP",
                     "Brier", "AUC"))
            for model in ("B0", "Zd", "Zf", "V3", "B2ref"):
                t = rep["tables"].get("%s|%s" % (name, model))
                if not t:
                    continue
                print("     %-6s %8.4f %8.4f %6.3f %6.3f %6.3f %7.4f %7.2f %8.4f %6s"
                      % (model, t["crps"], t["logloss"], t["cov50"], t["cov80"], t["cov90"],
                         t["mae"], t["sd_pred"], t["brier_any"],
                         ("%.4f" % t["auc_any"]) if t["auc_any"] is not None else "n/a"))
            for model in ("Zf", "V3"):
                pr = rep["paired"].get("%s|%s|B0" % (name, model))
                if pr:
                    print("     paired %-6s - B0: %+.4f +/- %.4f (n=%d, %d games)"
                          % (model, pr["mean"], pr["ci"], pr["n"], pr["clusters"]))
            pr = rep["paired"].get("%s|V3|Zf" % name)
            if pr:
                print("     paired   V3 - Zf: %+.4f +/- %.4f (tiered dispersion)"
                      % (pr["mean"], pr["ci"]))

    print("\n== pre-registered gate (coverage primary, all six comparisons)")
    checks = {}
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        for level in ("cov50", "cov80", "cov90"):
            nominal = float(level[3:]) / 100.0
            v3v, b0 = t["all (pregame candidates)|V3"][level], t["all (pregame candidates)|B0"][level]
            ok = abs(v3v - nominal) < abs(b0 - nominal)
            checks["%d|%s" % (season, level)] = {"nominal": nominal, "B0": b0, "V3": v3v, "pass": ok}
            print("   %d %s: B0 %.3f  V3 %.3f  |err| %.3f vs %.3f  %s"
                  % (season, level, b0, v3v, abs(b0 - nominal), abs(v3v - nominal),
                     "PASS" if ok else "FAIL"))
    mae_ok = True
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        v3m = t["all (pregame candidates)|V3"]["mae"]
        b0m = t["all (pregame candidates)|B0"]["mae"]
        ok = v3m <= b0m + 0.02
        mae_ok = mae_ok and ok
        print("   %d MAE: B0 %.4f  V3 %.4f  %s" % (season, b0m, v3m, "PASS" if ok else "FAIL"))
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
