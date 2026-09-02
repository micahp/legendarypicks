"""aggregates — NFL offseason aggregates layer."""
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
from .context import _table_columns  # noqa: E402


def _pkg__availability_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._availability_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _availability_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__dst_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._dst_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _dst_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__pk_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._pk_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _pk_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__regular_season_aggregates(*args, **kwargs):
    """Resolve `routers.nfl_offseason._regular_season_aggregates` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _regular_season_aggregates as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__table_columns(*args, **kwargs):
    """Resolve `routers.nfl_offseason._table_columns` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _table_columns as _pkg_f
    return _pkg_f(*args, **kwargs)

def _availability_aggregates(
    connection: sqlite3.Connection, season: int
) -> Dict[int, dict]:
    """Return one shared regular-season presence record per player.

    Presence is the union of stat-log weeks and published snap-count weeks.
    When logs exist, their most-used team owns the schedule denominator; snap
    teams are consulted only for players with no log rows. Ties prefer the team
    used in the latest week, then its code, so the choice is deterministic.
    """
    game_type_filter = f"AND CAST(game_no AS INTEGER) < {_POSTSEASON_FIRST_WEEK}"
    if "game_type" in _pkg__table_columns(connection, "player_game_logs"):
        game_type_filter = "AND game_type='REG'"

    presence: Dict[int, dict] = {}
    for row in connection.execute(
        f"""SELECT player_id, team, GROUP_CONCAT(game_no) AS weeks
            FROM player_game_logs
            WHERE league='nfl' AND season=? AND player_id IS NOT NULL
              {game_type_filter}
            GROUP BY player_id, team""",
        (season,),
    ):
        weeks: Set[int] = set()
        for token in (row["weeks"] or "").split(","):
            try:
                weeks.add(int(token))
            except (TypeError, ValueError):
                continue
        record = presence.setdefault(
            row["player_id"],
            {
                "weeks": set(),
                "log_team_counts": {},
                "log_team_max_week": {},
                "snap_team_counts": {},
                "snap_team_max_week": {},
            },
        )
        record["weeks"].update(weeks)
        if row["team"]:
            record["log_team_counts"][row["team"]] = len(weeks)
            record["log_team_max_week"][row["team"]] = max(weeks) if weeks else 0

    # Snap counts fill weeks where a player took the field without recording a
    # box-score touch. They must not change a logged mover's primary team.
    snap_columns = _pkg__table_columns(connection, "nfl_snap_counts")
    if {"player_id", "season", "week"}.issubset(snap_columns):
        snap_team = "team" if "team" in snap_columns else "NULL AS team"
        for row in connection.execute(
            f"""SELECT player_id, {snap_team}, GROUP_CONCAT(week) AS weeks
               FROM nfl_snap_counts
               WHERE season=? AND week < ?
               GROUP BY player_id, team""",
            (season, _POSTSEASON_FIRST_WEEK),
        ):
            weeks: Set[int] = set()
            for token in (row["weeks"] or "").split(","):
                try:
                    weeks.add(int(token))
                except (TypeError, ValueError):
                    continue
            record = presence.setdefault(
                row["player_id"],
                {
                    "weeks": set(),
                    "log_team_counts": {},
                    "log_team_max_week": {},
                    "snap_team_counts": {},
                    "snap_team_max_week": {},
                },
            )
            record["weeks"].update(weeks)
            if row["team"]:
                record["snap_team_counts"][row["team"]] = len(weeks)
                record["snap_team_max_week"][row["team"]] = max(weeks) if weeks else 0

    team_weeks: Dict[str, Set[int]] = defaultdict(set)
    sched_columns = _pkg__table_columns(connection, "nfl_schedule")
    has_schedule = {"home_team", "away_team", "week"}.issubset(sched_columns)
    if has_schedule:
        for row in connection.execute(
            """SELECT home_team AS team, week FROM nfl_schedule
               WHERE season=? AND week < ?
            UNION ALL
            SELECT away_team AS team, week FROM nfl_schedule
            WHERE season=? AND week < ?""",
            (season, _POSTSEASON_FIRST_WEEK, season, _POSTSEASON_FIRST_WEEK),
        ):
            try:
                team_weeks[row["team"]].add(int(row["week"]))
            except (TypeError, ValueError):
                continue
    else:
        for row in connection.execute(
            """SELECT team, CAST(game_no AS INTEGER) AS week
               FROM player_game_logs
               WHERE league='nfl' AND season=? AND team IS NOT NULL
                 AND CAST(game_no AS INTEGER) < ?
               GROUP BY team, game_no""",
            (season, _POSTSEASON_FIRST_WEEK),
        ):
            try:
                team_weeks[row["team"]].add(row["week"])
            except (TypeError, ValueError):
                continue

    out: Dict[int, dict] = {}
    for pid, record in presence.items():
        team_counts = record["log_team_counts"] or record["snap_team_counts"]
        team_max_week = (
            record["log_team_max_week"]
            if record["log_team_counts"]
            else record["snap_team_max_week"]
        )
        primary_team = (
            max(
                team_counts,
                key=lambda team: (
                    team_counts[team],
                    team_max_week.get(team, 0),
                    team,
                ),
            )
            if team_counts
            else None
        )
        out[pid] = {
            "games_played": len(record["weeks"]),
            "weeks": record["weeks"],
            "team_weeks": sorted(team_weeks.get(primary_team, set())),
            "team_games": (
                len(team_weeks.get(primary_team, set()))
                if has_schedule and team_weeks.get(primary_team)
                else _REG_SEASON_TEAM_GAMES
            ),
            "primary_team": primary_team,
        }

    return out

