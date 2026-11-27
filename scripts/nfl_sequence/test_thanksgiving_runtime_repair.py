"""Focused Thanksgiving regression tests, without historical outcome substitution."""
import unittest
import autonomous_game
import e1_drive


class ThanksgivingRepair(unittest.TestCase):
    def test_end_zone_projection_and_reflection(self):
        spot = autonomous_game._physical_stat_spot
        self.assertEqual(spot(102, 1), 0)
        self.assertEqual(spot(-2, -1), 0)
        self.assertEqual(spot(99.8, 1), 1)
        self.assertEqual(spot(0.2, -1), 1)
        with self.assertRaises(ValueError):
            spot(111, 1)

    def test_fumble_geometry_keeps_raw_displacement(self):
        facts = dict(recovery_side='D', recovery_spot={'x': 102},
                     dead_ball_spot={'x': 75}, return_yards=25, return_displacement_yards=27)
        actual = autonomous_game._validate_gridiron_fumble_return(facts, 1)
        self.assertEqual(actual, dict(recovery_yardline_100=0, dead_ball_yardline_100=25,
                                      return_yards=25, return_displacement_yards=27))
        facts['return_displacement_yards'] = 25
        with self.assertRaisesRegex(ValueError, 'raw_endpoints'):
            autonomous_game._validate_gridiron_fumble_return(facts, 1)

    def test_blocked_fg_halftime_is_not_the_live_play_terminal(self):
        before = dict(quarter=2, clock_seconds=4, offense_team='A')
        after = dict(quarter=2, clock_seconds=0, offense_team='B', end_of_drive='halftime')
        outcome = dict(field_goal_attempt=True, live_play_terminal='turnover',
                       touchdown=False, safety=False, clock_only_terminal=False)
        check = e1_drive._blocked_field_goal_terminal_valid
        self.assertTrue(check(before, after, outcome))
        self.assertFalse(check(before, dict(after, clock_seconds=1), outcome))
        self.assertFalse(check(before, after, dict(outcome, live_play_terminal='touchdown')))
        self.assertFalse(check(before, after, dict(outcome, field_goal_attempt=False)))
        self.assertFalse(check(before, after, dict(outcome, live_play_terminal=None)))

    def test_blocked_fg_clock_only_and_overtime(self):
        check = e1_drive._blocked_field_goal_terminal_valid
        for quarter, period in ((2, 'halftime'), (4, 'end_of_regulation'), (5, 'end_of_overtime')):
            before = dict(quarter=quarter, offense_team='A', clock_seconds=4)
            after = dict(quarter=quarter, offense_team='A', clock_seconds=0, end_of_drive=period)
            outcome = dict(field_goal_attempt=True, live_play_terminal=None,
                           clock_only_terminal=True, touchdown=False, safety=False)
            self.assertTrue(check(before, after, outcome))
            self.assertFalse(check(before, after, dict(outcome, clock_only_terminal=False)))


if __name__ == '__main__':
    unittest.main()
