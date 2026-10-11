"""nfl_lock.py -- write each game's projection once, then never overwrite it (SPEC A, 4.3 and 7).

The one lock path for every NFL model version. A model supplies a projector,
``project(home, away, neutral) -> (proj_home, proj_away, p_home_win)``; this module decides what
may be written and writes it. ``v1_projector`` adapts the points model; the EPA model builds its
own in ``lock_nfl_epa.py``.

Writes to `game_projections` (created by migrate_nfl_model_tables.py). Every row belongs to a run
in `model_runs`. A game has at most one row with locked = 1 per model_version, enforced by the
partial unique index. That row is the first projection a version wrote for the game and is the
only one grading uses for that version. Later runs append rows with locked = 0 for audit.

Market line: every written row points at a row in `nfl_line_snapshots`, copied from nflverse's
schedule at lock time with the capture time and the schedule's own `ingested_at`. Grading reads
the snapshot, never the live schedule, whose lines keep changing after the lock. `market_spread` is
nflverse's spread_line, read as the home team's expected margin (positive = home favored). Checked
on 2025 results: correlation with the actual home margin is +0.50, and the home team wins 65% of
games with a positive line.

Refusals, all decided before anything is written:
- kickoff: no row of any kind is written for a game whose kickoff (nflverse gameday + gametime,
  US Eastern, via check_nfl_schedule_scores.kickoff_utc) is at or before `now`. Such a game is
  listed in `started`. A game with no gameday raises: an unknown kickoff cannot be guarded.
- result: a game with a result and no lock is refused (or listed in `skipped` with skip_scored).
- a run that is not in model_runs, an empty week, or a team the projector cannot rate.
"""
from __future__ import annotations

import datetime as dt
import json

import check_nfl_schedule_scores as cs
import migrate_nfl_model_tables as mg
import nfl_ratings as nr

LEAGUE = "nfl"
MARKET_SOURCE = "nflverse"


def ensure_schema(con):
    mg.migrate(con)


def start_run(con, run_id, season, week, model_version, params, status="running",
              model="nfl-ratings-v1"):
    """Record a run before writing its projections. Returns the run_id."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
        " params_json, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, LEAGUE, season, week, model, model_version, now,
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
        "       market_total, market_source, locked_at, line_snapshot_id FROM game_projections "
        "WHERE league = ? AND game_id = ? AND locked = 1 AND model_version = ?",
        (LEAGUE, game_id, model_version)).fetchone()
    if row is None:
        return None
    keys = ("run_id", "proj_home", "proj_away", "proj_margin", "proj_total", "p_home_win",
            "market_spread", "market_total", "market_source", "locked_at", "line_snapshot_id")
    return dict(zip(keys, row))


def v1_projector(fit, sigma):
    """The points model (SPEC A section 4) as a projector."""
    if sigma <= 0:
        raise ValueError("sigma must be > 0")

    def project(home, away, neutral):
        if home not in fit.o or away not in fit.o:
            raise KeyError("fit has no rating for %s or %s" % (home, away))
        ph, pa = nr.expected_points(fit, home, away, neutral)
        return ph, pa, nr.win_probability(ph - pa, sigma)
    return project


def _snapshot(con, gid, captured_at, ingested_at, spread, total, home_ml, away_ml):
    cur = con.execute(
        "INSERT INTO nfl_line_snapshots (league, game_id, source, captured_at, source_ingested_at, "
        " spread_line, total_line, home_moneyline, away_moneyline) VALUES (?,?,?,?,?,?,?,?,?)",
        (LEAGUE, gid, MARKET_SOURCE, captured_at, ingested_at, spread, total, home_ml, away_ml))
    return cur.lastrowid


def lock_week(con, run_id, season, week, project, as_of=None, skip_scored=False, now=None):
    """Project every REG game in (season, week) under `run_id` with `project`.

    Returns {"new_locks", "refreshes", "skipped", "started"}: `started` lists games past kickoff
    (never written), `skipped` lists scored games without a lock (skip_scored=True only).
    """
    run = con.execute("SELECT model_version FROM model_runs WHERE run_id = ?",
                      (run_id,)).fetchone()
    if run is None:
        raise ValueError("run %s is not in model_runs; call start_run first" % run_id)
    model_version = run[0]
    now = now or dt.datetime.now(dt.timezone.utc)
    as_of = as_of or now.isoformat()
    games = con.execute(
        "SELECT game_id, home_team, away_team, location, home_score, away_score, spread_line, "
        "       total_line, home_moneyline, away_moneyline, gameday, gametime, ingested_at "
        "FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' ORDER BY game_id",
        (season, week)).fetchall()
    if not games:
        raise ValueError("no REG games for %d week %d" % (season, week))

    # Pass 1: validate every game before writing any row, so a refusal leaves nothing behind.
    plan, skipped, started = [], [], []
    for (gid, home, away, loc, hs, as_, spread, total, hml, aml, gameday, gametime,
         ingested_at) in games:
        if not gameday:
            raise ValueError("%s has no gameday; its kickoff cannot be guarded" % gid)
        if cs.kickoff_utc(gameday, gametime) <= now:
            started.append(gid)
            continue
        neutral = (loc or "").strip().lower() == "neutral"
        already = con.execute(
            "SELECT 1 FROM game_projections WHERE league = ? AND game_id = ? AND locked = 1 "
            "AND model_version = ?", (LEAGUE, gid, model_version)).fetchone()
        if already is None and hs is not None and as_ is not None:
            if not skip_scored:
                raise ValueError("refusing to lock %s after its result (%s-%s)" % (gid, hs, as_))
            skipped.append(gid)
            continue
        ph, pa, p = project(home, away, neutral)
        plan.append((gid, home, away, ph, pa, p, spread, total, hml, aml, ingested_at,
                     already is None))

    # Pass 2: write. Each row first copies the market line it was made against.
    new_locks = refreshes = 0
    for gid, home, away, ph, pa, p, spread, total, hml, aml, ingested_at, first in plan:
        snap = _snapshot(con, gid, as_of, ingested_at, spread, total, hml, aml)
        con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            " proj_home, proj_away, proj_margin, proj_total, p_home_win, market_spread, "
            " market_total, market_source, model_version, locked, locked_at, line_snapshot_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, LEAGUE, gid, season, week, home, away, ph, pa, ph - pa, ph + pa, p, spread,
             total, MARKET_SOURCE, model_version, 1 if first else 0, as_of, snap))
        if first:
            new_locks += 1
        else:
            refreshes += 1
    con.commit()
    return {"new_locks": new_locks, "refreshes": refreshes, "skipped": skipped,
            "started": started}