def _regular_season_aggregates(
    connection: sqlite3.Connection,
    season: int,
    availability: Optional[Dict[int, dict]] = None,
    player_ids: Optional[Sequence[int]] = None,
) -> Dict[int, dict]:
    """Return shared availability plus skill-position scoring aggregates.

    ``availability`` lets a caller that already built it pass it back in rather
    than pay for a second scan, matching _pk_aggregates. ``player_ids`` narrows
    the scan to a known set; it cannot change a result, because the aggregate
    groups by player, so the mock-draft pool restricts to its own 300 without
    forking the arithmetic -- which is the whole point of sharing this.
    """
    if availability is None:
        availability = _pkg__availability_aggregates(connection, season)
    game_type_filter = f"AND CAST(game_no AS INTEGER) < {_POSTSEASON_FIRST_WEEK}"
    if "game_type" in _pkg__table_columns(connection, "player_game_logs"):
        game_type_filter = "AND game_type='REG'"
    id_filter = ""
    id_params: Tuple = ()
    if player_ids is not None:
        id_filter = "AND player_id IN ({})".format(
            ",".join("?" for _ in player_ids)
        )
        id_params = tuple(player_ids)
    rows = connection.execute(
        f"""SELECT player_id,
                  SUM(CAST(json_extract(stats,'$.fpts_ppr')     AS REAL)) AS ppr_total,
                  AVG(CAST(json_extract(stats,'$.xfpts_ppr')    AS REAL)) AS xfp_per_game,
                  AVG(CAST(json_extract(stats,'$.off_pct')      AS REAL)) AS legacy_snap_pct,
                  -- A week with zero targets is a week the published file scores
                  -- 0.0, but ingest omits the key (see _RECV_KEYS in
                  -- ingest_nfl_weekly_stats), so a bare AVG drops it from the
                  -- denominator and reports a one-target cameo as a season rate.
                  -- The MAX guard keeps the other half of that distinction:
                  -- receiving is a season-level role, so a player who drew no
                  -- target all year stays NULL rather than averaging a real 0.0%.
                  -- legacy_snap_pct is used only when the published snap table is
                  -- unavailable. When present, nfl_snap_counts replaces it below.
                  CASE WHEN MAX(COALESCE(
                                   CAST(json_extract(stats,'$.target_share')
                                        AS REAL), 0)) > 0
                       THEN AVG(COALESCE(CAST(json_extract(stats,'$.target_share')
                                              AS REAL), 0))
                       END AS target_share
            FROM player_game_logs
            WHERE league='nfl' AND season=? AND player_id IS NOT NULL
              {game_type_filter}
              {id_filter}
            GROUP BY player_id""",
        (season, *id_params),
    ).fetchall()

    out: Dict[int, dict] = {}
    for row in rows:
        pid = row["player_id"]
        record = availability[pid]
        out[pid] = {
            **record,
            "ppr_total": row["ppr_total"],
            "xfp_per_game": row["xfp_per_game"],
            "snap_pct": row["legacy_snap_pct"],
            "target_share": row["target_share"],
        }

    for pid, record in availability.items():
        if pid not in out:
            out[pid] = {
                **record,
                "ppr_total": None,
                "xfp_per_game": None,
                "snap_pct": None,
                "target_share": None,
            }

    # off_pct is already published in nfl_snap_counts.  Reading that table
    # directly retains snap-only weeks that have no box-score row; averaging the
    # JSON enrichment inflated or erased the value for 284 players.  If the
    # published table exists it is authoritative, including an explicit miss:
    # do not fall back to the known-incomplete game-log subset.
    snap_columns = _pkg__table_columns(connection, "nfl_snap_counts")
    if {"player_id", "season", "week", "off_pct"}.issubset(snap_columns):
        for record in out.values():
            record["snap_pct"] = None
        snap_id_filter = ""
        snap_id_params: Tuple = ()
        if player_ids is not None:
            snap_id_filter = "AND player_id IN ({})".format(
                ",".join("?" for _ in player_ids)
            )
            snap_id_params = tuple(player_ids)
        for row in connection.execute(
            f"""SELECT player_id, ROUND(AVG(off_pct), 9) AS snap_pct
                FROM nfl_snap_counts
                WHERE season=? AND week < ? AND off_pct IS NOT NULL
                  {snap_id_filter}
                GROUP BY player_id""",
            (season, _POSTSEASON_FIRST_WEEK, *snap_id_params),
        ):
            if row["player_id"] in out:
                out[row["player_id"]]["snap_pct"] = row["snap_pct"]

    return out

