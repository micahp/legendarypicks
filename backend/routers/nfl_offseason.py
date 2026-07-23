"""NFL offseason and training-camp landing contracts.

These endpoints compose the data Legendary Picks already owns. They do not
call ESPN or nflverse on the request path. Calendar milestones are sourced
from the NFL's published 2026 calendar and must be refreshed for a new league
year before the contract can claim a current phase.
"""
import datetime as dt
import json
import re
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Query

from _core import _db, _normalize_name, proj_mod


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
    "adp": "na.adp",
    "season_proj_pts": None,  # computed in Python from player_game_logs
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

# ESPN's transaction text always prefixes a player mention with their position
# abbreviation ("WR A.J. Brown", "DE Myles Garrett") — reliable enough to pull
# player names out of free text without a real NLP pass.
_POSITION_PREFIX = re.compile(
    r"\b(?:QB|RB|WR|TE|FB|OL|OT|OG|C|DL|DE|DT|EDGE|LB|CB|S|FS|SS|K|P|LS|NT|DB)\s+"
    r"([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})"
)
# Negative lookbehind excludes splitting after a single-capital-letter initial
# ("A.J.", "T.J.") — those periods aren't sentence ends, just part of a name.
_SENTENCE_SPLIT = re.compile(r"(?<![A-Z]\.)(?<=[.!?])\s+(?=[A-Z])")
# A bare trailing period is sentence punctuation, not part of the name — unless
# the name itself legitimately ends in a single-letter initial ("A.J.").
_TRAILING_INITIAL = re.compile(r"\b[A-Z]\.$")


# players/nfl_adp only change via the daily ingest timers now (see
# docs/DATA-FRESHNESS-SPLIT-2026-07-23.md) — no reason to rebuild these two
# full-table dicts (~9.6k players + ~2.5k ADP rows) on every single request.
_SIGNIFICANCE_CACHE_TTL = 300
_significance_cache: Dict[str, object] = {"ts": 0.0, "name_to_pid": None, "pid_to_adp": None}


def _player_significance_lookup(connection: sqlite3.Connection):
    """name -> ADP, as a proxy for "how significant is this player" — lower ADP
    is more significant/valuable. Missing/unresolved names return None (treated
    as least significant, so a real ADP always wins the mirror tie-break)."""
    now = time.time()
    if now - _significance_cache["ts"] < _SIGNIFICANCE_CACHE_TTL and _significance_cache["name_to_pid"] is not None:
        name_to_pid: Dict[str, int] = _significance_cache["name_to_pid"]
        pid_to_adp: Dict[int, float] = _significance_cache["pid_to_adp"]
    else:
        name_to_pid = {}
        for r in connection.execute("SELECT id, name FROM players WHERE league='nfl'"):
            name_to_pid[_normalize_name(r["name"])] = r["id"]
        pid_to_adp = {}
        try:
            for r in connection.execute(
                "SELECT player_id, adp FROM nfl_adp WHERE season=? AND adp IS NOT NULL",
                (_CURRENT_SEASON,),
            ):
                pid_to_adp[r["player_id"]] = r["adp"]
        except sqlite3.OperationalError:
            pass  # nfl_adp not populated yet — significance lookup degrades to "unknown" for everyone
        _significance_cache["ts"] = now
        _significance_cache["name_to_pid"] = name_to_pid
        _significance_cache["pid_to_adp"] = pid_to_adp

    def significance(name: str) -> Optional[float]:
        pid = name_to_pid.get(_normalize_name(name))
        return pid_to_adp.get(pid) if pid is not None else None

    return significance


def _outgoing_player(sentence: str, players: List[str]) -> Optional[str]:
    """Which named player is THIS team's own outgoing asset, not the return
    they got back. ESPN's standard phrasing is "Traded [outgoing] to [team]
    for [incoming]" — a player named before " for " is outgoing; one named
    only after " for " (e.g. this team gave up picks only, got a named player
    back — "Traded a 1st... to Miami for WR Jaylen Waddle") is incoming, and
    must NOT be mistaken for this team's own significant piece."""
    if not players:
        return None
    m = re.search(r"\bfor\b", sentence)
    if not m:
        return players[0]  # no "for" clause (e.g. "Traded QB X to Kansas City.") — best effort
    before_for = sentence[: m.start()]
    before_names = _POSITION_PREFIX.findall(before_for)
    return before_names[0] if before_names else None  # gave up picks only, no named outgoing player


