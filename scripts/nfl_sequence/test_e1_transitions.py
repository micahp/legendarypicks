"""Transition tests for the E1 generator, from the rules matrix in docs/rules/NFL-2026-GAME-STATE-RULES.md (section 7).

Run: python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py

The generator is driven by a fake pool that always returns one observed play, so each test controls the outcome
and the derived clock runoff. These tests cover transition legality, not the football distribution.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import reducer  # noqa: E402


class FakePool:
    """Returns one observed-play cell per call. Call 1 gives `first`; later calls give `then`.

    Each entry is (event, row, runoff, spot), which is what build_pool stores for a usable observed play.
    """

    def __init__(self, first, then=None):
        self.calls = 0
        self.first = first
        self.then = then or first

    def get(self, key, default=None):
        self.calls += 1
        event, yards, runoff, spot = self.first if self.calls == 1 else self.then
        row = {'game_id': 'G1', 'play_id': 1.0, 'game_date': '2025-01-01', 'yards_gained': yards,
               'touchdown': 0, 'play_type': 'run' if event == 'run' else 'punt'}
        return [(event, row, runoff, spot)] * (e1.MIN_POOL + 5)


def start(quarter, clock, yl=75, down=1, togo=10, dir_=1):
    return {'quarter': quarter, 'clock': clock, 'offense': 'OFF', 'defense': 'DEF', 'yl': yl, 'down': down,
            'togo': togo, 'dir': dir_}


class QuarterTransitions(unittest.TestCase):
    def test_q1_expiry_continues_the_series_without_a_kickoff(self):
        # The first run outlasts the 100 seconds left, so Q1 expires on it. The drive goes on in Q2 and ends on a punt.
        pool = FakePool(('run', 4, 300, None), ('punt', 0, 10, 22))
        plays, terminal = e1.simulate(start(1, 100), 1, pool, 'e1-test-seed1')
        self.assertEqual(terminal, 'punt')
        self.assertEqual(len(plays), 2)
        first = plays[0]
        self.assertTrue(first['outcome']['quarter_change'])
        self.assertEqual(first['state_after']['quarter'], 2)
        self.assertEqual(first['state_after']['clock_seconds'], e1.QUARTER_LENGTH)
        self.assertEqual(first['state_after']['offense_team'], 'OFF')
        self.assertEqual(first['state_after']['yardline_100'], 71)
        self.assertEqual(first['state_after']['down'], 2)
        self.assertNotIn('end_of_drive', first['state_after'])
        self.assertEqual(first['field']['before']['dir'], 1)
        self.assertEqual(first['field']['after']['dir'], -1)
        self.assertEqual(first['field']['after']['los'], 71)
        self.assertEqual(plays[1]['state_before']['quarter'], 2)
        e1.check_drive(plays, terminal)

    def test_q2_expiry_is_halftime_and_not_a_turnover_on_downs(self):
        plays, terminal = e1.simulate(start(2, 100), 1, FakePool(('run', 4, 300, None)), 'e1-test-seed1')
        self.assertEqual(terminal, 'halftime')
        last = plays[-1]['state_after']
        self.assertEqual(last['end_of_drive'], 'halftime')
        self.assertEqual(last['quarter'], 2)
        self.assertEqual(last['clock_seconds'], 0)
        self.assertIsNone(last['yardline_100'])
        self.assertFalse(plays[-1]['outcome']['turnover'])
        self.assertIsNone(plays[-1]['field']['after']['dir'], 'no scrimmage endpoint at halftime (schema 1.1)')
        self.assertIsNone(plays[-1]['field']['after']['los'])
        self.assertIsNotNone(plays[-1]['outcome']['final_play_yardline_100'], 'the final play position is kept in outcome')
        e1.check_drive(plays, terminal)

    def test_q4_expiry_is_regulation_end(self):
        plays, terminal = e1.simulate(start(4, 100), 1, FakePool(('run', 4, 300, None)), 'e1-test-seed1')
        self.assertEqual(terminal, 'end_of_regulation')
        self.assertEqual(plays[-1]['state_after']['quarter'], 4)
        e1.check_drive(plays, terminal)

    def test_a_turnover_at_the_q1_expiry_ends_the_drive_in_the_new_quarter(self):
        # The interception runs out the clock. The quarter changes on that play, and the other team starts Q2 with a full clock.
        pool = FakePool(('interception', 0, 300, 30), ('punt', 0, 10, 22))
        plays, terminal = e1.simulate(start(1, 100), 1, pool, 'e1-test-seed1')
        self.assertEqual(terminal, 'turnover')
        last = plays[-1]['state_after']
        self.assertEqual((last['quarter'], last['clock_seconds'], last['offense_team'], last['yardline_100']), (2, 900, 'DEF', 30))
        self.assertTrue(plays[-1]['outcome']['quarter_change'])
        self.assertEqual(last['end_of_drive'], 'turnover')
        e1.check_drive(plays, terminal)

    def test_a_turnover_at_the_q2_expiry_ends_the_half_and_not_the_drive(self):
        # The same interception in Q2 ends the half. The terminal is halftime, not turnover: the half ends on the play, and
        # the next snap is the half-start kickoff.
        pool = FakePool(('interception', 0, 300, 30), ('punt', 0, 10, 22))
        plays, terminal = e1.simulate(start(2, 100), 1, pool, 'e1-test-seed1')
        self.assertEqual(terminal, 'halftime')
        last = plays[-1]['state_after']
        self.assertEqual((last['quarter'], last['clock_seconds'], last['end_of_drive']), (2, 0, 'halftime'))
        self.assertTrue(plays[-1]['outcome']['turnover'])
        e1.check_drive(plays, terminal)

    def test_blocked_punt_turnover_at_period_expiry_ends_at_halftime(self):
        def block(event, st, row, runoff, spot, rng):
            self.assertEqual(event, 'punt')
            return {'event': 'blocked_punt', 'clock_runoff_seconds': 1,
                    'kick_outcome': {'kick_type': 'punt', 'classification_status': 'classified_recovery',
                                     'recovery_role': 'receiving_team', 'recovery_yards_from_los': -5,
                                     'return_endpoint_yards_from_los': -20}}

        plays, terminal = e1.simulate(start(2, 1, yl=50, down=4, togo=5), 1,
                                      FakePool(('punt', 0, 10, 22)), 'e1-blocked-punt-expiry',
                                      special_teams=block)
        self.assertEqual(terminal, 'halftime')
        self.assertEqual(plays[-1]['event_type'], 'blocked_punt')
        self.assertTrue(plays[-1]['outcome']['turnover'])
        self.assertEqual(plays[-1]['state_after']['clock_seconds'], 0)
        e1.check_drive(plays, terminal)

    def test_a_fourth_down_turnover_keeps_turnover_on_downs_in_the_outcome(self):
        plays, terminal = e1.simulate(start(1, 600, yl=50, down=4, togo=10), 1,
                                      FakePool(('run', 0, 10, None)), 'e1-turnover-on-downs')
        self.assertEqual(terminal, 'turnover_on_downs')
        self.assertTrue(plays[-1]['outcome']['turnover_on_downs'])
        self.assertTrue(plays[-1]['outcome']['turnover'])

    def test_a_block_keeps_the_plays_made_before_it(self):
        def block(event, st, row, runoff, spot, rng):
            return {'blocker': 'blocked_kick_outcome_unresolved:punt:unclassified'}

        partial = []
        plays, terminal = e1.simulate(start(1, 600, yl=75, down=1, togo=10), 1,
                                      FakePool(('run', 5, 10, None), then=('punt', 0, 10, 22)), 'e1-keep-partial',
                                      special_teams=block, partial=partial)
        self.assertIsNone(plays)
        self.assertEqual(terminal, 'blocked_kick_outcome_unresolved:punt:unclassified')
        self.assertEqual([p['event_type'] for p in partial], ['run'])

    def test_blocked_punt_off_the_field_is_a_named_block_not_a_crash(self):
        def block(event, st, row, runoff, spot, rng):
            return {'event': 'blocked_punt', 'clock_runoff_seconds': 1,
                    'kick_outcome': {'kick_type': 'punt', 'classification_status': 'classified_recovery',
                                     'recovery_role': 'receiving_team', 'recovery_yards_from_los': -16,
                                     'return_endpoint_yards_from_los': -21}}

        plays, terminal = e1.simulate(start(1, 600, yl=90, down=4, togo=10), 1,
                                      FakePool(('punt', 0, 10, 22)), 'e1-blocked-punt-off-field',
                                      special_teams=block)
        self.assertIsNone(plays)
        self.assertEqual(terminal, 'blocked_kick_receiving_return_outside_field')

    def test_a_punt_at_the_q4_expiry_is_regulation_end_with_the_receiving_spot(self):
        pool = FakePool(('punt', 0, 300, 22), ('punt', 0, 10, 22))
        plays, terminal = e1.simulate(start(4, 100), 1, pool, 'e1-test-seed1')
        self.assertEqual(terminal, 'end_of_regulation')
        self.assertEqual(plays[-1]['state_after']['yardline_100'], 22)
        e1.check_drive(plays, terminal)

    def test_a_turnover_terminal_at_the_end_of_q2_is_refused_by_the_drive_check(self):
        # The check fails loudly on the old behaviour: a possession change recorded as the drive's end at a Q2 expiry.
        plays, terminal = e1.simulate(start(2, 100), 1, FakePool(('interception', 0, 300, 30), ('punt', 0, 10, 22)), 'e1-test-seed1')
        plays[-1]['state_after']['end_of_drive'] = 'turnover'
        with self.assertRaises(AssertionError):
            e1.check_drive(plays, 'turnover')

    def test_no_drive_terminates_at_q1_or_q3_expiry(self):
        for q in (1, 3):
            pool = FakePool(('run', 4, 300, None), ('punt', 0, 10, 22))
            plays, terminal = e1.simulate(start(q, 100), 1, pool, 'e1-test-seed1')
            self.assertEqual(terminal, 'punt')
            self.assertTrue(plays[0]['outcome']['quarter_change'])
            self.assertNotIn(terminal, ('end_of_period', 'halftime', 'end_of_regulation'))


class Reducer(unittest.TestCase):
    def test_turnover_on_downs_complements_field_position(self):
        # Second quarter, fourth and 5 at the own 40 (yardline 60), a 2-yard gain: the other team takes over at 42.
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}, 'run', 2)
        self.assertEqual(terminal, 'turnover_on_downs')
        self.assertTrue(flags['turnover_on_downs'])
        self.assertEqual(after['offense'], 'B')
        self.assertEqual(after['yl'], 42)
        self.assertEqual(after['down'], 1)

    def test_unknown_event_is_refused(self):
        with self.assertRaises(ValueError):
            reducer.apply_play({'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50}, 'kickoff', 0)

    def test_punt_gives_the_receiving_spot(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 3, 'yl': 40}, 'punt', 0, spot=22)
        self.assertEqual(terminal, 'punt')
        self.assertEqual(after['offense'], 'B')
        self.assertEqual(after['yl'], 22)

    def test_field_goal_attempt_has_no_result_and_no_next_spot(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 3, 'yl': 15}, 'field_goal_attempt', 0)
        self.assertIsNone(after)
        self.assertEqual(terminal, 'field_goal_attempt')
        self.assertTrue(flags['field_goal_attempt'])

    def test_blocked_kick_receiving_team_recovery_can_be_returned(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 8, 'yl': 55}, 'blocked_punt', 0,
            kick_outcome={'kick_type': 'punt', 'classification_status': 'classified_recovery',
                          'recovery_role': 'receiving_team', 'recovery_yards_from_los': -5,
                          'return_endpoint_yards_from_los': -11})
        self.assertEqual((terminal, after['offense'], after['down'], after['yl']), ('turnover', 'B', 1, 34))
        self.assertTrue(flags['turnover'])
        self.assertTrue(flags['punt_attempt'])

    def test_blocked_kick_return_off_the_field_is_a_named_block(self):
        # Seed 245: a blocked punt at the own 10 whose observed return ends 21 yards behind the line projects past the goal line.
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            reducer.apply_play({'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 8, 'yl': 90}, 'blocked_punt', 0,
                               kick_outcome={'kick_type': 'punt', 'classification_status': 'classified_recovery',
                                             'recovery_role': 'receiving_team', 'recovery_yards_from_los': -16,
                                             'return_endpoint_yards_from_los': -21})
        self.assertEqual(caught.exception.reason, 'blocked_kick_receiving_return_outside_field')
        self.assertIsInstance(caught.exception, ValueError)

    def test_blocked_kick_kicking_team_return_off_the_field_is_a_named_block(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            reducer.apply_play({'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 3}, 'blocked_punt', 0,
                               kick_outcome={'kick_type': 'punt', 'classification_status': 'classified_recovery',
                                             'recovery_role': 'kicking_team', 'recovery_yards_from_los': 0,
                                             'return_endpoint_yards_from_los': 5})
        self.assertEqual(caught.exception.reason, 'blocked_kick_kicking_return_outside_field')

    def test_blocked_kick_kicking_team_recovery_behind_los_can_fail_on_fourth_down(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}, 'blocked_field_goal', 0,
            kick_outcome={'kick_type': 'field_goal', 'classification_status': 'classified_recovery',
                          'recovery_role': 'kicking_team', 'recovery_yards_from_los': -10,
                          'return_endpoint_yards_from_los': -2})
        self.assertEqual((terminal, after['offense'], after['yl']), ('turnover_on_downs', 'B', 38))
        self.assertTrue(flags['turnover_on_downs'])

    def test_blocked_kick_kicking_team_recovery_behind_los_can_convert(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}, 'blocked_punt', 0,
            kick_outcome={'kick_type': 'punt', 'classification_status': 'classified_recovery',
                          'recovery_role': 'kicking_team', 'recovery_yards_from_los': -10,
                          'return_endpoint_yards_from_los': 6})
        self.assertIsNone(terminal)
        self.assertEqual((after['offense'], after['down'], after['togo'], after['yl']), ('A', 1, 10, 54))

    def test_kicking_team_recovery_beyond_los_requires_receiving_team_touch(self):
        st = {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 55}
        common = {'kick_type': 'field_goal', 'classification_status': 'classified_recovery',
                  'recovery_role': 'kicking_team', 'recovery_yards_from_los': 15,
                  'return_endpoint_yards_from_los': 15}
        with self.assertRaisesRegex(ValueError, 'touch result'):
            reducer.apply_play(st, 'blocked_field_goal', 0, kick_outcome=common)
        no_touch = dict(common, receiving_team_touched_beyond_line=False)
        after, terminal, flags = reducer.apply_play(st, 'blocked_field_goal', 0, kick_outcome=no_touch)
        self.assertEqual((terminal, after['offense'], after['yl']), ('turnover', 'B', 60))
        legal = dict(common, receiving_team_touched_beyond_line=True)
        after, terminal, flags = reducer.apply_play(st, 'blocked_field_goal', 0, kick_outcome=legal)
        self.assertIsNone(terminal)
        self.assertEqual((after['offense'], after['down'], after['yl']), ('A', 1, 40))

    def test_blocked_kick_return_touchdown_credits_the_recovery_side(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}, 'blocked_field_goal', 0,
            kick_outcome={'kick_type': 'field_goal', 'classification_status': 'touchdown', 'touchdown': True,
                          'scoring_role': 'receiving_team'})
        self.assertIsNone(after)
        self.assertEqual(terminal, 'touchdown')
        self.assertEqual(flags['scoring_team'], 'B')

    def test_receiving_team_return_rebases_at_multiple_kick_spots(self):
        outcome = {'kick_type': 'punt', 'classification_status': 'classified_recovery',
                   'recovery_role': 'receiving_team', 'recovery_yards_from_los': -18,
                   'return_endpoint_yards_from_los': -24}
        spots = []
        for kick_yl in (74, 50):
            after, terminal, _ = reducer.apply_play(
                {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 10, 'yl': kick_yl},
                'blocked_punt', 0, kick_outcome=outcome)
            self.assertEqual((terminal, after['offense']), ('turnover', 'B'))
            spots.append(after['yl'])
        self.assertEqual(spots, [2, 26])

    def test_kicking_team_first_down_result_rebases_at_multiple_kick_spots(self):
        outcome = {'kick_type': 'punt', 'classification_status': 'classified_recovery',
                   'recovery_role': 'kicking_team', 'recovery_yards_from_los': -10,
                   'return_endpoint_yards_from_los': 6}
        endpoints = []
        for kick_yl in (60, 50):
            after, terminal, _ = reducer.apply_play(
                {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': kick_yl},
                'blocked_punt', 0, kick_outcome=outcome)
            self.assertIsNone(terminal)
            self.assertEqual((after['offense'], after['down']), ('A', 1))
            endpoints.append(after['yl'])
        self.assertEqual(endpoints, [54, 44])

    def test_described_dead_ball_spot_rebases_at_multiple_kick_spots(self):
        outcome = {'kick_type': 'punt', 'classification_status': 'classified_dead_ball_spot',
                   'possession_after_role': 'receiving_team', 'dead_ball_yards_from_los': -9}
        spots = []
        for kick_yl in (86, 50):
            after, terminal, _ = reducer.apply_play(
                {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 10, 'yl': kick_yl},
                'blocked_punt', 0, kick_outcome=outcome)
            self.assertEqual((terminal, after['offense']), ('turnover', 'B'))
            spots.append(after['yl'])
        self.assertEqual(spots, [5, 41])

    def test_historical_next_snap_award_is_not_a_supported_blocked_kick_event(self):
        with self.assertRaisesRegex(ValueError, 'classified observed outcome'):
            reducer.apply_play(
                {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 10, 'yl': 50},
                'blocked_field_goal', 0,
                kick_outcome={'kick_type': 'field_goal', 'classification_status': 'classified_dead_ball_award',
                              'return_endpoint_yardline_100': 70})


FIXTURE_DIR = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e1'


class Vocabulary(unittest.TestCase):
    def test_terminals_constant_is_the_e1_vocabulary(self):
        self.assertEqual(
            reducer.TERMINALS,
            ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt',
             'halftime', 'end_of_regulation'))
        self.assertNotIn('end_of_period', reducer.TERMINALS)

    def test_pinned_records_use_exactly_the_terminals_in_the_constant(self):
        used = set()
        for path in FIXTURE_DIR.glob('*.json'):
            record = json.loads(path.read_text())
            terminal = record['plays'][-1]['state_after'].get('end_of_drive')
            self.assertIsNotNone(terminal, path.name)
            used.add(terminal)
            for play in record['plays'][:-1]:
                self.assertNotIn('end_of_drive', play['state_after'], path.name)
        self.assertEqual(used, set(reducer.TERMINALS))
        self.assertNotIn('end_of_period', used)

    def test_generated_and_pinned_play_ids_follow_the_simulation_id_contract(self):
        plays, _ = e1.simulate(start(1, 100), 1, FakePool(('run', 4, 10, None)), 'e1-contract-test')
        self.assertTrue(plays)
        self.assertEqual([p['id'] for p in plays], [f'e1-contract-test:{i}' for i in range(1, len(plays) + 1)])
        for path in FIXTURE_DIR.glob('*.json'):
            record = json.loads(path.read_text())
            self.assertEqual(
                [p['id'] for p in record['plays']],
                [f"{record['simulation_id']}:{i}" for i in range(1, len(record['plays']) + 1)],
                path.name,
            )


if __name__ == '__main__':
    unittest.main()
