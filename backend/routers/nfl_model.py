"""NFL model page: every locked game projection, per model version, beside the line it was locked
against and, once the game is final, its grade (SPEC A 2.2-2.3).

READ-ONLY. Reads game_projections (locked = 1 only: the projection grading uses), model_runs for
the model family, nfl_line_snapshots for the line, nfl_schedule for kickoff and the published
final, projection_grades for outcomes. Winner/total picks and grades are deterministic from
the frozen inputs and the settled scores stored by the grader; no extra grade columns are needed.

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
import nfl_metrics as mt

router = APIRouter()

ADOPTED = "nfl-v1 half_life=6 cap=14.0 prior_games=4 prior_shrink=0.3333 sigma=13.295"
ELO_STACK = "nfl-v1+elo stack"   # prefix of every version string lock_nfl_elo.py writes


def describe(model: Optional[str], version: str) -> Dict[str, Any]:
    """Family, short label and order for a model version string."""
    if (model or "").startswith("nfl-epa") or version.startswith("nfl-epa"):
        untuned = "untuned" in version
        return {"family": "v2", "label": "v2 EPA" + (" (untuned first lock)" if untuned else ""),
                "adopted": False, "order": 2 if untuned else 1}
    if version.startswith(ELO_STACK):
        return {"family": "v1+elo", "label": "v1 + Elo", "adopted": False, "order": 1.5}
    if version == ADOPTED:
        return {"family": "v1", "label": "v1 points", "adopted": True, "order": 0}
    return {"family": "v1", "label": "v1 points (10-09, before the freeze)", "adopted": False,
            "order": 3}


def _f(x):
    return None if x is None else float(x)


def su_result(p_home_win, home_score, away_score):
    """Legacy name for the winner grade; the shared rule lives in nfl_metrics."""
    return mt.grade_winner(p_home_win, home_score, away_score)


def record_payload(con, season: int) -> List[Dict[str, Any]]:
    """Season-to-date record per model version, over GRADED locked games only.

    Counts, not rates: n is small until midseason and a percentage over 25 games reads as more
    than it is. `awaiting` is locks with no grade yet (not final). Winner and total results
    are derived from immutable lock inputs and the score recorded in projection_grades;
    spread uses the grader's stored ATS result."""
    locked: Dict[str, int] = {}
    models: Dict[str, Any] = {}
    for mv, model, n in con.execute(
            "SELECT g.model_version, MAX(r.model), COUNT(*) FROM game_projections g "
            "JOIN model_runs r ON r.run_id = g.run_id AND r.status = 'ok' "
            "WHERE g.league = 'nfl' AND g.locked = 1 AND g.season = ? GROUP BY g.model_version",
            (season,)):
        locked[mv] = n
        models[mv] = model
    out: Dict[str, Dict[str, Any]] = {}
    for mv, pw, pt, total_line, ah, aa, brier, merr, ats in con.execute(
            "SELECT g.model_version, g.p_home_win, g.proj_total, "
            "       COALESCE(s.total_line, g.market_total), pg.actual_home, pg.actual_away, "
            "       pg.brier, pg.margin_err, pg.ats_result "
            "FROM game_projections g JOIN projection_grades pg ON pg.league = g.league "
            "AND pg.game_id = g.game_id AND pg.model_version = g.model_version "
            "JOIN model_runs r ON r.run_id = g.run_id AND r.status = 'ok' "
            "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
            "WHERE g.league = 'nfl' AND g.locked = 1 AND g.season = ?", (season,)):
        d = out.setdefault(mv, {"graded": 0, "su": {"win": 0, "loss": 0, "tie": 0, "no_pick": 0},
                                "ats": {"win": 0, "loss": 0, "push": 0, "no_pick": 0, "no_line": 0},
                                "total": {"win": 0, "loss": 0, "push": 0, "no_pick": 0, "no_line": 0},
                                "brier_sum": 0.0, "brier_n": 0, "abs_err_sum": 0.0})
        d["graded"] += 1
        d["su"][mt.grade_winner(pw, ah, aa)] += 1
        d["ats"][ats] += 1
        d["total"][mt.grade_total(pt, total_line, ah, aa)] += 1
        if brier is not None:
            d["brier_sum"] += brier
            d["brier_n"] += 1
        d["abs_err_sum"] += abs(merr)
    rows = []
    for mv, n_locked in locked.items():
        d = out.get(mv)
        graded = d["graded"] if d else 0
        rows.append(dict(describe(models[mv], mv), version=mv, locked=n_locked, graded=graded,
                         awaiting=n_locked - graded,
                         su=d["su"] if d else None, ats=d["ats"] if d else None,
                         total=d["total"] if d else None,
                         mean_brier=(d["brier_sum"] / d["brier_n"]) if d and d["brier_n"] else None,
                         brier_n=d["brier_n"] if d else 0,
                         mean_abs_margin_err=(d["abs_err_sum"] / graded) if d else None))
    return sorted(rows, key=lambda r: r["order"])


def record_before(results: List[tuple], team: str, week: int) -> str:
    """A team's regular-season record from completed games in earlier weeks: W-L, or W-L-T when there is a tie."""
    w = l = t = 0
    for game_week, home, away, hs, as_ in results:
        if game_week >= week or team not in (home, away):
            continue
        mine, theirs = (hs, as_) if team == home else (as_, hs)
        if mine > theirs:
            w += 1
        elif mine < theirs:
            l += 1
        else:
            t += 1
    return "%d-%d" % (w, l) if not t else "%d-%d-%d" % (w, l, t)


