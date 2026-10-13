"""nfl_projections -- Spec B section 6 API: version 2 player projections, ESPN beside them, and the record.

GET /api/nfl/projections/player/{player_id}   the coming game: v2 scenarios, Marcel-lite, ESPN's, optional P(over)
GET /api/nfl/projections?week=&season=        the slate (base scenario, v2 beside ESPN)
GET /api/nfl/projections/record?season=       graded record per week and stat: v2 vs Marcel-lite vs ESPN

Rows come from player_projections written by nfl_player_projections_job.py and capture_espn_weekly_projections.py.
For each (game, player, stat, scenario, model_version) the latest run is shown. A projection is conditional on the
player playing; p_plays is how likely that is. Nothing here computes a projection on a request except the P(over),
which is simulated from the stored means with a fixed seed.
"""
import sqlite3
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from . import router

MARKET_STAT = {"receiving_yards": "rec_yds", "receptions": "rec", "receiving_tds": "rec_td", "targets": "tgt"}
PASS_MARKET_STAT = {"passing_yards": "pass_yds", "pass_attempts": "att", "pass_completions": "cmp",
                    "passing_touchdowns": "pass_td"}
V2, MARCEL, ESPN = "v2", "marcel-lite", "espn-weekly"


def _db_pkg():
    from routers.players import _db as _pkg
    return _pkg()


def _latest(con, season, week, player_id=None):
    sql = ("SELECT pp.game_id, pp.player_id, pp.team, pp.stat, pp.mean, pp.median, pp.p10, pp.p90, pp.scenario, "
           "pp.model_version, pp.p_plays, pp.as_of, pp.run_id FROM player_projections pp JOIN ("
           "SELECT game_id g, player_id p, stat s, scenario sc, model_version mv, MAX(as_of) m FROM player_projections "
           "WHERE league='nfl' AND season=? AND week=?" + (" AND player_id=?" if player_id else "") +
           " GROUP BY 1,2,3,4,5) x ON pp.game_id=x.g AND pp.player_id=x.p AND pp.stat=x.s AND pp.scenario=x.sc "
           "AND pp.model_version=x.mv AND pp.as_of=x.m WHERE pp.league='nfl' AND pp.season=? AND pp.week=?")
    args = [season, week] + ([player_id] if player_id else []) + [season, week]
    return con.execute(sql, args).fetchall()


def _line(row):
    return {"mean": row[4], "median": row[5], "p10": row[6], "p90": row[7]}


@router.get("/api/nfl/projections/player/{player_id}")
def nfl_player_projection(player_id: int, week: Optional[int] = Query(None), season: Optional[int] = Query(None),
                          market: Optional[str] = Query(None), line: Optional[float] = Query(None)):
    with closing(_db_pkg()) as con:
        player = con.execute("SELECT id, name, team FROM players WHERE id=? AND league='nfl'", (player_id,)).fetchone()
        if not player:
            raise HTTPException(404, "Player not found")
        if week is None or season is None:
            nxt = con.execute(
                "SELECT pp.season, pp.week FROM player_projections pp JOIN nfl_schedule s ON s.game_id=pp.game_id "
                "WHERE pp.player_id=? AND pp.model_version='v2' AND s.home_score IS NULL "
                "ORDER BY pp.season, pp.week LIMIT 1", (player_id,)).fetchone()
            if nxt is None:
                return {"player_id": player_id, "name": player[1], "projection": None,
                        "reason": "no version 2 projection for an unplayed game"}
            season, week = nxt
        rows = _latest(con, season, week, player_id)
        if not rows:
            return {"player_id": player_id, "name": player[1], "season": season, "week": week, "projection": None,
                    "reason": "no version 2 projection for this week (fewer than 3 earlier games, listed Out or "
                              "Doubtful, not a running back, wide receiver or tight end, or not the team's "
                              "expected passer)"}
        game_id = rows[0][0]
        out = {"player_id": player_id, "name": player[1], "team": rows[0][2], "season": season, "week": week,
               "game_id": game_id, "model": "v2", "scenarios": {}, "marcel": {}, "espn": {}, "p_plays": None,
               "as_of": None, "conditional_on_playing": True}
        for r in rows:
            if r[9] == V2:
                out["scenarios"].setdefault(r[8], {})[r[3]] = _line(r)
                out["p_plays"], out["as_of"] = r[10], r[11]
            elif r[9] == MARCEL:
                out["marcel"][r[3]] = r[4]
            elif r[9] == ESPN:
                out["espn"][r[3]] = r[4]
        if market and line is not None:
            stat = MARKET_STAT.get(market)
            base = out["scenarios"].get("base", {})
            if stat and {"tgt", "rec", "rec_yds", "rec_td"} <= set(base):
                import nfl_player_projection_v2 as eng
                t = base["tgt"]["mean"]
                if t > 0:
                    draws = eng.simulate(t, base["rec"]["mean"] / t,
                                         base["rec_yds"]["mean"] / base["rec"]["mean"] if base["rec"]["mean"] > 0 else 0.0,
                                         base["rec_td"]["mean"] / t, n=4000, seed=7)
                    out["prob_over"] = {"market": market, "line": line, "p_over": round(
                        eng.summarize(draws, {"rec": 0, "rec_yds": 1, "rec_td": 2, "tgt": 3}[stat], line)["p_over"], 4),
                        "given": "plays"}
            pstat = PASS_MARKET_STAT.get(market)
            if pstat and set(PASS_MARKET_STAT.values()) <= set(base):
                import nfl_player_projection_v2 as eng
                a = base["att"]["mean"]
                c = base["cmp"]["mean"]
                if a > 0:
                    draws = eng.simulate_qb(a, c / a, base["pass_yds"]["mean"] / c if c > 0 else 0.0,
                                            base["pass_td"]["mean"] / a, n=4000, seed=7)
                    out["prob_over"] = {"market": market, "line": line, "p_over": round(
                        eng.summarize(draws, {"cmp": 0, "pass_yds": 1, "pass_td": 2, "att": 3}[pstat], line)["p_over"], 4),
                        "given": "plays"}
        return out


