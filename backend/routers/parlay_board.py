"""Read-only API for Parlay board — who is up a break in the set being played now.

Micah, 2026-09-03: "a roll at the top of the plays page for set watch, for people
who have broken and we are expecting them to win the set. That's a play in itself."

It IS its own play, and a different one from the match contract. Up a break in the
current set says a lot about that set and much less about the match, so the row
carries the SET market price (KXATPSETWINNER / KXWTASETWINNER), not the match price.

Same shape and same discipline as swing_board: the trading repo owns the model and
publishes atomically, this router only reads the file. Freshness is computed and
returned rather than left for the client to infer, because a parlay row that has
stopped updating is worse than an empty one — the set it describes may already be
over.
"""

import datetime as dt
import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

SNAPSHOT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "parlay_board.json")
)
MAX_SNAPSHOT_BYTES = 512 * 1024
# Legs are gated on spread and volume, which move slower than a set does.
STALE_AFTER_S = 180


@router.get("/api/live/parlay")
def parlay_board():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        size = os.path.getsize(SNAPSHOT_PATH)
        if size > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"snapshot too large: {size} bytes")
        with open(SNAPSHOT_PATH) as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return JSONResponse(
            {"available": False, "reason": "No parlay snapshot published yet.", "combos": []},
            status_code=200,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(
            {"available": False, "reason": f"Snapshot unreadable: {exc}", "combos": []},
            status_code=200,
        )

    age = None
    stale = True
    generated = payload.get("generated_at")
    if generated:
        try:
            age = (now - dt.datetime.fromisoformat(generated)).total_seconds()
            stale = age > STALE_AFTER_S
        except ValueError:
            age = None

    payload["available"] = True
    payload["age_seconds"] = None if age is None else round(age, 1)
    payload["stale"] = stale
    payload["stale_after_seconds"] = STALE_AFTER_S
    payload["served_at"] = now.isoformat()
    return JSONResponse(payload)
