from nba_api.live.nba.endpoints import scoreboard
from nba_api.stats.endpoints import commonplayerinfo, playergamelog, scoreboardv2
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

@app.get("/api/games/by-date")
async def get_games_by_date(date: str):
    """
    Returns games for a specific date using NBA Stats ScoreboardV2 to avoid third-party rate limits.
    Expects date in YYYY-MM-DD and converts to MM/DD/YYYY as required by ScoreboardV2.
    """
    try:
        # Convert YYYY-MM-DD -> MM/DD/YYYY
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_mmddyyyy = dt.strftime("%m/%d/%Y")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        sb = scoreboardv2.ScoreboardV2(game_date=date_mmddyyyy)
        data = sb.get_dict()

        # Extract result sets by name
        result_sets = {rs['name']: rs for rs in data.get('resultSets', [])}
        game_header = result_sets.get('GameHeader') or {}
        line_score = result_sets.get('LineScore') or {}

        gh_headers = game_header.get('headers', [])
        gh_rows = game_header.get('rowSet', [])
        ls_headers = line_score.get('headers', [])
        ls_rows = line_score.get('rowSet', [])

        # Build maps for quick lookup
        idx = {h: i for i, h in enumerate(gh_headers)}
        ls_idx = {h: i for i, h in enumerate(ls_headers)}

        # Map GAME_ID -> { home: {...}, away: {...} }
        game_map = {}
        for row in gh_rows:
            game_id = row[idx.get('GAME_ID')]
            home_id = row[idx.get('HOME_TEAM_ID')]
            away_id = row[idx.get('VISITOR_TEAM_ID')]
            status_text = row[idx.get('GAME_STATUS_TEXT')]
            start_time = row[idx.get('GAME_DATE_EST')]
            game_map[game_id] = {
                'gameId': str(game_id),
                'homeTeam': {'teamId': str(home_id), 'name': str(home_id), 'score': None},
                'awayTeam': {'teamId': str(away_id), 'name': str(away_id), 'score': None},
                'startTime': start_time,
                'status': 'FINAL' if str(status_text).lower().startswith('final') else (
                    'LIVE' if 'in progress' in str(status_text).lower() else 'SCHEDULED'
                )
            }

        # Fill team names/scores from LineScore
        for row in ls_rows:
            game_id = row[ls_idx.get('GAME_ID')]
            team_id = row[ls_idx.get('TEAM_ID')]
            abbr = row[ls_idx.get('TEAM_ABBREVIATION')]
            pts = row[ls_idx.get('PTS')]
            if game_id in game_map:
                g = game_map[game_id]
                if str(team_id) == g['homeTeam']['teamId']:
                    g['homeTeam']['name'] = abbr
                    g['homeTeam']['score'] = pts
                elif str(team_id) == g['awayTeam']['teamId']:
                    g['awayTeam']['name'] = abbr
                    g['awayTeam']['score'] = pts

        return list(game_map.values())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching games for date {date}: {str(e)}")

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
        
        # Calculate fantasy score (Pts=1, Reb=1.2, Ast=1.5, Stl=3, Blk=3, TO=-1)
        fantasy_score = (
            stats[24] * 1.0 +  # Points
            stats[18] * 1.2 +  # Rebounds
            stats[19] * 1.5 +  # Assists
            stats[20] * 3.0 +  # Steals
            stats[21] * 3.0 -  # Blocks
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