def _pk_aggregates(
    connection: sqlite3.Connection,
    season: int,
    availability: Optional[Dict[int, dict]] = None,
) -> Dict[int, dict]:
    """Compute ESPN-standard kicker fantasy points from ingested bucket columns.

    Scoring: 0-39 yd FG = 3, 40-49 = 4, 50+ = 5, PAT = 1, missed FG = -1.
    Buckets are stored in the game-log JSON blobs from ingest_nfl_weekly_stats.
    """
    game_type_filter = f"AND CAST(game_no AS INTEGER) < {_POSTSEASON_FIRST_WEEK}"
    if "game_type" in _pkg__table_columns(connection, "player_game_logs"):
        game_type_filter = "AND game_type='REG'"

    rows = connection.execute(
        f"""SELECT player_id,
                  COUNT(*)                                   AS games_played,
                  SUM(
                    COALESCE(CAST(json_extract(stats,'$.fg_made_0_19') AS REAL),0) * 3 +
                    COALESCE(CAST(json_extract(stats,'$.fg_made_20_29') AS REAL),0) * 3 +
                    COALESCE(CAST(json_extract(stats,'$.fg_made_30_39') AS REAL),0) * 3 +
                    COALESCE(CAST(json_extract(stats,'$.fg_made_40_49') AS REAL),0) * 4 +
                    COALESCE(CAST(json_extract(stats,'$.fg_made_50_59') AS REAL),0) * 5 +
                    COALESCE(CAST(json_extract(stats,'$.fg_made_60_') AS REAL),0) * 5 +
                    COALESCE(CAST(json_extract(stats,'$.pat_made') AS REAL),0) * 1 -
                    COALESCE(CAST(json_extract(stats,'$.fg_missed') AS REAL),0) * 1
                  )                                            AS pk_pts_total,
                  GROUP_CONCAT(game_no)                          AS weeks
           FROM player_game_logs
           WHERE league='nfl' AND season=?
             AND json_extract(stats,'$.fg_att') IS NOT NULL
             {game_type_filter}
           GROUP BY player_id""",
        (season,),
    ).fetchall()

    out: Dict[int, dict] = {}
    for row in rows:
        weeks = set()
        for token in (row["weeks"] or "").split(","):
            try:
                weeks.add(int(token))
            except ValueError:
                continue
        presence = availability.get(row["player_id"]) if availability else None
        gp = presence["games_played"] if presence else row["games_played"] or 0
        total = row["pk_pts_total"]
        out[row["player_id"]] = {
            "games_played": gp,
            "pk_pts_total": total,
            "pk_pts_per_game": round(total / gp, 1) if total and gp else None,
            "weeks": weeks,
        }
    return out

