"""NFL offseason and training-camp landing contracts.

These endpoints compose the data Legendary Picks already owns. They do not
call ESPN or nflverse on the request path. Calendar milestones are sourced
from the NFL's published 2026 calendar and must be refreshed for a new league
year before the contract can claim a current phase.
"""
import datetime as dt
import sqlite3
from contextlib import closing
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Query

from _core import _db


router = APIRouter()

_CONTEXT_CONTRACT = "nfl-season-context-v1"
_DRAFT_BOARD_CONTRACT = "nfl-draft-board-v1"
_CURRENT_SEASON = 2026
_CALENDAR_VALID_THROUGH = dt.date(2026, 12, 31)
_NFL_CALENDAR_SOURCE = {
    "name": "NFL Football Operations — Important Dates",
    "url": "https://operations.nfl.com/calendar-events/nfl-important-dates",
    "verified_at": "2026-07-21",
}
_NFL_CAMP_SOURCE = {
    "name": "NFL.com — 2026 Training Camp Reporting Dates",
    "url": "https://www.nfl.com/news/2026-nfl-training-camps-report-dates-locations-announced-for-all-32-teams",
    "verified_at": "2026-07-21",
}

_NFL_MILESTONES = (
    ("camp_opens", "Training camps begin opening", dt.date(2026, 7, 17), "training_camp"),
    ("all_teams_report", "All 32 teams in camp", dt.date(2026, 7, 28), "training_camp"),
    ("hall_of_fame_game", "Hall of Fame Game", dt.date(2026, 8, 6), "game"),
    ("preseason_week_1", "First preseason weekend", dt.date(2026, 8, 13), "game"),
    ("preseason_week_2", "Second preseason weekend", dt.date(2026, 8, 20), "game"),
    ("preseason_week_3", "Third preseason weekend", dt.date(2026, 8, 27), "game"),
    ("roster_cutdown", "53-player roster deadline", dt.date(2026, 8, 30), "roster"),
    ("kickoff_weekend", "Kickoff Weekend begins", dt.date(2026, 9, 9), "regular_season"),
)

_TEAM_ALIASES = {
    "JAC": "JAX",
    "LA": "LAR",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "WAS": "WSH",
}
_SKILL_POSITIONS = ("QB", "RB", "WR", "TE", "FB")
_POSITION_FILTERS = set(_SKILL_POSITIONS) | {"FLEX"}
_SORT_FIELDS = {
    "fantasy_ppr_g": "ps.fantasy_ppr_g",
    "fantasy_pts_g": "ps.fantasy_pts_g",
    "pass_yds_g": "ps.pass_yds_g",
    "rush_yds_g": "ps.rush_yds_g",
    "rec_yds_g": "ps.rec_yds_g",
    "targets": "ps.targets",
}


def _today() -> dt.date:
    # League phases change by whole calendar day. The host is configured for a
    # US timezone, so its local date is the least surprising boundary on the
    # Python 3.8 runtime (which does not ship zoneinfo).
    return dt.date.today()


def _table_columns(connection: sqlite3.Connection, table: str) -> Set[str]:
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _normalize_team(value) -> str:
    team = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(team, team)


def _phase_for(as_of: dt.date) -> Tuple[str, str]:
    if as_of.year != _CURRENT_SEASON or as_of > _CALENDAR_VALID_THROUGH:
        return "unknown", "Season state unavailable"
    if as_of < dt.date(2026, 7, 17):
        return "offseason", "Roster building"
    if as_of < dt.date(2026, 8, 6):
        return "training_camp", "Training Camp"
    if as_of < dt.date(2026, 9, 9):
        return "preseason", "Preseason"
    return "regular_season", "Regular Season"


def _milestones_for(as_of: dt.date) -> List[Dict]:
    milestones = []
    for event_id, label, event_date, kind in _NFL_MILESTONES:
        days_until = (event_date - as_of).days
        status = "past" if days_until < 0 else "today" if days_until == 0 else "upcoming"
        milestones.append({
            "id": event_id,
            "label": label,
            "date": event_date.isoformat(),
            "kind": kind,
            "status": status,
            "days_until": days_until if days_until >= 0 else None,
        })
    return milestones


