#!/usr/bin/env python3
"""record_nfl_backtests.py -- write the A3 tuning grid and the 2025 holdout into model_runs.

--tune     one model_runs row per 2024 grid configuration (36). Status 'tuning'.
--holdout  one row for the frozen configuration on 2025. Status 'holdout'. One-shot: a second
           call refuses, because the holdout may be evaluated once.

Results live in params_json under "results", next to the parameters, so every number a
configuration produced is stored with the configuration that produced it.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python record_nfl_backtests.py --tune
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python record_nfl_backtests.py --holdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

import migrate_nfl_model_tables as mg
import nfl_backtest as nb
import nfl_tune_2024 as tune

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
FROZEN_TAG = "A3-frozen-d30ea75"
HOLDOUT_RUN_ID = "nfl-holdout-2025-A3-frozen-d30ea75"


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def record_tune(con):
    """Write one row per grid configuration. Re-running replaces the same run ids."""
    import itertools
    mg.migrate(con)
    results = []
    for hl, cap, cp in itertools.product(tune.GRID["half_life"], tune.GRID["cap"],
                                         tune.GRID["cap_points"]):
        results.append(tune.evaluate(con, {"half_life": hl, "cap": cap, "cap_points": cp}))
    now = _now()
    for i, r in enumerate(results):
        run_id = "nfl-tune-2024-%02d" % i
        params = {"purpose": "tuning_2024", "season": 2024, "config": r["config"],
                  "results": {"sigma": r["sigma"], "n": r["n"], "brier": r["brier"],
                              "log_loss": r["log_loss"], "margin_mae": r["margin_mae"],
                              "nondefault": r["nondefault"]}}
        con.execute("INSERT OR REPLACE INTO model_runs (run_id, league, season, week, model, "
                    " model_version, started_at, finished_at, params_json, status, error) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, "nfl", 2024, None, "nfl-ratings-v1",
                     "nfl-ratings-v1 tuning 2024", now, now,
                     json.dumps(params, sort_keys=True), "tuning", None))
    con.commit()
    return len(results)


def record_holdout(con):
    """Evaluate 2025 once with the frozen configuration and record it. Refuses a second run."""
    mg.migrate(con)
    if con.execute("SELECT 1 FROM model_runs WHERE run_id = ?", (HOLDOUT_RUN_ID,)).fetchone():
        raise SystemExit("holdout already recorded (%s); it is evaluated once" % HOLDOUT_RUN_ID)
    rows = nb.backtest_season(con, 2025, FROZEN)
    summary = nb.summarize(rows, reps=10000)
    now = _now()
    params = {"purpose": "holdout_2025", "season": 2025, "config": {k: FROZEN[k] for k in
                                                                    ("half_life", "cap", "cap_points")},
              "sigma": FROZEN["sigma"], "config_tag": FROZEN_TAG, "results": summary}
    con.execute("INSERT INTO model_runs (run_id, league, season, week, model, model_version, "
                " started_at, finished_at, params_json, status, error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (HOLDOUT_RUN_ID, "nfl", 2025, None, "nfl-ratings-v1",
                 "nfl-ratings-v1 holdout 2025 " + FROZEN_TAG, now, now,
                 json.dumps(params, sort_keys=True, default=str), "holdout", None))
    con.commit()
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tune", action="store_true")
    g.add_argument("--holdout", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=30)
    try:
        mg.migrate(con)
        if args.tune:
            print("recorded %d tuning runs" % record_tune(con))
        else:
            s = record_holdout(con)
            print("recorded %s: n=%d brier=%.4f coin=%.4f home57=%.4f"
                  % (HOLDOUT_RUN_ID, s["n"], s["brier"]["model"], s["brier"]["coin"],
                     s["brier"]["home57"]))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
