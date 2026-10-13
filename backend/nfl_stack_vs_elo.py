#!/usr/bin/env python3
"""nfl_stack_vs_elo.py -- does the v1 + Elo stack beat Elo alone, and is v1 worth keeping in the mix? Read-only.

Question (Micah, 2026-10-13): Elo alone scores 0.2208 on 2011-2023 and the stack 0.2197; the 0.0011 gap has no
interval. Rows are the harness's graded set (nfl_feature_backtest.graded: 2011-2025, no ties, moneyline and spread
present). Models: Elo = the replica in nfl_elo_replica.py with 538's constants (probability straight from the rating
gap); stack = the `elo_diff` stack in the harness (OLS on v1 margin and Elo gap, seasons before the one scored);
v1 = frozen v1; market = de-vigged moneyline.

PRE-REGISTERED (written before the first run of this file)
Primary: paired difference of per-game Brier, stack minus Elo, with nfl_metrics.bootstrap_mean_diff_ci (5,000
resamples), for 2011-2023 pooled, 2024, 2025 and 2011-2025 pooled. A difference is called real only if its pooled
interval excludes zero.
Secondary (descriptive, no keep rule): the same paired difference by week bucket (2-4, 5-9, 10-14, 15+) and by season,
and the same for stack minus v1. No threshold or bucket is chosen after seeing a result; the buckets are the ones
nfl_year_breakdown.py used.
A note that cannot be removed: the week-bucket pattern (Elo better early, v1 better late) was found on these same
seasons, so any week-split reading here is a second look at the data that suggested it.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_stack_vs_elo.py
"""
from __future__ import annotations

import sqlite3

import nfl_elo_replica as er
import nfl_feature_backtest as fb
import nfl_metrics as nm

BUCKETS = (("wk 2-4", 2, 4), ("wk 5-9", 5, 9), ("wk 10-14", 10, 14), ("wk 15+", 15, 99))


def diff(rs, fa, fb_, label):
    a = [(fa(r) - r["outcome"]) ** 2 for r in rs]
    b = [(fb_(r) - r["outcome"]) ** 2 for r in rs]
    pt, lo, hi = nm.bootstrap_mean_diff_ci(a, b, reps=5000)
    return "%-26s n=%4d  %+.4f [%+.4f, %+.4f]%s" % (
        label, len(rs), pt, lo, hi, "  <- interval excludes 0" if (lo > 0 or hi < 0) else "")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    games = er.load_games(con)
    neutral = {g[0]: g[2] for g in games}
    pre = er.run_elo(games, er.start_ratings(con))
    rows = fb.base_rows(con)
    cols, _ = er.elo_diff(con, rows)
    stk = fb.stack(rows, cols)
    g = fb.graded(rows)
    for r in g:
        r["p_elo"] = er.prob(pre[r["game_id"]], neutral[r["game_id"]])
        r["p_stack"] = stk[r["game_id"]][1]
    pe, ps, pv = (lambda r: r["p_elo"]), (lambda r: r["p_stack"]), (lambda r: r["p_model"])
    print("Brier, stack minus Elo (negative = stack better), 95% bootstrap interval")
    for name, seasons in (("2011-2023", range(2011, 2024)), ("2024", (2024,)), ("2025", (2025,)), ("2011-2025", range(2011, 2026))):
        rs = [r for r in g if r["season"] in seasons]
        print("  " + diff(rs, ps, pe, name))
    print("\nby week bucket, 2011-2025")
    for name, lo, hi in BUCKETS:
        rs = [r for r in g if lo <= r["week"] <= hi]
        print("  " + diff(rs, ps, pe, "stack - Elo " + name))
        print("  " + diff(rs, ps, pv, "stack - v1   " + name))
    print("\nby season, stack minus Elo")
    for s in range(2011, 2026):
        print("  " + diff([r for r in g if r["season"] == s], ps, pe, str(s)))


if __name__ == "__main__":
    main()
