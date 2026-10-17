#!/usr/bin/env python3
"""lock_nfl_elo.py -- lock NFL games with the v1 + Elo stack, no earlier than 90 minutes before kickoff.

The fourth model on the Model tab. Definition (frozen, the `elo_diff` feature that met the keep rule in
docs/RESULTS-nfl-elo-and-era-2026-10-13.md; 2011-2023 Brier 0.2197 against 0.2229 for the recalibrated v1):
- Elo: 538's NFL Elo rebuilt from our scores (nfl_elo_replica.py; K 20, home 65, margin multiplier, tie
  multiplier 1.525, 2/3 carryover toward 1505), current ratings after every scored game, the season carryover
  applied to a team that has not played yet this season, neutral from the schedule's location.
- Stack: margin = b0 + b1 x (frozen v1 projected margin) + b2 x (home Elo - away Elo + 65 if not neutral), fitted
  by OLS on every v1 walk-forward row of seasons 2010 to season-1 (nfl_backtest.backtest_season, frozen v1
  parameters), sigma = sd (ddof 1) of that fit's residuals, p_home = Phi(margin / sigma).
- Scores: the total is v1's projected total; home = (total + margin) / 2, away = (total - margin) / 2.
A new season is a new version string, so a season's record is one model.

Timing (Micah, 2026-10-13): a lock is made no earlier than 90 minutes before kickoff, when the inactive lists and
late news are known, and never after kickoff. nfl_lock.lock_week enforces both (min_lead, kickoff guard) and
lists a game outside the window as too_early. Run it every few minutes: with no --week it looks only for games
that are inside the window and not locked yet, and exits at once when there are none (no fitting, no writes).

Dev DB only: a path ending in picks.db (production) is refused. Dry run by default.

  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python lock_nfl_elo.py [--apply]
  cd backend && LP_DB_PATH=... venv/bin/python lock_nfl_elo.py --season 2026 --week 6   # show every game
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

import numpy as np

import check_nfl_schedule_scores as cs
import lock_nfl_week as lw
import nfl_backtest as nb
import nfl_elo_replica as er
import nfl_feature_backtest as fb
import nfl_lock

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
LEAD = nfl_lock.LOCK_LEAD
MODEL = "nfl-v1-elo-stack"
HFA = er.BASE["hfa"]
CARRY = er.BASE["carry"]


def version_for(season):
    return ("nfl-v1+elo stack season=%d train=2010-%d elo=538 K=20 hfa=65 carry=0.3333 lead=90min"
            % (season, season - 1))


def elo_gap(rating, season_of, season, home, away, neutral):
    """Home minus away rating, plus the home value unless neutral; the carryover is applied to a team
    that has not played in `season` yet."""
    def cur(team):
        if team not in rating:
            raise KeyError("no Elo rating for %s" % team)
        r = rating[team]
        if season_of[team] != season:
            r = r * (1.0 - CARRY) + er.MEAN * CARRY
        return r
    return cur(home) - cur(away) + (0.0 if neutral else HFA)


def fit_stack(con, season):
    """(beta, sigma, n): OLS of the home margin on [1, v1 margin, Elo gap] over seasons 2010 to season-1."""
    games = er.load_games(con)
    pre = er.run_elo(games, er.start_ratings(con))
    neutral = {g[0]: g[2] for g in games}
    X, y = [], []
    for s in range(2010, season):
        for r in nb.backtest_season(con, s, fb.FROZEN):
            eh, ea = pre[r["game_id"]]
            X.append([1.0, r["proj_margin"], eh - ea + (0.0 if neutral[r["game_id"]] else HFA)])
            y.append(r["actual_margin"])
    if len(y) < 1000:
        raise ValueError("only %d training games before %d" % (len(y), season))
    beta = fb.ols(X, y)
    res = np.array(y) - np.array(X) @ beta
    return beta, float(np.std(res, ddof=1)), len(y)


def projector(fit, beta, sigma, rating, season_of, season):
    def project(home, away, neutral):
        ph, pa = nr_expected(fit, home, away, neutral)
        gap = elo_gap(rating, season_of, season, home, away, neutral)
        m = float(beta[0] + beta[1] * (ph - pa) + beta[2] * gap)
        total = ph + pa
        return (total + m) / 2.0, (total - m) / 2.0, fb.phi(m / sigma)
    return project


def nr_expected(fit, home, away, neutral):
    import nfl_ratings as nr
    if home not in fit.o or away not in fit.o:
        raise KeyError("fit has no rating for %s or %s" % (home, away))
    return nr.expected_points(fit, home, away, neutral)


def due_games(con, now, lead=LEAD):
    """[(game_id, season, week)] of REG games not started, kickoff within `lead`, not locked for this
    model yet. Only gamedays within a day of `now` are looked at (kickoff is US Eastern)."""
    lo = (now - dt.timedelta(days=1)).date().isoformat()
    hi = (now + dt.timedelta(days=1)).date().isoformat()
    out = []
    for gid, season, week, gameday, gametime in con.execute(
            "SELECT game_id, season, week, gameday, gametime FROM nfl_schedule "
            "WHERE game_type = 'REG' AND gameday IS NOT NULL AND gameday >= ? AND gameday <= ? "
            "ORDER BY gameday, gametime, game_id", (lo, hi)):
        kickoff = cs.kickoff_utc(gameday, gametime)
        if not (now < kickoff <= now + lead):
            continue
        if con.execute("SELECT 1 FROM game_projections g JOIN model_runs r ON r.run_id = g.run_id "
                       "AND r.status = 'ok' WHERE g.league = 'nfl' AND g.game_id = ? AND g.locked = 1 "
                       "AND g.model_version = ?", (gid, version_for(int(season)))).fetchone():
            continue
        out.append((gid, int(season), int(week)))
    return out


def build(con, season, week):
    nfl_lock.assert_inputs_complete(con, season, week)
    beta, sigma, n = fit_stack(con, season)
    fit, used, v1_version = lw.build(con, season, week, lw.DEFAULT_SIGMA)
    games = er.load_games(con)
    _, rating, season_of = er.run_elo(games, er.start_ratings(con), return_state=True)
    params = {"season": season, "week": week, "beta": [float(b) for b in beta], "sigma": sigma,
              "train_games": n, "train_seasons": "2010-%d" % (season - 1), "v1": v1_version,
              "v1_fit_games": used, "lead_minutes": int(LEAD.total_seconds() // 60), "mode": "lock",
              "skip_scored": True, "elo": {"K": 20, "hfa": HFA, "carry": CARRY, "tie_mult": er.TIE_MULT}}
    return projector(fit, beta, sigma, rating, season_of, season), params


def lock(con, season, week, now, apply):
    project, params = build(con, season, week)
    rows = con.execute("SELECT game_id, home_team, away_team, location, gameday, gametime, home_score "
                       "FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' "
                       "ORDER BY game_id", (season, week)).fetchall()
    print("model   %s" % version_for(season))
    print("stack   n=%d beta=%s sigma=%.3f" % (params["train_games"], [round(b, 4) for b in params["beta"]], params["sigma"]))
    print("%-18s %-4s %-4s %6s %6s %6s  %s" % ("game", "H", "A", "ph", "pa", "p_H", "window"))
    for gid, h, a, loc, gd, gt, hs in rows:
        ph, pa, p = project(h, a, (loc or "").strip().lower() == "neutral")
        ko = cs.kickoff_utc(gd, gt)
        state = ("played" if hs is not None else "started" if ko <= now else
                 "in window" if ko - LEAD <= now else "locks at %s" % (ko - LEAD).strftime("%m-%d %H:%MZ"))
        print("%-18s %-4s %-4s %6.1f %6.1f %6.2f  %s" % (gid, h, a, ph, pa, p, state))
    if not apply:
        print("dry run: nothing written.")
        return None
    nfl_lock.ensure_schema(con)
    as_of = now.isoformat()
    run_id = "nfl-elo-lock-%d-w%02d-%s" % (season, week, as_of)
    nfl_lock.start_run(con, run_id, season, week, version_for(season), params, model=MODEL)
    try:
        out = nfl_lock.lock_week(con, run_id, season, week, project, as_of=as_of, skip_scored=True,
                                 now=now, min_lead=LEAD)
    except Exception as exc:
        nfl_lock.finish_run(con, run_id, "failed", error=str(exc))
        raise
    nfl_lock.finish_run(con, run_id, "ok")
    print("applied run=%s new_locks=%d refreshes=%d too_early=%d started=%s"
          % (run_id, out["new_locks"], out["refreshes"], len(out["too_early"]), out["started"] or "none"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int, help="show every game of this week (still only locks games in the window)")
    ap.add_argument("--now", help="ISO time to act as (tests and dry runs)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if os.path.basename(DB) == "picks.db":
        raise SystemExit("refusing the production database %s" % DB)
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    con = sqlite3.connect(DB, timeout=30)
    try:
        if a.week is not None:
            if a.season is None:
                ap.error("--week needs --season")
            lock(con, a.season, a.week, now, a.apply)
            return 0
        due = due_games(con, now)
        if not due:
            print("nothing due: no unlocked game kicks off within %d minutes" % (LEAD.total_seconds() // 60))
            return 0
        print("due: %s" % ", ".join(g for g, _, _ in due))
        for season, week in sorted({(s, w) for _, s, w in due}):
            lock(con, season, week, now, a.apply)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