def _timestamp_date(value) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _roster_freshness(as_of: dt.date, last_verified_at) -> dict:
    verified_date = _timestamp_date(last_verified_at)
    if verified_date is None:
        return {"status": "unavailable", "age_days": None, "max_age_days": 7}
    age_days = max(0, (as_of - verified_date).days)
    return {
        "status": "current" if age_days <= 7 else "stale",
        "age_days": age_days,
        "max_age_days": 7,
    }


def _reference_coverage(connection: sqlite3.Connection, as_of: dt.date) -> dict:
    coverage = {
        "reference_stats": {
            "season": None,
            "rows": 0,
            "players": 0,
            "status": "unavailable",
        },
        "game_logs": {
            "season": None,
            "rows": 0,
            "players": 0,
            "status": "unavailable",
        },
        "current_roster": {
            "players": 0,
            "teams": 0,
            "skill_players_with_reference_stats": 0,
            "last_verified_at": None,
            "freshness": {"status": "unavailable", "age_days": None, "max_age_days": 7},
        },
        "team_reference": {
            "season": None,
            "status": "unavailable",
            "teams": 0,
            "games": 0,
        },
    }

    stats_columns = _table_columns(connection, "player_stats")
    if {"league", "season", "player_id"}.issubset(stats_columns):
        season_row = connection.execute(
            "SELECT MAX(season) FROM player_stats WHERE league='nfl'"
        ).fetchone()
        season = season_row[0] if season_row else None
        if season is not None:
            row = connection.execute(
                """SELECT COUNT(*) AS rows, COUNT(DISTINCT player_id) AS players
                   FROM player_stats WHERE league='nfl' AND season=?""",
                (season,),
            ).fetchone()
            coverage["reference_stats"] = {
                "season": season,
                "rows": row[0],
                "players": row[1],
                "status": "ready" if row[1] else "unavailable",
            }

    log_columns = _table_columns(connection, "player_game_logs")
    if {"league", "season", "player_id"}.issubset(log_columns):
        season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        season = season_row[0] if season_row else None
        if season is not None:
            row = connection.execute(
                """SELECT COUNT(*) AS rows, COUNT(DISTINCT player_id) AS players
                   FROM player_game_logs WHERE league='nfl' AND season=?""",
                (season,),
            ).fetchone()
            coverage["game_logs"] = {
                "season": season,
                "rows": row[0],
                "players": row[1],
                "status": "ready" if row[1] else "unavailable",
            }

    player_columns = _table_columns(connection, "players")
    required_players = {"id", "league", "team", "position", "active", "updated_at"}
    if required_players.issubset(player_columns):
        roster_row = connection.execute(
            """SELECT COUNT(*) AS players, COUNT(DISTINCT team) AS teams,
                      MAX(updated_at) AS last_verified_at
               FROM players WHERE league='nfl' AND active=1"""
        ).fetchone()
        linked = 0
        reference_season = coverage["reference_stats"]["season"]
        if reference_season is not None and {"player_id", "league", "season"}.issubset(stats_columns):
            placeholders = ",".join("?" for _ in _SKILL_POSITIONS)
            linked = connection.execute(
                f"""SELECT COUNT(DISTINCT p.id)
                    FROM players p JOIN player_stats ps ON ps.player_id=p.id
                    WHERE p.league='nfl' AND p.active=1
                      AND UPPER(COALESCE(p.position,'')) IN ({placeholders})
                      AND ps.league='nfl' AND ps.season=?""",
                (*_SKILL_POSITIONS, reference_season),
            ).fetchone()[0]
        last_verified_at = roster_row[2]
        coverage["current_roster"] = {
            "players": roster_row[0],
            "teams": roster_row[1],
            "skill_players_with_reference_stats": linked,
            "last_verified_at": last_verified_at,
            "freshness": _roster_freshness(as_of, last_verified_at),
        }

    manifest_columns = _table_columns(connection, "team_stats_coverage")
    required_manifest = {
        "league", "season", "status", "fetched_teams", "fetched_games", "completed_at",
    }
    if required_manifest.issubset(manifest_columns):
        row = connection.execute(
            """SELECT season, status, fetched_teams, fetched_games
               FROM team_stats_coverage WHERE league='nfl'
               ORDER BY season DESC, completed_at DESC LIMIT 1"""
        ).fetchone()
        if row:
            coverage["team_reference"] = {
                "season": row[0],
                "status": row[1],
                "teams": row[2],
                "games": row[3],
            }
    return coverage


