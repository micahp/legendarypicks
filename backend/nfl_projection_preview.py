#!/usr/bin/env python3
"""nfl_projection_preview.py -- write the v1 points model's projections for a week WITHOUT locking them.

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

import check_nfl_schedule_scores as cs
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


def write_previews(con, season, week, model_version, plan, run_id, now):
    """Replace this week's previews for this model version. Locked rows are never touched."""
    nfl_lock.ensure_schema(con)
    con.execute("DELETE FROM game_projections WHERE league = ? AND season = ? AND week = ? AND locked = 0 "
                "AND model_version = ?", (nfl_lock.LEAGUE, season, week, model_version))
    nfl_lock.start_run(con, run_id, season, week, model_version,
                       {"mode": "preview", "season": season, "week": week, "games": len(plan),
                        "written_at": now.isoformat()}, status="preview")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--now", default=None, help="ISO time (default: now); a game kicked off before it is not previewed")
    args = ap.parse_args(argv)
    if DB.endswith("picks.db"):
        raise SystemExit("refusing: %s is the prod database; previews are dev only" % DB)
    now = dt.datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else dt.datetime.now(dt.timezone.utc)

    con = sqlite3.connect(DB, timeout=60)
    try:
        nfl_lock.assert_inputs_complete(con, args.season, args.week)
        fit, used, version = lw.build(con, args.season, args.week, lw.DEFAULT_SIGMA)
        project = nfl_lock.v1_projector(fit, lw.DEFAULT_SIGMA)
        plan, started, scored = plan_previews(con, args.season, args.week, project, now)
        print("%s: %d game(s) to preview; %d already kicked off; %d scored" %
              (version, len(plan), len(started), len(scored)))
        for gid, home, away, ph, pa, p, spread, total in plan:
            print("  %-18s %s %.1f  %s %.1f  p(home) %.3f  market spread %s" %
                  (gid, home, ph, away, pa, p, "n/a" if spread is None else "%+.1f" % spread))
        if not args.apply:
            print("dry run: nothing written (pass --apply)")
            return 0
        run_id = "nfl-preview-%d-w%02d-%s" % (args.season, args.week, now.isoformat())
        n = write_previews(con, args.season, args.week, version, plan, run_id, now)
        print("wrote %d preview row(s) under %s (locked = 0)" % (n, run_id))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