def _dst_aggregates(connection: sqlite3.Connection, season: int) -> Tuple[Dict[int, dict], Dict[str, list]]:
    """One pass over nfl_dst_stats for the reference season.

    Returns (per-player aggregates, per-team week lists).
    """
    columns = _pkg__table_columns(connection, "nfl_dst_stats")
    required = {"player_id", "season", "week", "fantasy_pts"}
    if not required.issubset(columns):
        return {}, {}

    rows = connection.execute(
        """SELECT player_id,
                  COUNT(*)                                   AS games_played,
                  SUM(fantasy_pts)                            AS dst_total,
                  AVG(fantasy_pts)                            AS dst_avg,
                  GROUP_CONCAT(week)                          AS weeks
           FROM nfl_dst_stats
           WHERE season=?
           GROUP BY player_id""",
        (season,),
    ).fetchall()

    # Which weeks each team actually played — same logic as _regular_season_aggregates.
    # Use a set (not a list) to deduplicate: each team appears twice per week
    # in the UNION ALL (home + away), so a list would hold 34 entries per team.
    schedule_team_weeks: Dict[str, Set[int]] = defaultdict(set)
    for row in connection.execute(
        """SELECT home_team AS team, week FROM nfl_schedule
           WHERE season=? AND week < ?
        UNION ALL
        SELECT away_team AS team, week FROM nfl_schedule
        WHERE season=? AND week < ?""",
        (season, _POSTSEASON_FIRST_WEEK, season, _POSTSEASON_FIRST_WEEK),
    ):
        try:
            schedule_team_weeks[row["team"]].add(int(row["week"]))
        except (TypeError, ValueError):
            continue

    # Build a sorted-list version for the return value (used by the board for
    # team_weeks output field).  Per-player aggregates carry their own resolved
    # team_weeks so the board doesn't need to re-resolve by current_team.
    dst_team_weeks: Dict[str, list] = {
        team: sorted(weeks) for team, weeks in schedule_team_weeks.items()
    }

    out: Dict[int, dict] = {}
    for row in rows:
        weeks = set()
        for token in (row["weeks"] or "").split(","):
            try:
                weeks.add(int(token))
            except ValueError:
                continue
        # For a D/ST player, the "primary team" is the team the defense
        # belongs to — resolvable from the players table in the board, but
        # we store it here so the board can scope team_games correctly.
        pid = row["player_id"]
        out[pid] = {
            "games_played": row["games_played"] or 0,
            "dst_total": row["dst_total"],
            "dst_avg": row["dst_avg"],
            "weeks": weeks,
            "team_weeks": [],  # resolved per-player in the board
        }
    return out, dst_team_weeks
