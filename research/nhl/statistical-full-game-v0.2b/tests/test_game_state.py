"""Unit cases for explicit v0.2b state rules (hand-authored logic fixtures)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_state import (PenaltyLedger, possession_after_event, shootout_decided,
                        shot_side_for_possession)


class PossessionTests(unittest.TestCase):
    def test_faceoff_winner_controls_latent_possession(self):
        self.assertEqual(possession_after_event(None, "faceoff", "home"), "home")
        self.assertEqual(possession_after_event(None, "faceoff", "away"), "away")

    def test_turnover_changes_possession(self):
        self.assertEqual(possession_after_event("home", "giveaway", "home"), "away")
        self.assertEqual(possession_after_event("home", "takeaway", "away"), "away")

    def test_faceoff_winner_redirects_next_shot_away_from_donor_owner(self):
        possession = possession_after_event(None, "faceoff", "home")
        self.assertEqual(shot_side_for_possession(possession, "away"), "home")
        possession = possession_after_event(None, "faceoff", "away")
        self.assertEqual(shot_side_for_possession(possession, "home"), "away")

    def test_faceoff_without_winner_fails_closed(self):
        with self.assertRaises(ValueError):
            possession_after_event(None, "faceoff", None)


class PenaltyTests(unittest.TestCase):
    def test_minor_changes_manpower_and_expires_on_game_clock(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 100)
        ledger.start("home", "H12", "MIN")
        self.assertEqual(ledger.manpower("REG"), {"home": 4, "away": 5})
        self.assertEqual(ledger.penalized_players("home"), {"H12"})
        self.assertEqual(ledger.advance_to(1, 219), [])
        expired = ledger.advance_to(1, 220)
        self.assertEqual([p.player_id for p in expired], ["H12"])
        self.assertEqual(ledger.manpower("REG"), {"home": 5, "away": 5})

    def test_power_play_goal_releases_minor_but_not_major(self):
        minor = PenaltyLedger()
        minor.advance_to(1, 0)
        minor.start("home", "H12", "MIN")
        released = minor.on_goal("away")
        self.assertIsNotNone(released)
        self.assertEqual(released.player_id, "H12")
        self.assertEqual(minor.manpower("REG"), {"home": 5, "away": 5})

        major = PenaltyLedger()
        major.advance_to(1, 0)
        major.start("home", "H13", "MAJ")
        self.assertIsNone(major.on_goal("away"))
        self.assertEqual(major.manpower("REG"), {"home": 4, "away": 5})

    def test_goal_in_first_double_minor_segment_starts_second_segment(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 100)
        ledger.start("home", "H12", "MIN", duration_seconds=240)
        ledger.advance_to(1, 130)
        segment = ledger.on_goal("away")
        self.assertIsNotNone(segment)
        self.assertEqual(segment.remaining_seconds, 120)
        self.assertEqual(ledger.manpower("REG"), {"home": 4, "away": 5})
        self.assertEqual(ledger.advance_to(1, 249), [])
        self.assertEqual([p.player_id for p in ledger.advance_to(1, 250)], ["H12"])

    def test_goal_in_second_double_minor_segment_releases_player(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 100)
        ledger.start("home", "H12", "MIN", duration_seconds=240)
        ledger.advance_to(1, 230)
        segment = ledger.on_goal("away")
        self.assertIsNotNone(segment)
        self.assertEqual(ledger.manpower("REG"), {"home": 5, "away": 5})

    def test_power_play_goal_releases_minor_with_least_remaining_clock(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 0)
        ledger.start("home", "H12", "MIN")
        ledger.advance_to(1, 100)
        ledger.start("home", "H13", "MIN")
        released = ledger.on_goal("away")
        self.assertEqual(released.player_id, "H12")
        self.assertEqual(ledger.penalized_players("home"), {"H13"})
        self.assertEqual(ledger.manpower("REG"), {"home": 4, "away": 5})

    def test_third_concurrent_manpower_penalty_fails_closed(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 0)
        ledger.start("home", "H12", "MIN")
        ledger.start("home", "H13", "MAJ")
        with self.assertRaisesRegex(ValueError, "third concurrent"):
            ledger.start("home", "H14", "MIN")

    def test_unsupported_penalty_class_is_not_silently_approximated(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 0)
        with self.assertRaises(ValueError):
            ledger.start("home", "H12", "PENALTY_SHOT")

    def test_minor_clock_carries_across_regulation_periods(self):
        ledger = PenaltyLedger()
        ledger.advance_to(1, 1190)
        ledger.start("away", "A14", "MIN")
        self.assertEqual(ledger.advance_to(2, 70), [])
        expired = ledger.advance_to(2, 110)
        self.assertEqual([p.player_id for p in expired], ["A14"])


class ShootoutTests(unittest.TestCase):
    def test_regulation_shootout_stops_when_remaining_shots_cannot_tie(self):
        self.assertEqual(shootout_decided(
            {"home": 2, "away": 0}, {"home": 2, "away": 2}), "home")
        self.assertEqual(shootout_decided(
            {"home": 2, "away": 0}, {"home": 3, "away": 2}), "home")

    def test_regulation_shootout_continues_when_tie_is_possible(self):
        self.assertIsNone(shootout_decided(
            {"home": 2, "away": 1}, {"home": 2, "away": 2}))
        self.assertIsNone(shootout_decided(
            {"home": 3, "away": 3}, {"home": 3, "away": 3}))

    def test_sudden_death_requires_equal_attempts_before_winner(self):
        self.assertIsNone(shootout_decided(
            {"home": 3, "away": 2}, {"home": 4, "away": 3}))
        self.assertEqual(shootout_decided(
            {"home": 3, "away": 2}, {"home": 4, "away": 4}), "home")


if __name__ == "__main__":
    unittest.main()
