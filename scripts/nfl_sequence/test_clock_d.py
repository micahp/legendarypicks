"""Tests for the E3 research clock D (clock_d.py). The E2 default is tested in test_game_state.py and is unchanged here.

Run: python3 -m unittest scripts/nfl_sequence/test_clock_d.py
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock_d as cd  # noqa: E402


def model_with(pool, hazard, pool_stop=None, pool_all=None, hazard_bucket=None):
    """A fitted-model stand-in with explicit cells. `pool` and `hazard` use the keys D uses."""
    return cd.Model(pool, pool_stop or {}, pool_all or {}, hazard, hazard_bucket or {}, {}, {})


ROW = {'game_id': 'G1', 'play_id': 1}


class StopClass(unittest.TestCase):
    """The legal clock-stop class comes from the generated play and its consequence, never from the next snap."""

    def test_an_incomplete_pass_stops_the_clock(self):
        self.assertEqual(cd.stop_class('pass_incomplete', 0, 2, 300, None), 'incomplete')
        self.assertEqual(cd.stop_class('pass_incomplete', 1, 4, 240, None), 'incomplete')

    def test_turnovers_stop_the_clock(self):
        self.assertEqual(cd.stop_class('interception', 0, 2, 300, None), 'turnover')
        self.assertEqual(cd.stop_class('fumble_lost', 1, 4, 240, None), 'turnover')

    def test_a_score_stops_the_clock(self):
        self.assertEqual(cd.stop_class('run', 0, 2, 300, 'touchdown'), 'score')

    def test_a_sack_is_its_own_class_and_the_clock_runs(self):
        self.assertEqual(cd.stop_class('sack', 0, 4, 120, None), 'sack')
        self.assertEqual(cd.stop_class('sack', 1, 4, 240, None), 'oob_snap')
        self.assertEqual(cd.stop_class('sack', 1, 4, 360, None), 'oob_ready')

    def test_out_of_bounds_restart_policy_uses_the_correct_half_boundaries(self):
        self.assertEqual(cd.stop_class('run', 1, 2, 120, None), 'oob_snap')
        self.assertEqual(cd.stop_class('run', 1, 2, 121, None), 'oob_ready')
        self.assertEqual(cd.stop_class('run', 1, 4, 299, None), 'oob_snap')
        self.assertEqual(cd.stop_class('run', 1, 4, 300, None), 'oob_ready')
        self.assertEqual(cd.stop_class('run', 1, 1, 30, None), 'oob_ready')

    def test_an_in_bounds_play_lets_the_clock_run(self):
        self.assertEqual(cd.stop_class('run', 0, 4, 120, None), 'clock_runs')

    def test_out_of_bounds_restart_helper_distinguishes_ready_from_snap(self):
        self.assertEqual(cd.oob_clock_restart(2, 120), 'snap')
        self.assertEqual(cd.oob_clock_restart(2, 121), 'ready')
        self.assertEqual(cd.oob_clock_restart(4, 299), 'snap')
        self.assertEqual(cd.oob_clock_restart(4, 300), 'ready')

    def test_kicks_are_their_own_class(self):
        self.assertEqual(cd.stop_class('punt', 0, 1, 500, None), 'kick')
        self.assertEqual(cd.stop_class('punt', 1, 4, 240, None), 'kick')
        self.assertEqual(cd.stop_class('field_goal_attempt', 0, 4, 60, None), 'kick')


class Draw(unittest.TestCase):
    """The draw never runs the clock below zero, and a quarter end consumes exactly the remaining time."""

    def clock(self, model, seed=1):
        return cd.BoundaryClock(model, seed)

    def test_a_quarter_end_consumes_exactly_the_remaining_time(self):
        model = model_with({}, {('clock_runs', 30): (60, 60)}, hazard_bucket={30: (60, 60)})
        runoff, ended, refusal = self.clock(model).draw(ROW, 'run', None, 1, 25)
        self.assertEqual((runoff, ended, refusal), (25, True, None))

    def test_a_play_that_does_not_end_the_quarter_consumes_its_runoff(self):
        model = model_with({('run', 'clock_runs', False): [5] * 60}, {('clock_runs', 30): (0, 60)},
                           hazard_bucket={30: (0, 60)})
        runoff, ended, refusal = self.clock(model).draw(ROW, 'run', None, 1, 25)
        self.assertEqual((runoff, ended, refusal), (5, False, None))

    def test_draws_stay_below_the_remaining_time_when_the_quarter_does_not_end(self):
        pool = {('run', 'clock_runs', True): [10, 40, 90, 200] * 20}
        model = model_with(pool, {('clock_runs', 60): (0, 60)}, hazard_bucket={60: (0, 60)})
        clock = self.clock(model, seed=7)
        for _ in range(200):
            runoff, ended, _ = clock.draw(ROW, 'run', None, 2, 60)
            self.assertFalse(ended)
            self.assertLess(runoff, 60)

    def test_the_two_minute_stop_cuts_a_runoff_that_would_cross_the_mark(self):
        # A 60-second runoff from the 150 would cross the 2:00 mark, so the clock stops at 120 (30 seconds used).
        pool = {('run', 'clock_runs', False): [60] * 60}
        model = model_with(pool, {('clock_runs', 900): (0, 60)}, hazard_bucket={900: (0, 60)})
        runoff, ended, _ = self.clock(model).draw(ROW, 'run', None, 2, 150)
        self.assertEqual((runoff, ended), (30, False))

    def test_fourth_quarter_out_of_bounds_uses_last_five_minute_restart_pool(self):
        model = model_with({('run', 'oob_snap', False): [12] * 60},
                           {('oob_snap', 900): (0, 60)}, hazard_bucket={900: (0, 60)})
        model.flags[('G1', 1)] = (1, 0)
        clock = self.clock(model)
        runoff, ended, refusal = clock.draw(ROW, 'run', None, 4, 240)
        self.assertEqual((runoff, ended, refusal), (12, False, None))
        self.assertEqual(clock.log[-1]['stop'], 'oob_snap')

    def test_a_thin_hazard_key_refuses_the_draw_and_names_the_key(self):
        runoff, ended, refusal = self.clock(model_with({}, {})).draw(ROW, 'run', None, 1, 80)
        self.assertIsNone(runoff)
        self.assertFalse(ended)
        self.assertIn('thin hazard cell', refusal)

    def test_a_thin_runoff_key_refuses_a_play_that_does_not_end_the_quarter(self):
        model = model_with({}, {('clock_runs', 900): (0, 60)}, hazard_bucket={900: (0, 60)})
        runoff, _, refusal = self.clock(model).draw(ROW, 'run', None, 1, 500)
        self.assertIsNone(runoff)
        self.assertIn('thin runoff cell', refusal)

    def test_each_game_draws_from_its_own_seeded_stream(self):
        pool = {('run', 'clock_runs', False): list(range(1, 60))}
        model = model_with(pool, {('clock_runs', 900): (0, 60)}, hazard_bucket={900: (0, 60)})

        def sequence(seed):
            clock = self.clock(model, seed=seed)
            return [clock.draw(ROW, 'run', None, 1, 800)[0] for _ in range(20)]

        self.assertEqual(sequence(3), sequence(3), 'the same seed gives the same draws')
        self.assertNotEqual(sequence(3), sequence(4), 'a different seed gives different draws')


class Keys(unittest.TestCase):
    def test_the_clock_bucket_is_the_smallest_edge_that_holds_the_clock(self):
        self.assertEqual(cd.qsr_bucket(1), 15)
        self.assertEqual(cd.qsr_bucket(15), 15)
        self.assertEqual(cd.qsr_bucket(16), 30)
        self.assertEqual(cd.qsr_bucket(900), 900)


if __name__ == '__main__':
    unittest.main()
