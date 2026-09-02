"""Read-only API for the upcoming-matches board (matches that have not started).

Published by upcoming_board.py in the trading repo. No score is carried here and none
should be added: before a match starts there is no tape, so absorption, turn and game state
do not exist. This surface is a watchlist with the tournament's own reasons attached.
"""

import datetime as dt
import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

SNAPSHOT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "upcoming_board.json")
)
MAX_SNAPSHOT_BYTES = 512 * 1024
STALE_AFTER_S = 900          # upcoming markets move slowly; 15 min is generous but honest


@router.get("/api/live/upcoming-board")
def upcoming_board():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        if os.path.getsize(SNAPSHOT_PATH) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot too large")
        with open(SNAPSHOT_PATH) as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return JSONResponse({"available": False, "reason": "No snapshot yet.", "rows": []})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({"available": False, "reason": f"Unreadable: {exc}", "rows": []})

    age = None
    stale = True
    if payload.get("generated_at"):
        try:
            age = (now - dt.datetime.fromisoformat(payload["generated_at"])).total_seconds()
            stale = age > STALE_AFTER_S
        except ValueError:
            age = None
    payload["available"] = True
    payload["age_seconds"] = None if age is None else round(age, 1)
    payload["stale"] = stale
    payload["served_at"] = now.isoformat()
    return JSONResponse(payload)
