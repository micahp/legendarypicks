#!/usr/bin/env python3
"""sports_service.py — unified multi-league sports API (ESPN-backed) + prediction store.

ONE service. Replaces the old sportsipy-based `sports_service` and the NBA-only `nba_service`
(now a deprecation stub). All data flows through espn_client (free, reliable, every league).

What changed from the original:
  - real data for ALL leagues (was: dead sportsipy + a 1-game hardcoded fixture fallback)
  - predictions persisted to SQLite and graded against REAL finals (was: in-memory list vs fixture)
  - /strength endpoint: teams ranked by win% / differential / form — the quality prior shared
    with the prediction-market trading strategy (its only unfalsified edge: buy undervalued QUALITY)
"""
import os, sqlite3, datetime as dt
from contextlib import closing
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import espn_client as espn

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
ALLOWED_ORIGINS = os.environ.get("LP_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3007").split(",")

app = FastAPI(title="Legendary Picks Sports API", description="Multi-league sports data (ESPN)", version="2.0.0")
print(f"DEBUG: espn_client leagues: {sorted(espn.LEAGUES)}")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    with closing(_db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, game_id TEXT NOT NULL, predicted_winner TEXT NOT NULL,
          created_at TEXT NOT NULL, correct INTEGER);
        CREATE TABLE IF NOT EXISTS strength_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, abbrev TEXT NOT NULL,
          win_pct REAL, differential REAL, wins INTEGER, losses INTEGER);
        """)
        con.commit()


_init_db()


class PredictionIn(BaseModel):
    league: str
    game_id: str
    predicted_winner: str   # team abbreviation, e.g. "MIL"


@app.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


@app.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — real data from official CDL schedule page
        import cdl_client
        return cdl_client.get_matches(date_str=date)
    try:
        return espn.games(league, date)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    _snapshot_strength(league.lower(), rows)
    return rows


@app.get("/api/{league}/strength/{team}")
def get_team_strength(league: str, team: str):
    try:
        m = espn.team_strength_map(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = m.get(team.upper())
    if not row:
        raise HTTPException(404, f"team {team!r} not found in {league}")
    return row


@app.get("/api/{league}/boxscore/{game_id}")
def get_boxscore(league: str, game_id: str):
    try:
        return espn.boxscore(league, game_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/{league}/team/{team}/roster")
def get_roster(league: str, team: str):
    try:
        return espn.roster(league, team)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/predictions")
def submit_prediction(pred: PredictionIn):
    league = pred.league.lower()
    if league not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {pred.league!r}")
    correct = _evaluate(league, pred.game_id, pred.predicted_winner)
    with closing(_db()) as con:
        cur = con.execute(
            "INSERT INTO predictions(league,game_id,predicted_winner,created_at,correct) VALUES(?,?,?,?,?)",
            (league, pred.game_id, pred.predicted_winner.upper(),
             dt.datetime.now(dt.timezone.utc).isoformat(),
             None if correct is None else int(correct)))
        con.commit()
        pid = cur.lastrowid
    return {"id": pid, "league": league, "game_id": pred.game_id,
            "predicted_winner": pred.predicted_winner.upper(), "correct": correct}


@app.get("/api/predictions")
def list_predictions():
    out = []
    with closing(_db()) as con:
        for r in con.execute("SELECT * FROM predictions ORDER BY id").fetchall():
            correct = r["correct"]
            if correct is None:                     # re-grade: the game may have finished since
                correct = _evaluate(r["league"], r["game_id"], r["predicted_winner"])
                if correct is not None:
                    con.execute("UPDATE predictions SET correct=? WHERE id=?", (int(correct), r["id"]))
            out.append({"id": r["id"], "league": r["league"], "game_id": r["game_id"],
                        "predicted_winner": r["predicted_winner"], "correct": correct})
        con.commit()
    accuracy = None
    graded = [p for p in out if p["correct"] is not None]
    if graded:
        accuracy = round(sum(1 for p in graded if p["correct"]) / len(graded), 4)
    return {"predictions": out, "graded": len(graded), "accuracy": accuracy}


def _evaluate(league, game_id, predicted_winner):
    """True/False vs the REAL final, or None if the game isn't final yet."""
    try:
        res = espn.game_result(league, game_id)
    except ValueError:
        return None
    if res["winner"] is None:
        return None
    return predicted_winner.upper() == res["winner"].upper()


def _snapshot_strength(league, rows):
    """Persist a strength snapshot so we accumulate history (the trading side wants the time series)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO strength_snap(captured_at,league,abbrev,win_pct,differential,wins,losses) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, r["abbrev"], r["win_pct"], r["differential"], r["wins"], r["losses"])
             for r in rows])
        con.commit()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
