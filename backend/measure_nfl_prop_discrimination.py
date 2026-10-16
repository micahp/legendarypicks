#!/usr/bin/env python3
"""measure_nfl_prop_discrimination.py -- does the player model know anything the baseline or the market misses?

Brier alone cannot answer that. A model that predicts 0.5 for everything has a respectable Brier and no
information, and a model that shrinks toward 0.5 improves its Brier while losing discrimination. This measures
the three things separately, all out of sample and clustered by player-game:

  discrimination   AUC of P(over) against the outcome, for ours, the market and the calibrated version
  decomposition    Murphy reliability and resolution, overall and split by market and position group
  increment        a forward-only logistic stack of the market's log-odds and ours. If our number carries
                   information the market does not, the stack beats the market alone out of sample and the
                   coefficient on ours is positive. This is the test that matters: it asks whether LP adds
                   anything on top of the price, not whether LP is a better model in isolation.

Forward only: every week is scored by coefficients fitted on weeks strictly before it. Week 2 has no earlier
week, so nothing is stacked there and the metrics cover the weeks that can be.

Read-only. Usage: LP_DB_PATH=... python3 measure_nfl_prop_discrimination.py --season 2026 [--boot 400]
"""
import argparse
import math
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g

EPS = 1e-6
POS_GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}


