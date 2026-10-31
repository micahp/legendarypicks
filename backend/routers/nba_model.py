"""Read-only NBA research-model API for league model tabs."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse
import pytz
from pytz.exceptions import UnknownTimeZoneError

from nba_game_model import MODEL_INFO
from nba_model_store import (DEFAULT_DB, LOCK_PROTOCOL, MODEL_IDS,
                             export_payload, export_projection_payload,
                             export_record_page, open_db)

router = APIRouter()
MODEL_DB = os.environ.get("NBA_MODEL_DB_PATH", DEFAULT_DB)
ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "research" / "nba-game-model" / "benchmark.json"
SOURCE = "standalone NBA research model database"


def _benchmark() -> dict:
    try:
        return json.loads(BENCHMARK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="NBA research benchmark report is unavailable") from exc


@router.get("/api/nba/model/locks")
def nba_model_locks(response: Response,
                    season: int = Query(2027, ge=2020, le=2100),
                    view: str = "all"):
    if view not in {"all", "projections"}:
        raise HTTPException(status_code=422, detail="view must be 'all' or 'projections'")
    benchmark = _benchmark()
    if not os.path.exists(MODEL_DB):
        payload = {
            "league": "nba", "season": season, "state": "awaiting_history_import",
            "source": SOURCE, "default_model": "G3", "models": MODEL_INFO,
            "records": {}, "games": [], "benchmark": benchmark,
            "lock_protocol": LOCK_PROTOCOL,
        }
    else:
        try:
            con = open_db(MODEL_DB, readonly=True)
            try:
                payload = (export_projection_payload(con, season, benchmark)
                           if view == "projections" else export_payload(con, season, benchmark))
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="NBA research model database is unavailable") from exc
    headers = {"X-LP-Data-Source": SOURCE, "Cache-Control": "no-store"}
    response.headers.update(headers)
    return JSONResponse(payload, headers=headers)


@router.get("/api/nba/model/record")
def nba_model_record(response: Response,
                     season: int = Query(2027, ge=2020, le=2100),
                     model: str = Query("G3"),
                     days: int = Query(7, ge=1, le=31),
                     before: Optional[str] = Query(None, max_length=10),
                     timezone_name: str = Query("UTC", alias="timezone", max_length=64)):
    if model not in MODEL_IDS:
        raise HTTPException(status_code=422, detail="model must be G1, G2, or G3")
    try:
        pytz.timezone(timezone_name)
    except UnknownTimeZoneError as exc:
        raise HTTPException(status_code=422, detail="timezone must be a valid IANA timezone") from exc

    if not os.path.exists(MODEL_DB):
        payload = {"season": season, "model": model, "games": [], "record": None,
                   "has_more": False, "next_before": None}
    else:
        try:
            con = open_db(MODEL_DB, readonly=True)
            try:
                payload = export_record_page(con, season, model, days, before, timezone_name)
            finally:
                con.close()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="NBA research model database is unavailable") from exc
    headers = {"X-LP-Data-Source": SOURCE, "Cache-Control": "no-store"}
    response.headers.update(headers)
    return JSONResponse(payload, headers=headers)
