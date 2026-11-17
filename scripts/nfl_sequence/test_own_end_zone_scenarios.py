"""PR #49 acceptance scenarios, forced and deterministic.

Reducer level: every row of the own-end-zone table, resolved by apply_play.
Full-game level: the drive simulator with a penalty controller and the geometry
filter on (V1.7), so each row is applied through the same path a game uses.
Frozen V1.6 (default flags) is checked alongside.
"""
import collections
import unittest

import e0_single_play as e0
import e1_drive as e1
import football_assertions
import reducer
from penalty_game import PenaltyGameController
from test_penalty_goal_line_fumble import ChooseFirst, NoFoulSampler

OWN_ONE = {'quarter': 4, 'clock': 420, 'offense': 'A', 'defense': 'B',
           'yl': 99, 'down': 4, 'togo': 1, 'dir': 1}  # offense at its own 1
NO_LEGAL = 'goal_line_fumble_source_cell_has_no_geometrically_legal_outcome'


class ReducerOwnEndZoneScenarios(unittest.TestCase):
    def resolve(self, event, yards, recovery=None):
        return reducer.apply_play(dict(OWN_ONE), event, yards, recovery=recovery, own_end_zone='resolve')

    def test_run_tackled_in_own_end_zone_is_a_safety(self):
        _after, terminal, flags = self.resolve('run', -3)
        self.assertEqual(terminal, 'safety')
        self.assertTrue(flags['safety'])
        self.assertEqual(flags['scoring_team'], 'B')

    def test_completed_pass_ending_in_own_end_zone_is_a_safety(self):
        _after, terminal, flags = self.resolve('pass_complete', -3)
        self.assertEqual(terminal, 'safety')
        self.assertTrue(flags['safety'])

    def test_sack_in_own_end_zone_is_a_safety(self):
        _after, terminal, flags = self.resolve('sack', -3)
        self.assertEqual(terminal, 'safety')
        self.assertTrue(flags['safety'])

    def test_turnover_with_a_recovery_role_is_refused_because_the_event_has_no_recovery_location(self):
        # A sack_fumble_lost says possession was lost, not where the ball was recovered.
        # Offense-recovery safety and defense-recovery touchdown cannot be read from it.
        for recovery in ('offense', 'defense'):
            with self.assertRaises(ValueError):
                self.resolve('sack_fumble_lost', -3, recovery=recovery)

    def test_fumble_with_unknown_recovery_is_an_explicit_block(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            self.resolve('sack_fumble_lost', -3)
        self.assertEqual(caught.exception.reason, 'own_end_zone_fumble_recovery_unresolved')

    def test_frozen_v16_default_still_refuses_every_own_end_zone_loss(self):
        for event in ('run', 'pass_complete', 'sack'):
            with self.assertRaises(ValueError):
                reducer.apply_play(dict(OWN_ONE), event, -3)


class FullGameOwnEndZoneScenarios(unittest.TestCase):
    def pool(self, event, yards):
        row = {'game_id': '2024_01_WAS_NYG', 'play_id': 31, 'game_date': '2024-09-08',
               'play_type': 'run' if event == 'run' else 'pass', 'yards_gained': yards,
               'touchdown': 0, 'sack': 1 if event.startswith('sack') else 0,
               'fumble_lost': 1 if 'fumble' in event else 0, 'penalty': 0}
        key = (4, e0.ydstogo_bucket(1), e0.yardline_bucket(99))
        return dict(OWN_ONE), {key: [(event, row, 8, 20)]}

    def simulate(self, event, yards, geometry_filter=True):
        st, pool = self.pool(event, yards)
        penalties = PenaltyGameController(sampler=NoFoulSampler(), game_seed=61,
                                          team_identity={'A': 'WAS', 'B': 'NYG'},
                                          ruling_provider=lambda *a, **k: None)
        policy = ChooseFirst()
        policy.geometry_excluded = collections.Counter()
        out = e1.simulate(st, 61, pool, 'pr49-%s' % event, sampling_policy=policy,
                          penalty_controller=penalties, geometry_filter=geometry_filter,
                          own_end_zone='resolve')
        return out, policy

    def test_run_in_own_end_zone_ends_the_drive_as_a_safety(self):
        (plays, terminal), _policy = self.simulate('run', -3)
        self.assertEqual(terminal, 'safety')
        self.assertEqual(len(plays), 1)

    def test_completed_pass_in_own_end_zone_ends_the_drive_as_a_safety(self):
        (plays, terminal), _policy = self.simulate('pass_complete', -3)
        self.assertEqual(terminal, 'safety')
        self.assertEqual(len(plays), 1)

    def test_sack_in_own_end_zone_ends_the_drive_as_a_safety(self):
        (plays, terminal), _policy = self.simulate('sack', -3)
        self.assertEqual(terminal, 'safety')
        self.assertEqual(len(plays), 1)

    def test_own_end_zone_fumble_is_excluded_and_blocked_at_game_level(self):
        # The geometry filter removes a turnover whose net gain crosses the goal line,
        # because the game loop has no recovery role. With no legal row left: named block.
        (plays, terminal), policy = self.simulate('sack_fumble_lost', -3)
        self.assertIsNone(plays)
        self.assertEqual(terminal, NO_LEGAL)
        self.assertEqual(policy.geometry_excluded['turnover_source_rows'], 1)

    def test_frozen_v16_run_in_own_end_zone_is_clamped_to_a_safety(self):
        # Frozen V1.6 (no penalty controller, default flags). Runs, passes and sacks are
        # clamped at the goal line by the existing boundary rule, so they reach the reducer as
        # a safety. This is unchanged by PR 49.
        st, pool = self.pool('run', -3)
        plays, terminal = e1.simulate(st, 61, pool, 'pr49-v16-run', sampling_policy=ChooseFirst())
        self.assertEqual(terminal, 'safety')
        self.assertEqual(len(plays), 1)

    def test_frozen_v16_own_end_zone_fumble_is_still_refused(self):
        # Turnovers are not clamped, so the frozen V1.6 refusal still applies to them.
        st, pool = self.pool('sack_fumble_lost', -3)
        with self.assertRaises(football_assertions.FootballAssertionError):
            e1.simulate(st, 61, pool, 'pr49-v16-fumble', sampling_policy=ChooseFirst())


if __name__ == '__main__':
    unittest.main()
