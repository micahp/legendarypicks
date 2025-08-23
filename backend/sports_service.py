from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
from datetime import datetime
import logging

try:
    from sportsipy.nba.boxscore import Boxscores as NBABoxscores
    from sportsipy.nba.roster import Player as NBAPlayer
    from sportsipy.nfl.boxscore import Boxscores as NFLBoxscores
    from sportsipy.nfl.roster import Player as NFLPlayer
    from sportsipy.mlb.boxscore import Boxscores as MLBBoxscores
    from sportsipy.mlb.roster import Player as MLBPlayer
    from sportsipy.nhl.boxscore import Boxscores as NHLBoxscores
    from sportsipy.nhl.roster import Player as NHLPlayer
    SPORTS_LIB_AVAILABLE = True
except Exception as e:
    logging.exception("sportsipy not available: %s", e)
    SPORTS_LIB_AVAILABLE = False

app = FastAPI(
    title="Sports Stats API",
    description="Multi-league sports data and prediction service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "sample_data.json")
with open(DATA_FILE) as f:
    DATA = json.load(f)

predictions = []
prediction_counter = 1

class PredictionIn(BaseModel):
    league: str
    gameId: str
    predictedWinner: str

@app.get("/")
async def root():
    return {"message": "Sports Stats API", "leagues": list(DATA.keys())}

@app.get("/api/{league}/games")
async def get_games(league: str):
    league = league.lower()

    games = None
    if SPORTS_LIB_AVAILABLE:
        games = _fetch_games_from_library(league)

    if not games:
        if league not in DATA:
            raise HTTPException(status_code=404, detail="League not found")
        return DATA[league]["games"]

    return games

@app.get("/api/{league}/players/{player_id}")
async def get_player_stats(league: str, player_id: str):
    league = league.lower()

    player = None
    if SPORTS_LIB_AVAILABLE:
        player = _fetch_player_from_library(league, player_id)

    if not player:
        if league not in DATA:
            raise HTTPException(status_code=404, detail="League not found")
        players = DATA[league]["players"]
        if player_id not in players:
            raise HTTPException(status_code=404, detail="Player not found")
        return players[player_id]

    return player

@app.post("/api/predictions")
async def submit_prediction(pred: PredictionIn):
    global prediction_counter
    entry = pred.dict()
    entry["id"] = prediction_counter
    entry["correct"] = evaluate_prediction(entry)
    prediction_counter += 1
    predictions.append(entry)
    return entry

@app.get("/api/predictions")
async def list_predictions():
    for p in predictions:
        if p["correct"] is None:
            p["correct"] = evaluate_prediction(p)
    return predictions

def evaluate_prediction(pred):
    league = pred["league"].lower()
    if league not in DATA:
        return None
    game = next((g for g in DATA[league]["games"] if g["gameId"] == pred["gameId"]), None)
    if not game or game.get("status") != "FINAL":
        return None
    winner = game["homeTeam"]["teamId"] if game["homeTeam"].get("score", 0) >= game["awayTeam"].get("score", 0) else game["awayTeam"]["teamId"]
    return pred["predictedWinner"].lower() == winner.lower()


def _fetch_games_from_library(league: str):
    """Attempt to fetch games from sportsipy for the given league."""
    today = datetime.utcnow().date()
    key = f"{today.month}-{today.day}-{today.year}"
    try:
        if league == "nba":
            bs = NBABoxscores(today)
        elif league == "nfl":
            bs = NFLBoxscores(today)
        elif league == "mlb":
            bs = MLBBoxscores(today)
        elif league == "nhl":
            bs = NHLBoxscores(today)
        else:
            return None
        raw_games = bs.games.get(key, [])
        games = []
        for g in raw_games:
            games.append({
                "gameId": g.get("boxscore"),
                "homeTeam": {
                    "teamId": g.get("home_name"),
                    "name": g.get("home_name"),
                    "score": g.get("home_score"),
                },
                "awayTeam": {
                    "teamId": g.get("away_name"),
                    "name": g.get("away_name"),
                    "score": g.get("away_score"),
                },
                "startTime": g.get("time", ""),
                "status": "FINAL" if g.get("home_score") is not None else "SCHEDULED",
            })
        return games
    except Exception as exc:
        logging.exception("Failed fetching %s games: %s", league, exc)
        return None


def _fetch_player_from_library(league: str, player_id: str):
    """Attempt to fetch player stats using sportsipy."""
    try:
        if league == "nba":
            p = NBAPlayer(player_id)
        elif league == "nfl":
            p = NFLPlayer(player_id)
        elif league == "mlb":
            p = MLBPlayer(player_id)
        elif league == "nhl":
            p = NHLPlayer(player_id)
        else:
            return None
        data = {k.lstrip("_"): v for k, v in vars(p).items() if not k.startswith("_")}
        return data
    except Exception as exc:
        logging.exception("Failed fetching %s player %s: %s", league, player_id, exc)
        return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
