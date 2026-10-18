#!/usr/bin/env python3
"""audit_nfl_dispersion_v3.py -- is one dispersion parameter the problem?

v2's diagnosis: the ZINB over-covers its central intervals because a single R has to serve a 2-carry
back and a 20-carry back. This audit measures, on training seasons only and without fitting the v3
candidate, how much the moment-fit dispersion actually varies across the three usage tiers.

    LP_DB_PATH=... python3 audit_nfl_dispersion_v3.py --fit-seasons 2024 --fit-seasons 2024 2025
"""
import argparse
import os
import sqlite3

import nfl_player_projection_v2 as eng
import nfl_rushing_participation_v2 as v2

P_FLOOR = v2.P_FLOOR


def tier_stats(items, p_fn):
    """Pooled and per-tier moment dispersion, plus the observed spread, on candidates who appeared."""
    rows = {"__pooled__": []}
    for t in v2.TIERS:
        rows[t] = []
    for i in items:
        if not i["appeared"]:
            continue
        p = min(max(p_fn(i), P_FLOOR), 1.0)
        mu = i["m"] / p
        rec = (mu, i["y"])
        rows["__pooled__"].append(rec)
        rows[v2.tier_of(i["m"])].append(rec)
    out = {}
    for key, recs in rows.items():
        if not recs:
            continue
        num = sum(mu * mu for mu, _ in recs)
        den = sum((y - mu) ** 2 - mu for mu, y in recs)
        R = max(0.5, num / den) if den > 0 else float("nan")
        ys = [y for _, y in recs]
        mean = sum(ys) / len(ys)
        sd = (sum((y - mean) ** 2 for y in ys) / len(ys)) ** 0.5
        out[key] = {"n": len(recs), "R": R, "mean_y": mean, "sd_y": sd,
                    "mean_mu": sum(mu for mu, _ in recs) / len(recs)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-seasons", type=int, nargs="+", action="append", required=True,
                    help="repeat the flag for each fit window, e.g. --fit-seasons 2024 "
                         "--fit-seasons 2024 2025")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    seasons = sorted({s for win in a.fit_seasons for s in win})
    hist = eng.History.load(con, seasons)

    for win in a.fit_seasons:
        train = []
        for s in win:
            train.extend(v2.build_items(hist, s))
        p_cross, _ = v2.fit_p_cross(train)

        def p_fn(i, table=p_cross):
            return v2.p_of(i, table, None)

        stats = tier_stats(train, p_fn)
        pooled = stats["__pooled__"]
        print("\n== fit window %s: %d candidates, %d appeared" % (win, len(train),
                                                                  sum(i["appeared"] for i in train)))
        print("   %-10s %6s %8s %8s %8s %9s" % ("tier", "n", "R", "mean(mu)", "mean(y)", "sd(y)"))
        print("   %-10s %6d %8.3f %8.3f %8.3f %9.3f"
              % ("pooled", pooled["n"], pooled["R"], pooled["mean_mu"], pooled["mean_y"],
                 pooled["sd_y"]))
        for t in v2.TIERS:
            st = stats.get(t)
            if not st:
                continue
            print("   %-10s %6d %8.3f %8.3f %8.3f %9.3f"
                  % (v2.TIER_LABEL[t], st["n"], st["R"], st["mean_mu"], st["mean_y"], st["sd_y"]))
        spread = max(stats[t]["R"] for t in v2.TIERS if t in stats) / \
            min(stats[t]["R"] for t in v2.TIERS if t in stats)
        print("   max/min R across tiers: %.2fx" % spread)


if __name__ == "__main__":
    main()
