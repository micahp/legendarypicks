"""NFL model page: every locked game projection, per model version, beside the line it was locked
against and, once the game is final, its grade (SPEC A 2.2-2.3).

READ-ONLY. Reads game_projections (locked = 1 only: the projection grading uses), model_runs for
the model family, nfl_line_snapshots for the line, nfl_schedule for kickoff and the published
final, projection_grades for grades. Nothing is computed here except the labels.

A lock written before line snapshots existed (2026-10-11) has no snapshot; its line is the row's
own market_spread / market_total, flagged `line.source = "lock row"`. The 10-09 legacy locks
never recorded projected scores; proj_home / proj_away come back null and the page says so.
"""
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from _core import _db
import check_nfl_schedule_scores as cs

router = APIRouter()

ADOPTED = "nfl-v1 half_life=6 cap=14.0 prior_games=4 prior_shrink=0.3333 sigma=13.295"


def describe(model: Optional[str], version: str) -> Dict[str, Any]:
    """Family, short label and order for a model version string."""
    if (model or "").startswith("nfl-epa") or version.startswith("nfl-epa"):
        untuned = "untuned" in version
        return {"family": "v2", "label": "v2 EPA" + (" (untuned first lock)" if untuned else ""),
                "adopted": False, "order": 2 if untuned else 1}
    if version == ADOPTED:
        return {"family": "v1", "label": "v1 points", "adopted": True, "order": 0}
    return {"family": "v1", "label": "v1 points (10-09, before the freeze)", "adopted": False,
            "order": 3}


def _f(x):
    return None if x is None else float(x)


def locks_payload(con, season: int, week: Optional[int]) -> Dict[str, Any]:
    weeks = [r[0] for r in con.execute(
        "SELECT DISTINCT week FROM game_projections WHERE league = 'nfl' AND locked = 1 "
        "AND season = ? ORDER BY week", (season,))]
    if week is None:
        week = weeks[-1] if weeks else None
    out: Dict[str, Any] = {"season": season, "week": week, "weeks": weeks, "models": [],
                           "games": []}
    if week is None:
        return out
    rows = con.execute(
        "SELECT g.game_id, g.model_version, r.model, g.proj_home, g.proj_away, g.proj_margin, "
        "       g.proj_total, g.p_home_win, g.locked_at, g.market_spread, g.market_total, "
        "       s.snapshot_id, s.spread_line, s.total_line, s.home_moneyline, s.away_moneyline, "
        "       s.captured_at, pg.brier, pg.margin_err, pg.total_err, pg.ats_result "
        "FROM game_projections g "
        "LEFT JOIN model_runs r ON r.run_id = g.run_id "
        "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
        "LEFT JOIN projection_grades pg ON pg.league = g.league AND pg.game_id = g.game_id "
        "     AND pg.model_version = g.model_version "
        "WHERE g.league = 'nfl' AND g.locked = 1 AND g.season = ? AND g.week = ?",
        (season, week)).fetchall()
    models: Dict[str, Dict[str, Any]] = {}
    locks: Dict[str, Dict[str, Any]] = {}
    for (gid, mv, model, ph, pa, pm, pt, pw, locked_at, msp, mtot, snap, ssp, stot, hml, aml,
         cap, brier, merr, terr, ats) in rows:
        d = models.setdefault(mv, dict(describe(model, mv), version=mv, locks=0))
        d["locks"] += 1
        line = ({"spread": _f(ssp), "total": _f(stot), "home_moneyline": _f(hml),
                 "away_moneyline": _f(aml), "captured_at": cap, "source": "snapshot"}
                if snap is not None else
                {"spread": _f(msp), "total": _f(mtot), "home_moneyline": None,
                 "away_moneyline": None, "captured_at": locked_at, "source": "lock row"})
        grade = (None if merr is None else
                 {"brier": _f(brier), "margin_err": _f(merr), "total_err": _f(terr), "ats": ats})
        locks.setdefault(gid, {})[mv] = {
            "proj_home": _f(ph), "proj_away": _f(pa), "margin": _f(pm), "total": _f(pt),
            "p_home_win": _f(pw), "locked_at": locked_at, "line": line, "grade": grade}
    sched = con.execute(
        "SELECT game_id, home_team, away_team, location, gameday, gametime, home_score, "
        "       away_score, result FROM nfl_schedule WHERE season = ? AND week = ? "
        "AND game_type = 'REG' ORDER BY gameday, gametime, game_id", (season, week)).fetchall()
    for gid, home, away, loc, gameday, gametime, hs, as_, result in sched:
        kick = cs.kickoff_utc(gameday, gametime) if gameday else None
        out["games"].append({
            "game_id": gid, "home": home, "away": away,
            "neutral": (loc or "").strip().lower() == "neutral",
            "kickoff_utc": kick.strftime("%Y-%m-%dT%H:%M:%SZ") if kick else None,
            "final": ({"home": _f(hs), "away": _f(as_)}
                      if hs is not None and as_ is not None and result is not None else None),
            "locks": locks.get(gid, {}),
        })
    out["models"] = sorted(models.values(), key=lambda m: m["order"])
    return out


@router.get("/api/nfl/model/locks")
def nfl_model_locks(season: int = Query(2026, ge=2020, le=2100),
                    week: Optional[int] = Query(None, ge=1, le=22)):
    with closing(_db()) as con:
        payload = locks_payload(con, season, week)
    return JSONResponse(payload, headers={"X-LP-Data-Source": "db"})
