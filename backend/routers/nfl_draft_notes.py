from __future__ import annotations

"""NFL draft notes — server-side rank / watch / fade persistence.

Keyed by X-Device-Id with no auth gate.  Slice A of SPEC-accounts-and-mock-draft;
slice B will claim device-keyed rows on first sign-in via the ``user_id`` column.
"""

import os
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
#  Module-level DB path — mirrors ufc_picks.py so the router is self-contained
# ---------------------------------------------------------------------------

_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)

_CURRENT_SEASON = 2026
_CONTRACT = "nfl-draft-notes-v1"
_MAX_ROWS = 1000


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _conn():
    connection = sqlite3.connect(_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db():
    """Create the draft-notes table defensively.

    A notes-table failure must not prevent the sports API from starting
    (same pattern as ``ufc_picks.py``).
    """
    try:
        connection = _conn()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nfl_draft_notes (
                    device_id  TEXT    NOT NULL,
                    player_id  INTEGER NOT NULL,
                    season     INTEGER NOT NULL,
                    "rank"     INTEGER,
                    watch      INTEGER NOT NULL DEFAULT 0,
                    fade       INTEGER NOT NULL DEFAULT 0,
                    user_id    INTEGER,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (device_id, player_id, season)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_nfl_draft_notes_device "
                "ON nfl_draft_notes(device_id, season)"
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # A notes-table failure must not prevent the sports API from starting.
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


def _validate_player(connection, player_id: int) -> bool:
    """Return True when *player_id* exists as an NFL row.

    Does **not** require ``active=1`` so a retiree between page loads does not
    make an existing note un-writable (§3.1).
    """
    row = connection.execute(
        "SELECT 1 FROM players WHERE id=? AND league='nfl'",
        (player_id,),
    ).fetchone()
    return row is not None


def _row_count(connection, device_id: str, season: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM nfl_draft_notes "
        "WHERE device_id=? AND season=?",
        (device_id, season),
    ).fetchone()
    return row["n"]


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/nfl/draft-notes")
async def get_notes(
    season: int = Query(...),
    x_device_id: Optional[str] = Header(None),
):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "X-Device-Id header required"}, status=400)

    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)

    connection = _conn()
    try:
        rows = connection.execute(
            "SELECT player_id, \"rank\", watch, fade, updated_at "
            "FROM nfl_draft_notes "
            "WHERE device_id=? AND season=?",
            (device_id, season),
        ).fetchall()

        rank_obj = {}
        watch_obj = {}
        fade_obj = {}
        updated_at = None

        for row in rows:
            key = str(row["player_id"])
            if row["rank"] is not None:
                rank_obj[key] = row["rank"]
            if row["watch"]:
                watch_obj[key] = True
            if row["fade"]:
                fade_obj[key] = True
            if row["updated_at"] is not None:
                updated_at = (
                    row["updated_at"]
                    if updated_at is None
                    else max(updated_at, row["updated_at"])
                )

        return _json(
            {
                "contract": _CONTRACT,
                "season": season,
                "notes": {
                    "rank": rank_obj,
                    "watch": watch_obj,
                    "fade": fade_obj,
                },
                "note_count": len(rows),
                "updated_at": updated_at,
            }
        )
    finally:
        connection.close()


