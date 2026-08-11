"""Regression coverage for the shared scoreboard/detail live-status contract."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client
from routers import games


class GameResultStatusTests(unittest.TestCase):
    @staticmethod
    def _lcup(state, completed, detail):
        return {
            "header": {"competitions": [{
                "status": {
                    "period": 2,
                    "displayClock": detail,
                    "type": {"state": state, "completed": completed, "shortDetail": detail},
                },
                "competitors": [
                    {"team": {"abbreviation": "MIA"}, "score": "1", "winner": False},
                    {"team": {"abbreviation": "PUM"}, "score": "0", "winner": True},
                ],
            }]},
        }

    def test_leagues_cup_preserves_publisher_clock(self):
        with patch.object(espn_client, "summary",
                          return_value=self._lcup("in", False, "67'")):
            result = espn_client.game_result("lcup", "401000001")

        self.assertEqual(result["state"], "in")
        self.assertEqual(result["period"], 2)
        self.assertEqual(result["clock"], "67'")
        self.assertEqual(result["status_detail"], "67'")

    def test_a_match_in_progress_has_no_winner(self):
        """This case previously asserted winner == "PUM" at 67 minutes, from a
        `winner: true` flag on a competitor in a live fixture. A match in progress
        has no winner, and the non-soccer path already refused to name one (see
        test_game_result_home_away). `completed` decides for both now, so a live
        match cannot report a decided one to the game page."""
        with patch.object(espn_client, "summary",
                          return_value=self._lcup("in", False, "67'")):
            result = espn_client.game_result("lcup", "401000001")
        self.assertIsNone(result["winner"])

    def test_a_finished_match_keeps_the_publishers_winner_flag(self):
        """The guarantee this test exists for: soccer's winner comes from the
        publisher's flag, not from the scoreline, so a tie decided on penalties
        still grades to the side that actually advanced."""
        with patch.object(espn_client, "summary",
                          return_value=self._lcup("post", True, "FT")):
            result = espn_client.game_result("lcup", "401000001")
        self.assertTrue(result["completed"])
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
