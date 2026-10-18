#!/usr/bin/env python3
"""audit_nfl_interval_width_v3.py -- why does the 50% interval still hold 75% of outcomes?

Compares the empirical quantiles of carries with the interval bounds the candidate actually publishes,
by usage tier. Diagnostic only: nothing here is fitted or gated.

    LP_DB_PATH=... python3 audit_nfl_interval_width_v3.py --eval-season 2025 --fit-seasons 2024
"""
import argparse
import os
import sqlite3

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2
import nfl_rushing_participation_v3 as v3


def empirical_quantiles(values, qs):
    xs = sorted(values)
    out = {}
    for q in qs:
        idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        out[q] = xs[idx]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-season", type=int, required=True)
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True)
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    hist = eng.History.load(con, sorted(set(a.fit_seasons + [a.eval_season])))

    train = []
    for s in a.fit_seasons:
        train.extend(v2.build_items(hist, s))
    items = v2.build_items(hist, a.eval_season)
    p_cross, _ = v2.fit_p_cross(train)
    p_fn = lambda i: v2.p_of(i, p_cross, None)  # noqa: E731
    R_tier, _, pooled_R = v3.fit_r_tiered(train, p_fn)
    R0, _ = v2.fit_r(train, lambda i: 1.0)
    fit = {"R0": R0, "R": pooled_R, "R_tier": R_tier,
           "p_cross": p_cross, "p_status": {"__pooled__": 0.75}, "q": {}, "R_t": 5.0}

    print("== %d: empirical vs published interval bounds" % a.eval_season)
    for label, model in (("B0", "B0"), ("V3", "V3")):
        for tier in [None] + list(v3.TIERS):
            sub = [i for i in items if tier is None or v2.tier_of(i["m"]) == tier]
            if not sub:
                continue
            emp = empirical_quantiles([i["y"] for i in sub], (0.25, 0.5, 0.75, 0.9, 0.95))
            widths = {}
            covs = {}
            for level in (0.5, 0.8, 0.9):
                lo_hi = []
                hit = 0
                for i in sub:
                    cdf = v2.cdf_of(v3.pmf_for(model, i, fit))
                    lo, hi = v2.q_lower(cdf, level), v2.q_upper(cdf, level)
                    lo_hi.append(hi - lo)
                    hit += 1 if lo <= i["y"] <= hi else 0
                widths[level] = sum(lo_hi) / len(lo_hi)
                covs[level] = hit / len(sub)
            name = "all" if tier is None else v3.TIER_LABEL[tier]
            print("  %-2s %-8s n=%4d | observed q25/q50/q75/q90/q95 = %2d/%2d/%2d/%2d/%2d"
                  % (label, name, len(sub), emp[0.25], emp[0.5], emp[0.75], emp[0.9], emp[0.95]))
            print("       mean interval width 50/80/90 = %.2f/%.2f/%.2f | coverage = %.3f/%.3f/%.3f"
                  % (widths[0.5], widths[0.8], widths[0.9],
                     covs[0.5], covs[0.8], covs[0.9]))


if __name__ == "__main__":
    main()
