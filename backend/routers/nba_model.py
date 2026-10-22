"""Read-only NBA research-model API. It is exposed only by a dev deployment."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from nba_game_model import MODEL_INFO
from nba_model_runtime import require_dev_picks_db
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


def _missed_schedule(con: sqlite3.Connection, season: int) -> list[dict] | None:
    """Read qualifying schedule metadata without blocking the model report."""
    try:
        picks = require_dev_picks_db()
        picks_uri = f"{Path(picks).as_uri()}?mode=ro"
        con.execute("ATTACH DATABASE ? AS nba_picks", (picks_uri,))
        try:
            rows = con.execute(
                "SELECT game_id,season,season_type,source,start_utc AS scheduled_start_utc,"
                "home_team,away_team FROM nba_picks.nba_schedule WHERE season=? "
                "AND season_type IN ('REG','CUP') AND source='nba.com' "
                "AND start_utc IS NOT NULL",
                (season,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.execute("DETACH DATABASE nba_picks")
    except (OSError, RuntimeError, sqlite3.Error):
        return None


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
                payload = export_payload(
                    con, season, benchmark, missed_schedule=_missed_schedule(con, season)
                )
            finally:
                con.close()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="NBA research model database is unavailable") from exc
    headers = {"X-LP-Data-Source": SOURCE, "Cache-Control": "no-store"}
    response.headers.update(headers)
    return JSONResponse(payload, headers=headers)
