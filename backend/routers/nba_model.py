"""Read-only NBA research-model API. It is exposed only by a dev deployment."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from nba_game_model import MODEL_INFO
from nba_model_store import DEFAULT_DB, LOCK_PROTOCOL, export_payload, open_db

router = APIRouter()
MODEL_DB = os.environ.get("NBA_MODEL_DB_PATH", DEFAULT_DB)
ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "research" / "nba-game-model" / "benchmark.json"
SOURCE = "dev-only standalone NBA research model database"


def _dev_scope_enabled() -> bool:
    picks = os.environ.get("LP_DB_PATH")
    model = os.environ.get("NBA_MODEL_DB_PATH", DEFAULT_DB)
    if not picks:
        return False
    try:
        return (Path(picks).expanduser().resolve().name == "picks.dev.db"
                and Path(model).expanduser().resolve().name == "nba-model.dev.sqlite3")
    except OSError:
        return False


def _benchmark() -> dict:
    try:
        return json.loads(BENCHMARK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="NBA research benchmark report is unavailable") from exc


@router.get("/api/nba/model/locks")
def nba_model_locks(response: Response,
                    season: int = Query(2027, ge=2020, le=2100)):
    if not _dev_scope_enabled():
        raise HTTPException(status_code=404, detail="NBA research model is available on dev only")
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
                payload = export_payload(con, season, benchmark)
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="NBA research model database is unavailable") from exc
    headers = {"X-LP-Data-Source": SOURCE, "Cache-Control": "no-store"}
    response.headers.update(headers)
    return JSONResponse(payload, headers=headers)
