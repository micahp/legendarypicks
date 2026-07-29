from __future__ import annotations

"""NFL mock draft — pool endpoint + draft CRUD for single-player mock drafts vs. ADP bots.

SPEC-slice-D-mock-draft.md:
  - Pool: GET /api/nfl/mock-draft/pool?season=2026 — 300 players
    (QB/RB/WR/TE/PK/DEF) with copied published ADP.
  - Draft CRUD: create, append picks, resume, list — keyed by X-Device-Id.
  - Own _DB from LP_DB_PATH (no _core.py dependency).
"""

import json
import os
import sqlite3
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from .nfl_offseason import (
    _availability_aggregates,
    _dst_aggregates,
    _pk_aggregates,
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
_POOL_CAP = 300

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
    """Return the ~300-player ranked pool for mock drafts.

    X-Device-Id is NOT required for this endpoint — it is read-only public data.
    """
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)

    connection = _conn()
    try:
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
        # Query the pool: draftable positions, active players, from nfl_adp.
        # D/ST are selected separately (all 32) to guarantee they are never
        # displaced by the global 300-cap; non-DEF fill the remaining slots.
        # Both sets are then merged and sorted by the same ADP/ownership
        # ordering — no synthetic ADP, no fixed slot, no dst_rank.
        # ------------------------------------------------------------------
        _NON_DEF_POSITIONS = ("QB", "RB", "WR", "TE", "PK")
        _placeholders = ",".join("?" for _ in _NON_DEF_POSITIONS)

        # ── DEF: all 32, guaranteed a slot ──
        def_rows = connection.execute(
            """SELECT p.id AS player_id, p.name, p.position, p.team,
                      na.adp, na.percent_owned
               FROM players p
               JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
               WHERE p.league = 'nfl' AND p.active = 1
                 AND p.position = 'DEF'
                 AND na.adp IS NOT NULL""",
            (season,),
        ).fetchall()

        # ── Non-DEF: top N to fill pool cap ──
        _non_def_cap = _POOL_CAP - len(def_rows)
        non_def_rows: list = []
        if _non_def_cap > 0:
            non_def_rows = connection.execute(
                f"""SELECT p.id AS player_id, p.name, p.position, p.team,
                           na.adp, na.percent_owned
                    FROM players p
                    JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                    WHERE p.league = 'nfl' AND p.active = 1
                      AND p.position IN ({_placeholders})
                      AND (na.adp IS NOT NULL OR na.percent_owned > 0)
                    ORDER BY
                      CASE WHEN na.adp IS NOT NULL THEN 0 ELSE 1 END,
                      na.adp ASC,
                      na.percent_owned DESC,
                      p.name ASC
                    LIMIT ?""",
                (season, *_NON_DEF_POSITIONS, _non_def_cap),
            ).fetchall()

        # Merge both sets
        rows = list(def_rows) + list(non_def_rows)
        # Sort by the copied ESPN ADP. Nulls, if selected through published
        # ownership, follow all players with a published ADP.
        rows.sort(key=lambda r: (
            0 if r["adp"] is not None else 1,
            r["adp"] if r["adp"] is not None else 999999,
            -(r["percent_owned"] or 0),
            r["name"],
        ))

        if "stats" in _log_columns and rows:
            season_stats = _regular_season_aggregates(
                connection,
                _log_season,
                availability=availability,
                player_ids=[row["player_id"] for row in rows],
            )

        # Whether we hold any NFL game log for this player *before* the
        # reference season. Without it a surface cannot tell a rookie apart
        # from a veteran who missed the whole year, and the pool called Odell
        # Beckham Jr. a rookie -- an outright false statement about a player
        # with eight prior-season rows sitting in this same table.
        prior_sample_ids = set()
        if rows:
            _prior_placeholders = ",".join("?" for _ in rows)
            prior_sample_ids = {
                r[0]
                for r in connection.execute(
                    f"""SELECT DISTINCT player_id FROM player_game_logs
                        WHERE league='nfl' AND season < ?
                          AND player_id IN ({_prior_placeholders})""",
                    (_log_season, *[row["player_id"] for row in rows]),
                )
            }

        players = []
        for row in rows:
            pid = row["player_id"]
            pos = row["position"]

            if pos == "DEF":
                avail = dst_availability.get(pid)
                tw = dst_team_weeks.get(row["team"], [])
                team_games = len(tw) or _REG_SEASON_TEAM_GAMES
            else:
                avail = availability.get(pid)
                tw = avail.get("team_weeks", []) if avail else []
                team_games = (
                    avail.get("team_games", _REG_SEASON_TEAM_GAMES)
                    if avail
                    else _REG_SEASON_TEAM_GAMES
                )

            gp = avail["games_played"] if avail else 0
            wp = sorted(avail["weeks"]) if avail else []
            gm = max(0, team_games - gp) if avail else None
            sample = (
                "full"
                if gp >= _THIN_SAMPLE_GAMES
                else "thin"
                if gp > 0
                else "none"
            )

            # Field for field, the research board's derivation. Any change here
            # has to be made there too, or the two screens start disagreeing
            # about the same player again.
            stats = season_stats.get(pid)
            ppr_total = stats["ppr_total"] if stats else None
            ppr_per_game_played = (
                round(ppr_total / gp, 1)
                if ppr_total is not None and gp
                else None
            )
            ppr_per_team_game = (
                # Per-player team_games, not the 17-constant (see the board).
                round(ppr_total / team_games, 1)
                if ppr_total is not None and team_games
                else None
            )
            xfp_per_game = (
                round(stats["xfp_per_game"], 1)
                if stats and stats["xfp_per_game"] is not None
                else None
            )
            snap_pct = (
                round(stats["snap_pct"] * 100, 0)
                if stats and stats["snap_pct"] is not None
                else None
            )
            target_share = (
                round(stats["target_share"] * 100, 1)
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

            players.append({
                "player_id": pid,
                "name": row["name"],
                "position": pos,
                "team": row["team"],
                "adp": row["adp"],
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
            })

        return _json(
            {
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
        )
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

        inserted = 0
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            pick_no = pick.get("pick_no")
            team_no = pick.get("team_no")
            player_id = pick.get("player_id")
            auto = int(pick.get("auto", 0) or 0)

            if not isinstance(pick_no, int) or pick_no < 1 or pick_no > 180:
                continue
            if not isinstance(team_no, int) or team_no < 1 or team_no > 12:
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
        # 1. Player lookup
        player = connection.execute(
            "SELECT id, name, team, position, active FROM players WHERE id=? AND league='nfl'",
            (player_id,),
        ).fetchone()

        if player is None:
            return _json({"error": "Player not found"}, status=404)

        name = player["name"]
        team = player["team"]
        position = player["position"]
        active = bool(player["active"])

        # 2. ADP / percent owned from nfl_adp
        adp = None
        percent_owned = None
        adp_row = connection.execute(
            "SELECT adp, percent_owned FROM nfl_adp WHERE player_id=? AND season=?",
            (player_id, _CURRENT_SEASON),
        ).fetchone()
        if adp_row:
            adp = adp_row["adp"]
            percent_owned = adp_row["percent_owned"]

        # 3. Season stats from player_game_logs
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)
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
            team_games = len(team_weeks) or _REG_SEASON_TEAM_GAMES
        else:
            availability = availability_by_player.get(player_id)
            team_weeks = availability.get("team_weeks", []) if availability else []
            team_games = (
                availability.get("team_games", _REG_SEASON_TEAM_GAMES)
                if availability
                else _REG_SEASON_TEAM_GAMES
            )

        games_played = availability["games_played"] if availability else 0
        weeks_played = sorted(availability["weeks"]) if availability else []

        # Sample classification
        if games_played == 0:
            sample = "none"
        elif games_played < _THIN_SAMPLE_GAMES:
            sample = "thin"
        else:
            sample = "full"

        # PPR calculations
        ppr_total = _season_stats["ppr_total"] if _season_stats else None
        ppr_per_game_played = (
            round(ppr_total / games_played, 1)
            if ppr_total is not None and games_played
            else None
        )
        ppr_per_team_game = (
            round(ppr_total / team_games, 1)
            if ppr_total is not None and team_games
            else None
        )
        snap_pct = (
            round(_season_stats["snap_pct"] * 100, 0)
            if _season_stats and _season_stats["snap_pct"] is not None
            else None
        )
        target_share = (
            round(_season_stats["target_share"] * 100, 1)
            if _season_stats and _season_stats["target_share"] is not None
            else None
        )
        xfp_per_game = (
            round(_season_stats["xfp_per_game"], 1)
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
        })
    finally:
        connection.close()


# ---------------------------------------------------------------------------
#  Per-game log  (the research half of the player overlay)
# ---------------------------------------------------------------------------

# Which per-game fields matter, by position. Deliberately narrow: the log rows
# carry ~52 keys and a research table that shows all of them shows none of them.
_LOG_FIELDS = {
    "QB": ["off_pct", "cmp", "att", "pass_yds", "pass_td", "intc", "carries",
           "rush_yds", "rush_td", "fpts_ppr", "xfpts_ppr"],
    "RB": ["off_pct", "carries", "rush_yds", "rush_td", "targets", "rec",
           "rec_yds", "rec_td", "fpts_ppr", "xfpts_ppr"],
    "WR": ["off_pct", "targets", "target_share", "rec", "rec_yds", "rec_td",
           "adot", "separation", "fpts_ppr", "xfpts_ppr"],
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
                "stats": {f: stats.get(f) for f in fields},
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
