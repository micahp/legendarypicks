#!/usr/bin/env python3
"""nfl_year_breakdown.py -- year by year, and where Elo beats frozen v1. DESCRIPTIVE: no keep rule, nothing selected.

Question (Micah, 2026-10-13): 538 Elo looked like an outlier in some years; which years were better and why? Read-only.
Rows are the harness's graded set (nfl_feature_backtest.graded: 2011-2025, outcome, moneyline and spread present, no ties).
Models: coin 0.5; home field only (walk-forward rate, as benchmark_ladder_2010_2020.py); Elo = the replica in
nfl_elo_replica.py with 538's constants (verified exact against the file); v1 frozen; v1+Elo = the elo_diff stack column
in the harness (fb.stack); market = de-vigged moneyline.

Hypotheses written before looking at the tables below (the tables can only support or fail them; nothing else is claimed):
  H1 early season: Elo carries 2/3 of last season's rating in, v1 refits on current-season games with a prior, so Elo
     should be better in weeks 2 to 4 and the gap should narrow later.
  H2 big favourites: Elo's log margin damping and v1's cap of 14 treat blowouts differently, so the Elo-v1 gap should
     differ by the size of the market spread.
  H3 home field: a flat home value (Elo 65) should do worst in seasons where the realised home advantage moved (2020),
     and v1, which fits one, should do relatively better there.
Selection rule for the drill-down seasons, fixed here: the 4 seasons where Elo's Brier is lowest relative to v1 (largest
v1 minus Elo) and the 3 where it is highest. No other season is singled out.
Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_year_breakdown.py
"""
from __future__ import annotations

import sqlite3
import statistics as stt

import nfl_elo_replica as er
import nfl_feature_backtest as fb

BUCKETS = (("wk 2-4", 2, 4), ("wk 5-9", 5, 9), ("wk 10-14", 10, 14), ("wk 15+", 15, 99))
SPREADS = (("spread <3", 0.0, 3.0), ("spread 3-6.5", 3.0, 6.5), ("spread 6.5+", 6.5, 99.0))


def b(rs, f):
    return stt.mean((f(r) - r["outcome"]) ** 2 for r in rs) if rs else float("nan")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    games = er.load_games(con)
    neutral = {g[0]: g[2] for g in games}
    pre = er.run_elo(games, er.start_ratings(con))
    rows = fb.base_rows(con)
    cols, _ = er.elo_diff(con, rows)
    base, stk = fb.stack(rows), fb.stack(rows, cols)
    g = fb.graded(rows)
    for r in g:
        r["p_elo"] = er.prob(pre[r["game_id"]], neutral[r["game_id"]])
        r["p_stack"] = stk[r["game_id"]][1]
    models = (("Elo", lambda r: r["p_elo"]), ("v1", lambda r: r["p_model"]),
              ("v1+Elo", lambda r: r["p_stack"]), ("market", lambda r: r["p_market"]))
    print("YEAR      n  home%  total   Elo     v1   v1+Elo  market | v1-Elo  Elo-mkt")
    gaps = {}
    for s in range(2011, 2026):
        rs = [r for r in g if r["season"] == s]
        hw = sum(r["outcome"] for r in rs) / len(rs)
        tot = stt.mean(r["actual_total"] for r in rs)
        v = [b(rs, f) for _, f in models]
        gaps[s] = v[1] - v[0]
        print("%d  %4d  %5.1f  %5.1f  %.4f %.4f %.4f %.4f | %+.4f %+.4f" % (s, len(rs), hw * 100, tot, *v, v[1] - v[0], v[0] - v[3]))
    best = sorted(gaps, key=lambda s: -gaps[s])[:4]
    worst = sorted(gaps, key=lambda s: gaps[s])[:3]
    print("\ndrill-down seasons: Elo best vs v1 %s; worst %s" % (best, worst))

    def table(title, rs):
        print("\n%s (n=%d)" % (title, len(rs)))
        for name, lo, hi in BUCKETS:
            x = [r for r in rs if lo <= r["week"] <= hi]
            if x:
                print("  %-9s n=%4d  Elo %.4f  v1 %.4f  market %.4f  v1-Elo %+.4f" % (
                    name, len(x), b(x, models[0][1]), b(x, models[1][1]), b(x, models[3][1]),
                    b(x, models[1][1]) - b(x, models[0][1])))
        for name, lo, hi in SPREADS:
            x = [r for r in rs if lo <= abs(float(r["spread_line"])) < hi]
            if x:
                print("  %-12s n=%4d  Elo %.4f  v1 %.4f  market %.4f  v1-Elo %+.4f" % (
                    name, len(x), b(x, models[0][1]), b(x, models[1][1]), b(x, models[3][1]),
                    b(x, models[1][1]) - b(x, models[0][1])))
    table("ALL 2011-2025", g)
    for s in best + worst:
        table("%d (%s)" % (s, "Elo best" if s in best else "Elo worst"), [r for r in g if r["season"] == s])
    print("\ncalibration, all 2011-2025: mean predicted home win prob vs realised, by bin of the model's own p")
    for name, f in (models[0], models[1]):
        out = []
        for lo, hi in ((0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)):
            x = [r for r in g if lo <= f(r) < hi]
            if x:
                out.append("%.2f-%.2f n=%4d pred %.3f real %.3f" % (lo, min(hi, 1), len(x), stt.mean(f(r) for r in x), stt.mean(r["outcome"] for r in x)))
        print("  %-4s " % name + " | ".join(out))
    print("\nrealised home advantage by year (mean home margin, all graded games): " + " ".join(
        "%d:%+.1f" % (s, stt.mean(r["actual_margin"] for r in g if r["season"] == s)) for s in range(2011, 2026)))


if __name__ == "__main__":
    main()
