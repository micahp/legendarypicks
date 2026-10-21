#!/usr/bin/env python3
"""nfl_projection_preview.py -- write every live model's projections for a week WITHOUT locking them.

The live models are the three the lock job locks (lock_nfl_models.py): v1 points, v2 EPA and v1 + Elo. Each is built
and written on its own, so a model that cannot build (missing play-by-play for v2, say) fails alone, loudly, and the
others still get their previews; the job exits non-zero naming the failed models.

A preview is a row in game_projections with locked = 0. It is what the model says now, shown on the Model tab
labelled as not locked. The table requires locked_at on every row, so a preview stores the time it was written there;
locked = 0 is what makes it a preview, and the Model tab reports that time as "previewed", never as a lock time. It is never graded (the grader reads locked = 1 only), it does not block the lock (the lock's
checks read locked = 1 only), and the lock job writes the real lock 90 minutes before kickoff as before. Each run
replaces the previews of its week and model version, so a preview always reflects the latest inputs.

Dev DB only (a path ending in picks.db is refused). Dry run unless --apply.

  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python nfl_projection_preview.py --season 2026 --week 6 [--apply]
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


def plan_previews(con, season, week, project, now):
    """[(game_id, home, away, proj_home, proj_away, p_home_win, spread, total)] for REG games not yet kicked off."""
    games = con.execute(
        "SELECT game_id, home_team, away_team, location, gameday, gametime, spread_line, total_line, "
        "       home_score, away_score FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' "
        "ORDER BY game_id", (season, week)).fetchall()
    if not games:
        raise ValueError("no REG games for %d week %d" % (season, week))
    plan, skipped_started, skipped_scored = [], [], []
    for gid, home, away, loc, gameday, gametime, spread, total, hs, as_ in games:
        if not gameday:
            raise ValueError("%s has no gameday; its kickoff cannot be checked" % gid)
        if cs.kickoff_utc(gameday, gametime) <= now:
            skipped_started.append(gid)
            continue
        if hs is not None and as_ is not None:
            skipped_scored.append(gid)
            continue
        ph, pa, p = project(home, away, (loc or "").strip().lower() == "neutral")
        plan.append((gid, home, away, ph, pa, p, spread, total))
    return plan, skipped_started, skipped_scored


def write_previews(con, season, week, model_version, plan, run_id, now, model="nfl-ratings-v1"):
    """Replace this week's previews for this model version. Locked rows are never touched."""
    nfl_lock.ensure_schema(con)
    con.execute("DELETE FROM game_projections WHERE league = ? AND season = ? AND week = ? AND locked = 0 "
                "AND model_version = ?", (nfl_lock.LEAGUE, season, week, model_version))
    nfl_lock.start_run(con, run_id, season, week, model_version,
                       {"mode": "preview", "season": season, "week": week, "games": len(plan),
                        "written_at": now.isoformat()}, status="preview", model=model)
    for gid, home, away, ph, pa, p, spread, total in plan:
        con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, proj_home, "
            " proj_away, proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            " model_version, locked, locked_at, line_snapshot_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,NULL)",
            (run_id, nfl_lock.LEAGUE, gid, season, week, home, away, ph, pa, ph - pa, ph + pa, p, spread,
             total, "nflverse" if spread is not None else None, model_version, now.isoformat()))
    con.commit()
    return len(plan)


def build_v1(con, season, week):
    nfl_lock.assert_inputs_complete(con, season, week)
    fit, used, version = lw.build(con, season, week, lw.DEFAULT_SIGMA)
    return nfl_lock.v1_projector(fit, lw.DEFAULT_SIGMA), version, "nfl-ratings-v1"


def build_v2(con, season, week):
    nfl_lock.assert_inputs_complete(con, season, week, pbp=True)
    project, info = lepa.build(con, season, week)
    return project, lepa.model_version(info), lepa.bt.MODEL


def build_elo(con, season, week):
    project, _ = le.build(con, season, week)
    return project, le.version_for(season), le.MODEL


BUILDERS = {"v1": build_v1, "v2": build_v2, "elo": build_elo}


def preview_models(con, season, week, now, apply):
    """Preview every live model for the week. Returns the names of the models that failed."""
    failed = []
    for name, build in BUILDERS.items():
        try:
            project, version, model = build(con, season, week)
            plan, started, scored = plan_previews(con, season, week, project, now)
            print("%s %s: %d game(s) to preview; %d already kicked off; %d scored" %
                  (name, version, len(plan), len(started), len(scored)))
            for gid, home, away, ph, pa, p, spread, total in plan:
                print("  %-18s %s %.1f  %s %.1f  p(home) %.3f  market spread %s" %
                      (gid, home, ph, away, pa, p, "n/a" if spread is None else "%+.1f" % spread))
            if not apply:
                print("%s dry run: nothing written (pass --apply)" % name)
                continue
            run_id = "nfl-preview-%s-%d-w%02d-%s" % (name, season, week, now.isoformat())
            n = write_previews(con, season, week, version, plan, run_id, now, model=model)
            print("%s wrote %d preview row(s) under %s (locked = 0)" % (name, n, run_id))
        except Exception:
            traceback.print_exc()
            failed.append(name)
    return failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None,
                    help="default: the earliest REG week that still has an unscored game (the upcoming slate)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--now", default=None, help="ISO time (default: now); a game kicked off before it is not previewed")
    args = ap.parse_args(argv)
    if DB.endswith("picks.db"):
        raise SystemExit("refusing: %s is the prod database; previews are dev only" % DB)
    now = dt.datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else dt.datetime.now(dt.timezone.utc)

    con = sqlite3.connect(DB, timeout=60)
    try:
        if args.week is None:
            row = con.execute("SELECT MIN(week) FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
                              "AND (home_score IS NULL OR away_score IS NULL)", (args.season,)).fetchone()
            if row[0] is None:
                print("no unscored REG game in %d; nothing to preview" % args.season)
                return 0
            args.week = int(row[0])
        failed = preview_models(con, args.season, args.week, now, args.apply)
        if failed:
            print("FAILED models: %s" % ", ".join(failed), file=sys.stderr)
            return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