def logit(p):
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def auc(pairs):
    """Rank-based AUC with tie handling, vectorised. pairs = [(score, outcome)]."""
    import numpy as np
    s = np.asarray([p for p, _ in pairs], dtype=float)
    y = np.asarray([o for _, o in pairs], dtype=float)
    n1 = float(y.sum())
    n0 = float(len(y) - n1)
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ss = s[order]
    ranks = np.empty(len(s), dtype=float)
    i = 0
    n = len(ss)
    while i < n:
        j = i
        while j + 1 < n and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return (ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def brier(rows, f):
    return sum((r[f] - r["over"]) ** 2 for r in rows) / len(rows)


def logloss(rows, f):
    t = 0.0
    for r in rows:
        p = min(max(r[f], EPS), 1.0 - EPS)
        t += -(r["over"] * math.log(p) + (1 - r["over"]) * math.log(1 - p))
    return t / len(rows)


def murphy(rows, f):
    n = len(rows)
    base = sum(r["over"] for r in rows) / n
    rel = res = 0.0
    for b in range(10):
        lo, hi = b / 10.0, (b + 1) / 10.0
        c = [r for r in rows if lo <= r[f] < hi or (b == 9 and r[f] >= hi)]
        if not c:
            continue
        pk = sum(x[f] for x in c) / len(c)
        ok = sum(x["over"] for x in c) / len(c)
        rel += len(c) / n * (pk - ok) ** 2
        res += len(c) / n * (ok - base) ** 2
    return rel, res, base * (1 - base)


def fit_logistic(X, y, l2=1e-3):
    """IRLS-free fit by scipy BFGS on the penalised log loss. X is a list of feature lists."""
    import numpy as np
    from scipy.optimize import minimize
    Xa, ya = np.asarray(X, dtype=float), np.asarray(y, dtype=float)

    def obj(w):
        z = Xa.dot(w)
        # stable log loss
        ll = np.sum(np.logaddexp(0.0, z) - ya * z) / len(ya)
        return ll + l2 * np.sum(w[1:] ** 2)

    w0 = np.zeros(Xa.shape[1])
    r = minimize(obj, w0, method="BFGS")
    return list(r.x)


def cluster_boot(rows, fn, boot, seed=7):
    """Bootstrap a scalar metric over player-games. fn(list_of_rows) -> float."""
    import random
    by = defaultdict(list)
    for r in rows:
        by[(r["game_id"], r["player_id"])].append(r)
    keys = list(by)
    rng = random.Random(seed)
    obs = fn(rows)
    if obs is None:
        return None, None, None
    vals = []
    for _ in range(boot):
        pick = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        sample = [r for k in pick for r in by[k]]
        v = fn(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    lo = vals[int(0.025 * len(vals))] if vals else None
    hi = vals[int(0.975 * len(vals))] if vals else None
    return obs, lo, hi


def load(con, season):
    graded, _s, _d = g.grade(con, season)
    pos = {pid: p for pid, p in con.execute("SELECT id, position FROM players WHERE league='nfl'")}
    for r in graded:
        r["week"] = int(r["game_id"].split("_")[1])
        r["group"] = POS_GROUP.get(pos.get(r["player_id"]), "other")
        r["l_ours"] = logit(r["p_ours"])
        r["l_market"] = logit(r["p_market"])
    return graded


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--boot", type=int, default=400)
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    rows = load(con, a.season)
    weeks = sorted({r["week"] for r in rows})
    print("loaded %d items on %d player-games, weeks %s" % (
        len(rows), len({(r["game_id"], r["player_id"]) for r in rows}), weeks))

    print("\n== discrimination and decomposition (all items, no fitting) ==")
    print("  %-14s %8s %10s %10s %8s" % ("forecast", "Brier", "reliability", "resolution", "AUC"))
    for f, nm in (("p_ours", "v2 raw"), ("p_market", "market")):
        rel, res, unc = murphy(rows, f)
        print("  %-14s %8.4f %10.4f %10.4f %8.4f" % (nm, brier(rows, f), rel, res, auc([(r[f], r["over"]) for r in rows])))

    print("\n  AUC by market (ours vs market):")
    for m in sorted({r["market"] for r in rows}):
        sub = [r for r in rows if r["market"] == m]
        if len(sub) < 300:
            continue
        ao = auc([(r["p_ours"], r["over"]) for r in sub])
        am = auc([(r["p_market"], r["over"]) for r in sub])
        ro = murphy(sub, "p_ours")[1]
        rm = murphy(sub, "p_market")[1]
        print("    %-20s n %6d  AUC ours %.4f market %.4f | resolution ours %.5f market %.5f" % (
            m, len(sub), ao or 0, am or 0, ro, rm))

    print("\n  AUC by position group:")
    for grp in sorted({r["group"] for r in rows}):
        sub = [r for r in rows if r["group"] == grp]
        if len(sub) < 300:
            continue
        ao = auc([(r["p_ours"], r["over"]) for r in sub])
        am = auc([(r["p_market"], r["over"]) for r in sub])
        print("    %-6s n %6d  AUC ours %.4f  market %.4f" % (grp, len(sub), ao or 0, am or 0))

    # ---- the increment test: does ours add anything on top of the price? ----
    print("\n== increment over the market, forward only ==")
    print("  every week is scored by coefficients fitted on earlier weeks only")
    scorable = []
    coefs = []
    for held in weeks:
        train = [r for r in rows if r["week"] < held]
        test = [r for r in rows if r["week"] == held]
        if len(train) < 500 or not test:
            print("    week %s: no earlier weeks to fit on, skipped" % held)
            continue
        y = [r["over"] for r in train]
        w_mkt = fit_logistic([[1.0, r["l_market"]] for r in train], y)
        w_our = fit_logistic([[1.0, r["l_ours"]] for r in train], y)
        w_stk = fit_logistic([[1.0, r["l_market"], r["l_ours"]] for r in train], y)
        for r in test:
            r["s_mkt"] = sigmoid(w_mkt[0] + w_mkt[1] * r["l_market"])
            r["s_our"] = sigmoid(w_our[0] + w_our[1] * r["l_ours"])
            r["s_stk"] = sigmoid(w_stk[0] + w_stk[1] * r["l_market"] + w_stk[2] * r["l_ours"])
        scorable.extend(test)
        coefs.append((held, w_mkt[1], w_our[1], w_stk[1], w_stk[2]))
        print("    week %s: fitted on %6d, on market %+.3f, on ours %+.3f | stack: market %+.3f ours %+.3f" % (
            held, len(train), w_mkt[1], w_our[1], w_stk[1], w_stk[2]))
    if not scorable:
        print("  nothing scorable")
        return
    print("\n  out of sample on %d items, %d player-games (weeks %s):" % (
        len(scorable), len({(r["game_id"], r["player_id"]) for r in scorable}),
        sorted({r["week"] for r in scorable})))
    print("    %-22s %8s %8s %8s" % ("forecast", "Brier", "logloss", "AUC"))
    for f, nm in (("p_market", "market, raw"), ("p_ours", "ours, raw"), ("s_mkt", "market, refit"),
                  ("s_our", "ours, refit"), ("s_stk", "stack (market+ours)")):
        print("    %-22s %8.4f %8.4f %8.4f" % (
            nm, brier(scorable, f), logloss(scorable, f), auc([(r[f], r["over"]) for r in scorable]) or 0))
    d_ll = cluster_boot(scorable, lambda s: logloss(s, "s_mkt") - logloss(s, "s_stk"), a.boot)
    d_br = cluster_boot(scorable, lambda s: brier(s, "s_mkt") - brier(s, "s_stk"), a.boot)
    d_au = cluster_boot(scorable, lambda s: (auc([(r["s_stk"], r["over"]) for r in s]) or 0)
                        - (auc([(r["s_mkt"], r["over"]) for r in s]) or 0), a.boot)
    for nm, t in (("logloss market minus stack", d_ll), ("Brier market minus stack", d_br),
                  ("AUC stack minus market", d_au)):
        if t[0] is None:
            continue
        print("    %-26s %+.5f  clustered 95%% [%+.5f, %+.5f]" % (nm, t[0], t[1], t[2]))
    print("    (positive means the stack is better than the market alone)")


if __name__ == "__main__":
    main()
