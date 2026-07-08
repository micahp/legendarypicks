"""routers/momentum.py — momentum engine state + cross feed (SPEC-momentum-engine.md).

Read-only over momentum_state / momentum_crosses (written nightly by
compute_momentum.py). DISPLAY-ONLY until the validation harness passes —
nothing here adjusts projections, widget gates, or trading selection.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from contextlib import closing
from _core import _db

router = APIRouter()

_STATE_COLS = """league, entity_type, entity_id, entity_name, stat, season, n_games,
    fast, slow, spread, spread_pct, state, improving, crossed_at,
    games_since_cross, last_cross_direction, last_game_date, windows, computed_at"""


def _rows(con, sql, params):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


@router.get("/api/momentum/{league}/crosses")
def crosses(league: str,
            since: Optional[str] = Query(None, description="ISO date lower bound on cross_date"),
            direction: Optional[str] = Query(None, pattern="^(golden|death)$"),
            entity_type: Optional[str] = Query(None, pattern="^(player|team)$"),
            stat: Optional[str] = Query(None),
            limit: int = Query(100, ge=1, le=1000)):
    """The 'who just turned' feed — cross events, newest first."""
    sql = """SELECT league, entity_type, entity_id, entity_name, stat, direction,
                    cross_date, fast, slow, detected_at
             FROM momentum_crosses WHERE league = ?"""
    params: list = [league]
    if since:
        sql += " AND cross_date >= ?"; params.append(since)
    if direction:
        sql += " AND direction = ?"; params.append(direction)
    if entity_type:
        sql += " AND entity_type = ?"; params.append(entity_type)
    if stat:
        sql += " AND stat = ?"; params.append(stat)
    sql += " ORDER BY cross_date DESC, id DESC LIMIT ?"; params.append(limit)
    with closing(_db()) as con:
        return {"league": league, "crosses": _rows(con, sql, params)}


@router.get("/api/momentum/{league}/board")
def board(league: str,
          entity_type: str = Query("player", pattern="^(player|team)$"),
          stat: Optional[str] = Query(None),
          improving: Optional[bool] = Query(None),
          min_games: int = Query(0, ge=0),
          limit: int = Query(50, ge=1, le=500)):
    """Current states ranked by |spread_pct| — the hottest/coldest board."""
    sql = f"SELECT {_STATE_COLS} FROM momentum_state WHERE league = ? AND entity_type = ?"
    params: list = [league, entity_type]
    if stat:
        sql += " AND stat = ?"; params.append(stat)
    if improving is not None:
        sql += " AND improving = ?"; params.append(1 if improving else 0)
    if min_games:
        sql += " AND n_games >= ?"; params.append(min_games)
    sql += " ORDER BY ABS(COALESCE(spread_pct, 0)) DESC LIMIT ?"; params.append(limit)
    with closing(_db()) as con:
        return {"league": league, "board": _rows(con, sql, params)}


@router.get("/api/momentum/{league}/player/{player_id}")
def player(league: str, player_id: int):
    """All stat states for one player."""
    with closing(_db()) as con:
        rows = _rows(con, f"""SELECT {_STATE_COLS} FROM momentum_state
            WHERE league = ? AND entity_type = 'player' AND entity_id = ?""",
            [league, str(player_id)])
    if not rows:
        raise HTTPException(404, f"no momentum state for player {player_id} in {league}")
    return {"league": league, "player_id": player_id,
            "entity_name": rows[0]["entity_name"], "stats": rows}


@router.get("/api/momentum/{league}/team/{abbrev}")
def team(league: str, abbrev: str):
    """All stat states for one team."""
    with closing(_db()) as con:
        rows = _rows(con, f"""SELECT {_STATE_COLS} FROM momentum_state
            WHERE league = ? AND entity_type = 'team' AND UPPER(entity_id) = UPPER(?)""",
            [league, abbrev])
    if not rows:
        raise HTTPException(404, f"no momentum state for team {abbrev} in {league}")
    return {"league": league, "team": abbrev.upper(), "stats": rows}
