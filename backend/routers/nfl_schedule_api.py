"""NFL schedule API — exposes nfl_schedule data (team weeks + bye week).

BE-4: Minimum viable — per-team, per-season played weeks and bye week.
Reads nfl_schedule (season, week, game_type, home_team, away_team,
home_score, away_score, game_id, espn_id).  Only regular-season weeks
(1–18, i.e. week < 19) are considered.
"""

import sqlite3
from contextlib import closing
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query

from _core import _db

router = APIRouter()

_CONTRACT = "nfl-schedule-v1"
_REG_SEASON_LAST_WEEK = 18
_POSTSEASON_FIRST_WEEK = 19


def _team_weeks_and_bye(
    connection: sqlite3.Connection, season: int, team: str
) -> dict:
    """Return the weeks a team plays and its bye week for a regular season."""
    played: List[int] = [
        row[0]
        for row in connection.execute(
            """SELECT DISTINCT week FROM nfl_schedule
               WHERE season=? AND week < ? AND (home_team=? OR away_team=?)
               ORDER BY week""",
            (season, _POSTSEASON_FIRST_WEEK, team, team),
        ).fetchall()
    ]
    bye_week: Optional[int] = None
    for w in range(1, _REG_SEASON_LAST_WEEK + 1):
        if w not in played:
            bye_week = w
            break
    return {"team": team, "weeks_played": played, "bye_week": bye_week}


def _schedule_response(connection, season):
    """Build the full season response: all teams with weeks + bye."""
    connection.row_factory = sqlite3.Row
    teams: Set[str] = set()
    for row in connection.execute(
        """SELECT DISTINCT home_team FROM nfl_schedule
           WHERE season=? AND week < ?""",
        (season, _POSTSEASON_FIRST_WEEK),
    ).fetchall():
        teams.add(row["home_team"])
    for row in connection.execute(
        """SELECT DISTINCT away_team FROM nfl_schedule
           WHERE season=? AND week < ?""",
        (season, _POSTSEASON_FIRST_WEEK),
    ).fetchall():
        teams.add(row["away_team"])

    if not teams:
        raise HTTPException(
            status_code=404, detail=f"No schedule data for season {season}"
        )
    teams_data = [
        _team_weeks_and_bye(connection, season, t) for t in sorted(teams)
    ]
    return {"contract": _CONTRACT, "season": season, "teams": teams_data}


@router.get("/api/nfl/schedule/{season}")
def nfl_schedule_season_path(season: int):
    """Path-param: GET /api/nfl/schedule/2025."""
    with closing(_db()) as connection:
        return _schedule_response(connection, season)


@router.get("/api/nfl/schedule")
def nfl_schedule_season_query(season: int = Query(...)):
    """Query-param: GET /api/nfl/schedule?season=2025."""
    with closing(_db()) as connection:
        return _schedule_response(connection, season)


@router.get("/api/nfl/schedule/{season}/{team}")
def nfl_schedule_team(season: int, team: str):
    """Return one team's played weeks and bye week for a regular season."""
    team_upper = team.upper()
    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        data = _team_weeks_and_bye(connection, season, team_upper)
        if not data["weeks_played"]:
            raise HTTPException(
                status_code=404,
                detail=f"No schedule data for {team_upper} in season {season}",
            )
        return {"contract": _CONTRACT, "season": season, **data}
