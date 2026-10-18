#!/usr/bin/env python3
"""nfl_rushing_participation_v2.py -- does individualised P(plays) fix the zero mass?

Pre-registered in docs/SPEC-nfl-rushing-participation-v2.md (2026-10-18, before any v2 fit).
Population, target and weeks are v1's exactly; only the participation model and the count form change.

    B0      NB(m, R0)                          incumbent, no zero inflation
    Zd      pi[0] + (1-pi) NB(m/(1-pi), R)     single-inflation ZINB, designation-only p
    Zf      pi[0] + (1-pi) NB(m/(1-pi), R)     single-inflation ZINB, recent form x designation (PRIMARY)
    B2ref   (1-pq)[0] + pq ZTNB(m/q, R_t)      v1's hurdle, re-fitted here as a reference, not gated

pi = 1 - p, so the ZINB mean is exactly Spec B's frozen m: the point estimate never moves.
Coverage at 50/80/90 is the primary gate; CRPS is reported and does not gate.

Read-only on the DB. One command reproduces the whole result:

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 nfl_rushing_participation_v2.py --eval-seasons 2025 2026 \
            --json /root/lp-rushing-carries/docs/frozen-nfl-rushing-participation-v2.json
"""
import argparse
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict

import nfl_player_projection_v2 as eng

WEEKS = set(range(3, 19))
TIERS = ((0.0, 3.0), (3.0, 8.0), (8.0, float("inf")))
TIER_LABEL = {(0.0, 3.0): "m<3", (3.0, 8.0): "3<=m<8", (8.0, float("inf")): "m>=8"}
RT_GRID = (0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 55.0)
PARAMS = dict(eng.DEFAULTS, K_T=8.0)
P_LOG = eng.P_LOG_2024
MAXK = 160
KAPPA = 20.0          # shrinkage of the cross toward P_LOG, fixed by the audit's thin cells
P_FLOOR = 0.02        # keeps mu = m/(1-pi) finite
Q_FLOOR = 0.05


# -- distributions ---------------------------------------------------------------------------

def nb_pmf(m, R, maxk=MAXK):
    """NegBin with mean m and dispersion R: var = m + m^2/R."""
    if m <= 0:
        out = [0.0] * (maxk + 1)
        out[0] = 1.0
        return out
    r = max(float(R), 1e-6)
    q = r / (r + m)
    log_q, log_1q = math.log(q), math.log1p(-q)
    lg_r = math.lgamma(r)
    out, total = [0.0] * (maxk + 1), 0.0
    for k in range(maxk + 1):
        lg = math.lgamma(k + r) - math.lgamma(k + 1) - lg_r
        v = math.exp(lg + r * log_q + k * log_1q)
        out[k] = v
        total += v
    if total > 0:
        out = [v / total for v in out]
    return out


def zinb_pmf(m, R, p, maxk=MAXK):
    """Single inflation: (1-p) at zero, p * NB(m/p, R) elsewhere. Mean stays m; untruncated."""
    p = min(max(p, P_FLOOR), 1.0)
    pi = 1.0 - p
    nb = nb_pmf(m / p, R, maxk)
    out = [v * p for v in nb]
    out[0] += pi
    return out


def ztnb_pmf(mu, R, maxk=MAXK):
    p = nb_pmf(mu, R, maxk)
    z = 1.0 - p[0]
    if z <= 0:
        out = [0.0] * (maxk + 1)
        out[0] = 1.0
        return out
    return [0.0] + [v / z for v in p[1:]]


def cdf_of(pmf):
    out, acc = [], 0.0
    for v in pmf:
        acc += v
        out.append(min(1.0, acc))
    if out:
        out[-1] = 1.0
    return out


def crps_discrete(cdf, y):
    s = 0.0
    for k, f in enumerate(cdf):
        s += (f - (0.0 if k < y else 1.0)) ** 2
    if y > len(cdf) - 1:
        s += (y - len(cdf) + 1)
    return s


def q_lower(cdf, level):
    target = (1.0 - level) / 2.0
    for k, f in enumerate(cdf):
        if f >= target:
            return k
    return len(cdf) - 1


def q_upper(cdf, level):
    target = 1.0 - (1.0 - level) / 2.0
    for k, f in enumerate(cdf):
        if f >= target:
            return k
    return len(cdf) - 1


def covered(cdf, y, level):
    return 1.0 if q_lower(cdf, level) <= y <= q_upper(cdf, level) else 0.0


def mean_of(pmf):
    return sum(k * v for k, v in enumerate(pmf))


def _sd(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    mu = sum(vals) / n
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / n)


# -- population ------------------------------------------------------------------------------

