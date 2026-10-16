"""Read-only API for NHL model locks stored outside the LP picks databases."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from capture_nhl_game_lines import fetch_events, refresh_lines
from nhl_model_store import (DEFAULT_DB, DEFAULT_FEED, export_locked, export_previews,
                             latest_game_lines, latest_standings, open_db)

router = APIRouter()
MODEL_DB = os.environ.get("NHL_MODEL_DB_PATH", DEFAULT_DB)


def locks_payload(db_path: str, season: int) -> dict:
    if not os.path.exists(db_path):
        return {"model_version": "per-model-locked", "model_versions": {},
                "default_model": "B7_elo_xg_poisson", "frozen_at_utc": None,
                "source": "standalone NHL model database", "state": "awaiting_first_lock",
                "games": [], "missed_locks": [], "previews": [], "lines": {}, "standings": {}}
    try:
        con = open_db(db_path, readonly=True)
        try:
            payload = export_locked(con, season)
            payload["lines"] = latest_game_lines(con)
            payload["previews"] = export_previews(con, season, dt.datetime.now(dt.timezone.utc),
                                                  payload["lines"])
            payload["standings"] = latest_standings(con, season)
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="NHL model lock database is unavailable") from exc
    payload["state"] = ("available" if payload["games"] else
                         "missed_locks" if payload["missed_locks"] else "awaiting_first_lock")
    return payload


@router.get("/api/nhl/model/locks")
def nhl_model_locks(response: Response, season: int = Query(2026, ge=2020, le=2100)):
    payload = locks_payload(MODEL_DB, season)
    response.headers["X-LP-Data-Source"] = "standalone NHL model database"
    response.headers["Cache-Control"] = "no-store"
    return JSONResponse(payload, headers={"X-LP-Data-Source": "standalone NHL model database",
                                        "Cache-Control": "no-store"})


_REFRESH_LOCK = threading.Lock()


@router.post("/api/nhl/model/lines/refresh")
def refresh_nhl_lines():
    """Pull Bovada NHL lines when the newest snapshot is older than 15 minutes; otherwise do nothing."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"refreshed": False, "reason": "in_progress"}
    try:
        return refresh_lines(MODEL_DB, DEFAULT_FEED, fetch_events, dt.datetime.now(dt.timezone.utc))
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return JSONResponse({"refreshed": False, "reason": "error", "detail": str(exc)}, status_code=502)
    finally:
        _REFRESH_LOCK.release()
