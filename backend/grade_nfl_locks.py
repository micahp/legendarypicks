#!/usr/bin/env python3
"""grade_nfl_locks.py -- grade every locked NFL projection whose game is final (SPEC A 2.3, 7).

One row per (league, game_id, model_version) in projection_grades; the unique index makes a
second run a no-op for games already graded, and the run says how many it skipped.

A game is graded only when the publisher says it is over: both scores and nflverse's `result`
(home minus away) are present, `result` equals the score difference (a disagreement raises,
it is never graded), and kickoff was at least FINAL_AFTER_HOURS ago, so a score written while the
game is still being played cannot be graded as final.

Per row:
- brier, logloss of p_home_win against home win. A tie has no outcome: both stay NULL.
- margin_err = actual margin - projected margin; total_err = actual total - projected total
  (signed, so bias is visible; MAE is their absolute mean).
- ats_result: the model's side against the line it locked against, read from the line snapshot
  (or the row's own market_spread for locks written before snapshots existed). The model takes
  the home side when its projected margin is above the spread, away when below. 'win', 'loss',
  'push', 'no_pick' (projection equals the line) or 'no_line'.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python grade_nfl_locks.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sqlite3
import sys

import check_nfl_schedule_scores as cs
import nfl_lock
import nfl_metrics as mt

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
FINAL_AFTER_HOURS = 4.0
EPS = 1e-12


def ats(actual_margin, proj_margin, spread):
    if spread is None:
        return "no_line"
    if abs(proj_margin - spread) < 1e-9:
        return "no_pick"
    home = mt.ats_result(actual_margin, spread)       # cover / miss / push for the home side
    if home == "push":
        return "push"
    took_home = proj_margin > spread
    return "win" if (home == "cover") == took_home else "loss"


def grade_row(p_home, proj_margin, proj_total, spread, hs, as_):
    margin, total = hs - as_, hs + as_
    if hs == as_:
        brier = logloss = None
    else:
        y = 1.0 if hs > as_ else 0.0
        p = min(max(p_home, EPS), 1 - EPS)
        brier = (p_home - y) ** 2
        logloss = -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return brier, logloss, margin - proj_margin, total - proj_total, ats(margin, proj_margin, spread)


def run(con, now, dry_run=False):
    rows = con.execute(
        "SELECT g.game_id, g.model_version, g.proj_margin, g.proj_total, g.p_home_win, "
        "       COALESCE(s.spread_line, g.market_spread), "
        "       n.home_score, n.away_score, n.result, n.gameday, n.gametime "
        "FROM game_projections g "
        "JOIN model_runs r ON r.run_id = g.run_id AND r.status = 'ok' "
        "JOIN nfl_schedule n ON n.game_id = g.game_id "
        "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
        "WHERE g.league = ? AND g.locked = 1 ORDER BY g.game_id, g.model_version",
        (nfl_lock.LEAGUE,)).fetchall()
    counts = {"locked": len(rows), "graded": 0, "already": 0, "not_final": 0}
    for gid, mv, pm, pt, pw, spread, hs, as_, result, gameday, gametime in rows:
        if mv is None:
            raise ValueError("locked row %s has no model_version" % gid)
        if hs is None or as_ is None or result is None:
            counts["not_final"] += 1
            continue
        if abs(float(result) - (float(hs) - float(as_))) > 1e-9:
            raise ValueError("%s: published result %s disagrees with score %s-%s"
                             % (gid, result, hs, as_))
        hours = (now - cs.kickoff_utc(gameday, gametime)).total_seconds() / 3600.0
        if hours < FINAL_AFTER_HOURS:
            counts["not_final"] += 1
            continue
        if con.execute("SELECT 1 FROM projection_grades WHERE league = ? AND game_id = ? AND "
                       "model_version = ?", (nfl_lock.LEAGUE, gid, mv)).fetchone():
            counts["already"] += 1
            continue
        brier, ll, merr, terr, atsr = grade_row(pw, pm, pt, spread, float(hs), float(as_))
        if not dry_run:
            con.execute(
                "INSERT INTO projection_grades (league, game_id, model_version, actual_home, "
                " actual_away, brier, logloss, margin_err, total_err, ats_result, graded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (nfl_lock.LEAGUE, gid, mv, hs, as_, brier, ll, merr, terr, atsr, now.isoformat()))
        counts["graded"] += 1
    if not dry_run:
        con.commit()
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    try:
        nfl_lock.ensure_schema(con)
        counts = run(con, dt.datetime.now(dt.timezone.utc), dry_run=args.dry_run)
    finally:
        con.close()
    print("locked rows %(locked)d: graded %(graded)d, already graded %(already)d, "
          "not final %(not_final)d" % counts + (" (dry run: nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
