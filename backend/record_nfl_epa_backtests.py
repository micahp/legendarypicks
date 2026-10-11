#!/usr/bin/env python3
"""record_nfl_epa_backtests.py -- write the v2 (pure EPA) 2024 grid and 2025 second look to model_runs.

Values are the printed output of nfl_epa_backtest.py (stage tune2024, then holdout2025 with the
frozen half_life 12 / lam 450), run 2026-10-11 on the dev DB. One-shot per run_id: an existing
run is refused, so a second 2025 look cannot be recorded silently.

  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python record_nfl_epa_backtests.py
"""
import datetime as dt
import json
import os
import sqlite3
import sys

import nfl_lock

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
MODEL = "nfl-epa-v2"
# (half_life, lam, brier_v2, brier_v1, ll_v2, ll_v1, margin_mae_v2, margin_mae_v1, total_mae_v2, total_mae_v1)
GRID_2024 = [
    (3, 50, 0.2081, 0.1995, 0.6055, 0.5869, 9.986, 9.798, 10.713, 10.779),
    (3, 150, 0.2073, 0.1995, 0.6039, 0.5869, 9.975, 9.798, 10.804, 10.779),
    (3, 450, 0.2081, 0.1995, 0.6056, 0.5869, 9.988, 9.798, 10.864, 10.779),
    (6, 50, 0.2052, 0.1995, 0.5994, 0.5869, 9.965, 9.798, 10.490, 10.779),
    (6, 150, 0.2031, 0.1995, 0.5949, 0.5869, 9.937, 9.798, 10.590, 10.779),
    (6, 450, 0.2028, 0.1995, 0.5944, 0.5869, 9.936, 9.798, 10.680, 10.779),
    (12, 50, 0.2044, 0.1995, 0.5977, 0.5869, 9.960, 9.798, 10.376, 10.779),
    (12, 150, 0.2017, 0.1995, 0.5919, 0.5869, 9.921, 9.798, 10.471, 10.779),
    (12, 450, 0.2008, 0.1995, 0.5901, 0.5869, 9.917, 9.798, 10.574, 10.779),
]
KEYS = ("brier_v2", "brier_v1", "ll_v2", "ll_v1", "margin_mae_v2", "margin_mae_v1",
        "total_mae_v2", "total_mae_v1")
HOLDOUT = {"half_life": 12, "lam": 450, "n": 255, "ties_excluded": 1, "brier_v2": 0.2291,
           "brier_v1": 0.2288, "ll_v2": 0.6504, "ll_v1": 0.6496, "margin_mae_v2": 10.671,
           "margin_mae_v1": 10.671, "margin_mae_line": 9.971, "total_mae_v2": 10.496,
           "total_mae_v1": 10.614, "total_mae_line": 10.175,
           "brier_diff_v2_minus_v1": 0.0003, "ci95": [-0.0083, 0.0087],
           "reading": "not shown better; second look, 2025 was already v1's holdout"}


def put(con, run_id, season, version, params, status, now):
    if con.execute("SELECT 1 FROM model_runs WHERE run_id = ?", (run_id,)).fetchone():
        raise SystemExit("already recorded: %s" % run_id)
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
        " finished_at, params_json, status, error) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
        (run_id, "nfl", season, None, MODEL, version, now, now,
         json.dumps(params, sort_keys=True), status))


def main():
    con = sqlite3.connect(DB, timeout=60)
    nfl_lock.ensure_schema(con)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in GRID_2024:
        hl, lam = row[0], row[1]
        params = {"purpose": "tuning_2024", "season": 2024, "graded_games": 149,
                  "half_life": hl, "lam": lam, "shrink": 1 / 3, "start_week": 2, "min_pool": 100,
                  "results": dict(zip(KEYS, row[2:])), "chosen": (hl, lam) == (12, 450),
                  "script": "nfl_epa_backtest.py --stage tune2024"}
        put(con, "nfl-epa-v2-tune-2024-hl%g-lam%g" % (hl, lam), 2024,
            "nfl-epa-v2 tuning 2024", params, "tuning", now)
    put(con, "nfl-epa-v2-secondlook-2025-hl12-lam450", 2025,
        "nfl-epa-v2 second look 2025 hl=12 lam=450",
        {"purpose": "second_look_2025", "script": "nfl_epa_backtest.py --stage holdout2025",
         "results": HOLDOUT}, "holdout", now)
    con.commit()
    print("recorded %d tuning rows and 1 second-look row" % len(GRID_2024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