@router.put("/api/nfl/draft-notes")
async def put_note(
    request: Request,
    x_device_id: Optional[str] = Header(None),
):
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
    player_id = data.get("player_id")

    if not isinstance(season, int) or not isinstance(player_id, int):
        return _json({"error": "season and player_id must be integers"}, status=400)
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)
    if player_id <= 0:
        return _json({"error": "player_id must be positive"}, status=400)

    # Validate rank
    has_rank = "rank" in data
    rank_value = data.get("rank")
    if has_rank and rank_value is not None:
        if not isinstance(rank_value, int) or rank_value < 1 or rank_value > 999:
            return _json({"error": "rank must be null or an integer 1..999"}, status=400)

    # Validate watch
    has_watch = "watch" in data
    watch_value = data.get("watch")
    if has_watch:
        if watch_value is None:
            return _json({"error": "watch must be a boolean, not null"}, status=400)
        if not isinstance(watch_value, bool):
            return _json({"error": "watch must be a boolean"}, status=400)

    # Validate fade
    has_fade = "fade" in data
    fade_value = data.get("fade")
    if has_fade:
        if fade_value is None:
            return _json({"error": "fade must be a boolean, not null"}, status=400)
        if not isinstance(fade_value, bool):
            return _json({"error": "fade must be a boolean"}, status=400)

    now = int(time.time() * 1000)

    connection = _conn()
    try:
        # Validate player exists
        if not _validate_player(connection, player_id):
            return _json({"error": "player not found"}, status=404)

        # Load existing row (if any)
        existing = connection.execute(
            "SELECT \"rank\", watch, fade FROM nfl_draft_notes "
            "WHERE device_id=? AND player_id=? AND season=?",
            (device_id, player_id, season),
        ).fetchone()

        # Resolve final values
        if existing is None:
            final_rank = rank_value if has_rank else None
            final_watch = 1 if (watch_value if has_watch else False) else 0
            final_fade = 1 if (fade_value if has_fade else False) else 0
        else:
            final_rank = rank_value if has_rank else existing["rank"]
            final_watch = 1 if (watch_value if has_watch else bool(existing["watch"])) else 0
            final_fade = 1 if (fade_value if has_fade else bool(existing["fade"])) else 0

        # Delete-on-empty: when the result is all-default
        if final_rank is None and not final_watch and not final_fade:
            if existing is not None:
                connection.execute(
                    "DELETE FROM nfl_draft_notes "
                    "WHERE device_id=? AND player_id=? AND season=?",
                    (device_id, player_id, season),
                )
                connection.commit()
            return _json({"player_id": player_id, "deleted": True})

        # Enforce row cap before inserting a *new* row
        if existing is None and _row_count(connection, device_id, season) >= _MAX_ROWS:
            return _json(
                {"error": f"row cap of {_MAX_ROWS} reached for this device and season"},
                status=409,
            )

        connection.execute(
            """
            INSERT OR REPLACE INTO nfl_draft_notes
                (device_id, player_id, season, "rank", watch, fade, user_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (device_id, player_id, season, final_rank, final_watch, final_fade, now),
        )
        connection.commit()

        return _json(
            {
                "player_id": player_id,
                "rank": final_rank,
                "watch": bool(final_watch),
                "fade": bool(final_fade),
                "updated_at": now,
            }
        )
    finally:
        connection.close()


@router.post("/api/nfl/draft-notes/import")
async def import_notes(
    request: Request,
    x_device_id: Optional[str] = Header(None),
):
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
    notes = data.get("notes")

    if not isinstance(season, int):
        return _json({"error": "season must be an integer"}, status=400)
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)
    if not isinstance(notes, dict):
        return _json({"error": "notes must be an object"}, status=400)

    rank_obj = notes.get("rank") or {}
    watch_obj = notes.get("watch") or {}
    fade_obj = notes.get("fade") or {}

    if not isinstance(rank_obj, dict) or not isinstance(watch_obj, dict) or not isinstance(fade_obj, dict):
        return _json({"error": "notes.rank, notes.watch, notes.fade must be objects"}, status=400)

    # 1,000-entry cap before parsing individual player ids
    entry_count = len(rank_obj) + len(watch_obj) + len(fade_obj)
    if entry_count > _MAX_ROWS:
        return _json(
            {"error": f"notes object exceeds {_MAX_ROWS} entry cap"},
            status=400,
        )

    now = int(time.time() * 1000)
    imported = 0
    skipped = 0
    rejected = 0

    connection = _conn()
    try:
        # Gather existing player_ids for this device+season so we skip them
        existing_ids = {
            row["player_id"]
            for row in connection.execute(
                "SELECT player_id FROM nfl_draft_notes "
                "WHERE device_id=? AND season=?",
                (device_id, season),
            ).fetchall()
        }

        # Collect all (player_id, rank, watch, fade) tuples to insert
        candidates = {}

        for key, value in rank_obj.items():
            try:
                pid = int(key)
            except (ValueError, TypeError):
                rejected += 1
                continue
            if pid <= 0:
                rejected += 1
                continue
            if not isinstance(value, int) or value < 1 or value > 999:
                rejected += 1
                continue
            candidates.setdefault(pid, {})["rank"] = value

        for key in watch_obj:
            try:
                pid = int(key)
            except (ValueError, TypeError):
                rejected += 1
                continue
            if pid <= 0:
                rejected += 1
                continue
            candidates.setdefault(pid, {})["watch"] = 1

        for key in fade_obj:
            try:
                pid = int(key)
            except (ValueError, TypeError):
                rejected += 1
                continue
            if pid <= 0:
                rejected += 1
                continue
            candidates.setdefault(pid, {})["fade"] = 1

        for pid, fields in candidates.items():
            if pid in existing_ids:
                skipped += 1
                continue

            if not _validate_player(connection, pid):
                rejected += 1
                continue

            rank_val = fields.get("rank")
            watch_val = fields.get("watch", 0)
            fade_val = fields.get("fade", 0)

            # Skip rows that are all-default
            if rank_val is None and not watch_val and not fade_val:
                rejected += 1
                continue

            # Respect row cap
            if _row_count(connection, device_id, season) >= _MAX_ROWS:
                skipped += 1
                continue

            try:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO nfl_draft_notes
                        (device_id, player_id, season, "rank", watch, fade, user_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (device_id, pid, season, rank_val, watch_val, fade_val, now),
                )
                imported += 1
            except Exception:
                rejected += 1

        connection.commit()
        return _json({"imported": imported, "skipped": skipped, "rejected": rejected})
    finally:
        connection.close()
