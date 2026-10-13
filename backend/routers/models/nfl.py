"""Database-backed NFL team ratings and playoff odds. Locked projections and grades are served by
routers/nfl_model.py (/api/nfl/model/locks), so they are not duplicated here."""
from __future__ import annotations

from contextlib import closing
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from _core import _db

router = APIRouter()
DATA_SOURCE = "Legendary Picks NFL model tables"
SEED_COLUMNS = ["p_seed_%d" % seed for seed in range(1, 8)]


def _source(response):
    response.headers["X-LP-Data-Source"] = DATA_SOURCE


def _season(con, requested, table="playoff_odds"):
    if requested is not None:
        return int(requested)
    if table in ("playoff_odds", "team_ratings"):
        row = con.execute(
            "SELECT MAX(r.season) FROM model_runs r WHERE r.league='nfl' AND r.status='ok' "
            "AND EXISTS (SELECT 1 FROM %s data WHERE data.run_id=r.run_id "
            "GROUP BY data.run_id HAVING COUNT(DISTINCT data.team)=32)" % table).fetchone()
    else:
        raise ValueError("unsupported season source")
    if row is None or row[0] is None:
        raise HTTPException(status_code=404, detail="No completed NFL model run is available")
    return int(row[0])


def _latest_complete_run(con, table, season, week=None, model_version=None, team_count=None):
    if table not in ("playoff_odds", "team_ratings"):
        raise ValueError("unsupported model table")
    where = ["r.league='nfl'", "r.season=?", "r.status='ok'"]
    args = [season]
    if week is not None:
        where.append("r.week=?")
        args.append(week)
    if model_version is not None:
        where.append("r.model_version=?")
        args.append(model_version)
    having = ""
    if team_count is not None:
        having = " HAVING COUNT(DISTINCT data.team)=?"
        args.append(team_count)
    row = con.execute(
        "SELECT r.run_id,r.season,r.week,r.model_version,r.started_at," +
        "MAX(data.as_of),COUNT(DISTINCT data.team) FROM model_runs r "
        "JOIN %s data ON data.run_id=r.run_id WHERE %s "
        "GROUP BY r.run_id%s ORDER BY r.started_at DESC LIMIT 1" %
        (table, " AND ".join(where), having), args).fetchone()
    if row is None:
        raise HTTPException(status_code=404,
                            detail="No complete NFL %s run is available for season %d" %
                            (table, season))
    return {"run_id": row[0], "season": row[1], "week": row[2],
            "model_version": row[3], "started_at": row[4], "as_of": row[5],
            "teams": row[6]}


def _team_identity(con, season):
    rows = con.execute(
        "SELECT team,team_name,conference,division FROM nfl_teams WHERE season=? ORDER BY team",
        (season,)).fetchall()
    identity = {row[0]: {"team_name": row[1], "conference": row[2], "division": row[3]}
                for row in rows}
    if len(rows) != 32 or len(identity) != 32 or any(not row[2] or not row[3] for row in rows):
        raise HTTPException(status_code=503,
                            detail="Published NFL team mapping is incomplete for season %d" % season)
    return identity


def _require_team_rows(rows, identity, season):
    codes = {row[0] for row in rows}
    if len(rows) != 32 or codes != set(identity):
        raise HTTPException(status_code=503,
                            detail="NFL model run does not contain the 32 published teams for %d" % season)


@router.get("/api/nfl/playoff-odds")
def playoff_odds(response: Response, season: Optional[int] = Query(None),
                 week: Optional[int] = Query(None), model_version: Optional[str] = Query(None)):
    _source(response)
    with closing(_db()) as con:
        season = _season(con, season, "playoff_odds")
        run = _latest_complete_run(con, "playoff_odds", season, week, model_version, 32)
        identity = _team_identity(con, season)
        columns = ["team", "p_playoffs", "p_division", "p_bye"] + SEED_COLUMNS + [
            "wins_mean", "wins_p10", "wins_p90", "d_playoffs"]
        rows = con.execute(
            "SELECT %s FROM playoff_odds WHERE run_id=? ORDER BY team" % ",".join(columns),
            (run["run_id"],)).fetchall()
        _require_team_rows(rows, identity, season)
        teams = []
        for row in rows:
            entry = dict(zip(columns, row))
            entry.update(identity.get(entry["team"], {}))
            teams.append(entry)
        return {"contract": "nfl-playoff-odds-v1", **run, "teams": teams}


@router.get("/api/nfl/ratings")
def ratings(response: Response, season: Optional[int] = Query(None),
            week: Optional[int] = Query(None), model_version: Optional[str] = Query(None)):
    _source(response)
    with closing(_db()) as con:
        season = _season(con, season, "team_ratings")
        run = _latest_complete_run(con, "team_ratings", season, week, model_version, 32)
        identity = _team_identity(con, season)
        rows = con.execute(
            'SELECT team,"off","def",overall,games FROM team_ratings WHERE run_id=? ORDER BY team',
            (run["run_id"],)).fetchall()
        _require_team_rows(rows, identity, season)
        teams = []
        for team, offense, defense, overall, games in rows:
            teams.append({"team": team, **identity[team], "off": offense, "def": defense,
                          "overall": overall, "games": games})
        return {"contract": "nfl-ratings-v1", **run, "teams": teams}
