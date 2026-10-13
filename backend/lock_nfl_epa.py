#!/usr/bin/env python3
"""lock_nfl_epa.py -- lock one NFL week with the v2 pure EPA model (SPEC A 9.3).

Projections are built exactly the way nfl_epa_backtest.py grades them, so a lock is the same
model the backtest measured:
- ratings: plays of this season before --week (nfl_epa_model.fit), prior = last season's final
  fit shrunk one third, at the frozen half_life and lam;
- EPA to points (a, b, h) and sigma: fitted on walk-forward predictions of last season plus this
  season's scored weeks before --week (nfl_epa_backtest.fit_abh), never on the games being locked.
Writing goes through nfl_lock.lock_week: kickoff guard, line snapshot, one lock per version.

Frozen choice from the 2024 grid (docs/RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md): half_life
12, lam 450. Dry run by default.

  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python lock_nfl_epa.py \\
      --season 2026 --week 6 [--apply]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

import nfl_epa_backtest as bt
import nfl_epa_model as em
import nfl_lock

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
FROZEN_HALF_LIFE = 12.0
FROZEN_LAM = 450.0


def build(con, season, week, hl=FROZEN_HALF_LIFE, lam=FROZEN_LAM):
    """Returns (project, info). project(home, away, neutral) -> (proj_home, proj_away, p_home)."""
    prev_plays = bt.season_plays(con, season - 1)
    if not prev_plays:
        raise ValueError("no plays for %d: the EPA prior and calibration need it" % (season - 1))
    prev_teams = bt.teams_of(con, season - 1)
    older = bt.season_plays(con, season - 2)
    prev_prior = (bt.final_prior(older, bt.teams_of(con, season - 2), hl, lam) if older else None)
    prev_wf = bt.walk_forward(prev_plays, bt.sched(con, season - 1), prev_teams, prev_prior, hl, lam)
    prior = bt.final_prior(prev_plays, prev_teams, hl, lam)
    plays = [p for p in bt.season_plays(con, season) if p[0] < week]
    if not plays:
        raise ValueError("no plays of %d before week %d" % (season, week))
    teams = bt.teams_of(con, season)
    cur_wf = [r for r in bt.walk_forward(bt.season_plays(con, season), bt.sched(con, season),
                                         teams, prior, hl, lam) if r[0] < week]
    a_, b_, h_, sigma = bt.fit_abh(prev_wf + cur_wf)
    r = em.fit(plays, teams, prior=prior, half_life=hl, lam=lam)

    def project(home, away, neutral):
        hh = 0.0 if neutral else h_
        ph = a_ + b_ * em.predictor(r, home, away) + hh / 2
        pa = a_ + b_ * em.predictor(r, away, home) - hh / 2
        return ph, pa, em.phi((ph - pa) / sigma)

    info = {"half_life": hl, "lam": lam, "shrink": em.SHRINK, "a": a_, "b": b_, "h": h_,
            "sigma": sigma, "calib_games": len(prev_wf) + len(cur_wf),
            "prev_prior": prev_prior is not None, "plays": len(plays), "adopted": False}
    return project, info


def model_version(info):
    return ("nfl-epa-v2 pure per-play half_life=%g lam=%g shrink=%.4f NOT-ADOPTED"
            % (info["half_life"], info["lam"], info["shrink"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    con = sqlite3.connect(DB, timeout=60)
    try:
        nfl_lock.assert_inputs_complete(con, args.season, args.week, pbp=True)
        project, info = build(con, args.season, args.week)
        version = model_version(info)
        print("model   %s" % version)
        print("calib   a %.3f b %.3f h %.3f sigma %.3f on %d earlier games"
              % (info["a"], info["b"], info["h"], info["sigma"], info["calib_games"]))
        sched = con.execute(
            "SELECT game_id, home_team, away_team, location, spread_line, total_line "
            "FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' "
            "ORDER BY game_id", (args.season, args.week)).fetchall()
        print("%-17s %-4s %-4s %6s %6s %6s %6s %5s %6s %6s" % (
            "game", "H", "A", "pH", "pA", "marg", "total", "p_H", "spr", "tot"))
        for gid, h, a, loc, sp, tl in sched:
            ph, pa, p = project(h, a, (loc or "").strip().lower() == "neutral")
            print("%-17s %-4s %-4s %6.1f %6.1f %6.1f %6.1f %5.2f %6s %6s"
                  % (gid, h, a, ph, pa, ph - pa, ph + pa, p, sp, tl))
        if not args.apply:
            print("dry run: nothing written")
            return 0
        nfl_lock.ensure_schema(con)
        as_of = dt.datetime.now(dt.timezone.utc).isoformat()
        run_id = "nfl-epa-lock-%d-w%02d-%s" % (args.season, args.week, as_of)
        nfl_lock.start_run(con, run_id, args.season, args.week, version,
                           dict(info, mode="lock", season=args.season, week=args.week),
                           model=bt.MODEL)
        try:
            out = nfl_lock.lock_week(con, run_id, args.season, args.week, project, as_of=as_of,
                                     skip_scored=True)
        except Exception as exc:
            nfl_lock.finish_run(con, run_id, "failed", error=str(exc))
            raise
        nfl_lock.finish_run(con, run_id, "ok")
        print("applied run=%s new_locks=%d refreshes=%d skipped=%s started=%s"
              % (run_id, out["new_locks"], out["refreshes"], out["skipped"] or "none",
                 out["started"] or "none"))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
