"""nfl_lock.py -- write each game's projection once, then never overwrite it (SPEC A, 4.3).

Table nfl_projections. A game has at most one row with locked = 1, enforced by a partial
unique index. That row is the first projection written for the game and is the only one
grading uses. Later weekly runs append rows with locked = 0 and a newer as_of, for audit.

Market line at lock time: `market_home_margin` is the nflverse spread_line, read as the home
team's expected margin (positive = home favored). Checked against 2025 results: correlation
with the actual home margin is +0.50, and the home team wins 65% of games with a positive line.

Refusal: a game that already has a result cannot be locked for the first time. A projection
written after the result is not a projection, so the lock fails loudly.
"""
from __future__ import annotations

import datetime as dt

import nfl_ratings as nr

TABLE = "nfl_projections"


def ensure_schema(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS nfl_projections ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " season INTEGER NOT NULL,"
        " week INTEGER NOT NULL,"
        " game_id TEXT NOT NULL,"
        " home_team TEXT NOT NULL,"
        " away_team TEXT NOT NULL,"
        " neutral INTEGER NOT NULL,"
        " projected_margin REAL NOT NULL,"
        " projected_total REAL NOT NULL,"
        " p_home_win REAL NOT NULL,"
        " sigma REAL NOT NULL,"
        " market_home_margin REAL,"
        " market_total REAL,"
        " locked INTEGER NOT NULL,"
        " as_of TEXT NOT NULL,"
        " model_version TEXT NOT NULL,"
        " created_at TEXT DEFAULT (datetime('now')))")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_nfl_projection_locked "
                "ON nfl_projections(game_id) WHERE locked = 1")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_projections_week "
                "ON nfl_projections(season, week)")
    con.commit()


def locked_projection(con, game_id):
    """The one projection grading uses, or None if the game was never locked."""
    row = con.execute(
        "SELECT projected_margin, projected_total, p_home_win, sigma, market_home_margin, "
        "       market_total, as_of, model_version FROM nfl_projections "
        "WHERE game_id = ? AND locked = 1", (game_id,)).fetchone()
    if row is None:
        return None
    keys = ("projected_margin", "projected_total", "p_home_win", "sigma",
            "market_home_margin", "market_total", "as_of", "model_version")
    return dict(zip(keys, row))


def lock_week(con, season, week, fit, sigma, model_version, as_of=None):
    """Project every REG game in (season, week). Returns counts of new locks and refreshes."""
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    as_of = as_of or dt.datetime.now(dt.timezone.utc).isoformat()
    games = con.execute(
        "SELECT game_id, home_team, away_team, location, home_score, away_score, "
        "       spread_line, total_line FROM nfl_schedule "
        "WHERE season = ? AND week = ? AND game_type = 'REG' ORDER BY game_id",
        (season, week)).fetchall()
    if not games:
        raise ValueError("no REG games for %d week %d" % (season, week))
    # Pass 1: validate every game before writing any row, so a refusal leaves nothing behind.
    plan = []
    for gid, home, away, loc, hs, as_, spread, total in games:
        neutral = (loc or "").strip().lower() == "neutral"
        if home not in fit.o or away not in fit.o:
            raise KeyError("fit has no rating for %s or %s" % (home, away))
        already = con.execute("SELECT 1 FROM nfl_projections WHERE game_id = ? AND locked = 1",
                              (gid,)).fetchone()
        if already is None and hs is not None and as_ is not None:
            raise ValueError("refusing to lock %s after its result (%s-%s)" % (gid, hs, as_))
        ph, pa = nr.expected_points(fit, home, away, neutral)
        plan.append(((season, week, gid, home, away, int(neutral), ph - pa, ph + pa,
                      nr.win_probability(ph - pa, sigma), sigma, spread, total),
                     already is None))
    # Pass 2: write.
    new_locks = refreshes = 0
    for row, first in plan:
        con.execute(
            "INSERT INTO nfl_projections (season, week, game_id, home_team, away_team, neutral, "
            " projected_margin, projected_total, p_home_win, sigma, market_home_margin, "
            " market_total, locked, as_of, model_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row + (1 if first else 0, as_of, model_version))
        if first:
            new_locks += 1
        else:
            refreshes += 1
    con.commit()
    return {"new_locks": new_locks, "refreshes": refreshes}
