"""Read-only API for the FBS model surface.

The forecasts live in their own SQLite file, written only by fbs_model_runner.py. This router
never writes, never fits, and never contacts a sportsbook.
"""
from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from fbs_model_store import DEFAULT_DB, DEFAULT_MODEL, MODEL_IDS, MODEL_LABELS, MODEL_NOTES, export_payload, open_db

router = APIRouter()
MODEL_DB = os.environ.get("FBS_MODEL_DB_PATH", DEFAULT_DB)
SOURCE = "standalone FBS model database"


@router.get("/api/ncaaf/model/locks")
def ncaaf_model_locks(response: Response, season: int = Query(2026, ge=2020, le=2100)):
    if not os.path.exists(MODEL_DB):
        payload = {
            "league": "ncaaf", "default_model": DEFAULT_MODEL,
            "models": [{"id": m, "label": MODEL_LABELS[m], "note": MODEL_NOTES[m]} for m in MODEL_IDS],
            "records": {}, "season": season, "games": [], "ratings": [], "meta": {},
            "state": "awaiting_first_projection", "source": SOURCE,
            "diagnostics": {"schema_status": "not_initialized"},
        }
    else:
        try:
            con = open_db(MODEL_DB, readonly=True)
            try:
                payload = export_payload(con, season)
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="FBS model database is unavailable") from exc
    headers = {"X-LP-Data-Source": SOURCE, "Cache-Control": "no-store"}
    response.headers.update(headers)
    return JSONResponse(payload, headers=headers)