def _build_nfl_season_context(as_of: dt.date, connection: sqlite3.Connection) -> dict:
    phase, phase_label = _phase_for(as_of)
    milestones = _milestones_for(as_of)
    next_event = next((event for event in milestones if event["status"] != "past"), None)
    coverage = _reference_coverage(connection, as_of)
    return {
        "contract": _CONTEXT_CONTRACT,
        "league": "nfl",
        "as_of": as_of.isoformat(),
        "calendar_status": "current" if phase != "unknown" else "expired",
        "calendar_valid_through": _CALENDAR_VALID_THROUGH.isoformat(),
        "phase": phase,
        "phase_label": phase_label,
        "current_season": _CURRENT_SEASON,
        "reference_season": coverage["reference_stats"]["season"],
        "next_event": next_event,
        "milestones": milestones,
        "coverage": coverage,
        "sources": [_NFL_CALENDAR_SOURCE, _NFL_CAMP_SOURCE],
    }


@router.get("/api/nfl/season-context")
def nfl_season_context():
    """Season-aware landing context for the NFL league page (DB-only)."""
    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        return _build_nfl_season_context(_today(), connection)


_TRANSACTIONS_CONTRACT = "nfl-transactions-v1"


@router.get("/api/nfl/transactions")
def nfl_transactions(
    limit: int = Query(30, ge=1, le=100),
    team: Optional[str] = Query(None, description="team abbreviation, e.g. ATL"),
):
    """Recent NFL roster moves (waives, signings, IR, releases, retirements) —
    ingested from ESPN's public transactions feed by nfl_transactions_sync.py.
    "Offseason Movers" card content; see docs on why this replaced the raw
    season-milestone timeline (it's actual news, not a static calendar)."""
    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        columns = _table_columns(connection, "nfl_transactions")
        if not columns:
            return {"contract": _TRANSACTIONS_CONTRACT, "transactions": [], "count": 0}
        where = "WHERE team_abbr=?" if team else ""
        params = (team.upper(),) if team else ()
        rows = connection.execute(
            f"""SELECT txn_date, team_id, team_abbr, team_name, description
                FROM nfl_transactions {where}
                ORDER BY txn_date DESC, id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        return {
            "contract": _TRANSACTIONS_CONTRACT,
            "count": len(rows),
            "transactions": [
                {
                    "date": r["txn_date"],
                    "team": r["team_abbr"],
                    "teamName": r["team_name"],
                    "description": r["description"],
                }
                for r in rows
            ],
        }


def _draft_board_schema(connection: sqlite3.Connection) -> None:
    player_columns = _table_columns(connection, "players")
    stat_columns = _table_columns(connection, "player_stats")
    required_players = {"id", "name", "league", "team", "position", "active", "updated_at"}
    required_stats = {
        "player_id", "league", "season", "games", "nfl_position", "nfl_team",
        "fantasy_ppr_g", "fantasy_pts_g", "pass_yds_g", "rush_yds_g",
        "rec_yds_g", "targets", "receptions", "carries_g",
    }
    missing = sorted((required_players - player_columns) | (required_stats - stat_columns))
    if missing:
        raise HTTPException(
            503,
            f"NFL draft board data unavailable: missing columns {', '.join(missing)}",
        )


@router.get("/api/nfl/draft-board")
def nfl_draft_board(
    position: Optional[str] = Query(None),
    sort: str = Query("fantasy_ppr_g"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Bounded 2026 draft-prep population grounded in the latest NFL season.

    Current roster identity comes from ``players``; production comes from the
    latest ``player_stats`` season. A stale roster never produces a definitive
    ``team_changed`` claim.
    """
    selected_position = str(position or "").strip().upper() or None
    if selected_position is not None and selected_position not in _POSITION_FILTERS:
        raise HTTPException(400, f"position must be one of {sorted(_POSITION_FILTERS)}")
    if sort not in _SORT_FIELDS:
        raise HTTPException(400, f"sort must be one of {sorted(_SORT_FIELDS)}")

    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        _draft_board_schema(connection)
        season_row = connection.execute(
            "SELECT MAX(season) FROM player_stats WHERE league='nfl'"
        ).fetchone()
        season = season_row[0] if season_row else None
        if season is None:
            raise HTTPException(503, "NFL draft board data unavailable: no reference season")

        roster_row = connection.execute(
            "SELECT MAX(updated_at) FROM players WHERE league='nfl' AND active=1"
        ).fetchone()
        roster_verified_at = roster_row[0] if roster_row else None
        roster_freshness = _roster_freshness(_today(), roster_verified_at)

        position_expr = "UPPER(COALESCE(NULLIF(p.position,''), ps.nfl_position, ''))"
        where = [
            "p.league='nfl'",
            "p.active=1",
            "ps.league='nfl'",
            "ps.season=?",
            "ps.games>0",
            f"{_SORT_FIELDS[sort]} IS NOT NULL",
        ]
        params: list = [season]
        if selected_position == "FLEX":
            where.append(f"{position_expr} IN ('RB','WR','TE')")
        elif selected_position:
            where.append(f"{position_expr}=?")
            params.append(selected_position)
        else:
            where.append(f"{position_expr} IN ('QB','RB','WR','TE','FB')")
        where_sql = " AND ".join(where)
        eligible = connection.execute(
            f"""SELECT COUNT(*) FROM players p
                JOIN player_stats ps ON ps.player_id=p.id
                WHERE {where_sql}""",
            params,
        ).fetchone()[0]
        rows = connection.execute(
            f"""SELECT p.id AS player_id, p.name, {position_expr} AS position,
                       p.team AS current_team, COALESCE(NULLIF(ps.nfl_team,''), ps.team) AS reference_team,
                       ps.games, ps.fantasy_ppr_g, ps.fantasy_pts_g,
                       ps.pass_yds_g, ps.rush_yds_g, ps.rec_yds_g,
                       ps.targets, ps.receptions, ps.carries_g
                FROM players p JOIN player_stats ps ON ps.player_id=p.id
                WHERE {where_sql}
                ORDER BY {_SORT_FIELDS[sort]} DESC, ps.games DESC, p.name COLLATE NOCASE
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()

    roster_is_current = roster_freshness["status"] == "current"
    players = []
    for index, row in enumerate(rows):
        current_team = _normalize_team(row["current_team"])
        reference_team = _normalize_team(row["reference_team"])
        team_changed = None
        if roster_is_current and current_team and reference_team:
            team_changed = current_team != reference_team
        players.append({
            "rank": offset + index + 1,
            "player_id": row["player_id"],
            "name": row["name"],
            "position": row["position"],
            "current_team": current_team,
            "reference_team": reference_team,
            "team_changed": team_changed,
            "games": row["games"],
            "fantasy_ppr_g": row["fantasy_ppr_g"],
            "fantasy_pts_g": row["fantasy_pts_g"],
            "pass_yds_g": row["pass_yds_g"],
            "rush_yds_g": row["rush_yds_g"],
            "rec_yds_g": row["rec_yds_g"],
            "targets": row["targets"],
            "receptions": row["receptions"],
            "carries_g": row["carries_g"],
        })
    return {
        "contract": _DRAFT_BOARD_CONTRACT,
        "league": "nfl",
        "current_season": _CURRENT_SEASON,
        "reference_season": season,
        "scoring": "ppr",
        "sort": sort,
        "position": selected_position,
        "limit": limit,
        "offset": offset,
        "eligible_players": eligible,
        "returned_players": len(players),
        "roster": {
            "last_verified_at": roster_verified_at,
            "freshness": roster_freshness,
        },
        "players": players,
    }
