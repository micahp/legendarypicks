"""Shadow forecasts written beside the served tennis forecast, inside the same pre-match lock window.

Research, not served. Nothing here changes a served projection, the served lock table, or an API default. Shadow rows go
to `tennis_shadow_locks` under their own version labels, so grading can tell served, m2-2000 and m1-elo apart.

- tennis-shadow-m2-2000-v1: 50/50 logit blend of global and surface Elo, ratings from 2000-01-01. This is the M2 that
  research/tennis/rolling/2026-10-18/rolling_origin.py evaluated (A1, ATP incumbent).
- tennis-shadow-m1-elo-v1: global Elo over the same ratings. This is the reference A1 kept on WTA.

Inputs are the served pipeline's: the Sackmann identities from the match identity (the function the served projection
uses) and the event surface from SURFACE_BY_EVENT. An event with no mapped surface falls back to global Elo for the blend,
as the served projection does. Each row records `surfaceSource`, so grading can split those matches out.

Rows are frozen when written. The lock window is the caller's, and a row that already exists is never replaced.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from typing import Any

import tennis_point_model as tpm
from tennis_daily_projections import SURFACE_BY_EVENT, _logistic, _logit, _sackmann_player_ids

HISTORY_START = 20000101  # rolling_origin.WINNER_HISTORY_START
ELO_START = 1500.0  # rolling_origin.ELO_START
ELO_K = 32.0  # rolling_origin.ELO_K
SCALE = math.log(10.0) / 400.0  # rolling_origin.blend_p
M2_VERSION = "tennis-shadow-m2-2000-v1"
M1_VERSION = "tennis-shadow-m1-elo-v1"
VERSIONS = (M2_VERSION, M1_VERSION)
STATUS_LOCKED = "locked"
STATUS_MISSING = "missing"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tennis_shadow_locks("
    "league TEXT NOT NULL,game_id TEXT NOT NULL,model_version TEXT NOT NULL,game_date TEXT NOT NULL,"
    "start_time TEXT NOT NULL,locked_at TEXT NOT NULL,status TEXT NOT NULL,projection TEXT NOT NULL,"
    "PRIMARY KEY(league,game_id,model_version))"
)


def ensure_table(con) -> None:
    con.execute(SCHEMA)


def elo_p(rating_a: float, rating_b: float) -> float:
    """Same formula as rolling_origin.elo_p: probability that A wins."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def blend_p(global_r: dict, surface_r: dict, a: str, b: str, surface: str) -> float:
    """Same formula as rolling_origin.blend_p: 50/50 logit average of global and surface Elo."""
    p_global = _logistic((global_r[a] - global_r[b]) * SCALE)
    p_surface = _logistic((surface_r[(a, surface)] - surface_r[(b, surface)]) * SCALE)
    return _logistic(0.5 * (_logit(p_global) + _logit(p_surface)))


def ratings_before(con, tour: str, cutoff: int) -> tuple[dict, dict]:
    """Global and surface Elo from matches dated HISTORY_START up to the day before `cutoff`.

    The update rule is rolling_origin.winner_records: every row of an event-start date updates after that date, global
    and surface Elo update only on rows that have a surface, and no row informs another on the same date.
    """
    rows = con.execute(
        f"SELECT tourney_date, surface, CAST(winner_id AS TEXT), CAST(loser_id AS TEXT) FROM tennis_{tour}_matches "
        f"WHERE {tpm.TOUR_FILTER[tour]} AND tourney_date BETWEEN ? AND ? "
        "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
        (HISTORY_START, cutoff - 1),
    ).fetchall()
    global_r: dict = defaultdict(lambda: ELO_START)
    surface_r: dict = defaultdict(lambda: ELO_START)
    for _, group_iter in groupby(rows, key=itemgetter(0)):
        group = [row for row in group_iter if row[1] is not None]
        global_updates = [(w, lo, ELO_K * (1.0 - elo_p(global_r[w], global_r[lo]))) for _, _, w, lo in group]
        surface_updates = [(w, lo, surf, ELO_K * (1.0 - elo_p(surface_r[(w, surf)], surface_r[(lo, surf)])))
                           for _, surf, w, lo in group]
        for w, lo, delta in global_updates:
            global_r[w] += delta
            global_r[lo] -= delta
        for w, lo, surf, delta in surface_updates:
            surface_r[(w, surf)] += delta
            surface_r[(lo, surf)] -= delta
    return global_r, surface_r


