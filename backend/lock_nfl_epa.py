#!/usr/bin/env python3
"""lock_nfl_epa.py -- calibrate the pure-EPA model (nfl_epa_model.py) and lock a week with it.

Calibration season (a, b, h, sigma) is a completed season, walk-forward, so a lock for season S
uses only S-1 and earlier outcomes for the conversion. Dry run by default.

  LP_DB_PATH=... venv/bin/python lock_nfl_epa.py --season 2026 --week 5 --calib 2025 [--skip ID] [--apply]
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sqlite3
import sys

import numpy as np

import nfl_epa_model as em
import nfl_lock

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")


def teams_of(con, season):
    return sorted({r[0] for r in con.execute(
        "SELECT home_team FROM nfl_schedule WHERE season = ? AND game_type = 'REG'", (season,))})


def final_prior(con, season):
    rows = em.plays(con, season - 1)
    if not rows:
        return None
    return em.shrink(em.fit(rows, teams_of(con, season - 1)))


def games(con, season):
    return con.execute(
        "SELECT week, game_id, home_team, away_team, location, home_score, away_score, "
        "spread_line, total_line FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND home_score IS NOT NULL ORDER BY week, game_id", (season,)).fetchall()


def walk_forward(con, season, prior):
    """Per game predictors from data before its week only. Returns [(week, gid, h, a, neutral,
    pred_h, pred_a, hs, as_)]."""
    teams = teams_of(con, season)
    g = games(con, season)
    out = []
    for w in sorted({r[0] for r in g}):
        if w < 2:
            continue
        rows = em.plays(con, season, before_week=w)
        if not rows:
            continue
        r = em.fit(rows, teams, prior=prior)
        for wk, gid, h, a, loc, hs, as_, sp, tl in (x for x in g if x[0] == w):
            neutral = (loc or "").strip().lower() == "neutral"
            out.append((wk, gid, h, a, neutral, em.predictor(r, h, a), em.predictor(r, a, h),
                        hs, as_, sp, tl))
    return out


def calibrate_from(wf):
    obs = []
    for wk, gid, h, a, neu, ph, pa, hs, as_, sp, tl in wf:
        obs.append((ph, 0 if neu else 1, hs))
        obs.append((pa, 0 if neu else -1, as_))
    a_, b_, h_ = em.calibrate(obs)
    res = []
    for wk, gid, h, a, neu, ph, pa, hs, as_, sp, tl in wf:
        hh = 0.0 if neu else h_
        mh = a_ + b_ * ph + hh / 2
        ma = a_ + b_ * pa - hh / 2
        res.append(((hs - as_) - (mh - ma)))
    sigma = float(np.std(res, ddof=1))
    return a_, b_, h_, sigma


def project(wf_row, abh):
    wk, gid, h, a, neu, ph, pa, hs, as_, sp, tl = wf_row
    a_, b_, h_, sigma = abh
    hh = 0.0 if neu else h_
    return a_ + b_ * ph + hh / 2, a_ + b_ * pa - hh / 2


def score(wf, abh, label):
    """Brier / margin MAE / total MAE vs the line, same definitions as v1's backtest."""
    br, mae, tmae, smae, n, tn = [], [], [], [], 0, 0
    sigma = abh[3]
    for r in wf:
        ph, pa = project(r, abh)
        hs, as_, sp, tl = r[7], r[8], r[9], r[10]
        if hs == as_:
            continue
        p = em.phi((ph - pa) / sigma)
        br.append((p - (1 if hs > as_ else 0)) ** 2)
        mae.append(abs((hs - as_) - (ph - pa)))
        tmae.append(abs((hs + as_) - (ph + pa)))
        if sp is not None:
            smae.append(abs((hs - as_) - sp))
        n += 1
    print("%s games %d Brier %.4f margin MAE %.3f (line %.3f) total MAE %.3f"
          % (label, n, sum(br) / n, sum(mae) / n, sum(smae) / max(1, len(smae)), sum(tmae) / n))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--calib", type=int, required=True, help="completed season for a, b, h, sigma")
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    cprior = final_prior(con, args.calib)
    wf = walk_forward(con, args.calib, cprior)
    abh = calibrate_from(wf)
    print("calibration %d (prior %s): a %.3f b %.3f h %.3f sigma %.3f"
          % (args.calib, "yes" if cprior else "none", *abh))
    score(wf, abh, "in-sample %d" % args.calib)
    teams = teams_of(con, args.season)
    prior = final_prior(con, args.season)
    rows = em.plays(con, args.season, before_week=args.week)
    r = em.fit(rows, teams, prior=prior)
    version = ("nfl-epa-v2 pure per-play half_life=%g lam=%g shrink=%.4f calib=%d sigma=%.3f "
               "NOT-ADOPTED untuned" % (em.HALF_LIFE, em.LAM, em.SHRINK, args.calib, abh[3]))
    as_of = dt.datetime.now(dt.timezone.utc).isoformat()
    sched = con.execute(
        "SELECT game_id, home_team, away_team, location, home_score, spread_line, total_line "
        "FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' ORDER BY game_id",
        (args.season, args.week)).fetchall()
    plan = []
    print("model %s" % version)
    print("%-17s %-4s %-4s %6s %6s %6s %6s %5s %6s %6s" % ("game", "H", "A", "pH", "pA", "marg",
                                                      "total", "p_H", "spr", "tot"))
    for gid, h, a, loc, hs, sp, tl in sched:
        neu = (loc or "").strip().lower() == "neutral"
        hh = 0.0 if neu else abh[2]
        ph = abh[0] + abh[1] * em.predictor(r, h, a) + hh / 2
        pa = abh[0] + abh[1] * em.predictor(r, a, h) - hh / 2
        p = em.phi((ph - pa) / abh[3])
        skip = gid in args.skip or hs is not None
        print("%-17s %-4s %-4s %6.1f %6.1f %6.1f %6.1f %5.2f %6s %6s %s"
              % (gid, h, a, ph, pa, ph - pa, ph + pa, p, sp, tl, "SKIP" if skip else ""))
        if not skip:
            plan.append((gid, h, a, ph, pa, p, sp, tl))
    if not args.apply:
        print("dry run: nothing written")
        return 0
    nfl_lock.ensure_schema(con)
    run_id = "nfl-epa-lock-%d-w%02d-%s" % (args.season, args.week, as_of)
    nfl_lock.start_run(con, run_id, args.season, args.week, version,
                       {"model": "pure per-play EPA", "calib": args.calib, "a": abh[0],
                        "b": abh[1], "h": abh[2], "sigma": abh[3], "tuned": False,
                        "adopted": False, "mode": "lock"})
    new = 0
    for gid, h, a, ph, pa, p, sp, tl in plan:
        if con.execute("SELECT 1 FROM game_projections WHERE league='nfl' AND game_id=? AND "
                       "locked=1 AND model_version=?", (gid, version)).fetchone():
            continue
        con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            " proj_home, proj_away, proj_margin, proj_total, p_home_win, market_spread, "
            " market_total, market_source, model_version, locked, locked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (run_id, "nfl", gid, args.season, args.week, h, a, ph, pa, ph - pa, ph + pa, p, sp, tl,
             nfl_lock.MARKET_SOURCE, version, as_of))
        new += 1
    con.commit()
    nfl_lock.finish_run(con, run_id, "ok")
    print("applied run=%s new_locks=%d" % (run_id, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
