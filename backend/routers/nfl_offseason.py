"""NFL offseason and training-camp landing contracts.

These endpoints compose the data Legendary Picks already owns. They do not
call ESPN or nflverse on the request path. Calendar milestones are sourced
from the NFL's published 2026 calendar and must be refreshed for a new league
year before the contract can claim a current phase.
"""
import datetime as dt
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


router = APIRouter()

_CONTEXT_CONTRACT = "nfl-season-context-v1"
_DRAFT_BOARD_CONTRACT = "nfl-draft-board-v2"
_CURRENT_SEASON = 2026

# Draft board cache — the draft board only changes when nfl_adp, projections,
# or depth chart are re-ingested (daily timers), so a 5-min TTL is safe.
_DRAFT_BOARD_CACHE_TTL = 300
_draft_board_cache: dict = {"ts": 0.0, "payload": None}
_draft_board_cache_lock = threading.Lock()

# Availability's denominator is a constant, not a join. Verified on picks.dev.db:
# in each of 2024 and 2025, all 32 teams played exactly 17 regular-season games,
# across an 18-week schedule with one bye. Deriving it from team_game_results
# instead would drag in ROADMAP B1/B2/B3 (Joe Flacco read 13/34 because a
# mid-season team change summed both teams' seasons) for no gain.
_REG_SEASON_TEAM_GAMES = 17
_REG_SEASON_LAST_WEEK = 18

# Weeks 19-22 are the postseason. Counting them would let a deep playoff run
# report 21/17 games played.
_POSTSEASON_FIRST_WEEK = 19

# Below this, a per-game average is one or two games. xFP predicts better than
# actual points here (r=0.42 vs 0.37 over 2024->2025) but neither is reliable,
# so the surface must mark the sample rather than quietly rank on it.
_THIN_SAMPLE_GAMES = 4
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

_SKILL_POSITIONS = ("QB", "RB", "WR", "TE", "FB")
_DEF_POSITION = "DEF"
_FANTASY_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK", "DEF")
_POSITION_FILTERS = set(_FANTASY_DRAFT_POSITIONS) | {"FLEX"}
# Sort key -> (player field, ascending). Rank and projection come from the
# explicit 2026 ESPN fantasy contract; every missing value remains null and
# sorts after published values.
_SORT_FIELDS = {
    "rank": ("espn_ppr_rank", True),
    "proj": ("proj_ppr_points", False),
    "adp": ("adp", True),
    "ppr_per_team_game": ("ppr_per_team_game", False),
    "ppr_per_game_played": ("ppr_per_game_played", False),
    "xfp_per_game": ("xfp_per_game", False),
    "games_played": ("games_played", False),
    "snap_pct": ("snap_pct", False),
    "target_share": ("target_share", False),
    "dst_pts_per_game": ("dst_pts_per_game", False),
    "pk_pts_per_game": ("pk_pts_per_game", False),
}
# Name search. Bounded so a pathological query cannot turn one request into an
# unbounded pile of LIKE scans.
_SEARCH_MAX_LEN = 64
_SEARCH_MAX_TOKENS = 5


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
    """v2 reads per-game logs, not the season rollup in player_stats.

    The rollup's ``fantasy_ppr_g`` is points per game *played* -- an average
    conditioned on the player being healthy enough to play, which is the exact
    thing a drafter is trying to predict. Availability is only recoverable from
    the per-game rows, because a missed game has no row at all.
    """
    player_columns = _table_columns(connection, "players")
    log_columns = _table_columns(connection, "player_game_logs")
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
    if "game_type" in _table_columns(connection, "player_game_logs"):
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
    snap_columns = _table_columns(connection, "nfl_snap_counts")
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
    sched_columns = _table_columns(connection, "nfl_schedule")
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
        availability = _availability_aggregates(connection, season)
    game_type_filter = f"AND CAST(game_no AS INTEGER) < {_POSTSEASON_FIRST_WEEK}"
    if "game_type" in _table_columns(connection, "player_game_logs"):
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
    snap_columns = _table_columns(connection, "nfl_snap_counts")
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
    if "game_type" in _table_columns(connection, "player_game_logs"):
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
    columns = _table_columns(connection, "nfl_dst_stats")
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

    # Check cache (key includes all query params)
    cache_key = f"{selected_position}|{sort}|{q}|{limit}|{offset}"
    now = time.time()
    with _draft_board_cache_lock:
        if now - _draft_board_cache["ts"] < _DRAFT_BOARD_CACHE_TTL and _draft_board_cache["payload"] is not None:
            cached = _draft_board_cache["payload"]
            if cached.get("cache_key") == cache_key:
                return cached["response"]

    with closing(_db()) as connection:
        connection.row_factory = sqlite3.Row
        _draft_board_schema(connection)

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
        roster_freshness = _roster_freshness(_today(), roster_verified_at)

        aggregates = _regular_season_aggregates(connection, season)
        dst_aggregates, dst_team_weeks = _dst_aggregates(connection, season)
        pk_aggregates = _pk_aggregates(connection, season, aggregates)

        position_expr = "UPPER(COALESCE(NULLIF(p.position,''), ''))"
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
            if "injury_status" in _table_columns(connection, "players")
            else ", NULL AS injury_status"
        )
        adp_columns = _table_columns(connection, "nfl_adp")
        rank_select = (
            ", na.espn_ppr_rank"
            if "espn_ppr_rank" in adp_columns
            else ", NULL AS espn_ppr_rank"
        )
        projection_columns = _table_columns(connection, "nfl_player_projections")
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
        schedule_columns = _table_columns(connection, "nfl_schedule")
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

    # Update cache
    with _draft_board_cache_lock:
        _draft_board_cache["ts"] = time.time()
        _draft_board_cache["payload"] = {
            "cache_key": cache_key,
            "response": response,
        }

    return response
