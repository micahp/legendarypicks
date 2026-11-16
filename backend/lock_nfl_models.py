#!/usr/bin/env python3
"""lock_nfl_models.py -- lock every live NFL model, each no earlier than 90 minutes before kickoff.

One job for the Model tab's three live models (the 10-09 legacy v1 version is retired and writes nothing):
  v1    lock_nfl_week.py   the points model in use
  v2    lock_nfl_epa.py    the EPA model on trial
  elo   lock_nfl_elo.py    v1 + Elo on trial
The rule is one for all (Micah, 2026-10-13): a game is locked when its kickoff is within nfl_lock.LOCK_LEAD (90
minutes) and not before, never after kickoff. Each model is independent: a model that cannot lock (missing
play-by-play for v2, an unscored earlier game) fails alone, loudly, and the others still lock; the job exits
non-zero naming every failed model so the ops alert fires.

With no --week it scans only for games inside the window that some model has not locked yet and exits at once when
there are none. A game is due for a model when that model has no locked row for it, so a model that failed is
retried on the next tick while the window is open.

Dev DB by default (a path ending in picks.db is refused unless --allow-prod is explicit).
Dry run unless --apply.

  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python lock_nfl_models.py [--apply] [--now ISO]
  cd backend && LP_DB_PATH=/abs/path/picks.db venv/bin/python lock_nfl_models.py --allow-prod --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import traceback

import check_nfl_schedule_scores as cs
import lock_nfl_elo as le
import lock_nfl_epa as lepa
import lock_nfl_week as lw
import nfl_lock

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
LEAD = nfl_lock.LOCK_LEAD


def v1_version():
    return lw.model_version(lw.DEFAULT_SIGMA, lw.FROZEN_HALF_LIFE, lw.FROZEN_CAP, lw.FROZEN_PRIOR_GAMES)


def epa_version():
    return lepa.model_version({"half_life": lepa.FROZEN_HALF_LIFE, "lam": lepa.FROZEN_LAM,
                               "shrink": lepa.em.SHRINK})


VERSIONS = {"v1": lambda season: v1_version(), "v2": lambda season: epa_version(), "elo": le.version_for}


def due_by_model(con, now, lead=LEAD):
    """{model: [(game_id, season, week)]}: REG games not started, kickoff within `lead`, not locked by that model."""
    lo = (now - dt.timedelta(days=1)).date().isoformat()
    hi = (now + dt.timedelta(days=1)).date().isoformat()
    out = {m: [] for m in VERSIONS}
    for gid, season, week, gameday, gametime in con.execute(
            "SELECT game_id, season, week, gameday, gametime FROM nfl_schedule "
            "WHERE game_type = 'REG' AND gameday IS NOT NULL AND gameday >= ? AND gameday <= ? "
            "ORDER BY gameday, gametime, game_id", (lo, hi)):
        kickoff = cs.kickoff_utc(gameday, gametime)
        if not (now < kickoff <= now + lead):
            continue
        for model, version_of in VERSIONS.items():
            locked = con.execute(
                "SELECT 1 FROM game_projections g JOIN model_runs r ON r.run_id = g.run_id "
                "AND r.status = 'ok' WHERE g.league = 'nfl' AND g.game_id = ? AND g.locked = 1 "
                "AND g.model_version = ?", (gid, version_of(int(season)))).fetchone()
            if not locked:
                out[model].append((gid, int(season), int(week)))
    return out


def lock_v1(con, season, week, now, apply):
    nfl_lock.assert_inputs_complete(con, season, week)
    fit, used, version = lw.build(con, season, week, lw.DEFAULT_SIGMA)
    if not apply:
        print("v1 dry run: %s" % version)
        return
    nfl_lock.ensure_schema(con)
    as_of = now.isoformat()
    run_id = "nfl-lock-%d-w%02d-%s" % (season, week, as_of)
    params = {"season": season, "week": week, "sigma": lw.DEFAULT_SIGMA, "half_life": lw.FROZEN_HALF_LIFE,
              "cap": lw.FROZEN_CAP, "prior_games": lw.FROZEN_PRIOR_GAMES, "prior_shrink": lw.SHRINK,
              "cap_points": lw.FROZEN_CAP_POINTS, "config": "A3-frozen-d30ea75", "fit_games": used,
              "mode": "lock", "skip_scored": True, "lead_minutes": int(LEAD.total_seconds() // 60)}
    nfl_lock.start_run(con, run_id, season, week, version, params)
    _finish(con, run_id, lambda: nfl_lock.lock_week(
        con, run_id, season, week, nfl_lock.v1_projector(fit, lw.DEFAULT_SIGMA), as_of=as_of,
        skip_scored=True, now=now, min_lead=LEAD), "v1")


def lock_v2(con, season, week, now, apply):
    nfl_lock.assert_inputs_complete(con, season, week, pbp=True)
    project, info = lepa.build(con, season, week)
    version = lepa.model_version(info)
    if not apply:
        print("v2 dry run: %s" % version)
        return
    nfl_lock.ensure_schema(con)
    as_of = now.isoformat()
    run_id = "nfl-epa-lock-%d-w%02d-%s" % (season, week, as_of)
    nfl_lock.start_run(con, run_id, season, week, version,
                       dict(info, mode="lock", season=season, week=week,
                            lead_minutes=int(LEAD.total_seconds() // 60)), model=lepa.bt.MODEL)
    _finish(con, run_id, lambda: nfl_lock.lock_week(
        con, run_id, season, week, project, as_of=as_of, skip_scored=True, now=now, min_lead=LEAD), "v2")


def lock_elo(con, season, week, now, apply):
    le.lock(con, season, week, now, apply)


def _finish(con, run_id, do, label):
    try:
        out = do()
    except Exception as exc:
        nfl_lock.finish_run(con, run_id, "failed", error=str(exc))
        raise
    nfl_lock.finish_run(con, run_id, "ok")
    print("%s applied run=%s new_locks=%d refreshes=%d too_early=%d started=%s" % (
        label, run_id, out["new_locks"], out["refreshes"], len(out["too_early"]), out["started"] or "none"))


RUNNERS = {"v1": lock_v1, "v2": lock_v2, "elo": lock_elo}


def validate_db_target(db, allow_prod=False):
    """Require a deliberate flag for prod, and reject a prod flag pointed at dev."""
    is_prod = os.path.basename(os.path.normpath(db)) == "picks.db"
    if is_prod and not allow_prod:
        raise SystemExit("refusing the production database %s without --allow-prod" % db)
    if allow_prod and not is_prod:
        raise SystemExit("--allow-prod requires LP_DB_PATH to end in picks.db (got %s)" % db)


def run(con, now, apply, due=None):
    """Lock every model that has a due game. Returns the list of models that failed."""
    due = due if due is not None else due_by_model(con, now)
    failed = []
    for model, items in due.items():
        for season, week in sorted({(s, w) for _, s, w in items}):
            print("%s: due %s (season %d week %d)" % (model, ", ".join(g for g, s, w in items if (s, w) == (season, week)),
                                                      season, week))
            try:
                RUNNERS[model](con, season, week, now, apply)
            except Exception:
                traceback.print_exc()
                failed.append(model)
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--now", help="ISO time to act as (tests and dry runs)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-prod", action="store_true",
                    help="allow picks.db; required by the production lock service")
    a = ap.parse_args(argv)
    validate_db_target(DB, allow_prod=a.allow_prod)
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    con = sqlite3.connect(DB, timeout=60)
    try:
        due = due_by_model(con, now)
        if not any(due.values()):
            print("nothing due: no unlocked game kicks off within %d minutes" % (LEAD.total_seconds() // 60))
            return 0
        failed = run(con, now, a.apply, due)
        if failed:
            print("FAILED models: %s" % ", ".join(failed), file=sys.stderr)
            return 1
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
