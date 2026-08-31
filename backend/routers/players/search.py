"""search — players router search layer."""
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

# ── Postseason guard — replicate nfl_offseason.py pattern ──

def __db_pkg(*args, **kwargs):
    """Resolve `routers.players._db` at call time (tests patch the package attr)."""
    from routers.players import _db as _pkg
    return _pkg(*args, **kwargs)

def _reg_season_game_filter(connection, league):
    """Return the league-aware regular-season predicate.

    ``game_type`` was an NFL-only field when this was written, and non-NFL
    leagues got an empty predicate: every row is a regular-season row, because
    there was nothing else in the table. That stopped being true for NHL on
    2026-08-02, when the phase started being ingested. An empty predicate over a
    table holding playoff rows does not fail — it quietly adds postseason games
    to a regular-season count, which is the same shape of defect as the NULL
    column it replaced, in the opposite direction.

    So the rule is now about the values, not the league: a row that says which
    phase it belongs to is filtered on what it says. Rows that say nothing keep
    the old behaviour — for NFL the legacy week-number compatibility rule, for
    everyone else inclusion, because excluding a NULL would hide every league
    whose phase has not been ingested yet.
    """
    cols = {row[1] for row in connection.execute("PRAGMA table_info(player_game_logs)").fetchall()}
    if "game_type" not in cols:
        if str(league or "").lower() != "nfl":
            return "", []
        return "AND CAST(game_no AS INTEGER) < 19", []
    if str(league or "").lower() != "nfl":
        return "AND (game_type='REG' OR game_type IS NULL)", []
    if "game_no" not in cols:
        return "AND game_type='REG'", []
    return (
        "AND (game_type='REG' OR "
        "(game_type IS NULL AND CAST(game_no AS INTEGER) < 19))",
        [],
    )

@router.get("/api/players/search")
def search_players(q: str = Query("", description="Search query")):
    query = str(q or "").strip()
    if len(query) < 2:
        return []
    contains = "%{}%".format(query)
    prefix = "{}%".format(query)
    with closing(__db_pkg()) as con:
        # Only leagues this database is willing to offer. Search was the way into
        # a league the hub refuses to link to: on prod 2026-08-11 the hub offered
        # mlb/nba/nfl/nhl while `?q=Bates` returned 7 NCAAF players, each with a
        # working player page. Having data for a league is not the same as
        # offering it, and the registry is the only thing that knows which.
        league_sql, league_params = sql_league_filter(offered_leagues(con))
        has_tennis_rankings = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='tennis_ranking_snapshots'"
        ).fetchone() is not None
        ranking_evidence = (
            "EXISTS(SELECT 1 FROM tennis_ranking_snapshots tr "
            "WHERE tr.player_id=p.id)"
            if has_tennis_rankings else "0"
        )
        rows = con.execute(
            f"""SELECT p.id, p.name, p.team, p.league,
                      EXISTS(SELECT 1 FROM player_game_logs g WHERE g.player_id=p.id) AS has_logs,
                      EXISTS(SELECT 1 FROM props pr WHERE pr.player_id=p.id) AS has_props,
                      EXISTS(SELECT 1 FROM player_stats s WHERE s.player_id=p.id) AS has_stats,
                      {ranking_evidence} AS has_rankings
               FROM players p
               WHERE p.name LIKE ? COLLATE NOCASE
                 AND (
                   EXISTS(SELECT 1 FROM player_game_logs g WHERE g.player_id=p.id)
                   OR EXISTS(SELECT 1 FROM props pr WHERE pr.player_id=p.id)
                   OR EXISTS(SELECT 1 FROM player_stats s WHERE s.player_id=p.id)
                   OR {ranking_evidence}
                 )"""
            + league_sql
            + """
               ORDER BY
                 CASE
                   WHEN p.name = ? COLLATE NOCASE THEN 0
                   WHEN p.name LIKE ? COLLATE NOCASE THEN 1
                   ELSE 2
                 END,
                 has_props DESC, has_logs DESC, has_stats DESC, has_rankings DESC,
                 p.name COLLATE NOCASE, p.id
               LIMIT 20""",
            # Order matters: the league filter's placeholders sit in the WHERE
            # clause, between the name LIKE and the ORDER BY's two.
            [contains, *league_params, query, prefix],
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "team": r["team"],
            "league": r["league"],
            "coverage": {
                "game_logs": bool(r["has_logs"]),
                "props": bool(r["has_props"]),
                "season_stats": bool(r["has_stats"]),
                "rankings": bool(r["has_rankings"]),
            },
        }
        for r in rows
    ]
