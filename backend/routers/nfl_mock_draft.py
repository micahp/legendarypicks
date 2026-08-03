from __future__ import annotations

"""NFL mock draft — pool endpoint + draft CRUD for single-player mock drafts vs. ADP bots.

SPEC-slice-D-mock-draft.md:
  - Pool: GET /api/nfl/mock-draft/pool?season=2026 — the full ESPN player
    universe (~11,515: QB/RB/WR/TE/PK/DEF + IDP + free agents) with copied
    published ADP / PPR ranks. Draftable filtering is the UI's job.
  - Draft CRUD: create, append picks, resume, list — keyed by X-Device-Id.
  - Own _DB from LP_DB_PATH (no _core.py dependency).
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from nfl_rankings import (
    NFL_RANK_STATS,
    nfl_player_rank_context,
    nfl_player_stat_ranks_batch,
)
from ppr_scoring import STAT_IDS, normalize_stats

from .nfl_offseason import (
    _availability_aggregates,
    _database_cache_token,
    _dst_aggregates,
    _pk_aggregates,
    _percentage,
    _round,
    _rounded_ratio,
    _regular_season_aggregates,
    _table_columns,
)

# ---------------------------------------------------------------------------
#  Module-level DB path — mirrors ufc_picks.py / nfl_draft_notes.py
# ---------------------------------------------------------------------------

_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)

_CONTRACT = "nfl-mock-draft-v1"
_CURRENT_SEASON = 2026
_REG_SEASON_TEAM_GAMES = 17
_POSTSEASON_FIRST_WEEK = 19
_THIN_SAMPLE_GAMES = 4
_POOL_CACHE_TTL = 300
_POOL_CACHE_MAX_ENTRIES = 4
_pool_cache: dict = {}
_pool_cache_lock = threading.Lock()


def _pool_cache_get(key):
    if key is None:
        return None
    now = time.monotonic()
    with _pool_cache_lock:
        entry = _pool_cache.get(key)
        if entry is None:
            return None
        created_at, body = entry
        if now - created_at >= _POOL_CACHE_TTL:
            del _pool_cache[key]
            return None
        del _pool_cache[key]
        _pool_cache[key] = (created_at, body)
        return body


def _pool_cache_put(key, body):
    if key is None:
        return
    with _pool_cache_lock:
        _pool_cache.pop(key, None)
        _pool_cache[key] = (time.monotonic(), bytes(body))
        while len(_pool_cache) > _POOL_CACHE_MAX_ENTRIES:
            oldest = next(iter(_pool_cache))
            del _pool_cache[oldest]


def _clear_pool_cache():
    with _pool_cache_lock:
        _pool_cache.clear()


def _named_stat_line(raw_json, *, include_actual_first_downs=False):
    """Normalize a stored ESPN stat map into the overlay's stable vocabulary."""
    if not raw_json:
        return None
    try:
        stats = normalize_stats(json.loads(raw_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not stats:
        return None
    get = lambda key: stats.get(STAT_IDS[key])
    completion_pct = get("completion_pct")
    if completion_pct is not None and abs(completion_pct) <= 1:
        completion_pct *= 100
    return {
        "games": get("games"),
        "pass_att": get("pass_att"),
        "pass_cmp": get("pass_cmp"),
        "pass_yds": get("pass_yds"),
        "pass_td": get("pass_td"),
        "interceptions": get("interceptions"),
        "completion_pct": completion_pct,
        "sacks": get("sacks"),
        "rush_att": get("rush_att"),
        "rush_yds": get("rush_yds"),
        "rush_td": get("rush_td"),
        "receptions": get("receptions"),
        "targets": get("targets"),
        "rec_yds": get("rec_yds"),
        "rec_td": get("rec_td"),
        "fumbles": get("fumbles"),
        "fumbles_lost": get("fumbles_lost"),
        # ESPN's prior-season total map uses these measured IDs. Its fantasy
        # projection map shifts the extension IDs for some positions, so the
        # projection contract stays honestly null until that schema is
        # independently named and validated.
        "passing_first_downs": (
            get("passing_first_downs") if include_actual_first_downs else None
        ),
        "rushing_first_downs": (
            get("rushing_first_downs") if include_actual_first_downs else None
        ),
        "receiving_first_downs": (
            get("receiving_first_downs") if include_actual_first_downs else None
        ),
        "qbr": None,
        "passer_rating": None,
        "adj_qbr": None,
        "fg_att": get("fg_att"),
        "fg_made": get("fg_made"),
        "xp_att": get("xp_att"),
        "xp_made": get("xp_made"),
        "def_td": get("def_td"),
        "def_int": get("def_int"),
        "def_sack": get("def_sack"),
        "def_fumble_rec": get("def_fumble_rec"),
        "def_points_allowed": get("def_points_allowed"),
        "def_yds_allowed": get("def_yds_allowed"),
    }


# Draftable positions: skill positions, kickers, and team defenses.
_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK", "DEF")

# The league sizes we offer. 11 and 16 are real formats we deliberately do not
# support: the bot roster ceilings and the 15-round roster construction are
# sized for these three, and a size the engine was never built for would draft a
# board we cannot stand behind. 12 stays the default so drafts created before
# league size existed keep round-tripping.
_LEAGUE_SIZES = frozenset({10, 12, 14})
_DEFAULT_TEAMS = 12
_ROUNDS = 15


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _conn():
    connection = sqlite3.connect(_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db():
    """Create the mock-draft tables defensively.

    A table-init failure must not prevent the sports API from starting
    (same pattern as ``ufc_picks.py``).
    """
    try:
        connection = _conn()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_drafts (
                    id          TEXT PRIMARY KEY,
                    device_id   TEXT    NOT NULL,
                    user_id     INTEGER,
                    season      INTEGER NOT NULL,
                    seat        INTEGER NOT NULL,
                    teams       INTEGER NOT NULL DEFAULT 12,
                    rounds      INTEGER NOT NULL DEFAULT 15,
                    seed        INTEGER NOT NULL,
                    status      TEXT    NOT NULL,
                    created_at  INTEGER NOT NULL,
                    updated_at  INTEGER NOT NULL,
                    completed_at INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_mock_draft_picks (
                    draft_id   TEXT    NOT NULL,
                    pick_no    INTEGER NOT NULL,
                    team_no    INTEGER NOT NULL,
                    player_id  INTEGER NOT NULL,
                    auto       INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (draft_id, pick_no)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_drafts_device "
                "ON nfl_mock_drafts(device_id, season)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mock_draft_picks_draft "
                "ON nfl_mock_draft_picks(draft_id)"
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # A table-init failure must not prevent the sports API from starting.
        pass


_init_db()

router = APIRouter()


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status)


def _device_id(x_device_id: Optional[str]) -> Optional[str]:
    """Copy of ``ufc_picks.py:84`` — trim, empty means None."""
    if not x_device_id:
        return None
    device_id = x_device_id.strip()
    return device_id or None


def _compute_round_and_pick(pick_count: int, teams: int) -> tuple[int, int]:
    """Given total picks made and number of teams, return (current_round, current_pick).

    Round is 1-indexed, pick is 1-indexed within the round (snake draft).
    If 0 picks have been made, returns (1, 1).
    If all picks are made, returns (rounds, teams) — the draft is complete.
    """
    if pick_count == 0:
        return 1, 1
    # Round number: which round does the NEXT pick belong to?
    current_round = (pick_count // teams) + 1
    # Pick within round: remainder gives position
    remainder = pick_count % teams
    if remainder == 0:
        # Just finished a round — next pick is first of next round
        current_pick = teams
    else:
        current_pick = remainder
    return current_round, current_pick


# ---------------------------------------------------------------------------
#  Pool endpoint  (§0 and §1 of SPEC-slice-D-mock-draft.md)
# ---------------------------------------------------------------------------


@router.get("/api/nfl/mock-draft/pool")
def pool(season: int = Query(...)):
    """Return the full published player universe for mock drafts (v0.7.0 T2).

    No cap, no active/ownership filter: every nfl_adp row for the season is a
    pool entry — free agents included, rendering a "—" ADP. D/ST carry ESPN's
    published PPR rank as their ADP (v0.7.0 T1). X-Device-Id is NOT required
    for this endpoint — it is read-only public data.
    """
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)

    connection = _conn()
    try:
        database_token = _database_cache_token(connection)
        cache_key = (
            (database_token, season)
            if database_token is not None else None
        )
        cached_body = _pool_cache_get(cache_key)
        if cached_body is not None:
            return Response(content=cached_body, media_type="application/json")

        # ------------------------------------------------------------------
        # Availability aggregates — read from the most recent completed
        # season (what the player actually did), not from the draft season
        # (which hasn't been played yet).
        # ------------------------------------------------------------------
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)

        availability = _availability_aggregates(
            connection, _log_season
        )

        # One implementation of the season aggregate, shared with the research
        # board. job16 originally re-accumulated these in Python to guarantee
        # pool/detail parity, which anchored two surfaces to each other and left
        # the board -- the surface a drafter consults for truth -- disagreeing
        # with both on six players. The difference was never rounding mode but
        # float accumulation order: Chris Olave's 268.0 PPR over 16 games is an
        # exact 16.75, which SQLite's SUM reaches and a Python loop misses by a
        # last bit, so one screen said 16.8 and the other 16.7. Deriving all
        # three from _regular_season_aggregates makes the question moot.
        _log_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(player_game_logs)"
            ).fetchall()
        }
        season_stats = {}
        if "stats" in _log_columns:
            pk_by_player = _pk_aggregates(
                connection, _log_season, availability
            )
        else:
            pk_by_player = {}
        dst_availability, dst_team_weeks = _dst_aggregates(
            connection, _log_season
        )

        # ------------------------------------------------------------------
        # Query the pool: the FULL published universe for the season, from
        # nfl_adp (v0.7.0 T2 — 11,515 players incl. free agents). No cap, no
        # active filter, no ownership filter: the UI filters "available" vs
        # "drafted", and a free agent is a real pool entry that renders a "—"
        # ADP. Projections/rank/adp_ppr columns are conditional: a DB that has
        # not yet run the migrations must not 500 — it serves honest NULLs.
        # ------------------------------------------------------------------
        _has_proj = bool(_table_columns(connection, "nfl_player_projections"))
        _has_rank = "espn_ppr_rank" in _table_columns(connection, "nfl_adp")
        _has_ppr = "adp_ppr" in _table_columns(connection, "nfl_adp")
        _has_pos = "position" in _table_columns(connection, "nfl_adp")
        _has_injury = {"injury_status", "last_news_date"}.issubset(
            _table_columns(connection, "players")
        )
        _injury_select = (
            ", p.injury_status, p.last_news_date"
            if _has_injury else ", NULL AS injury_status, NULL AS last_news_date"
        )
        _position_expr = "na.position" if _has_pos else "p.position"
        _pos_select = f"{_position_expr} AS position"
        _proj_select = (
            ", np.lp_ppr_projected_points AS proj_ppr_points"
            if _has_proj else ", NULL AS proj_ppr_points"
        )
        _proj_join = (
            " LEFT JOIN nfl_player_projections np"
            " ON np.player_id = p.id AND np.season = ?"
            if _has_proj else ""
        )
        _proj_params = (season,) if _has_proj else ()
        _rank_select = ", na.espn_ppr_rank" if _has_rank else ", NULL AS espn_ppr_rank"
        _ppr_select = ", na.adp_ppr" if _has_ppr else ", NULL AS adp_ppr"
        # D/ST's published ADP is ESPN's PPR rank (v0.7.0 T1: DEN 234, SEA 239).
        # Pre-v0.7.0 DBs have no adp_ppr column and fall back to the ADP column.
        _adp_select = (
            "CASE WHEN na.position = 'DEF' THEN na.adp_ppr ELSE na.adp END AS adp"
            if (_has_ppr and _has_pos) else "na.adp"
        )

        rows = connection.execute(
            f"""SELECT p.id AS player_id, p.name, {_pos_select}, p.team,
                           {_adp_select}, na.percent_owned{_rank_select}{_ppr_select}{_proj_select}{_injury_select}
                    FROM players p
                    JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                    {_proj_join}
                    WHERE p.league = 'nfl'
                      AND {_position_expr} IN ({','.join('?' for _ in _DRAFT_POSITIONS)})""",
            (season, *_proj_params, *_DRAFT_POSITIONS),
        ).fetchall()

        # Sort by the published ESPN PPR rank — the ESPN-shell contract's RK
        # column. Nulls (e.g. Dominic Zvada, who has ADP but no published rank)
        # follow every ranked player; ADP/ownership break the tie inside a rank.
        rows.sort(key=lambda r: (
            0 if r["espn_ppr_rank"] is not None else 1,
            r["espn_ppr_rank"] if r["espn_ppr_rank"] is not None else 999999,
            0 if r["adp"] is not None else 1,
            r["adp"] if r["adp"] is not None else 999999,
            -(r["percent_owned"] or 0),
            r["name"],
        ))

        # Season aggregates over the whole log table, keeping the pool's rows.
        # Passing player_ids would build an IN clause of ~11,500 terms — past
        # SQLite 3.31's 999-variable limit. The unfiltered scan returns the
        # same per-player numbers: the aggregate groups by player, so narrowing
        # the scan cannot change a result (the helper's own contract).
        if "stats" in _log_columns and rows:
            _all_season_stats = _regular_season_aggregates(
                connection,
                _log_season,
                availability=availability,
            )
            season_stats = {
                pid: _all_season_stats[pid]
                for pid in (row["player_id"] for row in rows)
                if pid in _all_season_stats
            }

        # Whether we hold any NFL game log for this player *before* the
        # reference season. Without it a surface cannot tell a rookie apart
        # from a veteran who missed the whole year, and the pool called Odell
        # Beckham Jr. a rookie -- an outright false statement about a player
        # with eight prior-season rows sitting in this same table. Intersected
        # in Python because the IN clause would exceed the variable limit at
        # pool size.
        prior_sample_ids = set()
        if rows:
            prior_sample_ids = {
                r[0]
                for r in connection.execute(
                    """SELECT DISTINCT player_id FROM player_game_logs
                       WHERE league='nfl' AND season < ?""",
                    (_log_season,),
                )
            } & {row["player_id"] for row in rows}

        # ESPN-style 4-stat rank card for the whole pool, computed once
        # (4 queries) instead of once per player (~17,000 at pool size).
        pool_rank_map = (
            nfl_player_stat_ranks_batch(connection, _log_season) if rows else {}
        )

        players = []
        for row in rows:
            pid = row["player_id"]
            pos = row["position"]

            if pos == "DEF":
                avail = dst_availability.get(pid)
                tw = dst_team_weeks.get(row["team"], [])
                team_games = (
                    len(tw) or _REG_SEASON_TEAM_GAMES
                    if avail is not None
                    else None
                )
            else:
                avail = availability.get(pid)
                tw = avail.get("team_weeks", []) if avail else []
                team_games = (
                    avail.get("team_games", _REG_SEASON_TEAM_GAMES)
                    if avail
                    else None
                )

            gp = avail["games_played"] if avail is not None else None
            wp = sorted(avail["weeks"]) if avail else []
            gm = max(0, team_games - gp) if avail else None
            sample = (
                "full"
                if gp is not None and gp >= _THIN_SAMPLE_GAMES
                else "thin"
                if gp is not None and gp > 0
                else "none"
            )

            # Field for field, the research board's derivation. Any change here
            # has to be made there too, or the two screens start disagreeing
            # about the same player again.
            stats = season_stats.get(pid)
            ppr_total = stats["ppr_total"] if stats else None
            ppr_per_game_played = (
                _rounded_ratio(ppr_total, gp)
                if ppr_total is not None and gp
                else None
            )
            ppr_per_team_game = (
                # Per-player team_games, not the 17-constant (see the board).
                _rounded_ratio(ppr_total, team_games)
                if ppr_total is not None and team_games
                else None
            )
            xfp_per_game = (
                _round(stats["xfp_per_game"], 1)
                if stats and stats["xfp_per_game"] is not None
                else None
            )
            snap_pct = (
                _percentage(stats["snap_pct"], 0)
                if stats and stats["snap_pct"] is not None
                else None
            )
            target_share = (
                _percentage(stats["target_share"], 1)
                if stats and stats["target_share"] is not None
                else None
            )

            pk_pts_total = None
            pk_pts_per_game = None
            if pos == "PK":
                pk_row = pk_by_player.get(pid)
                if pk_row and pk_row["pk_pts_total"] is not None:
                    pk_pts_total = round(pk_row["pk_pts_total"], 1)
                    pk_pts_per_game = pk_row["pk_pts_per_game"]

            dst_pts_total = None
            dst_pts_per_game = None
            if pos == "DEF":
                dst_row = dst_availability.get(pid)
                if dst_row and dst_row["dst_total"] is not None:
                    dst_pts_total = round(dst_row["dst_total"], 1)
                    if dst_row["dst_avg"] is not None:
                        dst_pts_per_game = round(dst_row["dst_avg"], 1)

            if pos in ("PK", "DEF"):
                # All five, not three. A kicker who takes a fake-punt carry
                # picks up real offensive rows, and leaving these two alive
                # published Brandon Aubrey at 0.0 PPR/team-game and 0.8
                # xFP/game as though they were kicking output -- while the
                # research board, which suppresses all five, showed nothing.
                ppr_per_game_played = None
                ppr_per_team_game = None
                xfp_per_game = None
                snap_pct = None
                target_share = None

            # ESPN-style 4-stat rank card — from the batched rank map computed
            # once for the whole pool (v0.7.0: 4 queries, not 17,000).
            stat_ranks = {
                col: entry
                for col, _ in NFL_RANK_STATS.get(pos, ())
                for entry in [pool_rank_map.get(pid, {}).get(col)]
                if entry is not None
            }
            players.append({
                "player_id": pid,
                "name": row["name"],
                "position": pos,
                "team": row["team"],
                "injury_status": row["injury_status"],
                "last_news_date": row["last_news_date"],
                "adp": row["adp"],
                "espn_ppr_rank": row["espn_ppr_rank"],
                "adp_ppr": row["adp_ppr"],
                # 2026 season-long PPR projection computed from ESPN's
                # published projected stat line. Null means the source did not
                # publish a usable projection; it is never coerced to zero.
                "proj_ppr_points": row["proj_ppr_points"],
                "proj_season": season,
                "proj_source": "espn" if row["proj_ppr_points"] is not None else None,
                "percent_owned": row["percent_owned"],
                "sample": sample,
                "has_prior_nfl_sample": pid in prior_sample_ids,
                "games_played": gp,
                "games_missed": gm,
                "weeks_played": wp,
                "team_weeks": tw,
                "team_games": team_games,
                "ppr_per_game_played": ppr_per_game_played,
                "ppr_per_team_game": ppr_per_team_game,
                "xfp_per_game": xfp_per_game,
                "snap_pct": snap_pct,
                "target_share": target_share,
                "pk_pts_total": pk_pts_total,
                "pk_pts_per_game": pk_pts_per_game,
                "dst_pts_total": dst_pts_total,
                "dst_pts_per_game": dst_pts_per_game,
                "stat_ranks": stat_ranks,
            })

        payload = {
            "contract": _CONTRACT,
            "season": season,
            # `season` is the season being drafted; every statistic in this
            # payload describes `reference_season`. Without it a client has
            # to guess which year it is labelling, and the guess is right
            # until it silently isn't -- the draft board publishes this for
            # the same reason.
            "reference_season": _log_season,
            "count": len(players),
            "players": players,
        }
        response = _json(payload)
        # Cache encoded bytes: a cached multi-megabyte dict still pays JSON
        # serialization on every hit and is mutable by callers.
        _pool_cache_put(cache_key, response.body)
        return response
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Draft CRUD
# ---------------------------------------------------------------------------


@router.post("/api/nfl/mock-draft")
async def create_draft(request: Request, x_device_id: Optional[str] = Header(None)):
    """Create a new mock draft.  Returns the draft id.

    Body: {season, seat, seed, teams?}.  X-Device-Id required.

    ``teams`` is optional and defaults to 12, because every draft created before
    league size existed was a 12-team draft and has to keep round-tripping.
    ``seat`` is bounded by the league, not by the old literal 12 -- seat 13 is a
    real seat in a 14-team draft and a nonexistent one in a 12-team draft.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "invalid JSON body"}, status=400)
    if not isinstance(data, dict):
        return _json({"error": "body must be a JSON object"}, status=400)

    season = data.get("season")
    seat = data.get("seat")
    seed = data.get("seed")
    teams = data.get("teams", _DEFAULT_TEAMS)

    if not isinstance(season, int) or season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)
    # bool is a subclass of int, so True would otherwise pass as the number 1
    # and create a one-team draft.
    if isinstance(teams, bool) or not isinstance(teams, int) or teams not in _LEAGUE_SIZES:
        return _json(
            {"error": f"teams must be one of {sorted(_LEAGUE_SIZES)}"}, status=400
        )
    if isinstance(seat, bool) or not isinstance(seat, int) or seat < 1 or seat > teams:
        return _json({"error": f"seat must be 1..{teams}"}, status=400)
    if isinstance(seed, bool) or not isinstance(seed, int):
        return _json({"error": "seed must be an integer"}, status=400)

    now = int(time.time() * 1000)
    draft_id = str(uuid.uuid4())

    connection = _conn()
    try:
        connection.execute(
            """INSERT INTO nfl_mock_drafts
               (id, device_id, season, seat, teams, rounds, seed, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (draft_id, device_id, season, seat, teams, _ROUNDS, seed, now, now),
        )
        connection.commit()
    finally:
        connection.close()

    return _json({"id": draft_id})


@router.post("/api/nfl/mock-draft/{draft_id}/picks")
async def append_picks(
    draft_id: str, request: Request, x_device_id: Optional[str] = Header(None)
):
    """Append picks to a draft.  Idempotent on (draft_id, pick_no).

    Body: {picks: [{pick_no, team_no, player_id, auto?}, ...]}.
    X-Device-Id must match the draft's device_id, else 404.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return _json({"error": "invalid JSON body"}, status=400)
    if not isinstance(data, dict):
        return _json({"error": "body must be a JSON object"}, status=400)

    picks = data.get("picks")
    if not isinstance(picks, list) or not picks:
        return _json({"error": "picks must be a non-empty array"}, status=400)

    now = int(time.time() * 1000)

    connection = _conn()
    try:
        draft = connection.execute(
            "SELECT device_id, status FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

        if draft is None:
            return _json({"error": "not found"}, status=404)
        if draft["device_id"] != device_id:
            return _json({"error": "not found"}, status=404)
        if draft["status"] != "active":
            return _json({"error": "draft is not active"}, status=409)

        draft_row = connection.execute(
            "SELECT teams, rounds FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        max_pick = draft_row["teams"] * draft_row["rounds"]
        max_team = draft_row["teams"]

        inserted = 0
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            pick_no = pick.get("pick_no")
            team_no = pick.get("team_no")
            player_id = pick.get("player_id")
            auto = int(pick.get("auto", 0) or 0)

            if not isinstance(pick_no, int) or pick_no < 1 or pick_no > max_pick:
                continue
            if not isinstance(team_no, int) or team_no < 1 or team_no > max_team:
                continue
            if not isinstance(player_id, int):
                continue

            before = connection.total_changes
            connection.execute(
                """INSERT OR IGNORE INTO nfl_mock_draft_picks
                   (draft_id, pick_no, team_no, player_id, auto, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (draft_id, pick_no, team_no, player_id, auto, now),
            )
            if connection.total_changes > before:
                inserted += 1

        # Update the draft's updated_at timestamp.
        connection.execute(
            "UPDATE nfl_mock_drafts SET updated_at = ? WHERE id = ?",
            (now, draft_id),
        )
        connection.commit()
    finally:
        connection.close()

    return _json({"inserted": inserted})


def _missing_picks(pick_numbers):
    """Which pick numbers are absent from a draft that claims to have got this far.

    Picks arrive in batches over the network and the client's append is
    best-effort, so a dropped batch leaves a hole: [1,2,3,7,8,9] with nothing
    anywhere saying 6 picks never made it.  `INSERT OR IGNORE` on
    (draft_id, pick_no) means the hole is permanent -- later batches still
    insert, so no error surfaces on either side.

    Reported against the highest pick actually saved, not against the full
    180: a draft abandoned at pick 40 is incomplete, not holed, and calling
    those two the same thing would make the field useless.
    """
    if not pick_numbers:
        return []
    saved = set(pick_numbers)
    return [n for n in range(1, max(saved) + 1) if n not in saved]


@router.post("/api/nfl/mock-draft/{draft_id}/complete")
async def complete_draft(
    draft_id: str, x_device_id: Optional[str] = Header(None)
):
    """Mark a draft finished.  Idempotent.

    Nothing wrote this before, so `status` sat at 'active' for the life of
    every draft ever saved and `completed_at` was never set -- the server
    could not tell a draft abandoned at pick 4 from one that ran all 180.
    That distinction is the whole point of keeping the row: slice B's
    claim-on-sign-in inherits these, and "your drafts" cannot list what it
    cannot classify.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    now = int(time.time() * 1000)
    connection = _conn()
    try:
        draft = connection.execute(
            "SELECT device_id, status, teams, rounds FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None or draft["device_id"] != device_id:
            return _json({"error": "not found"}, status=404)

        pick_numbers = [
            r["pick_no"]
            for r in connection.execute(
                "SELECT pick_no FROM nfl_mock_draft_picks WHERE draft_id = ?",
                (draft_id,),
            ).fetchall()
        ]
        missing = _missing_picks(pick_numbers)

        if draft["status"] != "completed":
            connection.execute(
                "UPDATE nfl_mock_drafts SET status = 'completed', completed_at = ?, "
                "updated_at = ? WHERE id = ?",
                (now, now, draft_id),
            )
            connection.commit()

        return _json(
            {
                "id": draft_id,
                "status": "completed",
                "pick_count": len(pick_numbers),
                "picks_expected": draft["teams"] * draft["rounds"],
                # A completed draft with a hole is a real outcome, not an
                # error: we record what we hold rather than refusing the write.
                "missing_picks": missing,
            }
        )
    finally:
        connection.close()


@router.get("/api/nfl/mock-draft/{draft_id}")
def get_draft(draft_id: str, x_device_id: Optional[str] = Header(None)):
    """Resume a draft — returns draft metadata + all picks + computed round/pick.

    X-Device-Id must match the draft's device_id, else 404
    (same reasoning as picks: a device should not be able to probe draft ids).
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    connection = _conn()
    try:
        draft = connection.execute(
            "SELECT * FROM nfl_mock_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()

        if draft is None:
            return _json({"error": "not found"}, status=404)
        if draft["device_id"] != device_id:
            return _json({"error": "not found"}, status=404)

        picks_rows = connection.execute(
            "SELECT * FROM nfl_mock_draft_picks WHERE draft_id = ? ORDER BY pick_no",
            (draft_id,),
        ).fetchall()

        picks = [
            {
                "pick_no": row["pick_no"],
                "team_no": row["team_no"],
                "player_id": row["player_id"],
                "auto": bool(row["auto"]),
                "created_at": row["created_at"],
            }
            for row in picks_rows
        ]

        # Compute current round and current pick from the pick count.
        total_picks = len(picks)
        current_round, current_pick = _compute_round_and_pick(
            total_picks, draft["teams"]
        )

        return _json(
            {
                "id": draft["id"],
                "season": draft["season"],
                "seat": draft["seat"],
                "teams": draft["teams"],
                "rounds": draft["rounds"],
                "seed": draft["seed"],
                "status": draft["status"],
                "created_at": draft["created_at"],
                "updated_at": draft["updated_at"],
                "completed_at": draft["completed_at"],
                "picks": picks,
                "total_picks": total_picks,
                "picks_expected": draft["teams"] * draft["rounds"],
                # Absent pick numbers below the highest one saved. Empty is the
                # normal case; non-empty means a client append was dropped and
                # never retried, which nothing else in the payload would reveal.
                "missing_picks": _missing_picks(
                    [row["pick_no"] for row in picks_rows]
                ),
                "current_round": current_round,
                "current_pick": current_pick,
            }
        )
    finally:
        connection.close()


@router.get("/api/nfl/mock-drafts")
def list_drafts(x_device_id: Optional[str] = Header(None)):
    """List all mock drafts for this device (resume/history list).

    X-Device-Id required.
    """
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    connection = _conn()
    try:
        rows = connection.execute(
            """SELECT d.id, d.season, d.seat, d.teams, d.rounds, d.seed, d.status,
                      d.created_at, d.updated_at, d.completed_at,
                      COUNT(p.pick_no)  AS pick_count,
                      MAX(p.pick_no)    AS highest_pick
               FROM nfl_mock_drafts d
               LEFT JOIN nfl_mock_draft_picks p ON p.draft_id = d.id
               WHERE d.device_id = ?
               GROUP BY d.id
               ORDER BY d.updated_at DESC""",
            (device_id,),
        ).fetchall()

        # A list row has to be classifiable without fetching every draft:
        # how far it got, and whether what we hold is contiguous.
        drafts = [
            {
                "id": row["id"],
                "season": row["season"],
                "seat": row["seat"],
                "teams": row["teams"],
                "rounds": row["rounds"],
                "seed": row["seed"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
                "pick_count": row["pick_count"],
                "picks_expected": row["teams"] * row["rounds"],
                "missing_pick_count": (
                    (row["highest_pick"] or 0) - row["pick_count"]
                ),
            }
            for row in rows
        ]

        return _json({"drafts": drafts})
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Player detail endpoint — per-player info + QB lookup
# ---------------------------------------------------------------------------


@router.get("/api/nfl/draft/player/{player_id}")
def player_detail(player_id: int):
    """Return player detail for the mock draft overlay.

    Includes: name, team, position, ADP, percent owned, season stats,
    game strip (weeks played vs team weeks), and for WR/RB/TE the QB on
    their team.
    """
    connection = _conn()
    try:
        # 1. Player lookup. The injury columns are optional (a concurrent
        # feature's migration may not have landed on this DB) — selected only
        # where they exist, so a pre-migration DB serves honest NULLs instead
        # of 500ing on the SELECT.
        _injury_cols = (
            ", injury_status, last_news_date"
            if {"injury_status", "last_news_date"}
            <= {r["name"] for r in connection.execute("PRAGMA table_info(players)")}
            else ""
        )
        player = connection.execute(
            f"SELECT id, name, team, position, active{_injury_cols} "
            f"FROM players WHERE id=? AND league='nfl'",
            (player_id,),
        ).fetchone()

        if player is None:
            return _json({"error": "Player not found"}, status=404)

        name = player["name"]
        team = player["team"]
        position = player["position"]
        active = bool(player["active"])
        injury_status = player["injury_status"] if _injury_cols else None
        last_news_date = player["last_news_date"] if _injury_cols else None

        # 2. ADP / percent owned from nfl_adp. D/ST's published ADP is ESPN's
        #    PPR rank (v0.7.0 T1) — the same mapping the pool applies, so the
        #    overlay and the pool can never disagree about a defense. The rank
        #    columns are conditional: a pre-migration DB serves honest NULLs.
        adp = None
        percent_owned = None
        espn_ppr_rank = None
        espn_standard_rank = None
        adp_ppr = None
        adp_columns = _table_columns(connection, "nfl_adp")
        _has_ppr = "adp_ppr" in adp_columns
        _ppr_col = ", adp_ppr" if _has_ppr else ""
        _rank_cols = ", " + ", ".join(
            column if column in adp_columns else f"NULL AS {column}"
            for column in ("espn_ppr_rank", "espn_standard_rank")
        )
        adp_row = connection.execute(
            f"SELECT adp, percent_owned{_rank_cols}{_ppr_col} "
            f"FROM nfl_adp WHERE player_id=? AND season=?",
            (player_id, _CURRENT_SEASON),
        ).fetchone()
        if adp_row:
            percent_owned = adp_row["percent_owned"]
            if _has_ppr and position == "DEF":
                adp = adp_row["adp_ppr"]
            else:
                adp = adp_row["adp"]
            if _has_ppr:
                adp_ppr = adp_row["adp_ppr"]
            espn_ppr_rank = adp_row["espn_ppr_rank"]
            espn_standard_rank = adp_row["espn_standard_rank"]

        proj_2026_pts = None
        projection_2026 = None
        projection_source = None
        season_outlook = None
        season_outlook_source = None
        season_totals = None
        season_totals_source = None
        projection_columns = _table_columns(connection, "nfl_player_projections")
        if "lp_ppr_projected_points" in projection_columns:
            detail_columns = (
                "lp_ppr_projected_points", "raw_projection_json", "projected_games",
                "pass_att", "pass_cmp", "pass_yds", "pass_td", "interceptions",
                "rush_att", "rush_yds", "rush_td", "receptions", "targets",
                "rec_yds", "rec_td", "fg_att", "fg_made", "xp_att", "xp_made",
                "def_td", "def_int", "def_sack", "def_fumble_rec",
                "def_points_allowed", "def_yds_allowed", "season_outlook",
                "outlook_source", "actual_season", "raw_actual_json",
                "actual_qbr", "actual_passer_rating", "actual_adj_qbr", "qbr_source",
            )
            select_columns = ", ".join(
                column if column in projection_columns else f"NULL AS {column}"
                for column in detail_columns
            )
            split_filter = (
                " AND stat_split_type_id=0"
                if "stat_split_type_id" in projection_columns
                else ""
            )
            proj_row = connection.execute(
                f"SELECT {select_columns} FROM nfl_player_projections "
                f"WHERE player_id=? AND season=?{split_filter}",
                (player_id, _CURRENT_SEASON),
            ).fetchone()
        else:
            proj_row = None
        if proj_row:
            proj_2026_pts = proj_row["lp_ppr_projected_points"]
            projection_source = "espn" if proj_2026_pts is not None else None
            projection_2026 = _named_stat_line(proj_row["raw_projection_json"])
            season_outlook = proj_row["season_outlook"]
            season_outlook_source = proj_row["outlook_source"]
            actual_line = _named_stat_line(
                proj_row["raw_actual_json"], include_actual_first_downs=True
            )
            if actual_line:
                actual_line["qbr"] = proj_row["actual_qbr"]
                actual_line["passer_rating"] = proj_row["actual_passer_rating"]
                actual_line["adj_qbr"] = proj_row["actual_adj_qbr"]
                season_totals = {
                    "season": proj_row["actual_season"],
                    **actual_line,
                    "ppr_points": None,
                }
                season_totals_source = "espn"

        # 3. Season stats from player_game_logs
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)
        rank_context = nfl_player_rank_context(
            connection, player_id, position, _log_season
        )
        availability_by_player = _availability_aggregates(
            connection, _log_season
        )
        dst_by_player, dst_team_weeks = _dst_aggregates(
            connection, _log_season
        )

        # Third surface, same aggregate. This endpoint used to re-accumulate the
        # season in Python, which is how it ended up telling a drafter 16.7 for
        # a player the research board showed at 16.8.
        _season_stats = _regular_season_aggregates(
            connection,
            _log_season,
            availability=availability_by_player,
            player_ids=[player_id],
        ).get(player_id)

        if position == "DEF":
            availability = dst_by_player.get(player_id)
            team_weeks = dst_team_weeks.get(team, [])
            team_games = (
                len(team_weeks) or _REG_SEASON_TEAM_GAMES
                if availability is not None
                else None
            )
        else:
            availability = availability_by_player.get(player_id)
            team_weeks = availability.get("team_weeks", []) if availability else []
            team_games = (
                availability.get("team_games", _REG_SEASON_TEAM_GAMES)
                if availability
                else None
            )

        games_played = (
            availability["games_played"] if availability is not None else None
        )
        weeks_played = sorted(availability["weeks"]) if availability else []

        # Sample classification
        if games_played is None or games_played == 0:
            sample = "none"
        elif games_played < _THIN_SAMPLE_GAMES:
            sample = "thin"
        else:
            sample = "full"

        # PPR calculations
        ppr_total = _season_stats["ppr_total"] if _season_stats else None
        ppr_per_game_played = (
            _rounded_ratio(ppr_total, games_played)
            if ppr_total is not None and games_played
            else None
        )
        ppr_per_team_game = (
            _rounded_ratio(ppr_total, team_games)
            if ppr_total is not None and team_games
            else None
        )
        snap_pct = (
            _percentage(_season_stats["snap_pct"], 0)
            if _season_stats and _season_stats["snap_pct"] is not None
            else None
        )
        target_share = (
            _percentage(_season_stats["target_share"], 1)
            if _season_stats and _season_stats["target_share"] is not None
            else None
        )
        xfp_per_game = (
            _round(_season_stats["xfp_per_game"], 1)
            if _season_stats and _season_stats["xfp_per_game"] is not None
            else None
        )

        # 4. QB lookup — for WR/RB/TE, rank team QBs by games played, return top QB
        qb = None
        if position in ("WR", "RB", "TE") and team:
            qb_rows = connection.execute(
                """SELECT p.id, p.name, p.team
                   FROM players p
                   WHERE p.league='nfl' AND p.active=1
                     AND p.position='QB' AND p.team=?
                   ORDER BY p.id ASC""",
                (team,),
            ).fetchall()

            best_qb = None
            best_games = -1
            for qb_row in qb_rows:
                qb_availability = availability_by_player.get(qb_row["id"])
                games = (
                    qb_availability["games_played"]
                    if qb_availability
                    else 0
                )
                if games > best_games:
                    best_games = games
                    best_qb = {
                        "player_id": qb_row["id"],
                        "name": qb_row["name"],
                        "team": qb_row["team"],
                        "games_played": games,
                    }

            if best_qb is not None and best_games > 0:
                qb = best_qb

        # 5. PK scoring, kept separate from the shared presence aggregate.
        pk_pts_total = None
        pk_pts_per_game = None
        if position == "PK":
            pk_row = _pk_aggregates(
                connection, _log_season, availability_by_player
            ).get(player_id)
            if pk_row and pk_row["pk_pts_total"] is not None:
                pk_pts_total = round(pk_row["pk_pts_total"], 1)
                pk_pts_per_game = pk_row["pk_pts_per_game"]

        # 6. D/ST scoring from the same position-specific aggregate as the board.
        dst_pts_total = None
        dst_pts_per_game = None
        if position == "DEF":
            dst_row = dst_by_player.get(player_id)
            if dst_row and dst_row["dst_total"] is not None:
                dst_pts_total = round(dst_row["dst_total"], 1)
                if dst_row["dst_avg"] is not None:
                    dst_pts_per_game = round(dst_row["dst_avg"], 1)

        # ESPN publishes the actual counting-stat season line directly. PPR is
        # the one value absent from that source row, so pair it with the same
        # published-weekly scoring total already used everywhere else in this
        # endpoint. D/ST and kicker retain their position-specific scoring.
        if season_totals is not None:
            if position == "DEF":
                season_totals["ppr_points"] = dst_pts_total
            elif position == "PK":
                season_totals["ppr_points"] = pk_pts_total
            else:
                season_totals["ppr_points"] = (
                    round(ppr_total, 1) if ppr_total is not None else None
                )

        # 7. No presence means unknown missed games, not a fabricated 17.
        games_missed = (
            max(0, team_games - games_played)
            if availability is not None
            else None
        )

        # 7b. Same prior-sample flag the pool publishes, so the overlay does not
        #     call a veteran who missed the season a rookie.
        has_prior_nfl_sample = bool(
            connection.execute(
                """SELECT 1 FROM player_game_logs
                   WHERE league='nfl' AND player_id=? AND season < ? LIMIT 1""",
                (player_id, _log_season),
            ).fetchone()
        )

        # 8. PK/DEF null-override for skill-position fields — all five, so a
        #    fake-punt carry cannot surface as kicking output (see the pool).
        if position in ("PK", "DEF"):
            ppr_per_game_played = None
            ppr_per_team_game = None
            xfp_per_game = None
            snap_pct = None
            target_share = None

        return _json({
            "player_id": player_id,
            "name": name,
            "team": team,
            "position": position,
            "active": active,
            "adp": adp,
            "espn_ppr_rank": espn_ppr_rank,
            "espn_standard_rank": espn_standard_rank,
            "adp_ppr": adp_ppr,
            "proj_2026_pts": proj_2026_pts,
            "projection_2026": projection_2026,
            "projection_source": projection_source,
            "season_outlook": season_outlook,
            "season_outlook_source": season_outlook_source,
            "season_totals": season_totals,
            "season_totals_source": season_totals_source,
            "stat_ranks": rank_context["stats"],
            "stat_rank_season": rank_context["season"],
            "stat_rank_games": rank_context["games"],
            "percent_owned": percent_owned,
            "sample": sample,
            "has_prior_nfl_sample": has_prior_nfl_sample,
            "games_played": games_played,
            "games_missed": games_missed,
            "team_games": team_games,
            "weeks_played": weeks_played,
            "team_weeks": team_weeks,
            "ppr_per_game_played": ppr_per_game_played,
            "ppr_per_team_game": ppr_per_team_game,
            "snap_pct": snap_pct,
            "target_share": target_share,
            "xfp_per_game": xfp_per_game,
            "pk_pts_total": pk_pts_total,
            "pk_pts_per_game": pk_pts_per_game,
            "dst_pts_total": dst_pts_total,
            "dst_pts_per_game": dst_pts_per_game,
            "qb": qb,
            "injury_status": injury_status,
            "last_news_date": last_news_date,
        })
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Per-game log  (the research half of the player overlay)
# ---------------------------------------------------------------------------

# Which per-game fields matter, by position. Deliberately narrow: the log rows
# carry ~52 keys and a research table that shows all of them shows none of them.
#
# Reshaped 2026-08-02 toward ESPN's fantasy log. The brief was "I shouldn't have
# to scroll to see all the stats", and the binding constraint turned out not to
# be the column list at all -- it was PlayerDetailOverlay's max-w-[520px], which
# leaves room for about eight numeric columns after Wk and Opp. The box is now
# wider on desktop; these lists are still kept tight, because a research table
# that shows everything shows nothing.
#
# aDOT and Separation moved OUT to the player detail's advanced block. They are
# Next Gen scouting inputs, not box-score facts, and they were costing two of the
# eight columns on the surface where a fantasy manager is asking "what did he do".
# Snap %, target share and expected points stay: those are the three that answer
# a question the raw box score cannot.
_LOG_FIELDS = {
    "QB": ["off_pct", "cmp", "att", "pass_yds", "pass_td", "intc", "sacks_taken",
           "carries", "rush_yds", "rush_td", "fum_lost", "fpts_ppr", "xfpts_ppr"],
    "RB": ["off_pct", "carries", "rush_yds", "rush_td", "targets", "rec",
           "rec_yds", "rec_td", "fum_lost", "misc_td", "fpts_ppr", "xfpts_ppr"],
    "WR": ["off_pct", "targets", "target_share", "rec", "rec_yds", "rec_td",
           "fum_lost", "misc_td", "fpts_ppr", "xfpts_ppr"],
    # Raw counts only. Kicker fantasy points are computed from distance buckets
    # in _pk_aggregates; recomputing them here would be a second implementation
    # of the same number, which is how the board and the pool ended up printing
    # different figures for the same player. The season rate already ships on
    # the overview tab -- the log's job is what he actually kicked.
    "PK": ["fg_made", "fg_att", "fg_long", "pat_made", "pat_att"],
}
# D/ST have no player_game_logs rows at all -- their week rows live in
# nfl_dst_stats. Read that table rather than reporting 17 weeks of absence for a
# defense that played every one of them.
_DST_LOG_FIELDS = ["sacks", "interceptions", "tds", "safeties", "fumble_rec",
                   "points_allowed", "fantasy_pts"]
_LOG_FIELDS["TE"] = _LOG_FIELDS["WR"]
_LOG_FIELDS["FB"] = _LOG_FIELDS["RB"]


# Misc TD is computed, so it is defined once in nfl_stat_derivations and imported
# by every surface that renders it -- the player page shows the same column.
from nfl_stat_derivations import DERIVED as _DERIVED  # noqa: E402


@router.get("/api/nfl/draft/player/{player_id}/game-log")
def player_game_log(player_id: int):
    """Per-game log for the player overlay's research tab.

    Returns one entry per week the player's TEAM played -- not one per week he
    recorded a stat line. A log that lists only the games a player appeared in
    repeats the exact defect the availability work exists to fix: it makes a
    12-game season look like a full one, and it hides the weeks that are the
    most informative thing on the card.

    Weeks with no row are returned with `played: false` and null stats. Weeks
    absent from the team's schedule entirely (the bye) are simply not present,
    because a bye is not an absence.
    """
    connection = _conn()
    try:
        player = connection.execute(
            "SELECT id, name, team, position FROM players WHERE id=? AND league='nfl'",
            (player_id,),
        ).fetchone()
        if player is None:
            return _json({"error": "Player not found"}, status=404)

        position = player["position"]

        # Reference season = the most recent season with logs, matching pool().
        row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        season = (row[0] if row and row[0] else _CURRENT_SEASON - 1)

        availability = _availability_aggregates(connection, season)
        if position == "DEF":
            _dst_avail, dst_team_weeks = _dst_aggregates(connection, season)
            team_weeks = sorted(dst_team_weeks.get(player["team"], []))
        else:
            agg = availability.get(player_id) or {}
            team_weeks = sorted(agg.get("team_weeks", []))

        if position == "DEF":
            return _json(_dst_game_log(
                connection, player, player_id, season, team_weeks,
            ))

        fields = _LOG_FIELDS.get(position, [])

        by_week = {}
        for log in connection.execute(
            """SELECT game_no, opponent, team, stats, game_type
                 FROM player_game_logs
                WHERE player_id=? AND season=? AND league='nfl'""",
            (player_id, season),
        ):
            # Playoff rows sit alongside regular-season rows (B10). The team's
            # week list is regular season, so they drop out on the join -- but
            # drop them explicitly rather than relying on that coincidence.
            if log["game_type"] and log["game_type"] != "REG":
                continue
            try:
                week = int(log["game_no"])
            except (TypeError, ValueError):
                continue
            try:
                stats = json.loads(log["stats"]) if log["stats"] else {}
            except (TypeError, ValueError):
                stats = {}
            by_week[week] = {
                "opponent": log["opponent"],
                "team": log["team"],
                "stats": {
                    f: (_DERIVED[f](stats) if f in _DERIVED else stats.get(f))
                    for f in fields
                },
            }

        games = []
        for week in team_weeks:
            entry = by_week.get(week)
            games.append({
                "week": week,
                "played": entry is not None,
                "opponent": entry["opponent"] if entry else None,
                "team": entry["team"] if entry else None,
                "stats": entry["stats"] if entry else {f: None for f in fields},
            })

        return _json({
            "contract": "nfl-player-game-log-v1",
            "player_id": player_id,
            "name": player["name"],
            "position": position,
            "reference_season": season,
            "fields": fields,
            "team_games": len(team_weeks),
            "games_played": sum(1 for g in games if g["played"]),
            "games": games,
        })
    finally:
        connection.close()


def _dst_game_log(connection, player, player_id, season, team_weeks):
    """Week rows for a team defense, read from nfl_dst_stats.

    Separate from the skill-position path because D/ST never appear in
    player_game_logs. Routing them through it reported every week of a
    17-week season as "did not play" for a defense that played all 17 --
    a fabricated absence, which is the same defect as a fabricated number.
    """
    columns = _table_columns(connection, "nfl_dst_stats")
    if not {"player_id", "season", "week"}.issubset(columns):
        return {
            "contract": "nfl-player-game-log-v1",
            "player_id": player_id,
            "name": player["name"],
            "position": "DEF",
            "reference_season": season,
            "fields": [],
            "team_games": len(team_weeks),
            "games_played": 0,
            "games": [],
            "unavailable": "per-week D/ST scoring is not loaded",
        }

    fields = [f for f in _DST_LOG_FIELDS if f in columns]
    by_week = {}
    for row in connection.execute(
        "SELECT * FROM nfl_dst_stats WHERE player_id=? AND season=?",
        (player_id, season),
    ):
        try:
            by_week[int(row["week"])] = {f: row[f] for f in fields}
        except (TypeError, ValueError):
            continue

    games = []
    for week in team_weeks:
        stats = by_week.get(week)
        games.append({
            "week": week,
            "played": stats is not None,
            "opponent": None,
            "team": player["team"],
            "stats": stats if stats else {f: None for f in fields},
        })

    return {
        "contract": "nfl-player-game-log-v1",
        "player_id": player_id,
        "name": player["name"],
        "position": "DEF",
        "reference_season": season,
        "fields": fields,
        "team_games": len(team_weeks),
        "games_played": sum(1 for g in games if g["played"]),
        "games": games,
    }
