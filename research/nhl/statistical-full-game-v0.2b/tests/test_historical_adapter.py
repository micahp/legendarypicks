"""Unit tests for forward-only NHL historical inputs (fixtures are synthetic)."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import historical_adapter as adapter


class FakeSim:
    class Player:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class TeamRoster:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class PregameInputs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


def _player_rows(prefix):
    forwards = [
        {"playerId": int(f"{prefix}{i:02d}"), "position": "C" if i % 3 == 0 else "L",
         "name": {"default": f"Forward {prefix}-{i}"}, "toi": "12:00",
         "sog": 1, "goals": 0, "assists": 0, "faceoffWinningPctg": .5}
        for i in range(12)
    ]
    defense = [
        {"playerId": int(f"{prefix}2{i:02d}"), "position": "D",
         "name": {"default": f"Defense {prefix}-{i}"}, "toi": "18:00",
         "sog": 1, "goals": 0, "assists": 0, "faceoffWinningPctg": 0}
        for i in range(6)
    ]
    goalies = [{"playerId": int(f"{prefix}30"), "position": "G",
                "name": {"default": f"Goalie {prefix}"}, "toi": "60:00",
                "starter": True, "saves": 28, "shotsAgainst": 30, "goalsAgainst": 2}]
    return {"forwards": forwards, "defense": defense, "goalies": goalies}


class ForwardOnlyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = adapter.ForwardOnlyHistory()
        self.game = SimpleNamespace(game_id="2019020001", eligible=True,
                                    reg_ot_score={"home": 4, "away": 2},
                                    home_sog=31, away_sog=25,
                                    boxscore_compressed_sha256="fixture")
        self.manifest = {"game_id": 2019020001, "game_date": "2019-10-03",
                         "canonical_home_team": "AAA", "canonical_away_team": "BBB"}
        self.boxscore = {"id": 2019020001, "gameDate": "2019-10-03",
                         "homeTeam": {"abbrev": "AAA"}, "awayTeam": {"abbrev": "BBB"},
                         "playerByGameStats": {"homeTeam": _player_rows("1"),
                                                "awayTeam": _player_rows("4")}}

    def test_same_day_history_is_rejected_and_prior_history_builds_matchup(self):
        self.history.add_game(self.game, self.manifest, self.boxscore)
        with self.assertRaisesRegex(ValueError, "history cutoff violated"):
            self.history.make_inputs(sim=FakeSim, game_key="2019020002",
                                     game_date="2019-10-03", home="AAA", away="BBB")
        inputs = self.history.make_inputs(sim=FakeSim, game_key="2019020002",
                                          game_date="2019-10-04", home="AAA", away="BBB")
        self.assertEqual(inputs.mu_home, 4)
        self.assertEqual(inputs.mu_away, 2)
        self.assertAlmostEqual(inputs.snapshot["team_expected_sog"]["home"], 28.2727272727)
        self.assertAlmostEqual(inputs.snapshot["team_expected_sog"]["away"], 27.7272727273)
        self.assertTrue(inputs.snapshot["same_day_results_excluded"])
        self.assertEqual(len(inputs.home_roster.players), 19)
        self.assertEqual(len(inputs.home_roster.game_roster_ids), 19)
        self.assertEqual(inputs.home_roster.coverage["projected_game_roster_position_counts"],
                         {"C": 4, "D": 6, "G": 1, "L": 8})
        self.assertEqual(inputs.snapshot["projected_game_roster"]["status"],
                         "pregame_projection_only")
        self.assertFalse(inputs.snapshot["projected_game_roster"]["actual_target_game_lineup_used"])
        self.assertEqual(len(inputs.snapshot["projected_game_roster"]["players_by_side"]["home"]), 19)

    def test_history_must_be_added_chronologically(self):
        self.history.add_game(self.game, self.manifest, self.boxscore)
        earlier = SimpleNamespace(**{**self.game.__dict__, "game_id": "2019020000"})
        earlier_manifest = {**self.manifest, "game_id": 2019020000, "game_date": "2019-10-02"}
        earlier_box = {**self.boxscore, "id": 2019020000, "gameDate": "2019-10-02"}
        with self.assertRaisesRegex(ValueError, "history is not chronological"):
            self.history.add_game(earlier, earlier_manifest, earlier_box)

    def test_latest_prior_team_assignment_is_used(self):
        self.history.add_game(self.game, self.manifest, self.boxscore)
        self.assertEqual(self.history.players["100"].team, "AAA")
        self.assertEqual(self.history.players["400"].team, "BBB")
        self.assertEqual(self.history.players["130"].games_started, 1)


if __name__ == "__main__":
    unittest.main()