def build_items(hist, season, weeks=WEEKS, positions=("RB", "QB")):
    """v1's population: every Spec B candidate with a positive carry mean, and his realised carries."""
    out = []
    for (s, team), team_weeks in hist.team_weeks.items():
        if s != season:
            continue
        for week in sorted(team_weeks):
            if week not in weeks:
                continue
            rows = hist.by_team[(s, team)][week]
            if not rows:
                continue
            game_id, opp = rows[0].game_id, rows[0].opp
            actual = {r.pid: r.car for r in rows}
            status = hist.status.get((s, game_id, team), {})
            for pid, pos in hist.candidates(s, team, week).items():
                if pos not in positions:
                    continue
                got = eng.opportunities(hist, s, week, pid, pos, team, opp, game_id, "car", PARAMS)
                if not got or got[0] <= 0:
                    continue
                entry = status.get(pid, (None, None))
                k, last = hist.recent_form(s, team, week, pid)
                out.append({"season": s, "week": week, "team": team, "game_id": game_id,
                            "pid": pid, "pos": pos, "m": got[0], "y": actual.get(pid, 0),
                            "appeared": pid in actual, "status": entry[0] or "",
                            "played_flag": entry[1], "k": k, "last": last,
                            "p_log": hist.p_log(s, team, week, pid, P_LOG)})
    return out


# -- fitting ---------------------------------------------------------------------------------

def fit_p_cross(items):
    """p by (k, last, status), shrunk toward Spec B's P_LOG cell value."""
    app, tot = Counter(), Counter()
    for i in items:
        key = (i["k"], i["last"], i["status"])
        tot[key] += 1
        if i["appeared"]:
            app[key] += 1
    table = {}
    for key, n in tot.items():
        prior = P_LOG.get("%d%d" % (key[0], key[1]), 0.75)
        table[key] = (app[key] + KAPPA * prior) / (n + KAPPA)
    return table, dict(tot)


def fit_p_status(items):
    app, tot = Counter(), Counter()
    for i in items:
        tot[i["status"]] += 1
        if i["appeared"]:
            app[i["status"]] += 1
    rates = {s: app[s] / tot[s] for s in tot if tot[s]}
    n_all, k_all = sum(tot.values()), sum(app.values())
    rates["__pooled__"] = k_all / n_all if n_all else 1.0
    return rates, dict(tot)


def p_of(item, table, fallback):
    key = (item["k"], item["last"], item["status"])
    if key in table:
        return table[key]
    if "__pooled__" in table:  # cross tables have no pooled entry; status tables do
        return table[fallback] if fallback in table else table["__pooled__"]
    return P_LOG.get("%d%d" % (item["k"], item["last"]), 0.75)


def p_status_of(item, rates):
    return rates.get(item["status"], rates["__pooled__"])


def fit_r(items, p_fn):
    """Method of moments on candidates who appeared, with mu = m/(1-pi)."""
    num = den = 0.0
    n = 0
    for i in items:
        if not i["appeared"]:
            continue
        p = min(max(p_fn(i), P_FLOOR), 1.0)
        mu = i["m"] / p
        num += mu ** 2
        den += (i["y"] - mu) ** 2 - mu
        n += 1
    if den <= 0 or num <= 0:
        return 0.5, n
    return max(0.5, num / den), n


def fit_q(items):
    pos, tot = Counter(), Counter()
    for i in items:
        if not i["appeared"]:
            continue
        t = tier_of(i["m"])
        tot[t] += 1
        if i["y"] >= 1:
            pos[t] += 1
    return {t: (pos[t] / tot[t] if tot[t] else 1.0) for t in TIERS}, dict(tot)


def fit_rt(items, q):
    best = None
    for R in RT_GRID:
        tot, n = 0.0, 0
        for i in items:
            if not i["appeared"] or i["y"] < 1:
                continue
            qq = max(q[tier_of(i["m"])], Q_FLOOR)
            tot += crps_discrete(cdf_of(ztnb_pmf(i["m"] / qq, R)), i["y"])
            n += 1
        if not n:
            continue
        score = tot / n
        if best is None or score < best[0]:
            best = (score, R, n)
    return (best[1], best[0], best[2]) if best else (8.0, float("nan"), 0)


def tier_of(m):
    for lo, hi in TIERS:
        if lo <= m < hi:
            return (lo, hi)
    return TIERS[-1]


# -- scoring ---------------------------------------------------------------------------------

def pmf_for(model, item, fit):
    m = item["m"]
    if model == "B0":
        return nb_pmf(m, fit["R0"])
    if model == "Zd":
        return zinb_pmf(m, fit["R"], p_status_of(item, fit["p_status"]))
    if model == "Zf":
        return zinb_pmf(m, fit["R"], p_of(item, fit["p_cross"], None))
    if model == "B2ref":
        q = max(fit["q"][tier_of(m)], Q_FLOOR)
        p = p_status_of(item, fit["p_status"])
        return _hurdle(m, q, p, fit["R_t"])
    raise ValueError(model)