def locks_payload(con, season: int, week: Optional[int]) -> Dict[str, Any]:
    weeks = [r[0] for r in con.execute(
        "SELECT DISTINCT g.week FROM game_projections g "
        "JOIN model_runs r ON r.run_id = g.run_id "
        "WHERE g.league = 'nfl' AND g.locked IN (0, 1) AND g.season = ? "
        "AND ((g.locked = 1 AND r.status = 'ok') OR "
        "     (g.locked = 0 AND r.status IN ('ok', 'preview'))) ORDER BY g.week",
        (season,))]
    if week is None:
        week = weeks[-1] if weeks else None
    out: Dict[str, Any] = {"season": season, "week": week, "weeks": weeks, "models": [],
                           "games": [], "record": record_payload(con, season)}
    if week is None:
        return out
    rows = con.execute(
        "SELECT g.game_id, g.model_version, r.model, g.proj_home, g.proj_away, g.proj_margin, "
        "       g.proj_total, g.p_home_win, g.locked_at, g.market_spread, g.market_total, "
        "       s.snapshot_id, s.spread_line, s.total_line, s.home_moneyline, s.away_moneyline, "
        "       s.captured_at, pg.brier, pg.margin_err, pg.total_err, pg.ats_result, "
        "       pg.actual_home, pg.actual_away, g.locked "
        "FROM game_projections g "
        "JOIN model_runs r ON r.run_id = g.run_id "
        "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
        "LEFT JOIN projection_grades pg ON pg.league = g.league AND pg.game_id = g.game_id "
        "     AND pg.model_version = g.model_version "
        "WHERE g.league = 'nfl' AND g.locked IN (0, 1) AND g.season = ? AND g.week = ? "
        "AND ((g.locked = 1 AND r.status = 'ok') OR "
        "     (g.locked = 0 AND r.status IN ('ok', 'preview')))",
        (season, week)).fetchall()
    models: Dict[str, Dict[str, Any]] = {}
    locks: Dict[str, Dict[str, Any]] = {}
    for (gid, mv, model, ph, pa, pm, pt, pw, locked_at, msp, mtot, snap, ssp, stot, hml, aml,
         cap, brier, merr, terr, ats, ah, aa, is_locked) in rows:
        if not is_locked and mv in locks.get(gid, {}) and not locks[gid][mv]["preview"]:
            continue  # a real lock for this game and model always wins over its preview
        d = models.setdefault(mv, dict(describe(model, mv), version=mv, locks=0, previews=0))
        d["locks" if is_locked else "previews"] += 1
        # Match the lock grader's COALESCE semantics even for a partially populated snapshot.
        line = ({"spread": _f(ssp if ssp is not None else msp),
                 "total": _f(stot if stot is not None else mtot),
                 "home_moneyline": _f(hml),
                 "away_moneyline": _f(aml), "captured_at": cap, "source": "snapshot"}
                if snap is not None else
                {"spread": _f(msp), "total": _f(mtot), "home_moneyline": None,
                 "away_moneyline": None, "captured_at": locked_at, "source": "lock row"})
        # Winner and total grades are deterministic from the immutable lock and the final
        # scores stored by projection_grades; old graded rows need no backfill or schema change.
        grade = (None if merr is None else
                 {"brier": _f(brier), "margin_err": _f(merr), "total_err": _f(terr), "ats": ats,
                  "su": mt.grade_winner(pw, ah, aa),
                  "total": mt.grade_total(pt, line["total"], ah, aa)})
        # The pick is a single backend rule (nfl_metrics.pick_side) on the frozen spread the lock
        # was written against, so the page can never disagree with the grader.
        locks.setdefault(gid, {})[mv] = {
            "preview": not is_locked,
            "proj_home": _f(ph), "proj_away": _f(pa), "margin": _f(pm), "total": _f(pt),
            "p_home_win": _f(pw), "locked_at": locked_at if is_locked else None,
            "previewed_at": None if is_locked else locked_at,
            "pick": mt.pick_side(_f(pm), line["spread"]),  # legacy ATS alias
            "picks": {"winner": mt.pick_winner(_f(pw)),
                      "spread": mt.pick_side(_f(pm), line["spread"]),
                      "total": mt.pick_total(_f(pt), line["total"])},
            "line": line, "grade": grade}
    results = con.execute(
        "SELECT week, home_team, away_team, home_score, away_score FROM nfl_schedule WHERE season = ? "
        "AND game_type = 'REG' AND home_score IS NOT NULL AND away_score IS NOT NULL", (season,)).fetchall()
    sched = con.execute(
        "SELECT game_id, home_team, away_team, location, gameday, gametime, home_score, "
        "       away_score, result FROM nfl_schedule WHERE season = ? AND week = ? "
        "AND game_type = 'REG' ORDER BY gameday, gametime, game_id", (season, week)).fetchall()
    for gid, home, away, loc, gameday, gametime, hs, as_, result in sched:
        kick = cs.kickoff_utc(gameday, gametime) if gameday else None
        out["games"].append({
            "game_id": gid, "week": week, "home": home, "away": away,
            "home_record": record_before(results, home, week), "away_record": record_before(results, away, week),
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
