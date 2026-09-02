"""Draft CRUD endpoints for the NFL mock-draft package."""

import time
import uuid
from typing import Optional

from fastapi import Header, Request

from . import router
from .constants import (
    _CONTRACT,
    _CURRENT_SEASON,
    _DEFAULT_TEAMS,
    _LEAGUE_SIZES,
    _ROUNDS,
)
from .db import _conn
from .helpers import _compute_round_and_pick, _device_id, _json, _missing_picks


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