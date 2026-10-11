"""nfl_lock.py -- write each game's projection once, then never overwrite it (SPEC A, 4.3 and 7).

Writes to `game_projections` (created by migrate_nfl_model_tables.py). Every row belongs to a run
in `model_runs`. A game has at most one row with locked = 1 per model_version, enforced by the partial unique
index. That row is the first projection a version wrote for the game and is the only one grading
uses for that version. Later
runs append rows with locked = 0 for audit.

Market line at lock time: `market_spread` is the nflverse spread_line, read as the home team's
expected margin (positive = home favored). Checked on 2025 results: correlation with the actual
home margin is +0.50, and the home team wins 65% of games with a positive line.

Refusal: a game that already has a result cannot be locked for the first time. A projection
written after the result is not a projection, so the lock fails loudly and writes nothing.
"""
from __future__ import annotations

import datetime as dt
import json

import migrate_nfl_model_tables as mg
import nfl_ratings as nr

LEAGUE = "nfl"
MARKET_SOURCE = "nflverse"


def ensure_schema(con):
    mg.migrate(con)


def start_run(con, run_id, season, week, model_version, params, status="running"):
    """Record a run before writing its projections. Returns the run_id."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
        " params_json, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, LEAGUE, season, week, "nfl-ratings-v1", model_version, now,
         json.dumps(params, sort_keys=True), status))
    con.commit()
    return run_id


def finish_run(con, run_id, status, error=None):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute("UPDATE model_runs SET status = ?, finished_at = ?, error = ? WHERE run_id = ?",
                (status, now, error, run_id))
    con.commit()


def locked_projection(con, game_id, model_version):
    """The one projection grading uses for this version, or None if it never locked the game."""
    row = con.execute(
        "SELECT run_id, proj_home, proj_away, proj_margin, proj_total, p_home_win, market_spread, "
        "       market_total, market_source, locked_at FROM game_projections "
        "WHERE league = ? AND game_id = ? AND locked = 1 AND model_version = ?",
        (LEAGUE, game_id, model_version)).fetchone()
    if row is None:
        return None
    keys = ("run_id", "proj_home", "proj_away", "proj_margin", "proj_total", "p_home_win",
            "market_spread", "market_total", "market_source", "locked_at")
    return dict(zip(keys, row))


def lock_week(con, run_id, season, week, fit, sigma, as_of=None, skip_scored=False,
              skip_ids=()):
    """Project every REG game in (season, week) under `run_id`.

    Default: refuse the whole week if any game without a lock already has a result.
    skip_scored=True: lock only the unplayed games; played games without a lock are listed in
    `skipped` and never written. skip_ids: games listed there (already kicked off) are skipped too,
    scored or not. Returns {"new_locks", "refreshes", "skipped"}.
    """
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    run = con.execute("SELECT 1 FROM model_runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("run %s is not in model_runs; call start_run first" % run_id)
    model_version = con.execute("SELECT model_version FROM model_runs WHERE run_id = ?",
                                (run_id,)).fetchone()[0]
    as_of = as_of or dt.datetime.now(dt.timezone.utc).isoformat()
    games = con.execute(
        "SELECT game_id, home_team, away_team, location, home_score, away_score, spread_line, "
        "       total_line FROM nfl_schedule "
        "WHERE season = ? AND week = ? AND game_type = 'REG' ORDER BY game_id",
        (season, week)).fetchall()
    if not games:
        raise ValueError("no REG games for %d week %d" % (season, week))

    # Pass 1: validate every game before writing any row, so a refusal leaves nothing behind.
    plan, skipped = [], []
    for gid, home, away, loc, hs, as_, spread, total in games:
        neutral = (loc or "").strip().lower() == "neutral"
        if home not in fit.o or away not in fit.o:
            raise KeyError("fit has no rating for %s or %s" % (home, away))
        if gid in skip_ids:
            skipped.append(gid)
            continue
        already = con.execute(
            "SELECT 1 FROM game_projections WHERE league = ? AND game_id = ? AND locked = 1 "
            "AND model_version = ?", (LEAGUE, gid, model_version)).fetchone()
        if already is None and hs is not None and as_ is not None:
            if not skip_scored:
                raise ValueError("refusing to lock %s after its result (%s-%s)" % (gid, hs, as_))
            skipped.append(gid)
            continue
        ph, pa = nr.expected_points(fit, home, away, neutral)
        plan.append(((run_id, LEAGUE, gid, season, week, home, away, ph, pa, ph - pa, ph + pa,
                      nr.win_probability(ph - pa, sigma), spread, total, MARKET_SOURCE, model_version),
                     already is None))

    # Pass 2: write.
    new_locks = refreshes = 0
    for row, first in plan:
        con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            " proj_home, proj_away, proj_margin, proj_total, p_home_win, market_spread, "
            " market_total, market_source, model_version, locked, locked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row + (1 if first else 0, as_of))
        if first:
            new_locks += 1
        else:
            refreshes += 1
    con.commit()
    return {"new_locks": new_locks, "refreshes": refreshes, "skipped": skipped}