def _split_trade_sentences(description: str) -> List[Tuple[str, List[str], Optional[str]]]:
    """A logged transaction can bundle unrelated moves in one blob ("Signed X.
    Released Y. Traded Z..."). Split into sentences, keep only the trade ones,
    and pull out the player name(s) mentioned in each for bolding client-side,
    plus which one (if any) is THIS team's own outgoing player."""
    out = []
    for sentence in _SENTENCE_SPLIT.split(description.strip()):
        sentence = sentence.strip()
        if not sentence or "trad" not in sentence.lower():
            continue
        players = [
            p if _TRAILING_INITIAL.search(p) else p.rstrip(".")
            for p in _POSITION_PREFIX.findall(sentence)
        ]
        out.append((sentence, players, _outgoing_player(sentence, players)))
    return out


def _dedupe_trade_rows(connection: sqlite3.Connection, rows: list, limit: int) -> List[dict]:
    """Split raw transaction rows into individual trade sentences (dropping any
    bundled non-trade sentences), dedupe mirror entries — ESPN logs one row per
    team in a deal, so the same trade otherwise appears once per side — and
    return the most recent `limit` distinct trades.

    Mirror entries are grouped by the set of player names mentioned (reliable;
    team names in free text are often ambiguous, e.g. "Los Angeles" alone
    doesn't say Rams vs Chargers). Within a group, keep the entry for the team
    that gave up the more significant player (ADP as the significance proxy,
    lower = more significant) — that's "the from team" for a headline trade.
    If ADP can't disambiguate (tie, or neither player resolves), it doesn't
    matter which side is kept, so fall back to team abbreviation for a stable,
    deterministic pick."""
    significance = _player_significance_lookup(connection)
    groups: Dict[frozenset, list] = defaultdict(list)
    for r in rows:
        for sentence, players, from_player in _split_trade_sentences(r["description"]):
            key = frozenset(p.lower() for p in players) if players else frozenset({sentence.lower()})
            groups[key].append({
                "date": r["txn_date"],
                "team": r["team_abbr"],
                "teamName": r["team_name"],
                "description": sentence,
                "players": players,
                "_from_player": from_player,
            })

    def sort_key(e: dict) -> tuple:
        sig = significance(e["_from_player"]) if e["_from_player"] else None
        return (sig if sig is not None else float("inf"), e["team"])

    deduped = [min(events, key=sort_key) for events in groups.values()]
    deduped.sort(key=lambda e: e["date"], reverse=True)
    for e in deduped:
        del e["_from_player"]  # internal only, not part of the API contract
    return deduped[:limit]


