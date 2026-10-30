"""Transition tests for the E1 generator, from the rules matrix in docs/rules/NFL-2026-GAME-STATE-RULES.md (section 7).

Run: python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py

The generator is driven by a fake pool that always returns one observed play, so each test controls the outcome
and the derived clock runoff. These tests cover transition legality, not the football distribution.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import reducer  # noqa: E402
import football_assertions  # noqa: E402
from paired_random_streams import PairedRandomStreams  # noqa: E402


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


class FieldBoundarySampling(unittest.TestCase):
    def test_playcall_draw_count_does_not_shift_the_special_teams_stream(self):
        streams = PairedRandomStreams(12, 'c' * 64)
        special_draws = []

        class Policy:
            def __init__(self, extra_draws):
                self.extra_draws = extra_draws

            def sample(self, rng, cell, **_context):
                rng.random()
                for _ in range(self.extra_draws):
                    rng.random()
                return cell[0]

        def special_teams(_event, _state, _row, _runoff, _spot, rng):
            special_draws.append(rng.random())
            return None

        for extra_draws in (0, 7):
            plays, terminal = e1.simulate(
                start(1, 900), 91, FakePool(('punt', 0, 10, 22)), f'paired-{extra_draws}',
                special_teams=special_teams, sampling_policy=Policy(extra_draws),
                play_index_start=1, drive_index=3, paired_random_streams=streams,
            )
            self.assertEqual(terminal, 'punt')
            self.assertEqual(len(plays), 1)
        self.assertEqual(special_draws[0], special_draws[1])

    def test_illegal_sampled_play_keeps_game_wide_failure_context(self):
        pool = FakePool(('pass_incomplete', 5, 10, None))
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            e1.simulate(start(1, 900), 91, pool, 'illegal-incomplete', play_index_start=8)

        failure = raised.exception
        self.assertEqual(failure.failure_class, 'ILLEGAL_STATE')
        self.assertEqual(failure.context['play_index'], 8)
        self.assertEqual(failure.context['state_before'], {
            'quarter': 1, 'offense': 'OFF', 'defense': 'DEF', 'down': 1, 'togo': 10,
            'yl': 75, 'clock': 900, 'dir': 1,
        })
        self.assertEqual(failure.context['decision']['event'], 'pass_incomplete')
        self.assertEqual(failure.context['decision']['source_play'], {
            'game_id': 'G1', 'play_id': 1.0, 'season': None, 'week': None,
        })
        self.assertEqual(failure.context['outcome'], {
            'event_type': 'pass_incomplete', 'sampled_yards_gained': 5,
            'credited_yards_gained': 5, 'next_snap_spot': None, 'kick_outcome': None,
        })
        self.assertEqual(failure.context['state_after'], 'not_applied')

    def test_other_illegal_play_and_state_mutations_use_the_same_failure_class_and_context(self):
        mutations = (
            ('sack', 1, start(1, 900), 'sack cannot produce positive yardage'),
            ('run', 1, start(1, 900, down=5), 'down must be 1 through 4'),
        )
        for index, (event, yards, state, expected) in enumerate(mutations, start=1):
            with self.subTest(event=event, yards=yards, down=state['down']):
                with self.assertRaises(football_assertions.FootballAssertionError) as raised:
                    e1.simulate(state, 91, FakePool((event, yards, 10, None)),
                                f'illegal-{event}-{index}', play_index_start=20)
                failure = raised.exception
                self.assertEqual(failure.failure_class, 'ILLEGAL_STATE')
                self.assertEqual(failure.context['play_index'], 20)
                self.assertEqual(failure.context['state_before']['down'], state['down'])
                self.assertEqual(failure.context['decision']['event'], event)
                self.assertEqual(failure.context['outcome']['event_type'], event)
                self.assertEqual(failure.context['state_after'], 'not_applied')
                self.assertIn(expected, str(failure))

    def test_reducer_rejects_illegal_spots_and_uncredited_goal_line_overruns(self):
        state = {'offense': 'OFF', 'defense': 'DEF', 'down': 1, 'togo': 5, 'yl': 5}
        after, terminal, flags = reducer.apply_play(state, 'run', 5)
        self.assertIsNone(after)
        self.assertEqual(terminal, 'touchdown')
        self.assertTrue(flags['touchdown'])
        with self.assertRaisesRegex(ValueError, 'exceeds the 5 yards to the goal line'):
            reducer.apply_play(state, 'run', 6)
        with self.assertRaisesRegex(ValueError, 'past its own goal line'):
            reducer.apply_play({**state, 'yl': 95, 'togo': 5}, 'sack', -6)
        with self.assertRaisesRegex(ValueError, 'down must be 1 through 4'):
            reducer.apply_play({**state, 'down': 5}, 'run', 1)
        with self.assertRaisesRegex(ValueError, 'distance must be 1 through the distance to goal'):
            reducer.apply_play({**state, 'togo': 6}, 'run', 1)

    def test_goal_line_overruns_are_credited_at_the_boundary_with_raw_sample_preserved(self):
        class MixedPool:
            def __init__(self, invalid_yards, legal_yards):
                self.entries = []
                for play_id, yards in enumerate((invalid_yards, legal_yards), 1):
                    row = {'game_id': 'G1', 'play_id': float(play_id), 'game_date': '2025-01-01',
                           'yards_gained': yards, 'touchdown': 0, 'play_type': 'run'}
                    self.entries.extend([('run', row, 10, None)] * (e1.MIN_POOL + 5))

            def get(self, key, default=None):
                return self.entries

        for yl, invalid, legal, terminal in ((5, 6, 5, 'touchdown'), (95, -6, -5, 'safety')):
            with self.subTest(yardline=yl, terminal=terminal):
                plays, result = e1.simulate(start(4, 900, yl=yl, down=1, togo=min(5, yl)), 17,
                                            MixedPool(invalid, legal), f'boundary-{yl}')
                self.assertEqual(result, terminal)
                outcome = plays[0]['outcome']
                self.assertEqual(outcome['yards_gained'], legal)
                self.assertIn(outcome['sampled_yards_gained'], (invalid, legal))
                self.assertEqual(plays[0]['sampling']['cell_size'], 2 * (e1.MIN_POOL + 5))
                if invalid == outcome['sampled_yards_gained']:
                    self.assertEqual(outcome['yardage_boundary_adjustment'], {
                        'boundary': 'opponent_goal_line' if terminal == 'touchdown' else 'own_goal_line',
                        'sampled_yards_gained': invalid, 'credited_yards_gained': legal,
                    })
                else:
                    self.assertIsNone(outcome['yardage_boundary_adjustment'])
                e1.check_drive(plays, terminal)


class QuarterTransitions(unittest.TestCase):
    def test_contextual_sampler_receives_the_current_offense_and_defense(self):
        class Sampler:
            def __init__(self):
                self.seen = None

            def sample(self, rng, cell, offense, defense, state=None):
                self.seen = (offense, defense)
                return cell[0]

        sampler = Sampler()
        e1.simulate(start(4, 10), 1, FakePool(('run', 4, 10, None)), 'e1-context-sampler',
                    sampling_policy=sampler)
        self.assertEqual(sampler.seen, ('OFF', 'DEF'))

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

    def test_blocked_kick_at_q1_expiry_blocks_when_next_possession_is_unknown(self):
        def block(event, st, row, runoff, spot, rng):
            self.assertEqual(event, 'field_goal_attempt')
            return {'event': 'blocked_field_goal', 'clock_runoff_seconds': 1,
                    'kick_outcome': {'kick_type': 'field_goal', 'classification_status': 'period_expired'}}

        partial = []
        plays, blocker = e1.simulate(start(1, 1, yl=50, down=4, togo=5), 1,
                                     FakePool(('field_goal_attempt', 0, 1, None)), 'e1-blocked-fg-q1-expiry',
                                     special_teams=block, partial=partial)

        self.assertIsNone(plays)
        self.assertEqual(blocker, 'blocked_kick_period_expired_next_possession_unresolved')
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]['event_type'], 'blocked_field_goal')
        self.assertEqual(partial[0]['state_after']['quarter'], 2)
        self.assertEqual(partial[0]['state_after']['clock_seconds'], e1.QUARTER_LENGTH)

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
    def test_incomplete_pass_is_a_dead_ball_with_zero_yards(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 50}
        after, terminal, flags = reducer.apply_play(state, 'pass_incomplete', 0)
        self.assertIsNone(terminal)
        self.assertEqual((after['offense'], after['down'], after['togo'], after['yl']), ('A', 3, 7, 50))
        self.assertFalse(any(flags.values()))
        for impossible_gain in (-1, 1, 12):
            with self.subTest(yards=impossible_gain), self.assertRaisesRegex(ValueError, 'incomplete pass must have zero'):
                reducer.apply_play(state, 'pass_incomplete', impossible_gain)

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

    def test_blocked_kick_next_snap_requires_a_legal_spot_down_and_distance(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 55}
        valid = {'kick_type': 'field_goal', 'classification_status': 'classified_next_snap',
                 'possession_after_role': 'receiving_team', 'next_snap_yardline_100': 45,
                 'next_snap_down': 1, 'next_snap_ydstogo': 10}
        after, terminal, flags = reducer.apply_play(state, 'blocked_field_goal', 0, kick_outcome=valid)
        self.assertEqual((terminal, after['offense'], after['yl'], after['down'], after['togo']),
                         ('turnover', 'B', 45, 1, 10))
        self.assertTrue(flags['turnover'])
        for updates in (
            {'next_snap_yardline_100': 0}, {'next_snap_yardline_100': 100},
            {'next_snap_down': 5}, {'next_snap_ydstogo': 0}, {'next_snap_ydstogo': 46},
            {'next_snap_ydstogo': True},
        ):
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, 'legal observed start spot, down and distance'):
                reducer.apply_play(state, 'blocked_field_goal', 0, kick_outcome={**valid, **updates})

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
            reducer.apply_play({'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 3, 'yl': 3}, 'blocked_punt', 0,
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

    def test_blocked_kick_td_role_is_derived_from_published_source_teams(self):
        state = {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}
        outcome = {'kick_type': 'field_goal', 'classification_status': 'touchdown', 'touchdown': True,
                   'posteam': 'CHI', 'defteam': 'GB', 'scoring_team': 'GB'}
        after, terminal, flags = reducer.apply_play(state, 'blocked_field_goal', 0, kick_outcome=outcome)
        self.assertIsNone(after)
        self.assertEqual(terminal, 'touchdown')
        self.assertEqual(flags['scoring_team'], 'B')

        outcome['scoring_team'] = 'DET'
        with self.assertRaisesRegex(ValueError, 'needs a scoring-team role'):
            reducer.apply_play(state, 'blocked_field_goal', 0, kick_outcome=outcome)

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
             'halftime', 'end_of_regulation', 'end_of_overtime'))
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
        # end_of_overtime is not in any pinned fixture, which are regulation games; the overtime tests cover it.
        self.assertEqual(used, set(reducer.TERMINALS) - {'end_of_overtime'})
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


class HistoricalPoolCutoff(unittest.TestCase):
    def test_dynamic_pool_includes_prior_weeks_but_excludes_target_week_and_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'pbp.db'
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE nfl_pbp (' + ', '.join(f'"{name}"' for name in e1.COLUMNS) + ')')
            for season, week in ((2022, 1), (2025, 1), (2025, 2), (2025, 18), (2027, 1)):
                row = {name: None for name in e1.COLUMNS}
                row.update({'game_id': f'{season}_{week:02d}_TEST', 'play_id': 1, 'season': season, 'week': week,
                            'qtr': 1, 'game_seconds_remaining': 800})
                con.execute('INSERT INTO nfl_pbp VALUES (' + ','.join('?' * len(e1.COLUMNS)) + ')',
                            [row[name] for name in e1.COLUMNS])
            con.commit()
            con.close()

            pinned = e1.load(str(db))
            dynamic = e1.load(str(db), eligible_before=(2025, 2))
            self.assertEqual([r['game_id'] for r in pinned],
                             ['2022_01_TEST', '2025_01_TEST', '2025_02_TEST', '2025_18_TEST'])
            self.assertEqual([r['game_id'] for r in dynamic], ['2022_01_TEST', '2025_01_TEST'])


if __name__ == '__main__':
    unittest.main()
