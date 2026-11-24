import unittest

import pandas as pd

import ceg_contract as c
import ceg_event_tables as t

P = c.Provenance('ceg-arm-b', '0', 'x' * 64, ('intent', 'dropback'), ('s1', 's2'))
CALL = c.PlayCall('dropback', {'dropback': 0.6, 'designed_run': 0.4}, P)
RUN = c.PlayCall('designed_run', {'designed_run': 1.0}, P)
CLOCK = c.Clock(6.0, 30.0, 'running')
STATE = {'down': 1, 'togo': 10, 'yl': 75}


def play(**kw):
    base = dict(contract=c.CONTRACT_VERSION, call=CALL, event='pass_complete', yards_gained=12, air_yards=8,
                yards_after_catch=4, receiver='r1', passer='q1', clock=CLOCK, provenance=P)
    base.update(kw)
    return c.GeneratedPlay(**base)


class Contract(unittest.TestCase):
    def test_a_coherent_completion_passes(self):
        self.assertIsNone(c.validate(STATE, play()))

    def test_air_yards_and_yac_must_sum_to_the_gain(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(yards_after_catch=5))

    def test_a_sack_has_no_target_and_no_gain(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(event='sack', yards_gained=-7, air_yards=None, yards_after_catch=None))
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(event='sack', yards_gained=2, receiver=None, air_yards=None, yards_after_catch=None))

    def test_no_cap_but_the_field_holds(self):
        long_run = play(call=RUN, event='run', yards_gained=75, air_yards=None, yards_after_catch=None, receiver=None,
                        rusher='b1', touchdown_team='offense')
        self.assertEqual(c.validate(STATE, long_run), 'opponent_goal_line')
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(call=RUN, event='run', yards_gained=76, air_yards=None, yards_after_catch=None,
                                   receiver=None, rusher='b1'))

    def test_a_loss_to_the_own_goal_line_is_reported_not_refused(self):
        safety = play(call=RUN, event='run', yards_gained=-25, air_yards=None, yards_after_catch=None, receiver=None,
                      rusher='b1')
        self.assertEqual(c.validate(STATE, safety), 'own_goal_line')

    def test_a_fumble_needs_its_recovery(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(fumble=True))
        ok = play(fumble=True, possession=c.Possession('defense', 'fumble_recovery', 70, return_yards=3))
        self.assertIsNone(c.validate(STATE, ok))

    def test_a_stopped_clock_has_no_dead_ball_runoff(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(clock=c.Clock(5.0, 3.0, 'stopped')))
        self.assertEqual(c.Clock(5.0, 30.0, 'running').runoff_seconds, 35.0)

    def test_a_pre_snap_foul_voids_the_play(self):
        foul = c.Penalty('False Start', 'offense', -5, True, False, pre_snap=True)
        self.assertIsNone(c.validate(STATE, play(penalty=foul, yards_gained=0, receiver=None, air_yards=None,
                                                 yards_after_catch=None)))

    def test_intent_limits_the_event(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(call=RUN))

    def test_provenance_is_required(self):
        with self.assertRaises(c.ContractViolation):
            c.validate(STATE, play(provenance=None))


class PlayClass(unittest.TestCase):
    def frame(self, rows):
        cols = ['play_type', 'timeout', 'qb_dropback', 'qb_scramble', 'qb_spike', 'qb_kneel', 'two_point_attempt', 'penalty']
        return pd.DataFrame([dict(zip(cols, r)) for r in rows])

    def test_classes(self):
        d = self.frame([
            ('run', 0, 0, 0, 0, 0, 0, 0),          # designed run
            ('run', 0, 1, 1, 0, 0, 0, 0),          # scramble
            ('pass', 0, 1, 0, 0, 0, 0, 0),         # dropback
            ('qb_kneel', 0, 0, 0, 0, 1, 0, 0),     # kneel
            ('no_play', 1, 0, 0, 0, 0, 0, 0),      # timeout row
            ('no_play', 0, 0, 0, 0, 0, 0, 1),      # pre-snap penalty
            ('pass', 0, 1, 0, 0, 0, 1, 0),         # two-point try
            (None, 0, 0, 0, 0, 0, 0, 0),           # admin row
        ])
        self.assertEqual(t.play_class(d).tolist(), ['designed_run', 'scramble', 'dropback', 'kneel', 'timeout', 'no_play',
                                                     'two_point', 'admin'])


if __name__ == '__main__':
    unittest.main()
