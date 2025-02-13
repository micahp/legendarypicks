from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import commonplayerinfo, playergamelog
from nba_api.stats.static import players
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict, List
import json
from datetime import datetime

app = FastAPI(
    title="NBA Stats API",
    description="API for NBA game data and player statistics",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "message": "NBA Stats API",
        "version": "1.0.0",
        "endpoints": [
            "/api/games/today",
            "/api/team/{team_id}/roster",
            "/api/player/{player_id}/stats"
        ]
    }

@app.get("/api/games/today")
async def get_todays_games():
    try:
        # Get today's scoreboard
        board = scoreboard.ScoreBoard()
        games = board.get_dict()['scoreboard']['games']
        
        # Format the response
        formatted_games = []
        for game in games:
            formatted_games.append({
                'gameId': game['gameId'],
                'homeTeam': {
                    'teamId': game['homeTeam']['teamId'],
                    'name': game['homeTeam']['teamName'],
                    'score': game['homeTeam'].get('score', 0)
                },
                'awayTeam': {
                    'teamId': game['awayTeam']['teamId'],
                    'name': game['awayTeam']['teamName'],
                    'score': game['awayTeam'].get('score', 0)
                },
                'startTime': game['gameTimeUTC'],
                'status': game['gameStatus']
            })
        
        return formatted_games
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching games: {str(e)}")

@app.get("/api/team/{team_id}/roster")
async def get_team_roster(team_id: str):
    try:
        # Get all players
        all_players = players.get_active_players()
        
        # Filter players by team ID
        team_players = [
            {
                'playerId': str(player['id']),
                'name': f"{player['first_name']} {player['last_name']}",
                'team': player['team_id'],
                'position': player['position'],
                'jerseyNumber': str(player.get('jersey_number', ''))
            }
            for player in all_players
            if str(player['team_id']) == team_id
        ]
        
        if not team_players:
            raise HTTPException(status_code=404, detail=f"No players found for team ID: {team_id}")
        
        return team_players
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching roster: {str(e)}")

@app.get("/api/player/{player_id}/stats")
async def get_player_stats(player_id: str):
    try:
        # Get player's recent game log
        game_log = playergamelog.PlayerGameLog(player_id=player_id)
        stats = game_log.get_dict()['resultSets'][0]['rowSet'][0]
        
        # Calculate fantasy score
        fantasy_score = (
            stats[24] * 1.0 +  # Points
            stats[18] * 1.2 +  # Rebounds
            stats[19] * 1.5 +  # Assists
            stats[20] * 2.0 +  # Steals
            stats[21] * 2.0 -  # Blocks
            stats[22] * 1.0    # Turnovers
        )
        
        return {
            'playerId': player_id,
            'gameStats': {
                'points': stats[24],
                'rebounds': stats[18],
                'assists': stats[19],
                'steals': stats[20],
                'blocks': stats[21],
                'turnovers': stats[22]
            },
            'fantasyScore': fantasy_score
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching player stats: {str(e)}")

@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "message": "Endpoint not found. Available endpoints:",
            "endpoints": [
                "/api/games/today",
                "/api/team/{team_id}/roster",
                "/api/player/{player_id}/stats"
            ]
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 