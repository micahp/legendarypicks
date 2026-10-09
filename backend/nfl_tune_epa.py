"""nfl_tune_epa.py -- the pre-registered 2024 grid for the version 2 EPA blend (SPEC A, 9).

Version 1's own parameters are FROZEN (d30ea75: half_life 6, cap 14, prior_games 4,
cap_points None, shrink 1/3) and are not in this grid: v2 must beat v1 as configured.

Touches 2024 only. The holdout season (2025) is never read here. 2024 has no prior: 2023 is
not ingested, so both fits run prior-less, exactly as the A3 2024 grid did.

Grid: w_blend x epa_half_life x epa_cap. Per configuration, over the walk-forward 2024 rows
(weeks 2-18, fitted on earlier weeks only):
  sigma = standard deviation of that configuration's own 2024 residuals (the A3 rule);
  Brier/log loss on the re-scaled win probability, margin MAE on the blend itself.

Ranking: Brier to three decimals ascending; ties go to the configuration with fewer
non-default EPA parameters (the spec's tie rule); log loss is the final check.
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
import sys

import nfl_epa_efficiency as ee
import nfl_metrics as mt

SEASON = 2024
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
GRID = {
    "w_blend": [0.2, 0.3, 0.4, 0.5, 0.6],
    "epa_half_life": [3.0, 6.0, 12.0],
    "epa_cap": [10.0, 14.0, None],
}


def rank(results):
    def key(r):
        return (round(r["blend"]["brier"]["model"], 3), r["nondefault"],
                round(r["blend"]["log_loss"]["model"], 3))
    return sorted(results, key=key)


def main(argv=None):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        results = []
        for w, ehl, ecap in itertools.product(GRID["w_blend"], GRID["epa_half_life"],
                                              GRID["epa_cap"]):
            cfg = {"w_blend": w, "epa_half_life": ehl, "epa_cap": ecap}
            results.append(ee.evaluate(con, SEASON, cfg))
    finally:
        con.close()
    ordered = rank(results)
    print("%-8s %-8s %-8s %8s %9s %9s %8s" % ("w_blend", "epa_hl", "epa_cap",
                                              "sigma", "brier", "logloss", "margin_mae"))
    for r in ordered:
        c = r["config"]
        print("%-8g %-8g %-8s %8.2f %9.4f %9.4f %8.2f" % (
            c["w_blend"], c["epa_half_life"],
            "none" if c["epa_cap"] is None else "%g" % c["epa_cap"],
            r["sigma"], r["blend"]["brier"]["model"], r["blend"]["log_loss"]["model"],
            r["blend"]["margin_mae"]["model"]))
    v1 = results[0]["v1"]
    print("\nv1 baseline (frozen, same walk-forward, own sigma): "
          "brier %.4f log_loss %.4f margin_mae %.2f sigma %.3f n %d" % (
              v1["brier"]["model"], v1["log_loss"]["model"],
              v1["margin_mae"]["model"], v1["sigma"] if "sigma" in v1 else float("nan"),
              v1["n"]))
    best = ordered[0]
    print("chosen (2024 only):", json.dumps(best["config"]),
          "sigma", best["sigma"], "brier %.4f" % best["blend"]["brier"]["model"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
