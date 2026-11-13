"""Regression for V1.7 fractional penalties across sampling, audit and summary.

The historical model uses discrete buckets; the game reducer and decision
evidence must retain the true fractional state.  These are synthetic tests,
not real-game validation or calibration of the research penalty assumptions.
"""
import random
import unittest

import playcall_model as pm
import slc_engine as se
import slc_playcall as slc
from test_slc_playcall import STATE, SIZES, blank_artifact, cell


class FractionalStateTests(unittest.TestCase):
    def sampler(self, intercept=-30.0):
        return slc.PlayCallSampler(
            slc.PlayCallLayer(blank_artifact(intercept)),
            side_teams={'A': 'AAA', 'B': 'BBB'})

    def test_fractional_distance_uses_ceil_only_for_historical_bucket(self):
        expected = {0.5: 0, 1.0: 0, 2.0: 0, 2.5: 1, 4.25: 2,
                    6.75: 3, 9.5: 4, 14.5: 5}
        for distance, bucket in expected.items():
            with self.subTest(distance=distance):
                self.assertEqual(pm.distance_bucket(distance), bucket)
        for invalid in (0, -0.5, float('nan'), float('inf'), 100.01):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                pm.distance_bucket(invalid)

    def test_playcall_uses_fractional_distance_and_field_bucket_not_truncation(self):
        blocks = {name: [0.0] * size for name, size in
                  dict(SIZES, team_down=8).items()}
        blocks['down_dist'][1] = 5.0
        blocks['field'][3] = 7.0
        layer = slc.PlayCallLayer(blank_artifact(
            0.0, blocks=blocks))
        self.assertEqual(layer.logit(1, 2.5, 10.5, 0, 2, 400, 'AAA'), 12.0)
        self.assertEqual(layer.logit(1, 2, 10, 0, 2, 400, 'AAA'), 0.0)

    def test_decision_evidence_and_situational_summary_keep_fractional_state(self):
        sampler = self.sampler()
        pool = cell([('run', 'run')])
        for distance, yardline in ((0.5, 99.5), (2.5, 10.5),
                                   (8.25, 49.75), (14.5, 53.5)):
            with self.subTest(distance=distance, yardline=yardline):
                state = dict(STATE, togo=distance, yl=yardline)
                sampler.sample(random.Random(104), pool, 'A', 'B', state=state)
                decision = sampler.decisions[-1]
                self.assertEqual(decision['state']['togo'], distance)
                self.assertEqual(decision['state']['yardline_100'], yardline)
                summary = se.summary([decision])
                self.assertEqual(summary['decisions'], 1)
                situation = summary['situational_decision_counts'][0]
                self.assertEqual(situation['distance_bucket'],
                                 pm.DISTANCE_BUCKETS[pm.distance_bucket(distance)][2])
                self.assertEqual(situation['field_bucket'],
                                 pm.FIELD_BUCKETS[pm.field_bucket(yardline)])
                self.assertEqual(decision['decision_timing'], 'pre_outcome_sample')

    def test_zero_distance_remains_an_error_instead_of_being_suppressed(self):
        with self.assertRaises(ValueError):
            se.summary([{'state': {**STATE, 'togo': 0, 'yardline_100': 60,
                                   'team': 'AAA'}, 'event': 'run'}])

    def test_scramble_source_filter_preserves_own_endzone_geometry(self):
        sampler = self.sampler()
        sampler.scramble_bounds = {'max_gain_yards': 30, 'max_loss_yards': 15}
        sample = ('run', {'yards_gained': -1}, 7, 30)
        legal, rejected = sampler._legal_scramble_rows([sample], {'yl': 99.5})
        self.assertEqual(legal, [])
        self.assertEqual(rejected, 1)

    def test_field_goal_observed_ceiling_not_rounded_down(self):
        sampler = self.sampler()
        sampler.field_goal_distance_model = {'max_observed_attempt_yards': 70.0}
        entry = {'base': {('kick', 'field_goal_attempt'): 1}}
        state = dict(STATE, yl=53.5, quarter=4, clock=45)
        eligible, rejected, exception = sampler._field_goal_actions(entry, state)
        self.assertNotIn('field_goal_attempt', eligible)
        self.assertTrue(rejected)
        self.assertFalse(exception)
        state['yl'] = 53.0
        eligible, rejected, exception = sampler._field_goal_actions(entry, state)
        self.assertIn('field_goal_attempt', eligible)
        self.assertFalse(rejected)
        self.assertTrue(exception)


if __name__ == '__main__':
    unittest.main()