def _hurdle(m, q, p, R_t):
    pmf = ztnb_pmf(m / q, R_t)
    out = [v * p * q for v in pmf]
    out[0] = 1.0 - p * q
    return out


def score(items, fit, models):
    rows = {}
    for i in items:
        for model in models:
            pmf = pmf_for(model, i, fit)
            cdf = cdf_of(pmf)
            mu = mean_of(pmf)
            pan = 1.0 - cdf[0]
            rows[(model, i["game_id"], i["pid"])] = {
                "crps": crps_discrete(cdf, i["y"]),
                "logloss": -math.log(max(pmf[int(i["y"])] if int(i["y"]) < len(pmf) else 1e-12,
                                        1e-12)),
                "cov50": covered(cdf, i["y"], 0.5),
                "cov80": covered(cdf, i["y"], 0.8),
                "cov90": covered(cdf, i["y"], 0.9),
                "ae": abs(mu - i["y"]),
                "bias": mu - i["y"],
                "sd_pred": math.sqrt(sum((k - mu) ** 2 * v for k, v in enumerate(pmf))),
                "brier_any": (pan - (1.0 if i["y"] >= 1 else 0.0)) ** 2,
                "pan": pan, "y": i["y"], "pos": i["pos"], "week": i["week"],
                "appeared": i["appeared"],
            }
    return rows


def auc(pairs):
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda x: x[0])
    ranks, i = {}, 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_pos = sum(ranks[k] for k, (s, y) in enumerate(ordered) if y == 1)
    n1, n0 = len(pos), len(neg)
    return (r_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0)


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
        "sd_obs": _sd([rows[(model,) + k]["y"] for k in keys]),
        "brier_any": sum(rows[(model,) + k]["brier_any"] for k in keys) / n,
        "auc_any": auc([(rows[(model,) + k]["pan"], 1 if rows[(model,) + k]["y"] >= 1 else 0)
                        for k in keys]),
    }


def paired_rows(rows, model, base, keys):
    diffs, clusters = [], defaultdict(list)
    for key in keys:
        d = rows[(model,) + key]["crps"] - rows[(base,) + key]["crps"]
        diffs.append(d)
        clusters[key[0]].append(d)
    n = len(diffs)
    if n == 0:
        return None
    mean = sum(diffs) / n
    G = len(clusters)
    if G < 2:
        return {"mean": mean, "ci": 0.0, "n": n, "clusters": G}
    var = G / (G - 1.0) * sum((sum(v) - len(v) * mean) ** 2 for v in clusters.values()) / n ** 2
    return {"mean": mean, "ci": 1.96 * math.sqrt(var), "n": n, "clusters": G}


# -- main ------------------------------------------------------------------------------------

def run_season(hist, eval_season, fit_seasons, weeks, frozen=None):
    train = []
    for s in fit_seasons:
        train.extend(build_items(hist, s, weeks=weeks))
    items = build_items(hist, eval_season, weeks=weeks)

    p_cross, cross_n = fit_p_cross(train)
    p_status, status_n = fit_p_status(train)

    def p_primary(i):
        return p_of(i, p_cross, None)

    def p_designation(i):
        return p_status_of(i, p_status)

    if frozen:
        fit = {"R0": frozen["R0"], "R": frozen["R"],
               "p_cross": {tuple(json.loads(k)): v for k, v in frozen["p_cross"].items()},
               "p_status": frozen["p_status"],
               "q": {t: frozen["q"][TIER_LABEL[t]] for t in TIERS},
               "R_t": frozen["R_t"]}
        diagnostics = {"frozen": True}
    else:
        R0, n0 = fit_r(train, lambda i: 1.0)
        R_zinb, n1 = fit_r(train, p_primary)
        q, tier_n = fit_q(train)
        R_t, rt_crps, n_rt = fit_rt(train, q)
        fit = {"R0": R0, "R": R_zinb, "p_cross": p_cross, "p_status": p_status,
               "q": q, "R_t": R_t}
        diagnostics = {"R0": R0, "n_R0": n0, "R": R_zinb, "n_R": n1,
                       "q": {TIER_LABEL[t]: q[t] for t in TIERS}, "tier_n": tier_n,
                       "R_t": R_t, "rt_crps": rt_crps, "n_rt": n_rt,
                       "cross_cells": {"%d%d|%s" % k: round(v, 4) for k, v in p_cross.items()},
                       "cross_n": {"%d%d|%s" % k: v for k, v in cross_n.items()},
                       "p_status": {k: round(v, 4) for k, v in p_status.items()}}

    models = ("B0", "Zd", "Zf", "B2ref")
    rows = score(items, fit, models)
    subsets = {
        "all (pregame candidates)": [(i["game_id"], i["pid"]) for i in items],
        "RB": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "RB"],
        "QB (not gated)": [(i["game_id"], i["pid"]) for i in items if i["pos"] == "QB"],
        "appeared only": [(i["game_id"], i["pid"]) for i in items if i["appeared"]],
        "wk3-5 only": [(i["game_id"], i["pid"]) for i in items if i["week"] <= 5],
    }
    report = {"eval_season": eval_season, "fit_seasons": fit_seasons,
              "weeks": [min(weeks), max(weeks)],
              "counts": {"train": len(train), "eval": len(items),
                         "eval_appeared": sum(1 for i in items if i["appeared"]),
                         "eval_status": dict(Counter(i["status"] or "none" for i in items))},
              "fit": {k: v for k, v in diagnostics.items()},
              "tables": {}, "paired": {}}
    for name, keys in subsets.items():
        keys = [k for k in keys]
        for model in models:
            agg = aggregate(rows, model, keys)
            if agg:
                report["tables"]["%s|%s" % (name, model)] = agg
        if keys:
            obs = aggregate(rows, "B0", keys)
            report["tables"]["%s|obs" % name] = {"n": obs["n"], "sd_obs": obs["sd_obs"]}
        for model in ("Zd", "Zf", "B2ref"):
            report["paired"]["%s|%s|B0" % (name, model)] = paired_rows(rows, model, "B0", keys)
        report["paired"]["%s|Zf|Zd" % name] = paired_rows(rows, "Zf", "Zd", keys)
    return report


