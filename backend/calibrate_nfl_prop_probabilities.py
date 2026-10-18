#!/usr/bin/env python3
"""calibrate_nfl_prop_probabilities.py -- can v2's P(over) be repaired without new data?

Read-only. Runs the pre-registered v2 prop grade (`grade_nfl_prop_probabilities.grade`), then asks whether a
probability map fitted on OTHER weeks moves the Brier on the week it did not see.

Leave-one-week-out. For each graded week the map is fitted on the other weeks only and applied to that week,
so every reported number is out of sample. Four forecasts per item:

  raw             v2's own P(over)
  platt           logistic recalibration of logit(p): one slope, one intercept, fitted pooled
  isotonic        monotone step map (pool adjacent violators), fitted pooled
  isotonic_market the same map fitted per market, falling back to pooled below MIN_FIT training items

Reported per method: Brier, log loss and the reliability table, plus the market on identical items. Every
difference is also given clustered by player-game, because the items are alternate lines on the same
player-game and the item-level interval is optimistic. No gate. Nothing here is served.

Usage: LP_DB_PATH=... python3 calibrate_nfl_prop_probabilities.py --season 2026 [--csv out.csv]
"""
import argparse
import csv
import math
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g

EPS = 1e-6
MIN_FIT = 200


def logit(p):
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def fit_platt(pairs):
    """2-parameter logistic recalibration by Newton's method. pairs = [(p, y)] -> (a, b)."""
    a, b = 1.0, 0.0
    xs = [(logit(p), y) for p, y in pairs]
    for _ in range(200):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in xs:
            q = sigmoid(a * x + b)
            r = q - y
            w = q * (1.0 - q)
            ga += r * x
            gb += r
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a -= da
        b -= db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return a, b


def fit_isotonic(pairs):
    """PAVA on (p, y) sorted by p. Returns (xs, ys) where ys is non-decreasing."""
    s = sorted(pairs)
    xs = [p for p, _ in s]
    lvl_y, lvl_w, lvl_n = [], [], []
    for _p, y in s:
        lvl_y.append(float(y))
        lvl_w.append(1.0)
        lvl_n.append(1)
        while len(lvl_y) > 1 and lvl_y[-2] > lvl_y[-1]:
            y2, w2, n2 = lvl_y.pop(), lvl_w.pop(), lvl_n.pop()
            lvl_y[-1] = (lvl_y[-1] * lvl_w[-1] + y2 * w2) / (lvl_w[-1] + w2)
            lvl_w[-1] += w2
            lvl_n[-1] += n2
    ys = []
    for y, n in zip(lvl_y, lvl_n):
        ys.extend([y] * n)
    return xs, ys


def apply_isotonic(xs, ys, p):
    """Largest breakpoint at or below p."""
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if xs[mid] <= p:
            lo = mid
        else:
            hi = mid - 1
    return ys[lo]


def brier(rows, field):
    return sum((r[field] - r["over"]) ** 2 for r in rows) / len(rows) if rows else None


def logloss(rows, field):
    if not rows:
        return None
    tot = 0.0
    for r in rows:
        p = min(max(r[field], EPS), 1.0 - EPS)
        tot += -(r["over"] * math.log(p) + (1 - r["over"]) * math.log(1 - p))
    return tot / len(rows)


def clustered_diff(rows, fa, fb):
    """Mean per-item Brier difference fa - fb with a player-game-clustered 95% half-width."""
    d = [(r[fa] - r["over"]) ** 2 - (r[fb] - r["over"]) ** 2 for r in rows]
    n = len(d)
    mean = sum(d) / n
    cl = defaultdict(list)
    for r, x in zip(rows, d):
        cl[(r["game_id"], r["player_id"])].append(x)
    G = len(cl)
    if G < 2:
        return mean, None
    var = G / (G - 1.0) * sum((sum(v) - len(v) * mean) ** 2 for v in cl.values()) / n ** 2
    return mean, 1.96 * math.sqrt(var)


