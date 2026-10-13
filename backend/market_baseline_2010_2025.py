#!/usr/bin/env python3
"""market_baseline_2010_2025.py -- frozen v1 walk-forward vs the de-vigged moneyline and the
spread, 2010-2025. Read-only: the database is opened with mode=ro and nothing is recorded.

Usage: LP_DB_PATH=<dev db> venv/bin/python market_baseline_2010_2025.py
Output: per-season and pooled Brier (model, market, paired difference with a 95% bootstrap
interval) and margin MAE (model, spread). Results: docs/RESULTS-market-baseline-2010-2025-2026-10-11.md
"""
import os
import sqlite3
import statistics as stt

import nfl_backtest as nb
import nfl_metrics as nm

FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")


def report(name, rs):
    rs = [x for x in rs if x["p_market"] is not None and x["outcome"] is not None
          and x["spread_line"] is not None and x["actual_margin"] is not None]
    yo = [x["outcome"] for x in rs]
    bm = [(x["p_model"] - y) ** 2 for x, y in zip(rs, yo)]
    bk = [(x["p_market"] - y) ** 2 for x, y in zip(rs, yo)]
    pt, lo, hi = nm.bootstrap_mean_diff_ci(bm, bk, reps=5000)
    mp = stt.mean(abs(x["proj_margin"] - x["actual_margin"]) for x in rs)
    lp = stt.mean(abs(float(x["spread_line"]) - x["actual_margin"]) for x in rs)
    print("%-10s n=%d brier model=%.4f market=%.4f diff(model-market)=%+.4f [%+.4f,%+.4f] | "
          "margin MAE model=%.3f line=%.3f" % (name, len(rs), stt.mean(bm), stt.mean(bk),
                                              pt, lo, hi, mp, lp))


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = []
    for s in range(2010, 2026):
        rows += nb.backtest_season(con, s, FROZEN)
    for s in range(2010, 2026):
        report(str(s), [x for x in rows if x["season"] == s])
    report("2010-2025", rows)
    report("2024-2025", [x for x in rows if x["season"] >= 2024])


if __name__ == "__main__":
    main()