def _jsonable(obj):
    """Recursively make keys JSON-safe (the cross table is keyed by (k, last, status) tuples)."""
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
        if not d.get("frozen"):
            print("   R0 %.3f (%d appeared) | R %.3f (%d) | R_t %.2f | q %s"
                  % (d["R0"], d["n_R0"], d["R"], d["n_R"], d["R_t"],
                     {k: round(v, 3) for k, v in d["q"].items()}))
            print("   p by status %s" % {k: round(v, 3) for k, v in d["p_status"].items()
                                         if not k.startswith("__")})
        for name in ("all (pregame candidates)", "RB", "QB (not gated)"):
            print("\n   %s (n=%d)" % (name, rep["tables"]["%s|B0" % name]["n"]))
            print("     %-6s %8s %8s %6s %6s %6s %7s %7s %8s %8s %6s"
                  % ("model", "CRPS", "logloss", "cov50", "cov80", "cov90", "MAE", "sdP",
                     "bias", "Brier", "AUC"))
            for model in ("B0", "Zd", "Zf", "B2ref"):
                t = rep["tables"].get("%s|%s" % (name, model))
                if not t:
                    continue
                print("     %-6s %8.4f %8.4f %6.3f %6.3f %6.3f %7.4f %7.2f %+8.4f %8.4f %6s"
                      % (model, t["crps"], t["logloss"], t["cov50"], t["cov80"], t["cov90"],
                         t["mae"], t["sd_pred"], t["bias"], t["brier_any"],
                         ("%.4f" % t["auc_any"]) if t["auc_any"] is not None else "n/a"))
            for model in ("Zd", "Zf", "B2ref"):
                pr = rep["paired"].get("%s|%s|B0" % (name, model))
                if pr:
                    print("     paired %-6s - B0: %+.4f +/- %.4f (n=%d, %d games)"
                          % (model, pr["mean"], pr["ci"], pr["n"], pr["clusters"]))
            pr = rep["paired"].get("%s|Zf|Zd" % name)
            if pr:
                print("     paired Zf - Zd: %+.4f +/- %.4f (recent-form participation)"
                      % (pr["mean"], pr["ci"]))

    # pre-registered gate: coverage primary on all six comparisons, MAE secondary
    print("\n== pre-registered gate (coverage primary)")
    checks = {}
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        for level in ("cov50", "cov80", "cov90"):
            nominal = float(level[3:]) / 100.0
            zf, b0 = t["all (pregame candidates)|Zf"][level], t["all (pregame candidates)|B0"][level]
            ok = abs(zf - nominal) < abs(b0 - nominal)
            checks["%d|%s" % (season, level)] = {"nominal": nominal, "B0": b0, "Zf": zf, "pass": ok}
            print("   %d %s: B0 %.3f  Zf %.3f  |err| %.3f vs %.3f  %s"
                  % (season, level, b0, zf, abs(b0 - nominal), abs(zf - nominal),
                     "PASS" if ok else "FAIL"))
    mae_ok = True
    for season in a.eval_seasons:
        t = out["seasons"][str(season)]["tables"]
        zf = t["all (pregame candidates)|Zf"]["mae"]
        b0 = t["all (pregame candidates)|B0"]["mae"]
        ok = zf <= b0 + 0.02
        mae_ok = mae_ok and ok
        print("   %d MAE: B0 %.4f  Zf %.4f  %s" % (season, b0, zf, "PASS" if ok else "FAIL"))
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
