"""2026 Rule 14 scrimmage-kick transitions: legal cases and explicit refusals."""
import unittest

from penalty_enforcement import DownState
from penalty_fit import Context
from penalty_sampler import PenaltyProposal
from penalty_transition import transition
from penalty_scrimmage_kick import enforce_scrimmage_kick


class FixedSampler:
    def __init__(self, foul):
        self.foul = foul

    def propose(self, context, *, game_seed, opportunity_key):
        return PenaltyProposal(opportunity_key, context.phase, self.foul,
                               "model-hash", "source-hash", "test")


class ScrimmageKickTransitionTests(unittest.TestCase):
    def setUp(self):
        # Punter on own 39, fourth and three; receiver takes over at own 20.
        self.before = DownState(4, 3, 61, "WAS")
        self.after = DownState(1, 10, 80, "NYG")
        self.context = Context("live_ball", 2026, "WAS", "NYG", 4, 3, 61, "kick")

    def run_foul(self, foul, **overrides):
        args = dict(sampler=FixedSampler(foul), context=self.context,
                    game_seed=3, opportunity_key="drive2-play4-live",
                    before=self.before, after_play=self.after,
                    accepted=True, kick_type="punt",
                    foul_during_kick=True, kick_enforcement_option="previous_spot")
        args.update(overrides)
        return transition(**args)

    def test_offensive_holding_replays_punt_from_previous_spot(self):
        got = self.run_foul("offense:offensive_holding")
        self.assertEqual(got.state, DownState(4, 13, 71, "WAS"))
        self.assertFalse(got.enforcement["play_counts"])
        self.assertEqual(got.enforcement["enforcement_spot"], "previous")

    def test_accepted_kicking_team_holding_adds_to_receiving_dead_ball_spot(self):
        got = self.run_foul("offense:offensive_holding",
                            kick_enforcement_option="receiving_dead_ball",
                            receiver_retained=True)
        self.assertEqual(got.state, DownState(1, 10, 70, "NYG"))
        self.assertTrue(got.enforcement["play_counts"])
        self.assertEqual(got.enforcement["enforcement_spot"], "receiving_dead_ball")

    def test_defensive_offside_on_field_goal_awards_first_if_sticks_reached(self):
        got = self.run_foul("defense:offside", kick_type="field_goal")
        self.assertEqual(got.state, DownState(1, 10, 56, "WAS"))
        self.assertFalse(got.enforcement["play_counts"])

    def test_defensive_holding_requires_actual_block_attempt_context(self):
        with self.assertRaisesRegex(ValueError, "kick-block-attempt"):
            self.run_foul("defense:defensive_holding")
        got = self.run_foul("defense:defensive_holding",
                            defensive_holding_block_attempt=True)
        self.assertEqual(got.state, DownState(1, 10, 56, "WAS"))

    def test_declined_foul_retains_original_kick_and_possession(self):
        got = self.run_foul("offense:illegal_formation", accepted=False,
                            kick_enforcement_option=None)
        self.assertEqual(got.state, self.after)
        self.assertTrue(got.enforcement["play_counts"])
        self.assertFalse(got.enforcement["accepted"])

    def test_half_distance_on_previous_spot_near_kicking_own_goal(self):
        own_two = DownState(4, 5, 98, "WAS")
        after = DownState(1, 10, 80, "NYG")
        got = enforce_scrimmage_kick(before=own_two, after_play=after,
                                     kick_type="punt", offender="offense",
                                     foul="illegal_formation", accepted=True,
                                     enforcement_option="previous_spot",
                                     defense_team="NYG", foul_during_kick=True)
        self.assertEqual(got.state, DownState(4, 6, 99, "WAS"))

    def test_cannot_add_on_without_receiving_team_retaining_possession(self):
        with self.assertRaisesRegex(ValueError, "possession throughout"):
            self.run_foul("offense:offensive_holding",
                          kick_enforcement_option="receiving_dead_ball",
                          receiver_retained=False)

    def test_no_invented_election_or_foul_timing(self):
        with self.assertRaisesRegex(ValueError, "explicit enforcement election"):
            self.run_foul("offense:offensive_holding",
                          kick_enforcement_option=None)
        with self.assertRaisesRegex(ValueError, "foul timing"):
            self.run_foul("offense:offensive_holding", foul_during_kick=None)

    def test_illegal_block_requires_verified_subtype(self):
        with self.assertRaisesRegex(ValueError, "verified"):
            self.run_foul("offense:illegal_block")
        got = self.run_foul("offense:illegal_block", block_subtype="in_back")
        self.assertEqual(got.state, DownState(4, 13, 71, "WAS"))

    def test_cannot_force_pass_interference_or_roughing_passer_onto_kick(self):
        for foul in ("defense:defensive_pass_interference",
                     "defense:roughing_passer"):
            with self.subTest(foul=foul), self.assertRaisesRegex(ValueError, "not supported"):
                self.run_foul(foul)


if __name__ == "__main__":
    unittest.main()
