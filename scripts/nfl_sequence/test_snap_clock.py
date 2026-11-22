"""Snap clock: the clock rules after the whistle, the tempo draw and the two-minute warning."""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import snap_clock as sc  # noqa: E402


def table(dead_huddle=30, dead_no_huddle=15, no_huddle=0):
    many = 1000
    return {'live_seconds': {k: {'5.0': many} for k in sc.CLOCK_EVENTS},
            'dead_seconds': {f'{w}|tied|{tempo}': {str(dead): many}
                             for w in ('other', 'q2_last_2', 'q4_last_2', 'q4_last_5')
                             for tempo, dead in (('huddle', dead_huddle), ('no_huddle', dead_no_huddle))},
            'oob_ready_dead_seconds': {'other': {'8': many}},
            'no_huddle': {f'{w}|tied': {'snaps': many, 'no_huddle': no_huddle} for w in ('other', 'q2_last_2', 'q4_last_2', 'q4_last_5')}}


def runoff(clock, **kw):
    args = dict(quarter=1, qsr=600, event='run', out_of_bounds=False, timeout_called=False, margin=0)
    args.update(kw)
    return clock.runoff(random.Random(1), **args)


class Rules(unittest.TestCase):
    def setUp(self):
        self.clock = sc.SnapClock(table(), 'x')

    def test_a_running_clock_adds_the_dead_ball_time(self):
        self.assertEqual(runoff(self.clock)[0], 35)

    def test_an_incompletion_or_a_timeout_stops_the_clock_at_the_whistle(self):
        self.assertEqual(runoff(self.clock, event='pass_incomplete')[0], 5)
        self.assertEqual(runoff(self.clock, timeout_called=True)[0], 5)

    def test_out_of_bounds_stops_late_and_restarts_on_the_ready_signal_otherwise(self):
        self.assertEqual(runoff(self.clock, out_of_bounds=True, quarter=4, qsr=250)[0], 5)
        self.assertEqual(runoff(self.clock, out_of_bounds=True)[0], 13)

    def test_the_two_minute_warning_stops_the_clock_at_2_00(self):
        seconds, record = runoff(self.clock, quarter=2, qsr=130)
        self.assertEqual((seconds, record['two_minute_warning']), (10, 'clock_stopped_at_2:00'))
        seconds, record = runoff(self.clock, quarter=4, qsr=123)
        self.assertEqual((seconds, record['two_minute_warning']), (5, 'after_the_down'))

    def test_the_tempo_follows_the_no_huddle_rate(self):
        fast = sc.SnapClock(table(no_huddle=1000), 'x')
        seconds, record = runoff(fast)
        self.assertEqual((seconds, record['tempo']), (20, 'no_huddle'))

    def test_kicks_and_turnovers_are_not_timed_here(self):
        with self.assertRaises(ValueError):
            runoff(self.clock, event='punt')

    def test_the_real_table_loads_and_matches_its_manifest(self):
        clock = sc.SnapClock.load()
        self.assertGreater(runoff(clock)[0], 0)


if __name__ == '__main__':
    unittest.main()