@router.get("/api/nfl/transactions")
def nfl_transactions(
    limit: int = Query(30, ge=1, le=100),
    team: Optional[str] = Query(None, description="team abbreviation, e.g. ATL"),
    trades_only: bool = Query(False, description="only transactions whose description mentions a trade"),
):
    """Recent NFL roster moves (waives, signings, IR, releases, retirements) —
    ingested from ESPN's public transactions feed by nfl_transactions_sync.py.
    "Offseason Movers" card content; see docs on why this replaced the raw
    season-milestone timeline (it's actual news, not a static calendar).

    trades_only: no dedicated "type" field exists in ESPN's feed (free text
    only). Each bundled description is split into individual trade sentences
    (a signing/release bundled in the same blob is dropped), and mirror
    entries — ESPN logs one row per team in a deal, so the same trade
    otherwise appears twice — are deduped by the set of player names
    mentioned (reliable; team names in the text are often ambiguous, e.g.
    "Los Angeles" alone doesn't say Rams vs Chargers). Within a duplicate
    pair, keep the entry for the team that gave up the more significant
    player — ADP (nfl_adp) as the significance proxy, lower = more
    significant — since that's "the from team" for a headline trade; if
    ADP can't disambiguate (tie, or neither player resolves), it doesn't
    matter which side is kept, so fall back to team abbreviation for a
    stable, deterministic pick."""
    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        columns = _table_columns(connection, "nfl_transactions")
        if not columns:
            return {"contract": _TRANSACTIONS_CONTRACT, "transactions": [], "count": 0}
        conditions = []
        params: list = []
        if team:
            conditions.append("team_abbr=?")
            params.append(team.upper())
        if trades_only:
            conditions.append("description LIKE '%trad%'")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        # Trade sentences get split out of bundled rows and deduped, so pull a
        # wider raw window than `limit` — the final trade-event count is smaller
        # than the raw row count once bundling/mirroring collapse.
        raw_limit = limit * 6 if trades_only else limit
        rows = connection.execute(
            f"""SELECT txn_date, team_id, team_abbr, team_name, description
                FROM nfl_transactions {where}
                ORDER BY txn_date DESC, id DESC LIMIT ?""",
            (*params, raw_limit),
        ).fetchall()

        if not trades_only:
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

        deduped = _dedupe_trade_rows(connection, rows, limit)
        return {
            "contract": _TRANSACTIONS_CONTRACT,
            "count": len(deduped),
            "transactions": deduped,
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


def _compute_season_projections(
    connection: sqlite3.Connection, player_ids: List[int]
) -> Dict[int, dict]:
    """Batch-compute season_proj_pts + games_assumed for a set of players.

    Returns a dict keyed by player_id, each value is
    ``{"season_proj_pts": float | None, "games_assumed": int | None}``.
    """
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = connection.execute(
        f"""SELECT player_id, stats, season, game_date, game_no
            FROM player_game_logs
            WHERE league='nfl' AND player_id IN ({placeholders})
            ORDER BY player_id, season DESC, COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC""",
        player_ids,
    ).fetchall()

    # Group logs by player, keeping most-recent-first order
    player_logs: Dict[int, list] = defaultdict(list)
    for r in rows:
        player_logs[r["player_id"]].append(r)

    result: Dict[int, dict] = {}
    for pid, logs in player_logs.items():
        fpts_vals: List[float] = []
        season_games: Dict[int, int] = defaultdict(int)
        for log in logs:
            try:
                s = json.loads(log["stats"])
                # 2025 pbp ingest uses the canonical short key; 2024 nflverse-weekly
                # ingest uses the legacy long key (see _NFL_KEY_NORMALIZE in players.py)
                # — check both or every 2025 game silently drops out of the projection.
                val = s.get("fpts_ppr", s.get("fantasy_points_ppr"))
                if val is not None:
                    fpts_vals.append(float(val))
                    season_games[log["season"]] += 1
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        proj = proj_mod.project_stat(fpts_vals, min_games=3)
        games_assumed: Optional[int] = None
        season_proj_pts: Optional[float] = None

        if season_games:
            latest = max(season_games.keys())
            ga = season_games[latest]
            if ga > 0:
                games_assumed = min(ga, 17)
                if proj and games_assumed:
                    season_proj_pts = round(proj["projection"] * games_assumed, 1)

        result[pid] = {
            "season_proj_pts": season_proj_pts,
            "games_assumed": games_assumed,
        }

    return result


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

    # season_proj_pts is computed in Python; use fantasy_ppr_g for the SQL
    # WHERE filter (ensures we only include players with stats to project from).
    season_proj_sort = sort == "season_proj_pts"
    sql_sort = "fantasy_ppr_g" if season_proj_sort else sort
    sort_field = _SORT_FIELDS[sql_sort]

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
            f"{sort_field} IS NOT NULL",
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
        join_sql = "LEFT JOIN nfl_adp na ON na.player_id=p.id AND na.season=?"

        if season_proj_sort:
            # ── season_proj_pts sort: compute projections for ALL eligible,
            #    sort in Python, then fetch player details for the slice ──
            id_rows = connection.execute(
                f"""SELECT p.id AS player_id
                    FROM players p
                    JOIN player_stats ps ON ps.player_id=p.id
                    {join_sql}
                    WHERE {where_sql}""",
                [_CURRENT_SEASON, *params],
            ).fetchall()
            all_ids = [r["player_id"] for r in id_rows]
            eligible = len(all_ids)

            # Compute projections for the full eligible population
            proj_map = _compute_season_projections(connection, all_ids)

            # Sort eligible IDs by season_proj_pts DESC, then by games DESC, then name
            def _sort_key(pid: int) -> tuple:
                p = proj_map.get(pid, {})
                pts = p.get("season_proj_pts")
                return (0 if pts is not None else 1, -(pts or 0))

            all_ids.sort(key=_sort_key)
            page_ids = all_ids[offset : offset + limit]

            if not page_ids:
                rows = []
            else:
                id_placeholders = ",".join("?" for _ in page_ids)
                order_clause = f"fantasy_ppr_g DESC"
                rows = connection.execute(
                    f"""SELECT p.id AS player_id, p.name, {position_expr} AS position,
                               p.team AS current_team, COALESCE(NULLIF(ps.nfl_team,''), ps.team) AS reference_team,
                               ps.games, ps.fantasy_ppr_g, ps.fantasy_pts_g,
                               ps.pass_yds_g, ps.rush_yds_g, ps.rec_yds_g,
                               ps.targets, ps.receptions, ps.carries_g,
                               na.adp, na.percent_owned
                        FROM players p
                        JOIN player_stats ps ON ps.player_id=p.id
                        {join_sql}
                        WHERE p.id IN ({id_placeholders})
                        ORDER BY {order_clause}, ps.games DESC, p.name COLLATE NOCASE""",
                    [_CURRENT_SEASON, *page_ids],
                ).fetchall()
                # Reorder rows to match page_ids order
                row_by_id = {r["player_id"]: r for r in rows}
                rows = [row_by_id[pid] for pid in page_ids if pid in row_by_id]
        else:
            # ── normal sort: SQL ordering, compute projections for returned 50 ──
            eligible = connection.execute(
                f"""SELECT COUNT(*) FROM players p
                    JOIN player_stats ps ON ps.player_id=p.id
                    {join_sql}
                    WHERE {where_sql}""",
                [_CURRENT_SEASON, *params],
            ).fetchone()[0]
            order_clause = f"{sort_field} ASC" if sql_sort == "adp" else f"{sort_field} DESC"
            nulls = "NULLS LAST" if sql_sort == "adp" else ""
            rows = connection.execute(
                f"""SELECT p.id AS player_id, p.name, {position_expr} AS position,
                           p.team AS current_team, COALESCE(NULLIF(ps.nfl_team,''), ps.team) AS reference_team,
                           ps.games, ps.fantasy_ppr_g, ps.fantasy_pts_g,
                           ps.pass_yds_g, ps.rush_yds_g, ps.rec_yds_g,
                           ps.targets, ps.receptions, ps.carries_g,
                           na.adp, na.percent_owned
                    FROM players p
                    JOIN player_stats ps ON ps.player_id=p.id
                    {join_sql}
                    WHERE {where_sql}
                    ORDER BY {order_clause} {nulls}, ps.games DESC, p.name COLLATE NOCASE
                    LIMIT ? OFFSET ?""",
                [_CURRENT_SEASON, *params, limit, offset],
            ).fetchall()

            # Compute projections for just the returned players
            proj_map = _compute_season_projections(
                connection, [r["player_id"] for r in rows]
            )

    roster_is_current = roster_freshness["status"] == "current"
    players = []
    for index, row in enumerate(rows):
        current_team = _normalize_team(row["current_team"])
        reference_team = _normalize_team(row["reference_team"])
        team_changed = None
        if roster_is_current and current_team and reference_team:
            team_changed = current_team != reference_team
        pid = row["player_id"]
        proj = proj_map.get(pid, {})
        players.append({
            "rank": offset + index + 1,
            "player_id": pid,
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
            "adp": row["adp"],
            "percent_owned": row["percent_owned"],
            "season_proj_pts": proj.get("season_proj_pts"),
            "games_assumed": proj.get("games_assumed"),
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
