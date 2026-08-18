"""projections — players router projections layer."""
import json
import math
import sqlite3
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from league_offering import offered_leagues, sql_league_filter
from league_stats import LEADERBOARD_LEAGUES, canonical_population_sql
from nfl_rankings import nfl_player_rank_context
from nfl_stat_derivations import with_derived as _with_derived
from nfl_news import (ROTOWIRE_LABEL, load_news_feed, load_player_news_page, load_sleeper_crosswalk, merge_player_news, resolve_rotowire_id)
from . import router
from .search import _reg_season_game_filter  # noqa: E402


def __db_pkg(*args, **kwargs):
    """Resolve `routers.players._db` at call time (tests patch the package attr)."""
    from routers.players import _db as _pkg
    return _pkg(*args, **kwargs)

@router.get("/api/projections/player/{player_id}")
def player_projections(player_id: int,
                       season: Optional[int] = Query(None),
                       line: Optional[float] = Query(None),
                       market: Optional[str] = Query(None)):
    """Per-stat projections (recency-weighted EV + floor/median/ceiling) for a
    player, derived from player_game_logs. Pass ?line=&market= for P(over)."""
    import json as _json
    with closing(__db_pkg()) as con:
        prow = con.execute("SELECT id, name, league, team FROM players WHERE id=?", (player_id,)).fetchone()
        if not prow:
            raise HTTPException(404, "Player not found")
        if season is None:
            srow = con.execute(
                "SELECT season FROM player_game_logs WHERE player_id=? ORDER BY season DESC LIMIT 1",
                (player_id,)).fetchone()
            season = srow["season"] if srow else None
        params = [player_id]
        reg_filter, _ = _reg_season_game_filter(con, prow["league"])
        q = f"SELECT stats FROM player_game_logs WHERE player_id=? {reg_filter}"
        if season is not None:
            q += " AND season=?"; params.append(season)
        # most-recent-first; game_date is NULL for NFL (week-keyed) → fall back to week
        q += " ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC"
        rows = con.execute(q, params).fetchall()

    base = {"player_id": player_id, "name": prow["name"], "league": prow["league"],
            "team": prow["team"], "season": season, "games": len(rows)}
    if not rows:
        return {**base, "projections": {}}

    series: dict = {}
    for r in rows:
        for k, v in _json.loads(r["stats"]).items():
            if isinstance(v, (int, float)):
                # Normalize legacy (2024 nflverse) keys → canonical (2025 pbp) keys
                k = _NFL_KEY_NORMALIZE.get(k, k)
                series.setdefault(k, []).append(v)

    projections = {}
    for k, vals in series.items():
        pr = proj_mod.project_stat(vals)
        if not pr:
            continue
        if line is not None and (market is None or market == k):
            pr["prob_over"] = proj_mod.prob_over(vals, line)
        projections[k] = pr
    return {**base, "projections": projections}
