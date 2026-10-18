#!/usr/bin/env python3
"""audit_nfl_zero_interval_v4.py -- why does every candidate that models the zero mass over-cover?

Hypothesis: on a discrete distribution with a spike at zero, the 50% central interval is [q25, q75]. When
more than 25% of the mass sits at zero, q25 = 0, so the interval runs [0, q75] and contains ~75% of the
mass by construction - not because the model is mis-calibrated, but because the interval cannot start below
the minimum outcome.

This measures, per model, how often the lower 50% bound is pinned at zero, and what coverage those items
have versus the items where it is not pinned. Diagnostic only.

    LP_DB_PATH=... python3 audit_nfl_zero_interval_v4.py --eval-season 2025 --fit-seasons 2024
"""
import argparse
import os
import sqlite3

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2
import nfl_rushing_quantile_map_v4 as v4


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-season", type=int, required=True)
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True)
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % os.environ["LP_DB_PATH"], uri=True)
    hist = eng.History.load(con, sorted(set(a.fit_seasons + [a.eval_season])))

    train = []
    for s in a.fit_seasons:
        train.extend(v2.build_items(hist, s))
    items = v2.build_items(hist, a.eval_season)
    p_cross, _ = v2.fit_p_cross(train)
    R0, _ = v2.fit_r(train, lambda i: 1.0)
    R_pooled, _ = v2.fit_r(train, lambda i: v2.p_of(i, p_cross, None))
    anchors, _ = v4.fit_anchors(train, appeared_only=True)
    anchors_u, _ = v4.fit_anchors(train, appeared_only=False)
    fit = {"R0": R0, "R": R_pooled, "p_cross": p_cross, "anchors": anchors,
           "anchors_uncond": anchors_u}

    print("== %d, n=%d | zero share of outcome: %.3f"
          % (a.eval_season, len(items), sum(1 for i in items if i["y"] == 0) / len(items)))
    print("   %-5s %10s %10s %10s %10s %10s"
          % ("model", "P(0) mean", "q25=0 share", "cov50|q25=0", "cov50|q25>0", "cov50 all"))
    for model in ("B0", "Zf", "V4", "V4u"):
        pinned, free = [], []
        p0 = []
        for i in items:
            cdf = v2.cdf_of(v4.pmf_for(model, i, fit))
            p0.append(cdf[0])
            lo = v2.q_lower(cdf, 0.5)
            hit = 1.0 if lo <= i["y"] <= v2.q_upper(cdf, 0.5) else 0.0
            (pinned if lo == 0 else free).append(hit)
        all_hits = pinned + free
        print("   %-5s %10.3f %10.3f %10.3f %10.3f %10.3f"
              % (model, sum(p0) / len(p0), len(pinned) / len(items),
                 (sum(pinned) / len(pinned)) if pinned else float("nan"),
                 (sum(free) / len(free)) if free else float("nan"),
                 sum(all_hits) / len(all_hits)))
    print("\n   a 50% central interval that starts at 0 can only be [0, q75], which holds F(q75) ~ 0.75.")


if __name__ == "__main__":
    main()
