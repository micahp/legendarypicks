#!/usr/bin/env python3
"""nfl_tune_2024.py -- the pre-registered 2024 tuning grid (SPEC A, 6.1, selection rule in the spec).

Touches 2024 only. The holdout season is never read here.

Grid: half_life x margin cap x cap_points. Prior parameters are not in the grid: 2024 has no
prior, so they cannot be tuned on 2024 (spec, A3 rules).

Per configuration:
  1. walk-forward 2024 rows (weeks 2-18), fitted on earlier weeks only;
  2. sigma = standard deviation of that configuration's own 2024 residuals (spec: sigma is
     fitted from 2024 residuals);
  3. p_model recomputed with that sigma (projections do not depend on sigma).

Ranking: Brier to three decimals ascending; ties go to the configuration with fewer non-default
parameters (the spec's tie rule); log loss is the final check. Log loss does not override the tie.
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
import statistics
import sys

import nfl_backtest as nb
import nfl_metrics as mt
import nfl_ratings as nr

SEASON = 2024
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
GRID = {
    "half_life": [3.0, 6.0, 12.0],
    "cap": [14.0, 21.0, None],
    "cap_points": [None, 14.0, 21.0, 28.0],
}
DEFAULTS = {"half_life": 6.0, "cap": 21.0, "cap_points": None}


def nondefault_count(cfg):
    return sum(1 for k, v in DEFAULTS.items() if cfg[k] != v)


def evaluate(con, cfg):
    rows = nb.backtest_season(con, SEASON, cfg)
    resid = [r["actual_margin"] - r["proj_margin"] for r in rows]
    sigma = statistics.pstdev(resid)
    graded = [r for r in rows if r["outcome"] is not None]
    y = [r["outcome"] for r in graded]
    p = [nr.win_probability(r["proj_margin"], sigma) for r in graded]
    return {
        "config": cfg, "sigma": round(sigma, 3), "n": len(graded),
        "brier": mt.brier(p, y), "log_loss": mt.log_loss(p, y),
        "margin_mae": mt.mae([r["proj_margin"] for r in rows],
                             [r["actual_margin"] for r in rows]),
        "nondefault": nondefault_count(cfg),
    }


def rank(results):
    # Spec order: Brier to three decimals, then fewer non-default parameters, then log loss
    # as the last check. Log loss does not override the tie rule.
    def key(r):
        return (round(r["brier"], 3), r["nondefault"], round(r["log_loss"], 3))
    return sorted(results, key=key)


def main(argv=None):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        results = []
        for hl, cap, cp in itertools.product(GRID["half_life"], GRID["cap"], GRID["cap_points"]):
            cfg = {"half_life": hl, "cap": cap, "cap_points": cp}
            results.append(evaluate(con, cfg))
    finally:
        con.close()
    ordered = rank(results)
    print("%-10s %-6s %-10s %7s %8s %8s %8s" % ("half_life", "cap", "cap_points", "sigma",
                                              "brier", "logloss", "margin"))
    for r in ordered:
        c = r["config"]
        print("%-10g %-6s %-10s %7.2f %8.4f %8.4f %8.2f" % (
            c["half_life"], "none" if c["cap"] is None else "%g" % c["cap"],
            "none" if c["cap_points"] is None else "%g" % c["cap_points"],
            r["sigma"], r["brier"], r["log_loss"], r["margin_mae"]))
    best = ordered[0]
    print("chosen (2024 only):", json.dumps(best["config"]), "sigma", best["sigma"])
    default = next(r for r in results if r["nondefault"] == 0)
    print("default config:", json.dumps(default["config"]), "brier %.4f" % default["brier"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
