"""Regression coverage for the shared scoreboard/detail live-status contract."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client
from routers import games


class GameResultStatusTests(unittest.TestCase):
    def test_leagues_cup_preserves_publisher_clock_and_soccer_winner(self):
        summary = {
            "header": {"competitions": [{
                "status": {
                    "period": 2,
                    "displayClock": "67'",
                    "type": {"state": "in", "shortDetail": "67'"},
                },
                "competitors": [
                    {"team": {"abbreviation": "MIA"}, "score": "1", "winner": False},
                    {"team": {"abbreviation": "PUM"}, "score": "0", "winner": True},
                ],
            }]},
        }
        with patch.object(espn_client, "summary", return_value=summary):
            result = espn_client.game_result("lcup", "401000001")

        self.assertEqual(result["state"], "in")
        self.assertEqual(result["period"], 2)
        self.assertEqual(result["clock"], "67'")
        self.assertEqual(result["status_detail"], "67'")
        self.assertEqual(result["winner"], "PUM")


class DetailContractTests(unittest.TestCase):
    def test_detail_carries_live_status_fields(self):
        published = {
            "state": "in",
            "scores": {"MIA": 1, "PUM": 0},
            "winner": None,
            "period": 2,
            "clock": "67'",
            "status_detail": "67'",
        }

        def read_context(_league, _game_id, out):
            out["context"] = {
                "venue_name": "", "venue_city": "", "attendance": None,
                "officials": [], "home_team": "MIA", "away_team": "PUM",
            }
            out["live_score"] = {"home": 1, "away": 0}

        with patch.object(games.espn, "game_result", return_value=published), \
             patch.object(games, "_read_game_detail_from_db", side_effect=read_context), \
             patch.object(games.espn, "team_strength_map", return_value={}):
            detail = games.get_game_detail("lcup", "401000001")

        self.assertEqual(detail["state"], "in")
        self.assertEqual(detail["period"], 2)
        self.assertEqual(detail["clock"], "67'")
        self.assertEqual(detail["status_detail"], "67'")


if __name__ == "__main__":
    unittest.main()
