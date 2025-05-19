# src/core/nba_data.py
from nba_api.stats.endpoints import scoreboardv2, boxscoreplayertrackv2
from datetime import datetime
from typing import List, Dict, Any
import time
import os # For checking environment variable

# Example Mock Data
MOCK_BOX_SCORES = [
    {
        "player_id": 203999, "player_name": "Nikola Jokic", "game_id": "0022300001", 
        "team_abbreviation": "DEN", "PTS": 30, "REB": 15, "AST": 12, "STL": 2, "BLK": 1, "TOV": 3,
        "FGM": 12, "FGA": 20, "FG3M": 1, "FG3A": 3, "FTM": 5, "FTA": 6, "game_date": "2023-10-24" # Added game_date
    },
    {
        "player_id": 2544, "player_name": "LeBron James", "game_id": "0022300002",
        "team_abbreviation": "LAL", "PTS": 25, "REB": 8, "AST": 7, "STL": 1, "BLK": 0, "TOV": 4,
        "FGM": 10, "FGA": 22, "FG3M": 2, "FG3A": 7, "FTM": 3, "FTA": 4, "game_date": "2023-10-24" # Added game_date
    },
    { # Adding a player with some zero stats for variety
        "player_id": 1629029, "player_name": "Luka Doncic", "game_id": "0022300003",
        "team_abbreviation": "DAL", "PTS": 35, "REB": 10, "AST": 9, "STL": 0, "BLK": 0, "TOV": 5,
        "FGM": 13, "FGA": 25, "FG3M": 3, "FG3A": 9, "FTM": 6, "FTA": 7, "game_date": "2023-10-24"
    }
]

