#!/usr/bin/env python3
"""compare_nfl_prop_grade_csvs.py -- paired comparison of two prop-grade CSVs.

`grade_nfl_prop_probabilities.py --csv` writes one row per graded item. This compares two such files on the
items they share, keyed on (game_id, player_id, market, book, line), and on the items each one has.

Reported per market and overall:
  - items and player-games on each side, and on the shared items
  - Brier and log loss for ours and the market (the market column is carried in both files)
  - MAE of the point projection (ours and marcel-lite where present)
  - every difference paired per item and clustered by player-game (the items are alternate lines on the same
    player-game, so the item-level interval is optimistic)

Usage:
  python3 compare_nfl_prop_grade_csvs.py --a post.csv --b pre.csv --label-a postgame --label-b pregame
"""
import argparse
import csv
import math
from collections import defaultdict

EPS = 1e-6


def tight(p):
    return min(1.0 - 1e-9, max(1e-9, p))


def logloss(p, y):
    p = tight(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load(path):
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            key = (r["game_id"], r["player_id"], r["market"], r["book"], float(r["line"]))
            out[key] = {"p": float(r["p_ours"]), "mkt": float(r["p_market"]), "y": int(r["over"]),
                        "actual": float(r["actual"]),
                        "proj": float(r["proj"]) if r.get("proj") not in (None, "", "None") else None,
                        "marcel": float(r["proj_marcel"]) if r.get("proj_marcel") not in (None, "", "None") else None,
                        "cov80": int(r.get("cov80") or 0), "market": r["market"],
                        "pg": (r["game_id"], r["player_id"])}
    return out


def clustered(diffs, clusters):
    n = len(diffs)
    if not n:
        return None
    mean = sum(diffs) / n
    g = len(clusters)
    if g < 2:
        return mean, 0.0, n, g
    var = g / (g - 1.0) * sum((sum(v) - len(v) * mean) ** 2 for v in clusters.values()) / n ** 2
    return mean, 1.96 * math.sqrt(var), n, g


def pair(rows, fa, fb, b_minus_a=True):
    d, cl = [], defaultdict(list)
    for k, a in rows.items():
        b = fb.get(k)
        if b is None:
            continue
        va, vb = fa(a), fa(b)
        if va is None or vb is None:
            continue
        x = (vb - va) if b_minus_a else (va - vb)
        d.append(x)
        cl[a["pg"]].append(x)
    return clustered(d, cl)


def summary(rows):
    n = len(rows)
    if not n:
        return None
    return {"n": n,
            "pg": len({r["pg"] for r in rows.values()}),
            "brier": sum((r["p"] - r["y"]) ** 2 for r in rows.values()) / n,
            "mkt": sum((r["mkt"] - r["y"]) ** 2 for r in rows.values()) / n,
            "ll": sum(logloss(r["p"], r["y"]) for r in rows.values()) / n,
            "llmkt": sum(logloss(r["mkt"], r["y"]) for r in rows.values()) / n,
            "cov80": sum(r["cov80"] for r in rows.values()) / n,
            "mae": (sum(abs(r["proj"] - r["actual"]) for r in rows.values() if r["proj"] is not None)
                    / max(1, sum(1 for r in rows.values() if r["proj"] is not None))),
            "n_mae": sum(1 for r in rows.values() if r["proj"] is not None),
            "mae_marcel": (sum(abs(r["marcel"] - r["actual"]) for r in rows.values()
                               if r["marcel"] is not None and r["proj"] is not None)
                           / max(1, sum(1 for r in rows.values() if r["marcel"] is not None
                                        and r["proj"] is not None)))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", default=None)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--single", action="store_true",
                    help="one file only: report ours against the market carried in it, paired")
    a = ap.parse_args(argv)
    A, B = load(a.a), load(a.b) if a.b else {}

    if a.single:
        markets = sorted({k[2] for k in A}) + ["__all__"]
        print("%s: %d items, %d player-games" % (a.label_a, len(A), len({v["pg"] for v in A.values()})))
        print("\n%-20s %7s %7s %9s %9s %9s %8s %8s %7s" % (
            "market", "items", "pgames", "Brier", "mktBrier", "logloss", "mktLL", "cov80", "MAE"))
        for m in markets:
            ra = {k: v for k, v in A.items() if m == "__all__" or v["market"] == m}
            sa = summary(ra)
            if not sa:
                continue
            print("%-20s %7d %7d %9.4f %9.4f %9.4f %8.4f %7.3f %8.3f" % (
                m, sa["n"], sa["pg"], sa["brier"], sa["mkt"], sa["ll"], sa["llmkt"], sa["cov80"], sa["mae"]))
            pr = pair(ra, lambda r: (r["p"] - r["y"]) ** 2,
                      {k: dict(v, p=v["mkt"]) for k, v in ra.items()}, b_minus_a=False)
            if pr:
                print("    paired Brier ours-market %+.5f +/- %.5f (n=%d, %d player-games)"
                      % (pr[0], pr[1], pr[2], pr[3]))
            pm = pair(ra, lambda r: abs(r["proj"] - r["actual"]) if r["proj"] is not None else None,
                      {k: dict(v, proj=v["marcel"]) for k, v in ra.items() if v["marcel"] is not None},
                      b_minus_a=False)
            if pm:
                print("    paired MAE ours-marcel %+.4f +/- %.4f (n=%d, %d player-games)"
                      % (pm[0], pm[1], pm[2], pm[3]))
        return

    markets = sorted({k[2] for k in A} | {k[2] for k in B})
    print("A = %s (%d items), B = %s (%d items), shared %d items"
          % (a.label_a, len(A), a.label_b, len(B), len(set(A) & set(B))))
    print("\n%-20s %7s %7s %9s %9s %9s %9s %8s %8s" % (
        "market", "nA", "nB", "BrierA", "BrierB", "mktA", "mktB", "MAE_A", "MAE_B"))
    for m in markets + ["__all__"]:
        ra = {k: v for k, v in A.items() if m == "__all__" or v["market"] == m}
        rb = {k: v for k, v in B.items() if m == "__all__" or v["market"] == m}
        sa, sb = summary(ra), summary(rb)
        if not sa or not sb:
            continue
        print("%-20s %7d %7d %9.4f %9.4f %9.4f %9.4f %8.3f %8.3f" % (
            m, sa["n"], sb["n"], sa["brier"], sb["brier"], sa["mkt"], sb["mkt"], sa["mae"], sb["mae"]))
        only_a = len(set(ra) - set(rb))
        only_b = len(set(rb) - set(ra))
        pgs_a = len({v["pg"] for k, v in ra.items() if k not in rb})
        pgs_b = len({v["pg"] for k, v in rb.items() if k not in ra})
        print("    membership: %d items only in A (%d player-games), %d only in B (%d player-games)"
              % (only_a, pgs_a, only_b, pgs_b))
        for label, fn in (("Brier", lambda r: (r["p"] - r["y"]) ** 2),
                          ("MAE", lambda r: abs(r["proj"] - r["actual"]) if r["proj"] is not None else None)):
            shared = {k: v for k, v in ra.items() if k in rb}
            pr = pair(shared, fn, rb)
            if pr:
                print("    paired %s on shared items (B-A) %+.5f +/- %.5f (n=%d, %d player-games)"
                      % (label, pr[0], pr[1], pr[2], pr[3]))
    # overall coverage and the A/B arm's decile calibration in one line
    sa, sb = summary(A), summary(B)
    print("\nA cov80 %.3f  B cov80 %.3f  A logloss %.4f  B logloss %.4f  (market logloss %.4f/%.4f)"
          % (sa["cov80"], sb["cov80"], sa["ll"], sb["ll"], sa["llmkt"], sb["llmkt"]))
    if sa["n_mae"] and sb["n_mae"]:
        print("A marcel MAE %.3f on %d item rows   B marcel MAE %.3f on %d item rows"
              % (sa["mae_marcel"], sa["n_mae"], sb["mae_marcel"], sb["n_mae"]))


if __name__ == "__main__":
    main()
