from __future__ import annotations

"""NFL mock draft — pool endpoint + draft CRUD for single-player mock drafts vs. ADP bots.

SPEC-slice-D-mock-draft.md:
  - Pool: GET /api/nfl/mock-draft/pool?season=2026 — ~300 ranked players (QB/RB/WR/TE/PK).
  - Draft CRUD: create, append picks, resume, list — keyed by X-Device-Id.
  - Own _DB from LP_DB_PATH (no _core.py dependency).
"""

import os
import sqlite3
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
#  Module-level DB path — mirrors ufc_picks.py / nfl_draft_notes.py
# ---------------------------------------------------------------------------

_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)

_CONTRACT = "nfl-mock-draft-v1"
_CURRENT_SEASON = 2026
_ADP_SENTINEL = 169.0
_REG_SEASON_TEAM_GAMES = 17
_POSTSEASON_FIRST_WEEK = 19
_THIN_SAMPLE_GAMES = 4
_POOL_CAP = 300

# Draftable positions: skill positions plus kickers (code is PK, not K — §1 of spec).
_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK")


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

        # Per-player aggregates: games_played, weeks_played, and primary_team
        # (the team he logged the most games for that season — handles mid-season
        # trades and team-code mismatches between the players table and the logs,
        # exactly as nfl_offseason.py:571-605 does).  Ties are broken by
        # preferring the team with the highest logged week (the one he finished on).
        agg_rows = connection.execute(
            """SELECT player_id, COUNT(*) AS games_played,
                      GROUP_CONCAT(CAST(game_no AS INTEGER)) AS weeks_csv,
                      team
               FROM player_game_logs
               WHERE league='nfl' AND season=? AND player_id IS NOT NULL
                 AND CAST(game_no AS INTEGER) < ?
               GROUP BY player_id, team""",
            (_log_season, _POSTSEASON_FIRST_WEEK),
        ).fetchall()

        _per_player: dict[int, dict] = {}
        for row in agg_rows:
            pid = row["player_id"]
            team = row["team"]
            games = row["games_played"]
            weeks = [int(w) for w in (row["weeks_csv"] or "").split(",") if w]
            if pid not in _per_player:
                _per_player[pid] = {
                    "games_played": 0, "weeks": set(),
                    "team_counts": {}, "team_max_week": {},
                }
            rec = _per_player[pid]
            rec["games_played"] += games
            rec["weeks"].update(weeks)
            rec["team_counts"][team] = rec["team_counts"].get(team, 0) + games
            max_w = max(weeks) if weeks else 0
            rec["team_max_week"][team] = max(rec["team_max_week"].get(team, 0), max_w)

        aggregates: dict[int, int] = {}
        weeks_played_map: dict[int, list[int]] = {}
        primary_team_map: dict[int, str] = {}
        for pid, rec in _per_player.items():
            aggregates[pid] = rec["games_played"]
            weeks_played_map[pid] = sorted(rec["weeks"])
            # Primary team = most games; ties go to the later-week team.
            primary_team_map[pid] = max(
                rec["team_counts"],
                key=lambda t: (rec["team_counts"][t], rec["team_max_week"].get(t, 0)),
            )

        # ------------------------------------------------------------------
        # Team weeks — which weeks each team actually played (bye-aware).
        # Keyed by log-season team abbreviation, NOT by players.team, because
        # those differ (LAR/LA, WSH/WAS, AZ/ARI).
        # ------------------------------------------------------------------
        from collections import defaultdict
        _team_weeks_raw: dict[str, set[int]] = defaultdict(set)
        for tw_row in connection.execute(
            """SELECT team, CAST(game_no AS INTEGER) AS week
               FROM player_game_logs
               WHERE league='nfl' AND season=? AND team IS NOT NULL
                 AND CAST(game_no AS INTEGER) < ?
               GROUP BY team, game_no""",
            (_log_season, _POSTSEASON_FIRST_WEEK),
        ):
            try:
                _team_weeks_raw[tw_row["team"]].add(tw_row["week"])
            except (TypeError, ValueError):
                continue
        team_weeks_map: dict[str, list[int]] = {
            team: sorted(weeks) for team, weeks in _team_weeks_raw.items()
        }

        # ------------------------------------------------------------------
        # Query the pool: draftable positions, active players, from nfl_adp.
        # First tier: ADP < 169.0 (real ADP), sorted by ADP ascending.
        # Second tier: ADP >= 169.0 AND percent_owned > 0, sorted by
        #   percent_owned descending then name.
        # Cap at 300 total.
        # ------------------------------------------------------------------
        placeholders = ",".join("?" for _ in _DRAFT_POSITIONS)
        rows = connection.execute(
            f"""SELECT p.id AS player_id, p.name, p.position, p.team,
                       na.adp, na.percent_owned
                FROM players p
                JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                WHERE p.league = 'nfl' AND p.active = 1
                  AND p.position IN ({placeholders})
                  AND (na.adp < ? OR na.percent_owned > 0)
                ORDER BY
                  CASE WHEN na.adp < ? THEN 0 ELSE 1 END,
                  CASE WHEN na.adp < ? THEN na.adp ELSE 999999.0 END ASC,
                  na.percent_owned DESC,
                  p.name ASC
                LIMIT ?""",
            (
                season,
                *_DRAFT_POSITIONS,
                _ADP_SENTINEL,
                _ADP_SENTINEL,
                _ADP_SENTINEL,
                _POOL_CAP,
            ),
        ).fetchall()

        players = []
        for row in rows:
            pid = row["player_id"]
            games_played = aggregates.get(pid, 0)
            in_aggregates = pid in aggregates

            if not in_aggregates:
                sample = "none"
                games_missed = None
            elif games_played < _THIN_SAMPLE_GAMES:
                sample = "thin"
                games_missed = _REG_SEASON_TEAM_GAMES - games_played
            else:
                sample = "full"
                games_missed = _REG_SEASON_TEAM_GAMES - games_played

            players.append(
                {
                    "player_id": pid,
                    "name": row["name"],
                    "position": row["position"],
                    "team": row["team"],
                    "adp": row["adp"],
                    "percent_owned": row["percent_owned"],
                    "sample": sample,
                    "games_played": games_played,
                    "games_missed": games_missed,
                    "weeks_played": weeks_played_map.get(pid, []),
                    "team_weeks": team_weeks_map.get(primary_team_map.get(pid, ""), []),
                }
            )

        return _json(
            {
                "contract": _CONTRACT,
                "season": season,
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

    Body: {season, seat, seed}.  X-Device-Id required.
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

    if not isinstance(season, int) or season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)
    if not isinstance(seat, int) or seat < 1 or seat > 12:
        return _json({"error": "seat must be 1..12"}, status=400)
    if not isinstance(seed, int):
        return _json({"error": "seed must be an integer"}, status=400)

    now = int(time.time() * 1000)
    draft_id = str(uuid.uuid4())

    connection = _conn()
    try:
        connection.execute(
            """INSERT INTO nfl_mock_drafts
               (id, device_id, season, seat, teams, rounds, seed, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 12, 15, ?, 'active', ?, ?)""",
            (draft_id, device_id, season, seat, seed, now, now),
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


@router.get("/api/nfl/mock-draft/{draft_id}")
def get_draft(draft_id: str, x_device_id: Optional[str] = Header(None)):
    """Resume a draft — returns draft metadata + all picks.

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
            """SELECT id, season, seat, teams, rounds, seed, status,
                      created_at, updated_at, completed_at
               FROM nfl_mock_drafts
               WHERE device_id = ?
               ORDER BY updated_at DESC""",
            (device_id,),
        ).fetchall()

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
            }
            for row in rows
        ]

        return _json({"drafts": drafts})
    finally:
        connection.close()