def get_player_box_scores(game_date_str: str, use_mock_override: bool = False) -> List[Dict[str, Any]]:
    """
    Fetches player box scores for all games on a given date.
    
    Args:
        game_date_str: The date string in "YYYY-MM-DD" format.
        use_mock_override: If True, forces the use of mock data. Otherwise, mock data is
                           used if USE_MOCK_NBA_DATA environment variable is set to "true".
                           
    Returns:
        A list of dictionaries, where each dictionary is a player's box score.
    """
    # Check environment variable for mock data usage, unless overridden
    use_env_mock = os.getenv("USE_MOCK_NBA_DATA", "false").lower() == "true"
    if use_mock_override or use_env_mock:
        print(f"Using mock box score data for date: {game_date_str}.")
        # Ensure game_date in mock data matches the requested date for consistency
        # This is a simple update; for more complex scenarios, mock data might need to be generated
        updated_mock_scores = []
        for score in MOCK_BOX_SCORES:
            mock_score_copy = score.copy()
            mock_score_copy["game_date"] = game_date_str
            updated_mock_scores.append(mock_score_copy)
        return updated_mock_scores

    print(f"Fetching live box scores from nba_api for game date: {game_date_str}")
    try:
        # Validate game_date_str format (example)
        datetime.strptime(game_date_str, "%Y-%m-%d")
        
        # nba_api's ScoreboardV2 expects date as "MM/DD/YYYY"
        formatted_date = datetime.strptime(game_date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
        
        # Get game IDs for the specified date
        # Adding a timeout and headers as good practice for nba_api
        sb_data = scoreboardv2.ScoreboardV2(
            game_date=formatted_date, 
            league_id="00", # NBA
            day_offset="0",
            timeout=30, # seconds
            headers={'User-Agent': 'Mozilla/5.0'} # Common header
        )
        
        games_df = sb_data.game_header.get_data_frames()[0]
        game_ids = games_df['GAME_ID'].tolist()

        if not game_ids:
            print(f"No games found for date: {game_date_str}")
            return []

        all_player_stats = []
        for game_id in game_ids:
            print(f"Fetching player stats for game_id: {game_id}")
            # Adding timeout and headers
            player_stats_data = boxscoreplayertrackv2.BoxScorePlayerTrackV2(
                game_id=game_id, 
                timeout=30,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            
            player_logs_df = player_stats_data.player_stats.get_data_frames()[0]
            
            for player_log in player_logs_df.to_dict('records'):
                # Ensure all keys exist, providing default 0 if not found
                all_player_stats.append({
                    "player_id": player_log.get("PLAYER_ID"),
                    "player_name": player_log.get("PLAYER_NAME", "Unknown Player"),
                    "game_id": player_log.get("GAME_ID"),
                    "team_abbreviation": player_log.get("TEAM_ABBREVIATION", "N/A"),
                    "PTS": player_log.get("PTS", 0) or 0, # Handles None from .get() then None from empty data
                    "REB": player_log.get("REB", 0) or 0,
                    "AST": player_log.get("AST", 0) or 0,
                    "STL": player_log.get("STL", 0) or 0,
                    "BLK": player_log.get("BLK", 0) or 0,
                    "TOV": player_log.get("TO", 0) or 0, # 'TO' is standard for Turnovers in nba_api
                    "FGM": player_log.get("FGM", 0) or 0,
                    "FGA": player_log.get("FGA", 0) or 0,
                    "FG3M": player_log.get("FG3M", 0) or 0,
                    "FG3A": player_log.get("FG3A", 0) or 0,
                    "FTM": player_log.get("FTM", 0) or 0,
                    "FTA": player_log.get("FTA", 0) or 0,
                    "game_date": game_date_str 
                })
            time.sleep(0.7) # Be respectful to the API; increased delay slightly

        print(f"Fetched {len(all_player_stats)} live player box scores for {game_date_str}.")
        return all_player_stats
        
    except Exception as e:
        print(f"Error fetching live box scores from nba_api: {e}")
        print("Falling back to mock data due to error.")
        # Ensure game_date in mock data matches the requested date
        updated_mock_scores = []
        for score in MOCK_BOX_SCORES:
            mock_score_copy = score.copy()
            mock_score_copy["game_date"] = game_date_str
            updated_mock_scores.append(mock_score_copy)
        return updated_mock_scores

if __name__ == '__main__':
    # Example usage:
    # To use live data, ensure USE_MOCK_NBA_DATA is not "true" or use_mock_override=False
    # To force mock: get_player_box_scores("2023-10-24", use_mock_override=True)
    # To use live (if no env var): get_player_box_scores("2023-10-24")
    
    # Set to true to test mock data without setting environment variable
    test_date = "2023-11-20" # A date with likely games
    
    # Test with mock data
    print("\n--- Testing with Mock Data (override) ---")
    mock_scores = get_player_box_scores(test_date, use_mock_override=True)
    if mock_scores:
        for score in mock_scores[:2]: # Print first two for brevity
            print(score)
    else:
        print("No mock scores returned.")

    # Test with live data (will fallback to mock if API fails or USE_MOCK_NBA_DATA is true)
    # Note: Live API calls might be slow or fail in restricted environments
    print(f"\n--- Testing with Live Data (falls back to mock on error or if USE_MOCK_NBA_DATA=true) for {test_date} ---")
    # To truly test live, ensure USE_MOCK_NBA_DATA is not set or is 'false'
    # os.environ["USE_MOCK_NBA_DATA"] = "false" # Uncomment to force attempt at live data for this test run
    live_scores = get_player_box_scores(test_date) # use_mock_override defaults to False
    if live_scores:
        # Check if the returned data is actually live or the fallback mock
        if any(score.get("player_id") not in [m["player_id"] for m in MOCK_BOX_SCORES] for score in live_scores) or \
           (len(live_scores) > len(MOCK_BOX_SCORES) and not (os.getenv("USE_MOCK_NBA_DATA", "false").lower() == "true")): # Heuristic to check if it's not mock
            print("Successfully fetched LIVE data (or data different from static mock).")
        elif os.getenv("USE_MOCK_NBA_DATA", "false").lower() == "true":
            print("Fetched MOCK data due to USE_MOCK_NBA_DATA environment variable.")
        else:
            print("Fetched MOCK data (likely due to API error during live fetch attempt).")
        
        for score in live_scores[:3]: # Print first few for brevity
            print(score)
    else:
        print(f"No scores returned for {test_date} (live or mock).")

    # Example of a date with no games to test that scenario (e.g., deep offseason)
    # test_no_games_date = "2023-08-01" 
    # print(f"\n--- Testing with Live Data for a date with no games: {test_no_games_date} ---")
    # no_game_scores = get_player_box_scores(test_no_games_date)
    # print(f"Scores for {test_no_games_date}: {no_game_scores}")

    # Example of an invalid date format
    # print("\n--- Testing with invalid date format ---")
    # invalid_date_scores = get_player_box_scores("30-12-2023") # Should trigger error and fallback
    # print(f"Scores for invalid date: {invalid_date_scores}")

    # Example of PlayerGameLogs (alternative, might be simpler but less detailed for all players on a day)
    # from nba_api.stats.endpoints import playergamelogs
    # try:
    #     print("\n--- Alternative: PlayerGameLogs for a specific date range ---")
    #     # date_from and date_to should be in MM/DD/YYYY for PlayerGameLogs
    #     formatted_date_alt = datetime.strptime(test_date, "%Y-%m-%d").strftime("%m/%d/%Y")
    #     gamelogs = playergamelogs.PlayerGameLogs(
    #         date_from_nullable=formatted_date_alt, 
    #         date_to_nullable=formatted_date_alt,
    #         league_id_nullable="00",
    #         timeout=30,
    #         headers={'User-Agent': 'Mozilla/5.0'}
    #     )
    #     logs_df = gamelogs.get_data_frames()[0]
    #     print(f"Found {len(logs_df)} game logs using PlayerGameLogs for {test_date}.")
    #     # print(logs_df.head())
    # except Exception as e_alt:
    #     print(f"Error with PlayerGameLogs: {e_alt}")

    print("\n--- Testing complete ---")