def run(con, season, mode="lowo"):
    graded, _skipped, _disagree = g.grade(con, season)
    for r in graded:
        r["week"] = int(r["game_id"].split("_")[1])
    weeks = sorted({r["week"] for r in graded})
    fields = ("p_ours", "p_platt", "p_iso", "p_iso_market", "p_market")
    for r in graded:
        r["p_platt"] = r["p_ours"]
        r["p_iso"] = r["p_ours"]
        r["p_iso_market"] = r["p_ours"]
        r["calibrated"] = 0
    info = []
    for held in weeks:
        if mode == "forward":
            # Only the weeks strictly before the held-out week may train the map, which is all a production
            # fit would have. Week 2 has no earlier props, so nothing is calibrated there.
            train = [r for r in graded if r["week"] < held]
        else:
            train = [r for r in graded if r["week"] != held]
        test = [r for r in graded if r["week"] == held]
        if not train or not test:
            info.append((held, 0, None, None))
            continue
        pairs = [(r["p_ours"], r["over"]) for r in train]
        a, b = fit_platt(pairs)
        xs, ys = fit_isotonic(pairs)
        per_market = {}
        for m in {r["market"] for r in train}:
            mp = [(r["p_ours"], r["over"]) for r in train if r["market"] == m]
            per_market[m] = fit_isotonic(mp) if len(mp) >= MIN_FIT else (xs, ys)
        for r in test:
            r["p_platt"] = sigmoid(a * logit(r["p_ours"]) + b)
            r["p_iso"] = apply_isotonic(xs, ys, r["p_ours"])
            mxs, mys = per_market.get(r["market"], (xs, ys))
            r["p_iso_market"] = apply_isotonic(mxs, mys, r["p_ours"])
            r["calibrated"] = 1
        info.append((held, len(train), a, b))
    return graded, weeks, fields, info


def report(graded, weeks, fields, label, mode="lowo", info=None):
    print("\n%s: %d items, %d player-games, weeks %s" % (
        label, len(graded), len({(r["game_id"], r["player_id"]) for r in graded}), weeks))
    if mode == "forward":
        unc = [r for r in graded if not r["calibrated"]]
        print("  forward only: %d of %d items were scored by a map fitted on earlier weeks; %d (%.0f%%) had "
              "no earlier week to fit on" % (len(graded) - len(unc), len(graded), len(unc),
                                             100.0 * len(unc) / len(graded)))
        for held, n, a, b in (info or []):
            print("    week %s: trained on %6d items%s" % (
                held, n, "" if a is None else ", platt slope %+.3f intercept %+.3f" % (a, b)))
    names = {"p_ours": "raw v2", "p_platt": "platt", "p_iso": "isotonic",
             "p_iso_market": "isotonic/market", "p_market": "market"}
    # In forward mode an item with no earlier week has no map, so scoring it would mix calibrated and raw
    # items in the same row. Report the metrics on the calibrated subset and say so.
    metric = [r for r in graded if r["calibrated"]] if mode == "forward" else graded
    if mode == "forward":
        print("  metrics below are on the %d items a map could score (weeks %s)" % (
            len(metric), sorted({r["week"] for r in metric})))
    print("  %-18s %8s %8s   %s" % ("forecast", "Brier", "logloss", "vs raw (clustered 95%)"))
    for f in fields:
        d, hw = clustered_diff(metric, f, "p_ours") if f != "p_ours" else (0.0, None)
        extra = "" if f == "p_ours" else "  %+.5f%s" % (-d, "" if hw is None else " +/- %.5f" % hw)
        print("  %-18s %8.4f %8.4f%s" % (names[f], brier(metric, f), logloss(metric, f), extra))
    print("  (constant 0.5 scores Brier 0.2500)")
    print("  reliability, raw v2 vs isotonic/market (bin: n, predicted, observed)")
    for f in ("p_ours", "p_iso_market"):
        cells = []
        for b in range(10):
            lo, hi = b / 10.0, (b + 1) / 10.0
            cell = [r for r in metric if lo <= r[f] < hi or (b == 9 and r[f] >= hi)]
            if cell:
                cells.append("%.1f-%.1f n%d pred %.3f obs %.3f" % (
                    lo, hi, len(cell), sum(x[f] for x in cell) / len(cell),
                    sum(x["over"] for x in cell) / len(cell)))
        print("    %-16s %s" % (names[f], "; ".join(cells)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--csv")
    ap.add_argument("--mode", choices=("lowo", "forward"), default="lowo",
                    help="lowo fits on every other week; forward fits only on earlier weeks, which is all a "
                         "production fit would have")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    graded, weeks, fields, info = run(con, a.season, a.mode)
    label = "leave-one-week-out" if a.mode == "lowo" else "forward only (fit on earlier weeks)"
    report(graded, weeks, fields, label, a.mode, info)
    for m in sorted({r["market"] for r in graded}):
        sub = [r for r in graded if r["market"] == m]
        if len(sub) > 100:
            report(sub, weeks, fields, "  market: %s" % m, a.mode, info)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(graded[0]))
            w.writeheader()
            w.writerows(graded)


if __name__ == "__main__":
    main()
