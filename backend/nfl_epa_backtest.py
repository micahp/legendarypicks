#!/usr/bin/env python3
"""nfl_epa_backtest.py -- SPEC A 9.4 part 1: walk-forward backtest of the v2 pure EPA model.

PRE-REGISTERED 2026-10-11, committed before any run. Changing a rule after a result is a new
experiment and must be labelled as one.

Design
- Ratings for a game in week w use plays from weeks < w of that season only (nfl_epa_model.fit),
  prior = previous season's final fit shrunk one third. 2024 has no prior (2023 not loaded).
- EPA -> points (a, b, h) and sigma are refit before every graded week from a pool that contains
  only earlier games: all of the previous season's walk-forward predictions plus this season's
  games before the week. No game is ever used to calibrate its own prediction.
- Graded games: weeks >= START_WEEK of the season, and only while the pool has >= MIN_POOL games.
  2024 has no previous season, so its first graded week is later; v1 is scored on the SAME games.
- v1 comparator: nfl_backtest.backtest_season with the frozen configuration (half_life 6, cap 14,
  cap_points off), sigma 13.295, on the same game ids.
- Ties excluded from Brier / log loss, counted.

Grid (2024 only): half_life {3, 6, 12} x lam {50, 150, 450}. Defaults half_life 6, lam 150.
Selection: 2024 Brier to three decimals ascending, then fewer non-default parameters; log loss
is the check, never an override. The chosen pair is frozen, then 2025 is run ONCE.

Pass conditions (the only ones; the prospective test in 9.4 part 2 decides adoption):
- 2025 Brier of v2 below v1's on the same games, and the paired bootstrap 95% interval of
  (v2 - v1) Brier excludes zero. Anything else is reported as "not shown better".
2025 was already v1's holdout, so it is a second look, not a clean holdout.
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import os
import sqlite3
import statistics
import sys

import numpy as np

import nfl_backtest as nb
import nfl_epa_model as em
import nfl_lock
import nfl_metrics as mt

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
GRID = {"half_life": [3.0, 6.0, 12.0], "lam": [50.0, 150.0, 450.0]}
DEFAULTS = {"half_life": 6.0, "lam": 150.0}
START_WEEK = 2
MIN_POOL = 100
V1 = {"half_life": 6.0, "cap": 14.0, "cap_points": None}
V1_SIGMA = 13.295


def teams_of(con, season):
    return sorted({r[0] for r in con.execute(
        "SELECT home_team FROM nfl_schedule WHERE season = ? AND game_type = 'REG'", (season,))})


def season_plays(con, season):
    return em.plays(con, season)


def sched(con, season):
    return con.execute(
        "SELECT week, game_id, home_team, away_team, location, home_score, away_score, "
        "spread_line, total_line FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND home_score IS NOT NULL ORDER BY week, game_id", (season,)).fetchall()


def final_prior(plays_prev, teams_prev, hl, lam):
    return em.shrink(em.fit(plays_prev, teams_prev, half_life=hl, lam=lam))


def walk_forward(plays, g, teams, prior, hl, lam):
    """[(week, gid, h, a, neutral, pred_h, pred_a, hs, as_, spread, total)] from earlier weeks."""
    out = []
    for w in sorted({r[0] for r in g}):
        if w < START_WEEK:
            continue
        rows = [p for p in plays if p[0] < w]
        if not rows:
            continue
        r = em.fit(rows, teams, prior=prior, half_life=hl, lam=lam)
        for wk, gid, h, a, loc, hs, as_, sp, tl in (x for x in g if x[0] == w):
            neu = (loc or "").strip().lower() == "neutral"
            out.append((wk, gid, h, a, neu, em.predictor(r, h, a), em.predictor(r, a, h),
                        hs, as_, sp, tl))
    return out


def fit_abh(pool):
    obs = []
    for wk, gid, h, a, neu, ph, pa, hs, as_, sp, tl in pool:
        obs.append((ph, 0 if neu else 1, hs))
        obs.append((pa, 0 if neu else -1, as_))
    a_, b_, h_ = em.calibrate(obs)
    res = []
    for wk, gid, h, a, neu, ph, pa, hs, as_, sp, tl in pool:
        hh = 0.0 if neu else h_
        res.append((hs - as_) - ((a_ + b_ * ph + hh / 2) - (a_ + b_ * pa - hh / 2)))
    return a_, b_, h_, float(np.std(res, ddof=1))


def graded(wf, prev_wf):
    """Expanding calibration. Returns [(row, ph, pa, sigma)] for graded games."""
    out = []
    for w in sorted({r[0] for r in wf}):
        pool = list(prev_wf) + [r for r in wf if r[0] < w]
        if len(pool) < MIN_POOL:
            continue
        a_, b_, h_, sig = fit_abh(pool)
        for r in (x for x in wf if x[0] == w):
            hh = 0.0 if r[4] else h_
            out.append((r, a_ + b_ * r[5] + hh / 2, a_ + b_ * r[6] - hh / 2, sig))
    return out


def metrics(items, v1_by_id):
    """v2 and v1 metrics on the identical, non-tied game set."""
    p2, p1, y, m2, m1, t2, t1, ml, tl = [], [], [], [], [], [], [], [], []
    ties = 0
    for r, ph, pa, sig in items:
        hs, as_ = r[7], r[8]
        v = v1_by_id.get(r[1])
        if v is None:
            continue
        if hs == as_:
            ties += 1
            continue
        y.append(1 if hs > as_ else 0)
        p2.append(em.phi((ph - pa) / sig))
        p1.append(em.phi(v["proj_margin"] / V1_SIGMA))
        am, at = hs - as_, hs + as_
        m2.append(abs(am - (ph - pa)))
        m1.append(abs(am - v["proj_margin"]))
        t2.append(abs(at - (ph + pa)))
        t1.append(abs(at - v["proj_total"]))
        if r[9] is not None:
            ml.append(abs(am - r[9]))
        if r[10] is not None:
            tl.append(abs(at - r[10]))
    n = len(y)
    b2 = [(p - o) ** 2 for p, o in zip(p2, y)]
    b1 = [(p - o) ** 2 for p, o in zip(p1, y)]
    return {
        "n": n, "ties": ties,
        "brier_v2": sum(b2) / n, "brier_v1": sum(b1) / n,
        "ll_v2": mt.log_loss(p2, y), "ll_v1": mt.log_loss(p1, y),
        "margin_mae_v2": sum(m2) / n, "margin_mae_v1": sum(m1) / n,
        "margin_mae_line": sum(ml) / max(1, len(ml)),
        "total_mae_v2": sum(t2) / n, "total_mae_v1": sum(t1) / n,
        "total_mae_line": sum(tl) / max(1, len(tl)),
        "_b2": b2, "_b1": b1,
    }


def v1_rows(con, season):
    rows = nb.backtest_season(con, season, V1)
    return {r["game_id"]: r for r in rows}


def run_season(con, season, hl, lam, prev=None):
    """prev: (plays_prev, g_prev, teams_prev) or None. Returns graded items."""
    plays = season_plays(con, season)
    g = sched(con, season)
    teams = teams_of(con, season)
    prior, prev_wf = None, []
    if prev is not None:
        pp, pg, pt = prev
        prior = final_prior(pp, pt, hl, lam)
        # previous season's own walk-forward predictions (its prior: none loaded for 2024)
        prev_wf = walk_forward(pp, pg, pt, None, hl, lam)
    wf = walk_forward(plays, g, teams, prior, hl, lam)
    return graded(wf, prev_wf)


MODEL = "nfl-epa-v2"


def record(con, run_id, season, version, status, params, m):
    """One model_runs row with the metrics exactly as computed; a run id is written once."""
    if con.execute("SELECT 1 FROM model_runs WHERE run_id = ?", (run_id,)).fetchone():
        raise SystemExit("already recorded: %s (a result is recorded once)" % run_id)
    nfl_lock.ensure_schema(con)
    out = dict(params)
    out["results"] = {k: v for k, v in m.items() if not k.startswith("_")}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
        " finished_at, params_json, status, error) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
        (run_id, "nfl", season, None, MODEL, version, now, now, json.dumps(out, sort_keys=True),
         status))
    con.commit()


def line(label, m):
    print("%-26s n %3d  Brier v2 %.4f v1 %.4f | LL v2 %.4f v1 %.4f | margin MAE v2 %.3f v1 %.3f "
          "line %.3f | total MAE v2 %.3f v1 %.3f line %.3f"
          % (label, m["n"], m["brier_v2"], m["brier_v1"], m["ll_v2"], m["ll_v1"],
             m["margin_mae_v2"], m["margin_mae_v1"], m["margin_mae_line"],
             m["total_mae_v2"], m["total_mae_v1"], m["total_mae_line"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["tune2024", "holdout2025"], required=True)
    ap.add_argument("--half-life", type=float)
    ap.add_argument("--lam", type=float)
    ap.add_argument("--record", action="store_true",
                    help="write each result to model_runs as computed (once per run id)")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    if args.stage == "tune2024":
        v1 = v1_rows(con, 2024)
        res = []
        for hl, lam in itertools.product(GRID["half_life"], GRID["lam"]):
            items = run_season(con, 2024, hl, lam)
            m = metrics(items, v1)
            nd = (hl != DEFAULTS["half_life"]) + (lam != DEFAULTS["lam"])
            res.append((round(m["brier_v2"], 3), nd, hl, lam, m))
            line("2024 hl %g lam %g" % (hl, lam), m)
        res.sort(key=lambda r: (r[0], r[1]))
        best = res[0]
        print("CHOSEN (Brier to 3 decimals, then fewer non-defaults): half_life %g lam %g"
              % (best[2], best[3]))
        if args.record:
            for _, nd, hl, lam, m in res:
                record(con, "nfl-epa-v2-tune-2024-hl%g-lam%g" % (hl, lam), 2024,
                       "nfl-epa-v2 tuning 2024", "tuning",
                       {"purpose": "tuning_2024", "half_life": hl, "lam": lam,
                        "shrink": em.SHRINK, "start_week": START_WEEK, "min_pool": MIN_POOL,
                        "chosen": (hl, lam) == (best[2], best[3])}, m)
            print("recorded %d tuning rows" % len(res))
        return 0
    if args.half_life is None or args.lam is None:
        ap.error("holdout2025 needs --half-life and --lam (the frozen 2024 choice)")
    hl, lam = args.half_life, args.lam
    prev = (season_plays(con, 2024), sched(con, 2024), teams_of(con, 2024))
    items = run_season(con, 2025, hl, lam, prev=prev)
    m = metrics(items, v1_rows(con, 2025))
    line("2025 second look hl %g lam %g" % (hl, lam), m)
    pt, lo, hi = mt.bootstrap_mean_diff_ci(m["_b2"], m["_b1"])
    print("paired Brier diff (v2 - v1) %.4f, 95%% CI [%.4f, %.4f]; ties excluded %d" % (pt, lo, hi, m["ties"]))
    if args.record:
        m = dict(m, brier_diff_v2_minus_v1=pt, ci95=[lo, hi],
                 reading="second look; 2025 was already v1's holdout")
        record(con, "nfl-epa-v2-secondlook-2025-hl%g-lam%g" % (hl, lam), 2025,
               "nfl-epa-v2 second look 2025 hl=%g lam=%g" % (hl, lam), "holdout",
               {"purpose": "second_look_2025", "half_life": hl, "lam": lam,
                "shrink": em.SHRINK, "start_week": START_WEEK, "min_pool": MIN_POOL}, m)
        print("recorded the 2025 second look")
    return 0


if __name__ == "__main__":
    sys.exit(main())
