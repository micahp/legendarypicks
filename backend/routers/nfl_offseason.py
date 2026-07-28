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

from team_codes import CANONICAL_POSITIONS, normalize, normalize_optional


router = APIRouter()

_CONTEXT_CONTRACT = "nfl-season-context-v1"
_DRAFT_BOARD_CONTRACT = "nfl-draft-board-v2"
_CURRENT_SEASON = 2026

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

# ESPN parks undrafted players at a sentinel: 1,392 of 2,511 ADP rows sit at
# exactly 170.0. Only 248 players carry a real ADP, so anything at or past this
# is "not actually ranked" and must not be shown as though it were.
_ADP_SENTINEL = 169.0

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
_POSITION_FILTERS = CANONICAL_POSITIONS.get("nfl", set()) | {"FLEX"}
# Sort key -> (player field, ascending). Every one of these is a measurement of
# something that happened; none is a projection, and none is labelled as one.
_SORT_FIELDS = {
    "adp": ("adp", True),
    "ppr_per_team_game": ("ppr_per_team_game", False),
    "ppr_per_game_played": ("ppr_per_game_played", False),
    "xfp_per_game": ("xfp_per_game", False),
    "games_played": ("games_played", False),
    "snap_pct": ("snap_pct", False),
    "target_share": ("target_share", False),
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


def _regular_season_aggregates(connection: sqlite3.Connection, season: int) -> Dict[int, dict]:
    """One pass over the reference season's per-game rows.

    Returns per player: games played, total PPR, mean expected PPR, mean snap
    share, mean target share, and the set of weeks they appeared in (the strip).

    Postseason weeks are excluded -- see ``_POSTSEASON_FIRST_WEEK``. Missed games
    contribute nothing here by construction; that absence IS the measurement.
    """
    rows = connection.execute(
        """SELECT player_id,
                  COUNT(DISTINCT game_id)                                   AS games_played,
                  SUM(CAST(json_extract(stats,'$.fpts_ppr')     AS REAL))    AS ppr_total,
                  AVG(CAST(json_extract(stats,'$.xfpts_ppr')    AS REAL))    AS xfp_per_game,
                  AVG(CAST(json_extract(stats,'$.off_pct')      AS REAL))    AS snap_pct,
                  AVG(CAST(json_extract(stats,'$.target_share') AS REAL))    AS target_share,
                  GROUP_CONCAT(game_no)                                      AS weeks,
                  (SELECT team FROM player_game_logs inner_logs
                    WHERE inner_logs.player_id = player_game_logs.player_id
                      AND inner_logs.league='nfl' AND inner_logs.season=?
                      AND CAST(inner_logs.game_no AS INTEGER) < ?
                    GROUP BY team ORDER BY COUNT(*) DESC LIMIT 1)             AS primary_team
           FROM player_game_logs
           WHERE league='nfl' AND season=? AND player_id IS NOT NULL
             AND CAST(game_no AS INTEGER) < ?
           GROUP BY player_id""",
        (season, _POSTSEASON_FIRST_WEEK, season, _POSTSEASON_FIRST_WEEK),
    ).fetchall()

    # Which weeks each team actually played, from the published schedule.
    # After the vocabulary migration the logs speak ESPN, so the schedule join
    # works and the derivation from player_game_logs is no longer necessary.
    team_weeks: Dict[str, Set[int]] = defaultdict(set)
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

    out: Dict[int, dict] = {}
    for row in rows:
        weeks = set()
        for token in (row["weeks"] or "").split(","):
            try:
                weeks.add(int(token))
            except ValueError:
                continue
        games = row["games_played"] or 0
        total = row["ppr_total"]
        # A mid-season mover has logs under two teams. Use the one he appeared
        # for most; the games-played count is unaffected either way, and only
        # the bye slot could differ between the two schedules.
        primary_team = row["primary_team"]
        out[row["player_id"]] = {
            "games_played": games,
            "ppr_total": total,
            "xfp_per_game": row["xfp_per_game"],
            "snap_pct": row["snap_pct"],
            "target_share": row["target_share"],
            "weeks": weeks,
            "team_weeks": sorted(team_weeks.get(primary_team, set())),
        }
    return out


def _round(value, places=1):
    return None if value is None else round(value, places)


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
    sort: str = Query("adp"),
    q: Optional[str] = Query(None, description="name search; every token must appear"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Availability-first 2026 draft board.

    The headline is how often a player was on the field, not how well he did on
    the days he was. Both numbers ship together: PPR per game *played* is what
    every fantasy site shows, PPR per *team game* is what the roster spot
    actually returned. They diverge exactly when availability drops -- Joe Burrow
    2025 reads 16.8 and 7.9 off the same season.

    Nothing here is a projection and nothing is labelled as one.
    """
    selected_position = str(position or "").strip().upper() or None
    if selected_position is not None and selected_position not in _POSITION_FILTERS:
        raise HTTPException(400, f"position must be one of {sorted(_POSITION_FILTERS)}")
    if sort not in _SORT_FIELDS:
        raise HTTPException(400, f"sort must be one of {sorted(_SORT_FIELDS)}")
    sort_field, sort_ascending = _SORT_FIELDS[sort]
    search, search_tokens = _name_search(q)

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

        position_expr = "UPPER(COALESCE(NULLIF(p.position,''), ''))"
        where = ["p.league='nfl'", "p.active=1"]
        params: list = []
        if selected_position == "FLEX":
            where.append(f"{position_expr} IN ('RB','WR','TE')")
        elif selected_position:
            where.append(f"{position_expr}=?")
            params.append(selected_position)
        else:
            # No position filter — show all positions. (Previously restricted to
            # _SKILL_POSITIONS; expanded 2026-07-27 when kicker/IDP data landed.)
            pass

        # Narrow in SQL rather than after: the page a drafter searching for one
        # player gets back should be one player, not 522 rows filtered in the
        # browser.
        for token in search_tokens:
            where.append(r"p.name LIKE ? ESCAPE '\'")
            params.append(f"%{token}%")

        where_sql = " AND ".join(where)

        candidates = connection.execute(
            f"""SELECT p.id AS player_id, p.name, {position_expr} AS position,
                       p.team AS current_team,
                       na.adp, na.percent_owned,
                       d.pos_rank AS depth_rank, d.team AS depth_team
                FROM players p
                LEFT JOIN nfl_adp na
                       ON na.player_id=p.id AND na.season=?
                LEFT JOIN nfl_depth_chart d
                       ON d.player_id=p.id AND d.season=?
                WHERE {where_sql}""",
            [_CURRENT_SEASON, _CURRENT_SEASON, *params],
        ).fetchall()

    roster_is_current = roster_freshness["status"] == "current"
    players = []
    for row in candidates:
        pid = row["player_id"]
        agg = aggregates.get(pid)
        adp = row["adp"]
        ranked_adp = adp if (adp is not None and adp < _ADP_SENTINEL) else None

        # Eligible if we have something true to say: a real season, or a real
        # market price. A rookie with neither is not on the board at all --
        # better absent than present with a fabricated zero.
        if agg is None and ranked_adp is None:
            continue

        games_played = agg["games_played"] if agg else 0
        ppr_total = (agg["ppr_total"] if agg else None) or None
        if agg is None:
            sample = "none"
        elif games_played < _THIN_SAMPLE_GAMES:
            sample = "thin"
        else:
            sample = "full"

        players.append({
            "player_id": pid,
            "name": row["name"],
            "position": row["position"],
            "current_team": normalize("nfl", row["current_team"]),
            # Current role, from the published depth chart. This is what a rookie
            # has instead of a season.
            "depth_rank": row["depth_rank"],
            "depth_team": normalize_optional("nfl", row["depth_team"]) if row["depth_team"] else None,
            "adp": ranked_adp,
            "adp_is_ranked": ranked_adp is not None,
            "percent_owned": row["percent_owned"],
            # Availability: the headline. Denominator is every game the team
            # played, so a missed game costs the drafter exactly what it cost.
            "games_played": games_played,
            "team_games": _REG_SEASON_TEAM_GAMES,
            "weeks_played": sorted(agg["weeks"]) if agg else [],
            # The 17 weeks his team actually played, so the strip can show a bye
            # as a bye rather than as an absence.
            "team_weeks": agg["team_weeks"] if agg else [],
            # Both averages, always together.
            "ppr_per_game_played": _round(ppr_total / games_played) if ppr_total and games_played else None,
            "ppr_per_team_game": _round(ppr_total / _REG_SEASON_TEAM_GAMES) if ppr_total else None,
            "xfp_per_game": _round(agg["xfp_per_game"]) if agg else None,
            "snap_pct": _round(agg["snap_pct"] * 100, 0) if agg and agg["snap_pct"] is not None else None,
            "target_share": _round(agg["target_share"] * 100, 1) if agg and agg["target_share"] is not None else None,
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

    return {
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
