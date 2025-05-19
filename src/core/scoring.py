# src/core/scoring.py
from typing import Dict, Any

SCORING_RULES = {
    "PTS": 1.0,
    "REB": 1.2,
    "AST": 1.5,
    "STL": 3.0,
    "BLK": 3.0,
    "TOV": -1.0,
    "DD": 1.5,  # Bonus for Double-Double
    "TD": 3.0   # Bonus for Triple-Double
}

def calculate_fantasy_points(box_score: Dict[str, Any], rules: Dict[str, float] = SCORING_RULES) -> float:
    """
    Calculates fantasy points for a player based on their box score and scoring rules.

    Args:
        box_score: A dictionary representing the player's box score.
                   Expected keys: "PTS", "REB", "AST", "STL", "BLK", "TOV".
        rules: A dictionary defining the points for each stat category.

    Returns:
        The total fantasy points as a float, rounded to 2 decimal places.
    """
    if not box_score: # Handle empty box score
        return 0.0

    fantasy_points = 0.0

    # Calculate base points from individual stats
    fantasy_points += box_score.get("PTS", 0) * rules.get("PTS", 0.0)
    fantasy_points += box_score.get("REB", 0) * rules.get("REB", 0.0)
    fantasy_points += box_score.get("AST", 0) * rules.get("AST", 0.0)
    fantasy_points += box_score.get("STL", 0) * rules.get("STL", 0.0)
    fantasy_points += box_score.get("BLK", 0) * rules.get("BLK", 0.0)
    fantasy_points += box_score.get("TOV", 0) * rules.get("TOV", 0.0)

    # Check for Double-Double and Triple-Double
    stat_categories_for_bonus = [
        box_score.get("PTS", 0),
        box_score.get("REB", 0),
        box_score.get("AST", 0),
        box_score.get("STL", 0),
        box_score.get("BLK", 0)
    ]
    
    num_double_digit_stats = 0
    for stat_value in stat_categories_for_bonus:
        if stat_value >= 10:
            num_double_digit_stats += 1
    
    if num_double_digit_stats >= 3:
        fantasy_points += rules.get("TD", 0.0)
    elif num_double_digit_stats >= 2:
        fantasy_points += rules.get("DD", 0.0)
        
    return round(fantasy_points, 2)
