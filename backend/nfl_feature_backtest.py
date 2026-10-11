#!/usr/bin/env python3
"""nfl_feature_backtest.py -- one candidate feature at a time, stacked on frozen v1, judged
against a recalibrated v1 and against the de-vigged market. Read-only: the database is opened
with mode=ro and nothing is recorded. Plan: docs/PLAN-nfl-features-2026-10-11.md.

PRE-REGISTERED RULES (shared by every feature; written before any feature was run)
- Base: frozen v1 walk-forward rows (nfl_backtest.backtest_season, half_life 6, cap 14,
  cap_points off), seasons 2010-2025. Each row uses only earlier weeks of its season.
- Stack: for target season S, OLS of actual home margin on [1, v1 projected margin, feature
  columns], fitted on every base row of seasons 2010 to S-1 (ties included in the margin fit).
  sigma = sd (ddof 1) of that fit's residuals unless the feature defines its own sigma.
  p_home = Phi(margin / sigma). Baseline B is the same stack with no feature columns.
- Every feature column for a game is computed from data dated before that game's week.
- Graded set: games with an outcome (no tie), a moneyline and a spread. Groups: 2011-2023
  pooled (development; 2010 is training only), 2024 (confirmation), 2025 (second look only,
  it was v1's holdout).
- Intervals: nfl_metrics.bootstrap_mean_diff_ci, 5,000 resamples, its fixed seed.
- KEEP rule: the pooled 2011-2023 interval of Brier(feature) - Brier(B) lies entirely below
  zero, AND the 2024 and 2025 point differences are not above zero. Anything else is not kept.
  Margin MAE (feature - B) is reported the same way; a feature that changes only sigma cannot
  move it. The gap to the market (feature - market) is reported for every group.
- No parameter is chosen by looking at any result of this harness. Feature parameters are fixed
  in each feature's own docstring before it is run.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_feature_backtest.py --feature <name>
       (--feature base prints B and frozen v1 only)
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys

import numpy as np

import nfl_backtest as nb
import nfl_metrics as nm

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
SEASONS = list(range(2010, 2026))
GROUPS = (("2011-2023", range(2011, 2024)), ("2024", (2024,)), ("2025", (2025,)))
REPS = 5000


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def base_rows(con):
    rows = []
    for s in SEASONS:
        rows += nb.backtest_season(con, s, FROZEN)
    return rows


def ols(X, y):
    beta, *_ = np.linalg.lstsq(np.asarray(X), np.asarray(y), rcond=None)
    return beta


def stack(rows, cols=None, sigma_fn=None):
    """Return game_id -> (proj_margin, p_home) for seasons 2011-2025.

    cols: game_id -> list of feature values (None = baseline B).
    sigma_fn(train_rows, residuals) -> function(row) -> sigma, or None for one sigma.
    """
    out = {}
    for s in SEASONS[1:]:
        train = [r for r in rows if r["season"] < s]
        test = [r for r in rows if r["season"] == s]

        def x(r):
            return [1.0, r["proj_margin"]] + (list(cols[r["game_id"]]) if cols else [])
        beta = ols([x(r) for r in train], [r["actual_margin"] for r in train])
        res = np.array([r["actual_margin"] for r in train]) - np.array([x(r) for r in train]) @ beta
        if sigma_fn is None:
            sd = float(np.std(res, ddof=1))
            sig = lambda r, sd=sd: sd
        else:
            sig = sigma_fn(train, res)
        for r in test:
            m = float(np.dot(x(r), beta))
            out[r["game_id"]] = (m, phi(m / sig(r)))
    return out


def graded(rows):
    return [r for r in rows if r["p_market"] is not None and r["outcome"] is not None
            and r["spread_line"] is not None and r["season"] >= 2011]


def report(rows, base, feat, label):
    print("feature: %s" % label)
    for name, seasons in GROUPS:
        g = [r for r in graded(rows) if r["season"] in seasons]
        y = [r["outcome"] for r in g]
        bb = [(base[r["game_id"]][1] - o) ** 2 for r, o in zip(g, y)]
        bf = [(feat[r["game_id"]][1] - o) ** 2 for r, o in zip(g, y)]
        bk = [(r["p_market"] - o) ** 2 for r, o in zip(g, y)]
        bv = [(r["p_model"] - o) ** 2 for r, o in zip(g, y)]
        eb = [abs(base[r["game_id"]][0] - r["actual_margin"]) for r in g]
        ef = [abs(feat[r["game_id"]][0] - r["actual_margin"]) for r in g]
        es = [abs(float(r["spread_line"]) - r["actual_margin"]) for r in g]
        d_fb = nm.bootstrap_mean_diff_ci(bf, bb, reps=REPS)
        d_fk = nm.bootstrap_mean_diff_ci(bf, bk, reps=REPS)
        d_bk = nm.bootstrap_mean_diff_ci(bb, bk, reps=REPS)
        m_fb = nm.bootstrap_mean_diff_ci(ef, eb, reps=REPS)
        n = len(g)
        print("  %-9s n=%4d Brier v1 %.4f B %.4f F %.4f mkt %.4f | F-B %+.4f [%+.4f,%+.4f] | "
              "F-mkt %+.4f [%+.4f,%+.4f] | B-mkt %+.4f [%+.4f,%+.4f]"
              % (name, n, sum(bv) / n, sum(bb) / n, sum(bf) / n, sum(bk) / n,
                 *d_fb, *d_fk, *d_bk))
        print("  %-9s        margin MAE B %.3f F %.3f spread %.3f | F-B %+.3f [%+.3f,%+.3f]"
              % ("", sum(eb) / n, sum(ef) / n, sum(es) / n, *m_fb))


FEATURES = {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=["base"] + sorted(FEATURES))
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = base_rows(con)
    base = stack(rows)
    if a.feature == "base":
        report(rows, base, base, "base (F = B)")
        return 0
    cols, sigma_fn = FEATURES[a.feature](con, rows)
    report(rows, base, stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
