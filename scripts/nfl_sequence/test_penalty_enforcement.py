"""All 16 V1.7 foul types: 2026 rules, spot, down and fail-closed regressions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from penalty_enforcement import DownState, Enforcement, MODEL_FOULS, RULES, enforce
from penalty_fit import CATEGORIES


class PenaltyEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.before = DownState(2, 8, 60, "ARI")
        self.after = DownState(3, 3, 55, "ARI")

    def e(self, side, foul, *, pre=False, play_class="dropback", after=None, **kwargs):
        return enforce(
            before=self.before, after_play=self.before if pre else (after or self.after),
            phase="pre_snap" if pre else "live_ball",
            offender=side, foul=foul, accepted=True, play_class=play_class,
            defense_team="DAL", **kwargs)

    def test_catalog_exactly_matches_16_rules(self):
        self.assertEqual(len(RULES), 16)
        labels = {(side, foul) for phase in CATEGORIES for side in CATEGORIES[phase]
                  for foul in CATEGORIES[phase][side]}
        self.assertEqual(set(RULES), labels)
        self.assertEqual(MODEL_FOULS, labels)

    def test_each_modeled_foul_has_a_legal_accepted_scrimmage_fixture(self):
        # All 16 foul labels must produce the expected transition, not just
        # exist in the registry or pass a mock sampler.
        cases = [
            ("offense", "false_start", True, {}, DownState(2, 13, 65, "ARI")),
            ("offense", "delay_of_game", True, {}, DownState(2, 13, 65, "ARI")),
            ("defense", "encroachment", True, {}, DownState(2, 3, 55, "ARI")),
            ("defense", "neutral_zone_infraction", True, {}, DownState(2, 3, 55, "ARI")),
            ("offense", "offensive_holding", False, {}, DownState(2, 18, 70, "ARI")),
            ("offense", "offensive_pass_interference", False, {}, DownState(2, 18, 70, "ARI")),
            ("offense", "illegal_block", False,
             {"block_subtype": "in_back", "foul_yardline_100": 50},
             DownState(2, 8, 60, "ARI")),
            ("offense", "intentional_grounding", False,
             {"foul_yardline_100": 64}, DownState(3, 18, 70, "ARI")),
            ("offense", "illegal_formation", False, {}, DownState(2, 13, 65, "ARI")),
            ("offense", "illegal_shift", False, {}, DownState(2, 13, 65, "ARI")),
            ("offense", "illegal_motion", False, {}, DownState(2, 13, 65, "ARI")),
            ("defense", "defensive_holding", False, {}, DownState(1, 10, 55, "ARI")),
            ("defense", "defensive_pass_interference", False,
             {"foul_yardline_100": 40}, DownState(1, 10, 40, "ARI")),
            ("defense", "illegal_contact", False, {}, DownState(1, 10, 55, "ARI")),
            ("defense", "roughing_passer", False,
             {"pass_outcome": "incomplete"}, DownState(1, 10, 45, "ARI")),
            ("defense", "offside", False, {}, DownState(2, 3, 55, "ARI")),
        ]
        self.assertEqual(len(cases), 16)
        for side, foul, pre, kwargs, expected in cases:
            with self.subTest(foul=foul):
                result = self.e(side, foul, pre=pre, **kwargs)
                self.assertEqual(result.state, expected)
                self.assertTrue(result.accepted)
                self.assertTrue(result.rule_basis.startswith("NFL 2026 Rule"))

    def test_automatic_first_down_and_goal_to_go(self):
        near = DownState(2, 8, 13, "ARI")
        got = enforce(before=near, after_play=near, phase="live_pass",
                      offender="defense", foul="defensive_holding", accepted=True)
        self.assertEqual(got.state, DownState(1, 8, 8, "ARI"))
        self.assertTrue(got.automatic_first_down)

    def test_half_distance_on_both_sides_including_half_yard(self):
        own_two = DownState(1, 10, 98, "ARI")
        first = enforce(before=own_two, after_play=own_two, phase="pre_snap",
                        offender="offense", foul="false_start", accepted=True)
        self.assertEqual(first.state, DownState(1, 11, 99, "ARI"))
        opponent_three = DownState(2, 3, 3, "ARI")
        second = enforce(before=opponent_three, after_play=opponent_three,
                         phase="pre_snap", offender="defense",
                         foul="encroachment", accepted=True)
        self.assertEqual(second.state, DownState(2, 1.5, 1.5, "ARI"))
        self.assertEqual(second.yards, 1.5)

    def test_pre_snap_defensive_foul_converts_short_yardage(self):
        short = DownState(3, 3, 60, "ARI")
        result = enforce(before=short, after_play=short, phase="pre_snap",
                         offender="defense", foul="encroachment", accepted=True)
        self.assertEqual(result.state, DownState(1, 10, 55, "ARI"))
        self.assertTrue(result.automatic_first_down)

    def test_defensive_pass_interference_endzone_and_inside_two(self):
        before = DownState(2, 3, 3, "ARI")
        e = enforce(before=before, after_play=before, phase="live_pass",
                    offender="defense", foul="defensive_pass_interference",
                    foul_yardline_100=0, accepted=True)
        self.assertEqual(e.state, DownState(1, 1, 1, "ARI"))
        near = DownState(2, 1, 1, "ARI")
        e = enforce(before=near, after_play=near, phase="live_pass",
                    offender="defense", foul="defensive_pass_interference",
                    foul_yardline_100=0, accepted=True)
        self.assertEqual(e.state, DownState(1, .5, .5, "ARI"))
        with self.assertRaisesRegex(ValueError, "beyond line"):
            self.e("defense", "defensive_pass_interference", foul_yardline_100=70)

    def test_grounding_is_loss_of_down_at_worse_spot(self):
        ordinary = self.e("offense", "intentional_grounding", foul_yardline_100=75)
        self.assertEqual(ordinary.state, DownState(3, 23, 75, "ARI"))
        self.assertTrue(ordinary.loss_of_down)
        self.assertFalse(ordinary.replay_down)
        inside_own_ten = DownState(2, 8, 95, "ARI")
        e = enforce(before=inside_own_ten, after_play=inside_own_ten,
                    phase="live_pass", offender="offense", foul="intentional_grounding",
                    foul_yardline_100=97, accepted=True)
        self.assertEqual(e.state, DownState(3, 10, 97, "ARI"))
        # From own 15, the passer throws at own 7 (eight yards back).
        # That is less than ten behind the LOS, but more than half of
        # the distance to the offense's goal: enforce at release spot.
        own_fifteen = DownState(2, 10, 85, "ARI")
        halfway_exception = enforce(
            before=own_fifteen, after_play=own_fifteen,
            phase="live_pass", offender="offense", foul="intentional_grounding",
            foul_yardline_100=93, accepted=True)
        self.assertEqual(halfway_exception.state, DownState(3, 18, 93, "ARI"))

    def test_fourth_down_grounding_changes_possession_with_explicit_opponent(self):
        fourth = DownState(4, 5, 60, "ARI")
        result = enforce(before=fourth, after_play=fourth, phase="live_pass",
                         offender="offense", foul="intentional_grounding",
                         foul_yardline_100=64, defense_team="DAL", accepted=True)
        self.assertEqual(result.state, DownState(1, 10, 30, "DAL"))
        self.assertTrue(result.turnover_on_downs)
        with self.assertRaisesRegex(ValueError, "defending team"):
            enforce(before=fourth, after_play=fourth, phase="live_pass",
                    offender="offense", foul="intentional_grounding",
                    foul_yardline_100=64, accepted=True)

    def test_roughing_completed_pass_is_added_to_end_of_run(self):
        result = self.e("defense", "roughing_passer", pass_outcome="complete")
        self.assertEqual(result.state, DownState(1, 10, 40, "ARI"))
        self.assertTrue(result.play_counts)
        self.assertEqual(result.enforcement_spot, "end_of_run")
        self.assertTrue(result.automatic_first_down)
        self.assertEqual(self.e("defense", "roughing_passer",
                                pass_outcome="incomplete").state.yardline_100, 45)

    def test_run_holding_and_illegal_block_use_real_foul_spot(self):
        h = self.e("offense", "offensive_holding", play_class="run",
                   foul_yardline_100=50)
        self.assertEqual(h.state, DownState(2, 8, 60, "ARI"))
        b = self.e("offense", "illegal_block", play_class="run",
                   block_subtype="above_waist", foul_yardline_100=50)
        self.assertEqual(b.state, DownState(2, 8, 60, "ARI"))

    def test_acceptance_and_clock_metadata_do_not_claim_clock_simulation(self):
        declined = enforce(before=self.before, after_play=self.after,
                           phase="live_pass", offender="offense",
                           foul="offensive_pass_interference", accepted=False)
        self.assertEqual(declined.state, self.after)
        self.assertTrue(declined.play_counts)
        self.assertFalse(declined.replay_down)
        accepted = self.e("offense", "illegal_formation")
        self.assertEqual(accepted.clock_action, "replay_down")
        self.assertFalse(accepted.play_counts)

    def test_foul_type_not_interchangeable_between_phase_or_play_classes(self):
        with self.assertRaisesRegex(ValueError, "phase"):
            self.e("offense", "false_start")
        with self.assertRaisesRegex(ValueError, "play-class"):
            self.e("offense", "offensive_pass_interference", play_class="run")
        with self.assertRaisesRegex(ValueError, "play-class"):
            self.e("defense", "roughing_passer", play_class="kick")
        with self.assertRaisesRegex(ValueError, "modeled types"):
            self.e("offense", "mystery_foul")

    def test_source_dependent_fouls_fail_closed_without_evidence(self):
        with self.assertRaisesRegex(ValueError, "foul spot"):
            self.e("defense", "defensive_pass_interference")
        with self.assertRaisesRegex(ValueError, "foul spot"):
            self.e("offense", "intentional_grounding")
        with self.assertRaisesRegex(ValueError, "subtype"):
            self.e("offense", "illegal_block", foul_yardline_100=50)
        with self.assertRaisesRegex(ValueError, "foul spot"):
            self.e("offense", "offensive_holding", play_class="run")
        with self.assertRaisesRegex(ValueError, "pass outcome"):
            self.e("defense", "roughing_passer")
        own_one = DownState(2, 10, 99, "ARI")
        # The 2026 special case uses the passer's release spot instead of
        # enforcing ten yards through the goal line.
        near_goal = enforce(before=own_one, after_play=own_one, phase="live_pass",
                            offender="offense", foul="intentional_grounding",
                            foul_yardline_100=99.5, accepted=True)
        self.assertEqual(near_goal.state, DownState(3, 10.5, 99.5, "ARI"))
        # A pass actually thrown from inside the end zone is a safety;
        # fail closed until the scoring transition driver can record it.
        with self.assertRaisesRegex(ValueError, "field of play"):
            enforce(before=own_one, after_play=own_one, phase="live_pass",
                    offender="offense", foul="intentional_grounding",
                    foul_yardline_100=100, accepted=True)

    def test_does_not_silently_discard_possession_or_score_transitions(self):
        flipped = DownState(1, 10, 40, "DAL")
        with self.assertRaisesRegex(ValueError, "possession change"):
            enforce(before=self.before, after_play=flipped, phase="live_pass",
                    offender="offense", foul="offensive_holding", accepted=True)
        touchdown = DownState(1, 10, 0, "ARI")
        with self.assertRaisesRegex(ValueError, "scoring"):
            enforce(before=self.before, after_play=touchdown, phase="live_pass",
                    offender="offense", foul="offensive_holding", accepted=True)
        with self.assertRaisesRegex(ValueError, "completed"):
            enforce(before=self.before, after_play=self.after,
                    phase="pre_snap", offender="offense",
                    foul="false_start", accepted=True)


if __name__ == "__main__":
    unittest.main()
