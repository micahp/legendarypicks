"""NFL model page: every locked game projection, per model version, beside the line it was locked
against, its one Model Pick and, once the game is final, that pick's grade (SPEC A 2.2-2.3).

READ-ONLY. Reads game_projections (locked = 1 only: the projection grading uses), model_runs for
the model family, nfl_line_snapshots for the line, nfl_schedule for kickoff, teams and the published
final, projection_grades for the recorded final, and prop_games for preseason scores (team
strength). The Model Pick follows docs/MODEL-PICK-RULES.md, "NFL order". It is computed from the
frozen lock inputs (the snapshot line or the lock row's own line, and the locked projection) plus
team strength from games dated before the kickoff date. Nothing is stored, so no backfill is
needed. Grading reads the same pick and the final score projection_grades recorded, so a later
line or projection cannot change a locked pick or its grade.

A lock written before line snapshots existed (2026-10-11) has no snapshot; its line is the row's
own market_spread / market_total, flagged `line.source = "lock row"`. The 10-09 legacy locks
never recorded projected scores; proj_home / proj_away come back null and the page says so.
"""
from __future__ import annotations

import re
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from _core import _db
import check_nfl_schedule_scores as cs
import nfl_metrics as mt

router = APIRouter()

ADOPTED = "nfl-v1 half_life=6 cap=14.0 prior_games=4 prior_shrink=0.3333 sigma=13.295"
ELO_STACK = "nfl-v1+elo stack"   # prefix of every version string lock_nfl_elo.py writes
TEAM_COUNT = 32
# Team codes are the schedule's own (nfl_schedule and nfl_teams use LAR and WSH in this
# database). prop_games rows may carry a full team name instead, which nfl_teams maps. The ESPN to
# nflverse spelling in capture_espn_weekly_projections.TEAM_FIX (LAR to LA, WSH to WAS) is accepted
# only when its target is one of the season's team codes.
PROP_ALIASES = {"LA": "LAR", "WAS": "WSH"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


# ---------------------------------------------------------------- team strength

def _date(value: Optional[str], where: str) -> str:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("%s: not a YYYY-MM-DD date: %r" % (where, value))
    return value


def _per_game_margins(rows: List[Tuple[str, str, str, float, float]], before: str) -> Dict[str, float]:
    """team -> (points for - points against) / games, over the games dated before `before`.

    The only look-ahead control: a game dated on or after the kickoff date is skipped, and a
    game's date must be a real YYYY-MM-DD (checked when the rows are loaded)."""
    total: Dict[str, float] = {}
    games: Dict[str, int] = {}
    for date, home, away, fh, fa in rows:
        if date >= before:
            continue
        for team, diff in ((home, fh - fa), (away, fa - fh)):
            total[team] = total.get(team, 0.0) + diff
            games[team] = games.get(team, 0) + 1
    return {team: total[team] / games[team] for team in games}


class StrengthTiers:
    """Team strength tiers for one season. Loads the season's games on first use, then computes
    the tiers once per kickoff date, so a request with many games reads the database once.

    Games feeding the tiers: preseason prop_games (league nfl) dated from July 1 up to the first REG
    gameday, with both final scores; and nfl_schedule REG games with both scores. Each kickoff date
    sees only games dated before it. A team with no games yet has no tier (None).
    """

    def __init__(self, con, season: int):
        self.con = con
        self.season = season
        self._teams: Optional[Dict[str, str]] = None
        self._rows: Optional[List[Tuple[str, str, str, float, float]]] = None
        self._by_date: Dict[str, Dict[str, str]] = {}

    def _load(self) -> None:
        con, season = self.con, self.season
        teams = {code: name for code, name in con.execute(
            "SELECT team, team_name FROM nfl_teams WHERE season = ?", (season,))}
        if len(teams) != TEAM_COUNT:
            raise ValueError("nfl_teams holds %d teams for %d, expected %d"
                             % (len(teams), season, TEAM_COUNT))
        by_name = {name: code for code, name in teams.items()}

        def code_of(raw, where):
            if raw in teams:
                return raw
            if raw in by_name:
                return by_name[raw]
            if PROP_ALIASES.get(raw) in teams:
                return PROP_ALIASES[raw]
            raise ValueError("%s: cannot map team %r to a team code" % (where, raw))

        first = con.execute("SELECT MIN(gameday) FROM nfl_schedule WHERE season = ? "
                            "AND game_type = 'REG'", (season,)).fetchone()[0]
        if first is None:
            raise ValueError("no REG games scheduled for %d, so the preseason window has no end"
                             % season)
        rows = []
        for pid, date, home, away, fh, fa in con.execute(
                "SELECT id, date, home, away, final_home, final_away FROM prop_games "
                "WHERE league = 'nfl' AND date >= ? AND date < ? "
                "AND final_home IS NOT NULL AND final_away IS NOT NULL ORDER BY id",
                ("%d-07-01" % season, _date(first, "first REG gameday"))):
            where = "prop_games %s" % pid
            if not home or not away:
                raise ValueError("%s: a preseason game with a missing team" % where)
            rows.append((_date(date, where), code_of(home, where), code_of(away, where),
                         float(fh), float(fa)))
        for gid, gameday, home, away, hs, as_ in con.execute(
                "SELECT game_id, gameday, home_team, away_team, home_score, away_score "
                "FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
                "AND home_score IS NOT NULL AND away_score IS NOT NULL ORDER BY game_id",
                (season,)):
            where = "nfl_schedule %s" % gid
            rows.append((_date(gameday, where), code_of(home, where), code_of(away, where),
                         float(hs), float(as_)))
        self._teams, self._rows = teams, rows

    def for_kickoff(self, gameday: Optional[str], home: str, away: str) -> Tuple[Optional[str], Optional[str]]:
        """(home tier, away tier) for a game kicking off on `gameday`."""
        if self._rows is None:
            self._load()
        assert self._teams is not None and self._rows is not None
        where = "%s @ %s on %s" % (away, home, gameday)
        if home not in self._teams or away not in self._teams:
            raise ValueError("%s: a team is not in nfl_teams for %d" % (where, self.season))
        day = _date(gameday, where)
        if day not in self._by_date:
            self._by_date[day] = mt.strength_tiers(_per_game_margins(self._rows, day))
        tiers = self._by_date[day]
        return tiers.get(home), tiers.get(away)


def model_pick_for(tiers: StrengthTiers, gameday: Optional[str], home: str, away: str,
                   spread: Optional[float], total: Optional[float], proj_margin: float,
                   proj_total: float) -> Dict[str, Any]:
    """The Model Pick for one lock, with its display label. Every consumer calls this."""
    home_tier, away_tier = tiers.for_kickoff(gameday, home, away)
    pick = mt.model_pick(spread, proj_margin, total, proj_total, home_tier, away_tier)
    pick["label"] = mt.pick_label(pick, home, away)
    return pick


# ---------------------------------------------------------------- record and locks

def record_payload(con, season: int, tiers: Optional[StrengthTiers] = None) -> List[Dict[str, Any]]:
    """Season-to-date record per model version, over GRADED locked games only.

    `pick` tallies the Model Pick: win, loss, push, and no_pick / no_line counted apart (they are
    never wins or losses). `su` (straight-up) and the mean Brier are model metrics, labelled as
    such and reported beside the pick. Counts, not rates: n is small until midseason.
    `awaiting` is locks with no grade yet (not final). Previews never enter this record."""
    tiers = tiers or StrengthTiers(con, season)
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
    for (mv, pw, pm, pt, spread, total, ah, aa, brier, merr, gameday, home, away) in con.execute(
            "SELECT g.model_version, g.p_home_win, g.proj_margin, g.proj_total, "
            "       COALESCE(s.spread_line, g.market_spread), COALESCE(s.total_line, g.market_total), "
            "       pg.actual_home, pg.actual_away, pg.brier, pg.margin_err, n.gameday, g.home, g.away "
            "FROM game_projections g JOIN projection_grades pg ON pg.league = g.league "
            "AND pg.game_id = g.game_id AND pg.model_version = g.model_version "
            "JOIN model_runs r ON r.run_id = g.run_id AND r.status = 'ok' "
            "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
            "LEFT JOIN nfl_schedule n ON n.game_id = g.game_id "
            "WHERE g.league = 'nfl' AND g.locked = 1 AND g.season = ?", (season,)):
        pick = model_pick_for(tiers, gameday, home, away, _f(spread), _f(total), _f(pm), _f(pt))
        result = mt.grade_pick(pick, ah, aa)
        if result is None:
            raise ValueError("%s %s: a graded lock has no final score" % (home, mv))
        d = out.setdefault(mv, {"graded": 0,
                                "pick": {"win": 0, "loss": 0, "push": 0, "no_pick": 0, "no_line": 0},
                                "su": {"win": 0, "loss": 0, "tie": 0, "no_pick": 0},
                                "brier_sum": 0.0, "brier_n": 0, "abs_err_sum": 0.0})
        d["graded"] += 1
        d["pick"][result] += 1
        d["su"][mt.grade_winner(pw, ah, aa)] += 1
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
                         pick=d["pick"] if d else None, su=d["su"] if d else None,
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
    tiers = StrengthTiers(con, season)
    out: Dict[str, Any] = {"season": season, "week": week, "weeks": weeks, "models": [],
                           "games": [], "record": record_payload(con, season, tiers)}
    if week is None:
        return out
    rows = con.execute(
        "SELECT g.game_id, g.model_version, r.model, g.proj_home, g.proj_away, g.proj_margin, "
        "       g.proj_total, g.p_home_win, g.locked_at, g.market_spread, g.market_total, "
        "       s.snapshot_id, s.spread_line, s.total_line, s.home_moneyline, s.away_moneyline, "
        "       s.captured_at, pg.brier, pg.margin_err, pg.total_err, "
        "       pg.actual_home, pg.actual_away, g.locked, g.home, g.away, n.gameday "
        "FROM game_projections g "
        "JOIN model_runs r ON r.run_id = g.run_id "
        "LEFT JOIN nfl_line_snapshots s ON s.snapshot_id = g.line_snapshot_id "
        "LEFT JOIN nfl_schedule n ON n.game_id = g.game_id "
        "LEFT JOIN projection_grades pg ON pg.league = g.league AND pg.game_id = g.game_id "
        "     AND pg.model_version = g.model_version "
        "WHERE g.league = 'nfl' AND g.locked IN (0, 1) AND g.season = ? AND g.week = ? "
        "AND ((g.locked = 1 AND r.status = 'ok') OR "
        "     (g.locked = 0 AND r.status IN ('ok', 'preview')))",
        (season, week)).fetchall()
    models: Dict[str, Dict[str, Any]] = {}
    locks: Dict[str, Dict[str, Any]] = {}
    for (gid, mv, model, ph, pa, pm, pt, pw, locked_at, msp, mtot, snap, ssp, stot, hml, aml,
         cap, brier, merr, terr, ah, aa, is_locked, home, away, gameday) in rows:
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
        pick = model_pick_for(tiers, gameday, home, away, line["spread"], line["total"],
                              _f(pm), _f(pt))
        grade = (None if merr is None else
                 {"brier": _f(brier), "margin_err": _f(merr), "total_err": _f(terr),
                  "su": mt.grade_winner(pw, ah, aa),
                  "pick": mt.grade_pick(pick, ah, aa)})
        locks.setdefault(gid, {})[mv] = {
            "preview": not is_locked,
            "proj_home": _f(ph), "proj_away": _f(pa), "margin": _f(pm), "total": _f(pt),
            "p_home_win": _f(pw), "locked_at": locked_at if is_locked else None,
            "previewed_at": None if is_locked else locked_at,
            "pick": pick,
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
