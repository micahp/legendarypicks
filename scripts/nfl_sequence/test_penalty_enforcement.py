"""Rule-bounded penalty transition fixtures; unsupported cases fail closed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from penalty_enforcement import DownState, enforce


class PenaltyEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.before = DownState(2, 8, 60, "ARI")
        self.after = DownState(3, 3, 55, "ARI")

    def test_offensive_false_start_keeps_down_and_enforces_five(self):
        result = enforce(before=self.before, after_play=self.after, phase="pre_snap",
                         offender="offense", foul="false_start", accepted=True)
        self.assertEqual(result.state, DownState(2, 13, 65, "ARI"))
        self.assertEqual(result.yards, 5)

    def test_defensive_pre_snap_foul_can_create_first_down(self):
        short = DownState(3, 3, 60, "ARI")
        result = enforce(before=short, after_play=short, phase="pre_snap",
                         offender="defense", foul="encroachment", accepted=True)
        self.assertEqual(result.state, DownState(1, 10, 55, "ARI"))

    def test_defensive_holding_auto_first_from_previous_spot(self):
        result = enforce(before=self.before, after_play=self.after, phase="live_pass",
                         offender="defense", foul="defensive_holding", accepted=True)
        self.assertEqual(result.state, DownState(1, 10, 55, "ARI"))

    def test_dpi_uses_foul_spot_and_auto_first(self):
        result = enforce(before=self.before, after_play=self.after, phase="live_pass",
                         offender="defense", foul="defensive_pass_interference",
                         accepted=True, foul_yardline_100=40)
        self.assertEqual(result.state, DownState(1, 10, 40, "ARI"))

    def test_declined_penalty_leaves_play_result_unchanged(self):
        result = enforce(before=self.before, after_play=self.after, phase="live_pass",
                         offender="offense", foul="offensive_holding", accepted=False)
        self.assertFalse(result.accepted)
        self.assertEqual(result.state, self.after)

    def test_unsupported_goal_line_half_distance_and_turnover_fail(self):
        near_goal = DownState(1, 5, 98, "ARI")
        with self.assertRaisesRegex(ValueError, "half-distance"):
            enforce(before=near_goal, after_play=near_goal, phase="pre_snap",
                    offender="offense", foul="false_start", accepted=True)
        with self.assertRaisesRegex(ValueError, "near goal line"):
            enforce(before=self.before, after_play=self.after, phase="live_pass",
                    offender="defense", foul="defensive_pass_interference",
                    accepted=True, foul_yardline_100=2)
        changed = DownState(1, 10, 40, "DAL")
        with self.assertRaisesRegex(ValueError, "possession change"):
            enforce(before=self.before, after_play=changed, phase="live_pass",
                    offender="offense", foul="offensive_holding", accepted=True)


if __name__ == "__main__":
    unittest.main()
