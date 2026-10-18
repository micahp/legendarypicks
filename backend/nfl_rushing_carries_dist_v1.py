#!/usr/bin/env python3
"""nfl_rushing_carries_dist_v1.py -- does modeling participation and carry-count
uncertainty explicitly improve the distribution Spec B produces for rushing carries?

Pre-registered in docs/SPEC-nfl-rushing-carries-dist-v1.md (2026-10-17, corrected the same
day before any valid holdout number). Spec B's carry point estimate is frozen; only the
shape of the distribution around it changes.

    B0   NB(m, R)                              incumbent shape, no participation
    B1   (1-p)[0] + p NB(m, R)                 participation
    B2   (1-pq)[0] + pq ZTNB(m/q, R_t)         participation + role-aware hurdle
    B2'  (1-q)[0] + q ZTNB(m/q, R_t)           hurdle only (played subset, attribution)

Conditioning matters and is the whole experiment: `m` is Spec B's mean **given he plays**.
`p` is P(plays | designation), `q` is P(carries >= 1 | plays), so `q * ZTNB(m/q)` has mean
`m` and `p * m` is the unconditional mean. All PMFs are analytic, so CRPS, coverage and
quantiles carry no simulation error.

Read-only on the DB. Usage:

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 nfl_rushing_carries_dist_v1.py --eval-season 2025 \
            --fit-seasons 2024 --json /tmp/rush_2025.json
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
MAXK = 160
Q_FLOOR = 0.05
COLS = ("RB", "QB")


# -- distributions ---------------------------------------------------------------------------

def nb_pmf(m, R, maxk=MAXK):
    """NegBin with mean m and dispersion R: var = m + m^2 / R."""
    if m <= 0:
        p = [0.0] * (maxk + 1)
        p[0] = 1.0
        return p
    r = max(float(R), 1e-6)
    q = r / (r + m)
    log_q, log_1q = math.log(q), math.log1p(-q)
    lg_r = math.lgamma(r)
    out = [0.0] * (maxk + 1)
    total = 0.0
    for k in range(maxk + 1):
        lg = math.lgamma(k + r) - math.lgamma(k + 1) - lg_r
        v = math.exp(lg + r * log_q + k * log_1q)
        out[k] = v
        total += v
    if total > 0:
        out = [v / total for v in out]
    return out


def ztnb_pmf(mu, R, maxk=MAXK):
    """NegBin with mean mu, truncated to k >= 1 and renormalised."""
    p = nb_pmf(mu, R, maxk)
    z = 1.0 - p[0]
    if z <= 0:
        out = [0.0] * (maxk + 1)
        out[0] = 1.0
        return out
    return [0.0] + [v / z for v in p[1:]]


def mixture_zero(pmf, keep):
    """(1-keep) at zero, keep * pmf elsewhere."""
    out = [v * keep for v in pmf]
    out[0] = 1.0 - keep + pmf[0] * keep
    return out


def cdf_of(pmf):
    out, acc = [], 0.0
    for v in pmf:
        acc += v
        out.append(min(1.0, acc))
    if out:
        out[-1] = 1.0
    return out


def crps_discrete(cdf, y):
    """CRPS = sum_k (F(k) - 1{y <= k})^2 over the integer support."""
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


# -- parameter fitting -----------------------------------------------------------------------

def tier_of(m):
    for lo, hi in TIERS:
        if lo <= m < hi:
            return (lo, hi)
    return TIERS[-1]


def fit_r(items):
    """Method of moments over games he played: var = m + m^2 / R."""
    num = den = 0.0
    n = 0
    for i in items:
        if i["played_flag"] != 1:
            continue
        num += i["m"] ** 2
        den += (i["y"] - i["m"]) ** 2 - i["m"]
        n += 1
    if den <= 0 or num <= 0:
        return 0.5, n
    return max(0.5, num / den), n


def fit_q(items):
    """P(carries >= 1 | plays), by usage tier of the projected mean."""
    pos, tot = Counter(), Counter()
    for i in items:
        if i["played_flag"] != 1:
            continue
        t = tier_of(i["m"])
        tot[t] += 1
        if i["y"] >= 1:
            pos[t] += 1
    return {t: (pos[t] / tot[t] if tot[t] else 1.0) for t in TIERS}, dict(tot)


def fit_p(items):
    """P(plays | report designation) on the candidate population itself."""
    pos, tot = Counter(), Counter()
    for i in items:
        if i["played_flag"] is None:
            continue
        tot[i["status"]] += 1
        if i["played_flag"] == 1:
            pos[i["status"]] += 1
    rates = {s: pos[s] / tot[s] for s in tot if tot[s]}
    n_all, k_all = sum(tot.values()), sum(pos.values())
    rates["__pooled__"] = k_all / n_all if n_all else 1.0
    return rates, dict(tot)


def fit_rt(items, q):
    """Dispersion of the zero-truncated NegBin, by minimum CRPS on games with a carry."""
    best = None
    for R in RT_GRID:
        tot, n = 0.0, 0
        for i in items:
            if i["played_flag"] != 1 or i["y"] < 1:
                continue
            t = tier_of(i["m"])
            qq = max(q[t], Q_FLOOR)
            tot += crps_discrete(cdf_of(ztnb_pmf(i["m"] / qq, R)), i["y"])
            n += 1
        if not n:
            continue
        score = tot / n
        if best is None or score < best[0]:
            best = (score, R, n)
    return (best[1], best[0], best[2]) if best else (8.0, float("nan"), 0)


# -- population ------------------------------------------------------------------------------

def build_items(hist, season, positions=COLS, weeks=None):
    """Every Spec B candidate with a positive carry mean, and his realized carries."""
    weeks = weeks or WEEKS
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
                out.append({"season": s, "week": week, "team": team, "opp": opp,
                            "game_id": game_id, "pid": pid, "pos": pos,
                            "m": got[0], "y": actual.get(pid, 0),
                            "appeared": pid in actual,
                            "status": entry[0] or "",
                            "played_flag": entry[1]})
    return out


# -- models ----------------------------------------------------------------------------------

def p_for(fit, status):
    if status in fit["p"]:
        return fit["p"][status]
    return fit["p"]["__pooled__"]


def pmf_for(model, item, fit):
    m = item["m"]
    t = tier_of(m)
    q = max(fit["q"][t], Q_FLOOR)
    p = p_for(fit, item["status"])
    if model == "B0":
        return nb_pmf(m, fit["R"])
    if model == "B1":
        return mixture_zero(nb_pmf(m, fit["R"]), p)
    if model == "B2":
        return mixture_zero(ztnb_pmf(m / q, fit["R_t"]), p * q)
    if model == "B2p":
        return mixture_zero(ztnb_pmf(m / q, fit["R_t"]), q)
    raise ValueError(model)


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
                "cov50": covered(cdf, i["y"], 0.5),
                "cov80": covered(cdf, i["y"], 0.8),
                "cov90": covered(cdf, i["y"], 0.9),
                "ae": abs(mu - i["y"]),
                "bias": mu - i["y"],
                "sd_pred": math.sqrt(sum((k - mu) ** 2 * v for k, v in enumerate(pmf))),
                "brier_any": (pan - (1.0 if i["y"] >= 1 else 0.0)) ** 2,
                "pan": pan, "y": i["y"], "pos": i["pos"], "appeared": i["appeared"],
                "week": i["week"], "played_flag": i["played_flag"],
            }
    return rows


def auc(pairs):
    """Rank AUC with tie handling; pairs = [(score, label)]."""
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
        "crps": sum(rows[(model, g, p)]["crps"] for g, p in keys) / n,
        "cov50": sum(rows[(model, g, p)]["cov50"] for g, p in keys) / n,
        "cov80": sum(rows[(model, g, p)]["cov80"] for g, p in keys) / n,
        "cov90": sum(rows[(model, g, p)]["cov90"] for g, p in keys) / n,
        "mae": sum(rows[(model, g, p)]["ae"] for g, p in keys) / n,
        "bias": sum(rows[(model, g, p)]["bias"] for g, p in keys) / n,
        "sd_pred": sum(rows[(model, g, p)]["sd_pred"] for g, p in keys) / n,
        "sd_obs": _sd([rows[(model, g, p)]["y"] for g, p in keys]),
        "brier_any": sum(rows[(model, g, p)]["brier_any"] for g, p in keys) / n,
        "auc_any": auc([(rows[(model, g, p)]["pan"], 1 if rows[(model, g, p)]["y"] >= 1 else 0)
                        for g, p in keys]),
    }


def paired_rows(rows, model, base, keys):
    """Per-player-game CRPS difference (model - base), clustered by game."""
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--eval-season", type=int, required=True)
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True,
                    help="seasons with availability, strictly before the evaluation season")
    ap.add_argument("--weeks", type=int, nargs=2, default=[3, 18],
                    help="evaluation week window, inclusive (default 3 18)")
    ap.add_argument("--frozen", help="a previous run's JSON: use its fitted parameters, do not refit")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)

    fit_seasons = [s for s in a.fit_seasons if s < a.eval_season]
    if not fit_seasons:
        raise SystemExit("no fit seasons before the evaluation season")
    weeks = set(range(a.weeks[0], a.weeks[1] + 1))
    hist = eng.History.load(con, sorted(set(fit_seasons + [a.eval_season])))
    print("loaded %d log rows: fit %s, eval %d weeks %d-%d"
          % (len(hist.rows), fit_seasons, a.eval_season, a.weeks[0], a.weeks[1]))

    train_items = []
    for s in fit_seasons:
        train_items.extend(build_items(hist, s, weeks=weeks))
    eval_items = build_items(hist, a.eval_season, weeks=weeks)
    played = sum(1 for i in train_items if i["played_flag"] == 1)
    print("training candidate-games %d (%d played); eval %d (%d played)"
          % (len(train_items), played, len(eval_items),
             sum(1 for i in eval_items if i["played_flag"] == 1)))

    if a.frozen:
        with open(a.frozen) as fh:
            prior = json.load(fh)["fit"]
        inv = {v: k for k, v in TIER_LABEL.items()}
        fit = {"R": prior["R"], "R_t": prior["R_t"],
               "q": {inv[k]: v for k, v in prior["q"].items()},
               "p": prior["p"]}
        print("\nfrozen parameters from %s (no refit)" % a.frozen)
        print("  R %.3f, R_t %.2f, q %s, p %s"
              % (fit["R"], fit["R_t"], {TIER_LABEL[t]: round(v, 3) for t, v in fit["q"].items()},
                 {k: round(v, 3) for k, v in fit["p"].items() if not k.startswith("__")}))
        R = n_r = R_t = rt_crps = n_rt = None
        q, tier_n, p, p_n = fit["q"], {}, fit["p"], {}
    else:
        R, n_r = fit_r(train_items)
        q, tier_n = fit_q(train_items)
        R_t, rt_crps, n_rt = fit_rt(train_items, q)
        p, p_n = fit_p(train_items)
        fit = {"R": R, "q": q, "R_t": R_t, "p": p}

        print("\nfitted on %s (weeks %d-%d, candidate population):"
              % (fit_seasons, a.weeks[0], a.weeks[1]))
        print("  R  (NegBin dispersion, played) %.3f over %d games" % (R, n_r))
        for t in TIERS:
            print("  q[%s] = %.3f   (played games in tier: %d)"
                  % (TIER_LABEL[t], q[t], tier_n.get(t, 0)))
        print("  R_t (zero-truncated dispersion) %.2f, CRPS %.4f over %d games with a carry"
              % (R_t, rt_crps, n_rt))
        print("  p  (plays | designation): %s"
              % {k: round(v, 3) for k, v in p.items() if not k.startswith("__")})

    rows = score(eval_items, fit, ("B0", "B1", "B2", "B2p"))

    subsets = {
        "all (pregame candidates)": [("all", (i["game_id"], i["pid"])) for i in eval_items],
        "RB": [("RB", (i["game_id"], i["pid"])) for i in eval_items if i["pos"] == "RB"],
        "QB (not gated)": [("QB", (i["game_id"], i["pid"])) for i in eval_items if i["pos"] == "QB"],
        "played only": [("played", (i["game_id"], i["pid"])) for i in eval_items
                        if i["played_flag"] == 1],
        "wk3-5 only": [("wk3-5", (i["game_id"], i["pid"])) for i in eval_items if i["week"] <= 5],
    }

    report = {"eval_season": a.eval_season, "fit_seasons": fit_seasons,
              "weeks": a.weeks, "frozen": a.frozen,
              "fit": {"R": R, "q": {TIER_LABEL[t]: q[t] for t in TIERS}, "R_t": R_t,
                      "p": p, "p_counts": p_n},
              "counts": {"train": len(train_items), "train_played": played,
                         "eval": len(eval_items),
                         "eval_played": sum(1 for i in eval_items if i["played_flag"] == 1),
                         "eval_status": dict(Counter(i["status"] or "none" for i in eval_items)),
                         "eval_inactive_with_status": dict(Counter(
                             i["status"] or "none" for i in eval_items if i["played_flag"] == 0))},
              "tables": {}, "paired": {}}

    print("\n== %d: metrics ==" % a.eval_season)
    for name, keys in subsets.items():
        keys = [k for _, k in keys]
        models = ("B0", "B1", "B2", "B2p") if name == "played only" else ("B0", "B1", "B2")
        print("\n  %s (n=%d)" % (name, len(keys)))
        print("    %-4s %8s %6s %6s %6s %7s %7s %8s %8s %6s"
              % ("model", "CRPS", "cov50", "cov80", "cov90", "MAE", "sdP(obs)", "bias", "Brier", "AUC"))
        for model in models:
            agg = aggregate(rows, model, keys)
            if agg is None:
                continue
            report["tables"]["%s|%s" % (name, model)] = agg
            print("    %-4s %8.4f %6.3f %6.3f %6.3f %7.4f %7.2f %+8.4f %8.4f %6s"
                  % (model, agg["crps"], agg["cov50"], agg["cov80"], agg["cov90"],
                     agg["mae"], agg["sd_pred"], agg["bias"], agg["brier_any"],
                     ("%.4f" % agg["auc_any"]) if agg["auc_any"] is not None else "n/a"))
        if keys:
            last = aggregate(rows, models[0], keys)
            if last:
                report["tables"]["%s|obs" % name] = {"n": last["n"], "sd_obs": last["sd_obs"]}
        for model in [m for m in models if m != "B0"]:
            pr = paired_rows(rows, model, "B0", keys)
            report["paired"]["%s|%s|B0" % (name, model)] = pr
            if pr:
                print("    paired %s - B0: %+.4f +/- %.4f (n=%d, %d games)"
                      % (model, pr["mean"], pr["ci"], pr["n"], pr["clusters"]))

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print("\nwrote %s" % a.json)


if __name__ == "__main__":
    main()
