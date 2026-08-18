"""board — NFL offseason board layer."""
import copy
import datetime as dt
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Set, Tuple
from fastapi import APIRouter, HTTPException, Query
from _core import _db, _normalize_name
from team_codes import normalize, normalize_optional
from .constants import (_CONTEXT_CONTRACT, _DRAFT_BOARD_CONTRACT, _CURRENT_SEASON, _DRAFT_BOARD_CACHE_TTL, _DRAFT_BOARD_CACHE_MAX_ENTRIES, _DATABASE_TOKEN_MEMO_MAX_ENTRIES, _DRAFT_CACHE_SOURCES, _REG_SEASON_TEAM_GAMES, _REG_SEASON_LAST_WEEK, _POSTSEASON_FIRST_WEEK, _THIN_SAMPLE_GAMES, _CALENDAR_VALID_THROUGH, _NFL_CALENDAR_SOURCE, _NFL_CAMP_SOURCE, _NFL_MILESTONES, _SKILL_POSITIONS, _DEF_POSITION, _FANTASY_DRAFT_POSITIONS, _POSITION_FILTERS, _SORT_FIELDS, _SEARCH_MAX_LEN, _SEARCH_MAX_TOKENS, _TRANSACTIONS_CONTRACT, _POSITION_PREFIX, _SENTENCE_SPLIT, _TRAILING_INITIAL, _SIGNIFICANCE_CACHE_TTL)  # noqa: E402
from . import router
from .cache import _database_cache_token, _draft_board_cache_get, _draft_board_cache_put  # noqa: E402
from .context import _roster_freshness, _table_columns, _today  # noqa: E402
from .aggregates import _dst_aggregates, _pk_aggregates, _regular_season_aggregates  # noqa: E402


def _pkg__dst_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._dst_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _dst_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__roster_freshness(*args, **kwargs):
    """Resolve `routers.nfl_offseason._roster_freshness` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _roster_freshness as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__today(*args, **kwargs):
    """Resolve `routers.nfl_offseason._today` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _today as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__pk_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._pk_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _pk_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__regular_season_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._regular_season_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _regular_season_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__db(*args, **kwargs):
    """Resolve `routers.nfl_offseason._db` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _db as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__database_cache_token(*args, **kwargs):
    """Resolve `routers.nfl_offseason._database_cache_token` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _database_cache_token as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__table_columns(*args, **kwargs):
    """Resolve `routers.nfl_offseason._table_columns` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _table_columns as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__draft_board_cache_get(*args, **kwargs):
    """Resolve `routers.nfl_offseason._draft_board_cache_get` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _draft_board_cache_get as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__draft_board_cache_put(*args, **kwargs):
    """Resolve `routers.nfl_offseason._draft_board_cache_put` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _draft_board_cache_put as _pkg_f
    return _pkg_f(*args, **kwargs)

def _draft_board_schema(connection: sqlite3.Connection) -> None:
    """v2 reads per-game logs, not the season rollup in player_stats.

    The rollup's ``fantasy_ppr_g`` is points per game *played* -- an average
    conditioned on the player being healthy enough to play, which is the exact
    thing a drafter is trying to predict. Availability is only recoverable from
    the per-game rows, because a missed game has no row at all.
    """
    player_columns = _pkg__table_columns(connection, "players")
    log_columns = _pkg__table_columns(connection, "player_game_logs")
    required_players = {"id", "name", "league", "team", "position", "active",
                        "updated_at"}
    required_logs = {"player_id", "league", "season", "game_no", "game_id",
                     "team", "stats"}
    missing = sorted((required_players - player_columns)
                     | (required_logs - log_columns))
    if missing:
        raise HTTPException(
            503,
            f"NFL draft board data unavailable: missing columns {', '.join(missing)}",
        )

def _round(value, places=1):
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return 0.0 if rounded == 0 else float(rounded)

def _rounded_ratio(numerator, denominator, places=1):
    """Round a published decimal ratio without binary-float tie drift."""
    if numerator is None or not denominator:
        return None
    quantum = Decimal(1).scaleb(-places)
    # Weekly PPR is published to hundredths (QB yardage is 0.04/yard). SQLite
    # SUM can return 109.89999999999998 for the exact published 109.90; restore
    # the publisher's scale before division so a 7.85 tie does not become 7.8.
    published_total = Decimal(str(numerator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    value = published_total / Decimal(str(denominator))
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return 0.0 if rounded == 0 else float(rounded)

def _percentage(value, places=1):
    """Convert a published 0-1 share to percent without a float multiply."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    rounded = (Decimal(str(value)) * Decimal(100)).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    return 0.0 if rounded == 0 else float(rounded)