def forecasts(global_r: dict, surface_r: dict, home: str, away: str, surface: str | None) -> dict[str, float]:
    """Home-side probabilities for both versions. The blend falls back to global Elo without a surface."""
    m1 = elo_p(global_r[home], global_r[away])
    if surface:
        m2 = blend_p(global_r, surface_r, home, away, surface)
    else:
        m2 = _logistic((global_r[home] - global_r[away]) * SCALE)
    return {M2_VERSION: m2, M1_VERSION: m1}


def _projection(p_home: float, home: dict[str, Any], away: dict[str, Any], version: str,
                surface: str | None, game_date: str) -> dict[str, Any]:
    favourite = max(p_home, 1.0 - p_home)
    return {
        "probability": favourite,
        "projectedWinner": home["name"] if p_home >= 0.5 else away["name"],
        "homeProbability": p_home,
        "homeSackmannId": home["sackmannId"],
        "awaySackmannId": away["sackmannId"],
        "surface": surface,
        "surfaceSource": "event_map" if surface else "unmapped",
        "cutoffDate": game_date,
        "historyStart": HISTORY_START,
        "k": ELO_K,
        "eloStart": ELO_START,
        "modelVersion": version,
    }


def write_shadow_locks(con, league: str, match: dict[str, Any], starts_at_utc, locked_at, replays: dict) -> int:
    """Write the shadow rows for one match that is inside its lock window. Returns the number of rows written.

    `replays` caches the ratings for (league, cutoff) within one request. An existing row is never replaced, so a re-run
    writes nothing new. A match whose identity is not resolved gets one `missing` row per version instead.
    """
    game_id = str(match["gameId"])
    existing = {row[0] for row in con.execute(
        "SELECT model_version FROM tennis_shadow_locks WHERE league=? AND game_id=?", (league, game_id))}
    pending = [version for version in VERSIONS if version not in existing]
    if not pending:
        return 0
    game_date = starts_at_utc.date().isoformat()
    locked = locked_at.isoformat()
    ids = _sackmann_player_ids(match)
    home = {"name": match.get("home"), "sackmannId": ids["home"]}
    away = {"name": match.get("away"), "sackmannId": ids["away"]}
    if not ids["home"] or not ids["away"]:
        for version in pending:
            con.execute(
                "INSERT OR IGNORE INTO tennis_shadow_locks(league,game_id,model_version,game_date,start_time,locked_at,status,projection) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (league, game_id, version, game_date, match["startTime"], locked, STATUS_MISSING,
                 json.dumps({"reason": "identity_unresolved", "modelVersion": version})),
            )
        return len(pending)
    surface = SURFACE_BY_EVENT.get(str(match.get("tournamentId") or ""))
    cutoff = int(game_date.replace("-", ""))
    if (league, cutoff) not in replays:
        replays[(league, cutoff)] = ratings_before(con, league, cutoff)
    global_r, surface_r = replays[(league, cutoff)]
    probabilities = forecasts(global_r, surface_r, ids["home"], ids["away"], surface)
    written = 0
    for version in pending:
        projection = _projection(probabilities[version], home, away, version, surface, game_date)
        cursor = con.execute(
            "INSERT OR IGNORE INTO tennis_shadow_locks(league,game_id,model_version,game_date,start_time,locked_at,status,projection) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (league, game_id, version, game_date, match["startTime"], locked, STATUS_LOCKED, json.dumps(projection)),
        )
        written += cursor.rowcount
    return written