@router.get("/api/nfl/projections")
def nfl_projection_slate(week: Optional[int] = Query(None), season: Optional[int] = Query(None)):
    with closing(_db_pkg()) as con:
        if season is None:
            season = con.execute("SELECT MAX(season) FROM player_projections").fetchone()[0]
        weeks = [w for (w,) in con.execute(
            "SELECT DISTINCT week FROM player_projections WHERE league='nfl' AND season=? AND model_version='v2' "
            "ORDER BY week", (season,))]
        if week is None:
            week = weeks[-1] if weeks else None
        if week is None:
            return {"season": season, "week": None, "weeks": [], "conditional_on_playing": True, "players": []}
        names = {pid: (n, pos) for pid, n, pos in con.execute(
            "SELECT id, name, position FROM players WHERE league='nfl'")}
        by = {}
        for r in _latest(con, season, week):
            if r[8] != "base":
                continue
            e = by.setdefault((r[0], r[1]), {"game_id": r[0], "player_id": r[1], "team": r[2],
                                             "name": names.get(r[1], ("", ""))[0], "position": names.get(r[1], ("", ""))[1],
                                             "p_plays": None, "v2": {}, "marcel": {}, "espn": {}})
            if r[9] == V2:
                e["v2"][r[3]] = _line(r)
                e["p_plays"] = r[10]
            elif r[9] == MARCEL:
                e["marcel"][r[3]] = r[4]
            elif r[9] == ESPN:
                e["espn"][r[3]] = r[4]
        players = sorted((e for e in by.values() if e["v2"]),
                         key=lambda e: -(e["v2"].get("rec_yds") or {"mean": 0})["mean"])
    return {"season": season, "week": week, "weeks": weeks, "conditional_on_playing": True, "players": players}


@router.get("/api/nfl/projections/record")
def nfl_projection_record(season: Optional[int] = Query(None)):
    """Graded error per week and stat; versions are compared on the same player-games only."""
    import grade_nfl_player_projections as grader
    with closing(_db_pkg()) as con:
        if season is None:
            season = con.execute("SELECT MAX(season) FROM player_projection_grades").fetchone()[0]
        weeks = [w for (w,) in con.execute(
            "SELECT DISTINCT week FROM player_projection_grades WHERE season=? ORDER BY week", (season,))]
        out = []
        for w in weeks:
            present = sorted({v for (v,) in con.execute(
                "SELECT DISTINCT model_version FROM player_projection_grades WHERE season=? AND week=? AND scenario='base'",
                (season, w))})
            counts = {v: dict(zip(("graded", "dnp"), con.execute(
                "SELECT COUNT(DISTINCT CASE WHEN played=1 THEN game_id||'|'||player_id END), "
                "COUNT(DISTINCT CASE WHEN played=0 THEN game_id||'|'||player_id END) FROM player_projection_grades "
                "WHERE season=? AND week=? "
                "AND model_version=? AND scenario='base'", (season, w, v)).fetchone())) for v in present}
            out.append({"week": w, "counts": counts,
                        "stats": grader.summary(con, season, w, versions=present)})
        return {"season": season, "weeks": out,
                "note": "Errors are mean absolute error and bias (projection minus actual) over the player-games every "
                        "listed version projected and the player played. Players who did not play are not scored."}
