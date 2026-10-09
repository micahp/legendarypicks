#!/usr/bin/env python3
"""lock_nfl_week.py -- lock the game projections for one NFL week (SPEC A, 4.3 and A2).

Inputs are the ones the lock is defined by, and all are recorded in model_version:
- fit: scored REG games of weeks before --week only (nfl_ratings_data.fit_for_week)
- prior: final rating of season - 1, shrunk one third (nfl_ratings_data.prior_for_season)
- sigma: passed in (measured in the A2 walk-forward: 13.4 for 2024-2025 pooled)

Dry run by default: prints the projection for every game and writes nothing. --apply locks
the unplayed games. Played games with no lock are listed as skipped, never written.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python lock_nfl_week.py \\
      --season 2026 --week 5 [--sigma 13.4] [--apply]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

import nfl_lock
import nfl_ratings as nr
import nfl_ratings_data as nrd

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
# The frozen A3 configuration (SPEC A, 6.1, d30ea75): chosen on 2024 only, held out on 2025.
# Week-5 2026 locks were written before this freeze with the then-default cap of 21 and sigma
# 13.4; they stay as they are (locks are never overwritten) and are recorded as such.
FROZEN_HALF_LIFE = 6.0
FROZEN_CAP = 14.0
FROZEN_PRIOR_GAMES = 4.0
FROZEN_CAP_POINTS = None
DEFAULT_SIGMA = 13.295
SHRINK = nrd.DEFAULT_SHRINK


def model_version(sigma, half_life, cap, prior_games):
    return ("nfl-v1 half_life=%g cap=%s prior_games=%g prior_shrink=%.4f sigma=%g"
            % (half_life, cap, prior_games, SHRINK, sigma))


def build(con, season, week, sigma, half_life=FROZEN_HALF_LIFE, cap=FROZEN_CAP,
          prior_games=FROZEN_PRIOR_GAMES):
    # The prior is built with the same parameters as the fit, so one configuration is used.
    prior = nrd.prior_for_season(con, season, shrink=SHRINK, half_life=half_life, cap=cap,
                                 prior_games=prior_games)
    fit, used = nrd.fit_for_week(con, season, week, prior=prior, half_life=half_life,
                                 cap=cap, prior_games=prior_games)
    return fit, used, model_version(sigma, half_life, cap, prior_games)


def plan_rows(con, season, week, fit, sigma):
    rows = con.execute(
        "SELECT game_id, home_team, away_team, location, home_score, away_score, spread_line "
        "FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' ORDER BY game_id",
        (season, week)).fetchall()
    out = []
    for gid, h, a, loc, hs, as_, spread in rows:
        ph, pa = nr.expected_points(fit, h, a, (loc or "").strip().lower() == "neutral")
        out.append((gid, h, a, ph - pa, nr.win_probability(ph - pa, sigma), spread,
                    None if hs is None else "%g-%g" % (hs, as_)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--sigma", type=float, default=DEFAULT_SIGMA)
    ap.add_argument("--apply", action="store_true", help="write the locks (default: dry run)")
    args = ap.parse_args(argv)
    if args.sigma <= 0:
        ap.error("sigma must be > 0")
    as_of = dt.datetime.now(dt.timezone.utc).isoformat()
    con = sqlite3.connect(DB, timeout=30)
    try:
        fit, used, version = build(con, args.season, args.week, args.sigma)
        print("model   %s" % version)
        print("fit     %d games before week %d; mu %.2f h %.2f" % (used, args.week, fit.mu, fit.h))
        print("as_of   %s" % as_of)
        print("%-18s %-4s %-4s %8s %6s %8s %s" % ("game", "H", "A", "proj_m", "p_H", "mkt_H", "result"))
        for gid, h, a, pm, pw, spread, result in plan_rows(con, args.season, args.week, fit, args.sigma):
            print("%-18s %-4s %-4s %8.1f %6.2f %8s %s" % (gid, h, a, pm, pw,
                                                       "" if spread is None else "%g" % spread,
                                                       result or ""))
        if not args.apply:
            print("dry run: nothing written. Re-run with --apply to lock the unplayed games.")
            return 0
        nfl_lock.ensure_schema(con)
        run_id = "nfl-lock-%d-w%02d-%s" % (args.season, args.week, as_of)
        params = {"season": args.season, "week": args.week, "sigma": args.sigma,
                  "half_life": FROZEN_HALF_LIFE, "cap": FROZEN_CAP,
                  "prior_games": FROZEN_PRIOR_GAMES, "prior_shrink": SHRINK,
                  "cap_points": FROZEN_CAP_POINTS, "config": "A3-frozen-d30ea75",
                  "fit_games": used, "mode": "lock", "skip_scored": True}
        nfl_lock.start_run(con, run_id, args.season, args.week, version, params)
        try:
            out = nfl_lock.lock_week(con, run_id, args.season, args.week, fit, args.sigma,
                                     as_of=as_of, skip_scored=True)
        except Exception as exc:
            nfl_lock.finish_run(con, run_id, "failed", error=str(exc))
            raise
        nfl_lock.finish_run(con, run_id, "ok")
        print("applied run=%s new_locks=%d refreshes=%d skipped=%s"
              % (run_id, out["new_locks"], out["refreshes"], out["skipped"] or "none"))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
