"""Read-only API for the live buy-only markdown board (/live-discounts).

The trading repo owns the model and atomically publishes the snapshot; this router only
reads the destination file. No Kalshi client and no network request happens here.

Separate from ``/api/live/discounts`` on purpose. That endpoint is MLB-only and keys off
ESPN situations; this one ranks fadeable markdowns across every series on the Kalshi tape,
which is what the US Open and Leagues Cup windows actually need.

Freshness is reported, never assumed. The writer runs on a short cron, so a snapshot that
stopped updating means the tape stopped — the single most misleading thing this surface
could do is render a stale board as a calm one, so ``stale`` is always computed and
returned rather than left for the client to infer.
"""

import datetime as dt
import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

SNAPSHOT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "swing_board.json")
)
MAX_SNAPSHOT_BYTES = 512 * 1024
STALE_AFTER_S = 180


@router.get("/api/live/swing-board")
def swing_board():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        size = os.path.getsize(SNAPSHOT_PATH)
        if size > MAX_SNAPSHOT_BYTES:
            raise ValueError(f"snapshot too large: {size} bytes")
        with open(SNAPSHOT_PATH) as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return JSONResponse(
            {"available": False, "reason": "No snapshot published yet.", "cards": []},
            status_code=200,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(
            {"available": False, "reason": f"Snapshot unreadable: {exc}", "cards": []},
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