def _escape_like(term: str) -> str:
    # Otherwise a user typing "%" matches the entire board.
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def _name_search(raw) -> Tuple[Optional[str], List[str]]:
    """Normalize a name query into (echo, tokens).

    Every token must appear somewhere in the name, in any order. A drafter types
    "rice" or "ja gibbs" -- fragments, in whatever order they remember -- not a
    canonical full name, so prefix matching would miss the way people search.
    """
    echo = " ".join(str(raw or "").split())[:_SEARCH_MAX_LEN].strip()
    if not echo:
        return None, []
    return echo, [_escape_like(token) for token in echo.split()][:_SEARCH_MAX_TOKENS]

@router.get("/api/nfl/draft-board")
def nfl_draft_board(
    position: Optional[str] = Query(None),
    sort: str = Query("rank"),
    q: Optional[str] = Query(None, description="name search; every token must appear"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """2026 fantasy draft board with published rank and projected PPR.

    The headline is how often a player was on the field, not how well he did on
    the days he was. Both numbers ship together: PPR per game *played* is what
    every fantasy site shows, PPR per *team game* is what the roster spot
    actually returned. They diverge exactly when availability drops -- Joe Burrow
    2025 reads 16.8 and 7.9 off the same season.

    The projection is season-long 2026 PPR computed from ESPN's published
    projected stat line. Missing source projections remain null.
    """
    selected_position = str(position or "").strip().upper() or None
    if selected_position is not None and selected_position not in _POSITION_FILTERS:
        raise HTTPException(400, f"position must be one of {sorted(_POSITION_FILTERS)}")
    if sort not in _SORT_FIELDS:
        raise HTTPException(400, f"sort must be one of {sorted(_SORT_FIELDS)}")
    sort_field, sort_ascending = _SORT_FIELDS[sort]
    search, search_tokens = _name_search(q)

    with closing(_pkg__db()) as connection:
        connection.row_factory = sqlite3.Row
        _draft_board_schema(connection)

        database_token = _pkg__database_cache_token(connection)
        cache_key = (
            (
                database_token,
                _pkg__today().isoformat(),
                selected_position,
                sort,
                search,
                limit,
                offset,
            )
            if database_token is not None else None
        )
        cached = _pkg__draft_board_cache_get(cache_key)
        if cached is not None:
            return cached

        season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        season = season_row[0] if season_row else None
        if season is None:
            raise HTTPException(503, "NFL draft board data unavailable: no reference season")

        roster_row = connection.execute(
            "SELECT MAX(updated_at) FROM players WHERE league='nfl' AND active=1"
        ).fetchone()
        roster_verified_at = roster_row[0] if roster_row else None
        roster_freshness = _pkg__roster_freshness(_pkg__today(), roster_verified_at)

        aggregates = _pkg__regular_season_aggregates(connection, season)
        dst_aggregates, dst_team_weeks = _pkg__dst_aggregates(connection, season)
        pk_aggregates = _pkg__pk_aggregates(connection, season, aggregates)

        # Position comes from nfl_adp (the fantasy table) with players as the
        # fallback: a team defence plays no position, so `players.position` is
        # NULL for the 32 D/ST rows, and the fantasy label lives in nfl_adp.
        position_expr = (
            "UPPER(COALESCE(NULLIF(COALESCE(na.position, p.position), ''), ''))"
            if "position" in _pkg__table_columns(connection, "nfl_adp")
            else "UPPER(COALESCE(NULLIF(p.position,''), ''))"
        )
        where = ["p.league='nfl'", "p.active=1"]
        params: list = []
        if selected_position == "FLEX":
            where.append(f"{position_expr} IN ('RB','WR','TE')")
        elif selected_position:
            where.append(f"{position_expr}=?")
            params.append(selected_position)
        else:
            # The all-player fantasy board is still a fantasy board. Aggregate
            # TQB rows, IDP, coaches, punters, and line positions belong in the
            # source universe, not in this user-facing pool.
            where.append(
                f"{position_expr} IN ({','.join('?' for _ in _FANTASY_DRAFT_POSITIONS)})"
            )
            params.extend(_FANTASY_DRAFT_POSITIONS)

        # Narrow in SQL rather than after: the page a drafter searching for one
        # player gets back should be one player, not 522 rows filtered in the
        # browser.  Each token matches either the player name or team name so
        # "cowboys" returns everyone on Dallas.
        for token in search_tokens:
            where.append(r"(p.name LIKE ? ESCAPE '\' OR p.team LIKE ? ESCAPE '\')")
            params.append(f"%{token}%")
            params.append(f"%{token}%")

        where_sql = " AND ".join(where)

        injury_select = (
            ", p.injury_status"
            if "injury_status" in _pkg__table_columns(connection, "players")
            else ", NULL AS injury_status"
        )
        adp_columns = _pkg__table_columns(connection, "nfl_adp")
        rank_select = (
            ", na.espn_ppr_rank"
            if "espn_ppr_rank" in adp_columns
            else ", NULL AS espn_ppr_rank"
        )
        projection_columns = _pkg__table_columns(connection, "nfl_player_projections")
        has_projection = "lp_ppr_projected_points" in projection_columns
        projection_select = (
            ", np.lp_ppr_projected_points AS proj_ppr_points"
            if has_projection
            else ", NULL AS proj_ppr_points"
        )
        projection_join = (
            "LEFT JOIN nfl_player_projections np "
            "ON np.player_id=p.id AND np.season=?"
            if has_projection
            else ""
        )
        projection_params = [_CURRENT_SEASON] if has_projection else []
        candidates = connection.execute(
            f"""SELECT p.id AS player_id, p.name, {position_expr} AS position,
                       p.team AS current_team,
                       na.adp, na.percent_owned,
                       d.pos_rank AS depth_rank, d.team AS depth_team,
                       d.pos_abb AS depth_position{injury_select}
                       {rank_select}{projection_select}
                FROM players p
                LEFT JOIN nfl_adp na
                       ON na.player_id=p.id AND na.season=?
                {projection_join}
                LEFT JOIN nfl_depth_chart d
                       ON d.rowid=(
                           SELECT d2.rowid
                           FROM nfl_depth_chart d2
                           WHERE d2.player_id=p.id AND d2.season=?
                           ORDER BY d2.pos_rank IS NULL,
                                    d2.pos_rank ASC,
                                    d2.pos_abb ASC
                           LIMIT 1
                       )
                WHERE {where_sql}""",
            [_CURRENT_SEASON, *projection_params, _CURRENT_SEASON, *params],
        ).fetchall()

        # The current-season schedule publishes 17 played weeks in an 18-week
        # grid. Exactly one missing week is the bye; anything else is
        # incomplete coverage and remains null.
        bye_weeks: Dict[str, Optional[int]] = {}
        schedule_columns = _pkg__table_columns(connection, "nfl_schedule")
        if {"season", "game_type", "week", "home_team", "away_team"}.issubset(
            schedule_columns
        ):
            played: Dict[str, Set[int]] = defaultdict(set)
            for schedule_row in connection.execute(
                """SELECT home_team AS team, week FROM nfl_schedule
                   WHERE season=? AND game_type='REG'
                UNION ALL
                   SELECT away_team AS team, week FROM nfl_schedule
                   WHERE season=? AND game_type='REG'""",
                (_CURRENT_SEASON, _CURRENT_SEASON),
            ):
                try:
                    played[normalize("nfl", schedule_row["team"])].add(
                        int(schedule_row["week"])
                    )
                except (TypeError, ValueError):
                    continue
            all_weeks = set(range(1, 19))
            for team, weeks in played.items():
                missing_weeks = all_weeks - weeks
                bye_weeks[team] = (
                    next(iter(missing_weeks)) if len(missing_weeks) == 1 else None
                )

    roster_is_current = roster_freshness["status"] == "current"
    players = []
    for row in candidates:
        pid = row["player_id"]
        is_def = row["position"] == "DEF"
        is_pk = row["position"] == "PK"
        availability = dst_aggregates.get(pid) if is_def else aggregates.get(pid)
        scoring = (
            dst_aggregates.get(pid)
            if is_def
            else pk_aggregates.get(pid)
            if is_pk
            else aggregates.get(pid)
        )
        published_adp = row["adp"]

        # Eligible if we have something true to say: a real season, or a real
        # market price. A rookie with neither is not on the board at all --
        # better absent than present with a fabricated zero.
        if availability is None and published_adp is None:
            continue

        games_played = (
            availability["games_played"] if availability is not None else None
        )
        if is_def and scoring:
            dst_total = scoring.get("dst_total")
            dst_pts_per_game = _round(scoring["dst_avg"]) if scoring["dst_avg"] is not None else None
            pk_pts_total = None
            pk_pts_per_game = None
            ppr_total = None
            ppr_per_game_played = None
            ppr_per_team_game = None
            xfp_per_game = None
            snap_pct = None
            target_share = None
        elif is_pk and scoring:
            pk_pts_total = scoring.get("pk_pts_total")
            pk_pts_per_game = scoring.get("pk_pts_per_game")
            dst_total = None
            dst_pts_per_game = None
            ppr_total = None
            ppr_per_game_played = None
            ppr_per_team_game = None
            xfp_per_game = None
            snap_pct = None
            target_share = None
        else:
            # Not `or None`: a player measured across a full season who scored
            # exactly 0.0 PPR is a fact we hold, and `0 or None` throws it away,
            # rendering an em dash that claims we know nothing about him.
            ppr_total = scoring["ppr_total"] if scoring else None
            dst_total = None
            dst_pts_per_game = None
            pk_pts_total = None
            pk_pts_per_game = None
            xfp_per_game = (
                scoring["xfp_per_game"] if scoring and not is_pk else None
            )
            snap_pct = scoring["snap_pct"] if scoring and not is_pk else None
            target_share = scoring["target_share"] if scoring and not is_pk else None

        sample = (
            "full"
            if games_played is not None and games_played >= _THIN_SAMPLE_GAMES
            else "thin"
            if games_played is not None and games_played > 0
            else "none"
        )

        # Per-player team_games from actual team_weeks, not the 17-constant.
        # After a mid-season trade the new team may have played a different
        # number of games.  For skill players the aggregate already stores
        # team_weeks scoped to the primary team (the one they appeared for
        # most); for D/ST we resolve from the deduplicated dst_team_weeks
        # using current_team (team defenses don't change teams).
        if is_def:
            player_team_weeks = dst_team_weeks.get(row["current_team"], [])
            team_games_val = len(player_team_weeks) or _REG_SEASON_TEAM_GAMES
        elif availability:
            player_team_weeks = availability.get("team_weeks", [])
            team_games_val = availability.get(
                "team_games", _REG_SEASON_TEAM_GAMES
            )
        else:
            player_team_weeks = []
            team_games_val = None

        # The team this player actually played most of their games for.
        # Mid-season movers (Flacco) have a different current_team; this
        # is the one whose schedule drives team_games.
        raw_primary_team = availability.get("primary_team") if availability else None
        primary_team = normalize("nfl", raw_primary_team) if raw_primary_team else None

        players.append({
            "player_id": pid,
            "name": row["name"],
            "position": row["position"],
            "current_team": normalize_optional("nfl", row["current_team"]),
            "primary_team": primary_team,
            # Current role, from the published depth chart. This is what a rookie
            # has instead of a season.
            "depth_rank": row["depth_rank"],
            "depth_team": normalize_optional("nfl", row["depth_team"]) if row["depth_team"] else None,
            "depth_position": row["depth_position"],
            "adp": published_adp,
            "adp_is_ranked": published_adp is not None,
            "espn_ppr_rank": row["espn_ppr_rank"],
            "proj_ppr_points": row["proj_ppr_points"],
            "proj_season": _CURRENT_SEASON,
            "proj_source": (
                "espn" if row["proj_ppr_points"] is not None else None
            ),
            "bye_week": bye_weeks.get(
                normalize_optional("nfl", row["current_team"])
            ),
            "percent_owned": row["percent_owned"],
            "injury_status": row["injury_status"],
            # Availability: the headline. Denominator is every game the team
            # played, so a missed game costs the drafter exactly what it cost.
            "games_played": games_played,
            "games_missed": (
                max(0, team_games_val - games_played)
                if availability is not None
                else None
            ),
            "team_games": team_games_val,
            "weeks_played": sorted(availability["weeks"]) if availability else [],
            # The 17 weeks his team actually played, so the strip can show a bye
            # as a bye rather than as an absence.
            "team_weeks": player_team_weeks,
            # Both averages, always together.
            "ppr_per_game_played": (
                _rounded_ratio(ppr_total, games_played)
                if ppr_total is not None and games_played
                else None
            ),
            # team_games_val, not the 17-constant. The metric claims "what this
            # roster spot actually returned", and after a mid-season trade the
            # player's team may have played a different number of games -- which
            # is exactly what the comment at the top of this block says.
            "ppr_per_team_game": (
                _rounded_ratio(ppr_total, team_games_val)
                if ppr_total is not None and team_games_val
                else None
            ),
            "xfp_per_game": _round(xfp_per_game) if xfp_per_game is not None else None,
            "snap_pct": _percentage(snap_pct, 0),
            "target_share": _percentage(target_share, 1),
            # D/ST-specific fields
            "dst_pts_per_game": dst_pts_per_game,
            "dst_pts_total": (
                _round(dst_total, 1) if dst_total is not None else None
            ),
            # PK-specific fields
            "pk_pts_per_game": pk_pts_per_game,
            "pk_pts_total": (
                _round(pk_pts_total, 1) if pk_pts_total is not None else None
            ),
            "sample": sample,
            "team_changed": None,
        })

    if roster_is_current:
        for player in players:
            if player["depth_team"] and player["current_team"]:
                player["team_changed"] = player["current_team"] != player["depth_team"]

    def _key(player):
        value = player.get(sort_field)
        # Missing values sort last under either direction -- never at the top
        # pretending to be a leader.
        if value is None:
            return (1, 0.0, player["name"].lower())
        return (0, value if sort_ascending else -value, player["name"].lower())

    players.sort(key=_key)
    eligible = len(players)
    page = players[offset: offset + limit]
    for index, player in enumerate(page):
        player["rank"] = offset + index + 1

    response = {
        "contract": _DRAFT_BOARD_CONTRACT,
        "league": "nfl",
        "current_season": _CURRENT_SEASON,
        "reference_season": season,
        "scoring": "ppr",
        "team_games": _REG_SEASON_TEAM_GAMES,
        "thin_sample_games": _THIN_SAMPLE_GAMES,
        "sort": sort,
        "position": selected_position,
        "query": search,
        "limit": limit,
        "offset": offset,
        "eligible_players": eligible,
        "returned_players": len(page),
        "roster": {
            "last_verified_at": roster_verified_at,
            "freshness": roster_freshness,
        },
        "players": page,
    }

    _pkg__draft_board_cache_put(cache_key, response)

    return response
