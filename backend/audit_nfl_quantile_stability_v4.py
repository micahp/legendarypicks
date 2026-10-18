#!/usr/bin/env python3
"""audit_nfl_quantile_stability_v4.py -- are the tier quantiles stable enough to map forward?

v4 replaces the parametric count with an empirical quantile map fitted by usage tier. That only works if
the quantiles of a tier are similar from one season to the next; this audit measures that before any v4
model code exists, and measures how much of the carry distribution is zero mass.

Reports, per season and tier, over candidates who appeared (the conditional distribution the map models):
n, the 5/10/25/50/75/90/95% quantiles, the mean, and the zero share.

    LP_DB_PATH=... python3 audit_nfl_quantile_stability_v4.py --seasons 2024 2025 2026
"""
import argparse
import os
import sqlite3

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2

LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def quantiles(values, levels=LEVELS):
    xs = sorted(values)
    n = len(xs)
    out = []
    for q in levels:
        pos = q * (n - 1)
        lo, hi = int(pos), min(n - 1, int(pos) + 1)
        frac = pos - lo
        out.append(xs[lo] * (1 - frac) + xs[hi] * frac)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026])
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    hist = eng.History.load(con, sorted(a.seasons))

    print("levels:", " ".join("%.2f" % q for q in LEVELS))
    for season in a.seasons:
        items = v2.build_items(hist, season)
        print("\n== %d (%d candidates, %d appeared)" % (season, len(items),
                                                        sum(i["appeared"] for i in items)))
        rows = [("all", items)] + [(v2.TIER_LABEL[t], [i for i in items if v2.tier_of(i["m"]) == t])
                                   for t in v2.TIERS]
        for label, sub in rows:
            app = [i for i in sub if i["appeared"]]
            if not app:
                continue
            ys = [i["y"] for i in app]
            qs = quantiles(ys)
            zero = sum(1 for y in ys if y == 0) / len(ys)
            print("  %-9s n=%4d  q: %s | mean %5.2f | zero share %.3f"
                  % (label, len(app), " ".join("%5.1f" % q for q in qs),
                     sum(ys) / len(ys), zero))
    print("\ncross-season drift by tier (appeared, 2024 vs 2025, in carries):")
    by_season = {}
    for season in (2024, 2025):
        items = v2.build_items(hist, season)
        by_season[season] = {}
        for t in v2.TIERS:
            ys = [i["y"] for i in items if i["appeared"] and v2.tier_of(i["m"]) == t]
            by_season[season][t] = quantiles(ys) if ys else None
    for t in v2.TIERS:
        a24, a25 = by_season[2024][t], by_season[2025][t]
        if not a24 or not a25:
            continue
        diffs = [b - x for x, b in zip(a24, a25)]
        print("  %-9s deltas %s | max |delta| %.1f"
              % (v2.TIER_LABEL[t], " ".join("%+.1f" % d for d in diffs), max(abs(d) for d in diffs)))


if __name__ == "__main__":
    main()
