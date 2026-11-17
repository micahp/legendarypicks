"""Forced goal-line fumble transitions through each arm's classifier and drive loop. No seed batch.

Frozen V1 (legacy) and frozen V1.6 (conditional, refuse, no geometry) behaviour is pinned as it is today. Those tests
name a known defect; they document it and do not endorse it. V1.6 is not changed by this file.

Run: python3 -m unittest scripts/nfl_sequence/test_forced_arms.py
"""
import collections
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402
import football_assertions  # noqa: E402
import game_state as gs  # noqa: E402
import game_stats  # noqa: E402
import reducer  # noqa: E402
from test_penalty_goal_line_fumble import ChooseFirst  # noqa: E402
from test_recovery_model import ForcedRecovery, ScriptedPlays, play_game_with  # noqa: E402

OWN_ONE = {'quarter': 4, 'clock': 420, 'offense': 'A', 'defense': 'B', 'yl': 99, 'down': 4, 'togo': 1, 'dir': 1}
OWN_EIGHT = dict(OWN_ONE, yl=92, down=1, togo=10)
MIDFIELD = dict(OWN_ONE, yl=50, down=1, togo=10)
NEXT_OFFENSE_SPOT = 80  # the historical next snap: the defense's own 20, as seen by the new offense
NO_LEGAL = 'goal_line_fumble_source_cell_has_no_geometrically_legal_outcome'


def source_row(yards, **flags):
    row = {'game_id': 'G1', 'play_id': 1, 'game_date': '2025-01-01', 'penalty': 0, 'two_point_attempt': 0,
           'qb_scramble': 0, 'down': 1, 'ydstogo': 10, 'yardline_100': 99, 'game_seconds_remaining': 900,
           'qtr': 4, 'posteam': 'A', 'defteam': 'B', 'yards_gained': yards, 'sack': 0, 'fumble_lost': 0,
           'interception': 0, 'touchdown': 0, 'complete_pass': 0, 'play_type': 'run'}
    row.update(flags)
    return row


def next_snap():
    return {'game_id': 'G1', 'qtr': 4, 'game_seconds_remaining': 880, 'posteam': 'B', 'play_type': 'run',
            'yardline_100': NEXT_OFFENSE_SPOT, 'down': 1, 'ydstogo': 10}


def classify(separate_sack_fumbles, row):
    excluded = collections.Counter()
    return e1.classify(row, next_snap(), excluded, separate_sack_fumbles=separate_sack_fumbles), excluded


def drive(state, event, row, *, own_end_zone, geometry_filter, recovery_model=None):
    key = (state['down'], e0.ydstogo_bucket(state['togo']), e0.yardline_bucket(state['yl']))
    pool = {key: [(event, row, 8, NEXT_OFFENSE_SPOT)]}
    policy = ChooseFirst()
    policy.geometry_excluded = collections.Counter()
    return e1.simulate(dict(state), 61, pool, 'forced-%s' % event, sampling_policy=policy,
                       own_end_zone=own_end_zone, geometry_filter=geometry_filter, recovery_model=recovery_model)


class ClassificationByArm(unittest.TestCase):
    def test_sack_fumble_is_a_separate_event_only_in_conditional_mode(self):
        row = source_row(-3, play_type='pass', sack=1, fumble_lost=1)
        legacy, _ = classify(False, row)
        conditional, _ = classify(True, row)
        self.assertEqual(legacy[0], 'fumble_lost')
        self.assertEqual(conditional[0], 'sack_fumble_lost')

    def test_fumble_return_touchdown_rows_are_excluded_from_the_pool_in_every_mode(self):
        for sack in (0, 1):
            row = source_row(-6, play_type='pass', sack=sack, fumble_lost=1, touchdown=1)
            for separate in (False, True):
                out, excluded = classify(separate, row)
                self.assertIsNone(out, f'sack={sack} separate={separate} should be excluded')
                self.assertEqual(sum(excluded.values()), 1)


class FrozenV1AndV16KnownDefects(unittest.TestCase):
    """Pinned as they are. A generic or sack fumble past the own goal line is not resolved in these arms."""

    def test_v1_legacy_sack_fumble_past_the_own_goal_line_becomes_a_silent_turnover(self):
        # KNOWN DEFECT, frozen V1: the legacy classifier reads the sack-fumble as a generic fumble_lost, and the
        # reducer does not check generic turnovers against the goal line.
        row = source_row(-3, play_type='pass', sack=1, fumble_lost=1)
        (event, _, spot), _ = classify(False, row)
        self.assertEqual(event, 'fumble_lost')
        plays, terminal = drive(OWN_ONE, event, row, own_end_zone='refuse', geometry_filter=False)
        self.assertEqual(terminal, 'turnover')
        self.assertEqual(plays[0]['outcome'].get('turnover'), True)

    def test_v16_generic_fumble_past_the_own_goal_line_becomes_a_silent_turnover(self):
        # KNOWN DEFECT, frozen V1.6: the same silent path exists for a non-sack fumble that crosses the goal line.
        row = source_row(-3, play_type='run', fumble_lost=1)
        (event, _, _), _ = classify(True, row)
        self.assertEqual(event, 'fumble_lost')
        plays, terminal = drive(OWN_ONE, event, row, own_end_zone='refuse', geometry_filter=False)
        self.assertEqual(terminal, 'turnover')

    def test_v16_sack_fumble_past_the_own_goal_line_is_refused_not_resolved(self):
        # Frozen V1.6 raises. The game is not completed through this path.
        row = source_row(-3, play_type='pass', sack=1, fumble_lost=1)
        (event, _, _), _ = classify(True, row)
        self.assertEqual(event, 'sack_fumble_lost')
        with self.assertRaises(football_assertions.FootballAssertionError):
            drive(OWN_ONE, event, row, own_end_zone='refuse', geometry_filter=False)


class V17ForcedOwnEndZoneTransitions(unittest.TestCase):
    def test_generic_fumble_into_the_own_end_zone_without_a_recovery_is_a_named_block(self):
        row = source_row(-3, play_type='run', fumble_lost=1)
        plays, terminal = drive(OWN_ONE, 'fumble_lost', row, own_end_zone='resolve', geometry_filter=True)
        self.assertIsNone(plays)
        self.assertEqual(terminal, NO_LEGAL)

    def test_sack_fumble_into_the_own_end_zone_with_an_offense_recovery_is_a_safety(self):
        row = source_row(-3, play_type='pass', sack=1, fumble_lost=1)
        model = ForcedRecovery('offense_recovers_in_own_end_zone', 'safety')
        plays, terminal = drive(OWN_ONE, 'sack_fumble_lost', row, own_end_zone='resolve', geometry_filter=True,
                                recovery_model=model)
        self.assertEqual(terminal, 'safety')
        self.assertEqual(len(plays), 1)

    def test_pass_fumble_from_the_own_8_with_a_defense_recovery_in_the_end_zone_is_a_touchdown(self):
        row = source_row(-10, play_type='pass', fumble_lost=1, complete_pass=1)
        model = ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown')
        plays, terminal = drive(OWN_EIGHT, 'fumble_lost', row, own_end_zone='resolve', geometry_filter=True,
                                recovery_model=model)
        self.assertEqual(terminal, 'touchdown')

    def test_midfield_fumble_control_stays_an_ordinary_turnover_in_every_v17_arm(self):
        row = source_row(5, play_type='run', fumble_lost=1)
        for model in (None, ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown')):
            plays, terminal = drive(MIDFIELD, 'fumble_lost', row, own_end_zone='resolve', geometry_filter=True,
                                    recovery_model=model)
            self.assertEqual(terminal, 'turnover')



class FieldFumbleFirst(ScriptedPlays):
    """The first offensive play is an ordinary fumble that the defense recovers in the field. No recovery model."""

    def __init__(self):
        super().__init__(fumble_first=False, fumble_on_fourth=False)

    def get(self, key, default=None):
        if self.calls == 0:
            self.calls += 1
            row = {'game_id': 'G1', 'play_id': 1, 'game_date': '2025-01-01', 'yards_gained': -2, 'touchdown': 0,
                   'play_type': 'run', 'sack': 0, 'fumble_lost': 1}
            return [('fumble_lost', row, self.runoff, 60)] * 60
        return super().get(key, default)


def first_event(record, event):
    return next(p for d in record['drives'] for p in d['plays'] if p['event_type'] == event)


class LostFumbleAccountingSemantics(unittest.TestCase):
    """A lost fumble is a statistic. A possession change is a separate flag. The two can differ."""

    def test_the_helper_reads_the_key_when_present_and_the_turnover_flag_otherwise(self):
        self.assertTrue(reducer.lost_to_defense('sack_fumble_lost', {'fumble_lost_to_defense': True,
                                                                     'turnover': False}))
        self.assertFalse(reducer.lost_to_defense('sack_fumble_lost', {'fumble_lost_to_defense': False,
                                                                      'turnover': True}))
        self.assertTrue(reducer.lost_to_defense('fumble_lost', {'turnover': True}))  # ordinary turnover, no key
        self.assertFalse(reducer.lost_to_defense('interception', {'turnover': True}))
        self.assertFalse(reducer.lost_to_defense('run', {'fumble_lost_to_defense': True}))

    def test_a_defensive_recovery_touchdown_is_a_lost_fumble_without_a_possession_change(self):
        _after, terminal, flags = reducer.apply_modeled_recovery(dict(OWN_ONE), 'touchdown', side='defense')
        self.assertEqual(terminal, 'touchdown')
        self.assertTrue(flags['fumble_lost_to_defense'])
        self.assertFalse(flags['turnover'])
        self.assertEqual(flags['scoring_team'], 'B')

    def test_an_offensive_recovery_safety_is_not_a_lost_fumble(self):
        _after, terminal, flags = reducer.apply_modeled_recovery(dict(OWN_ONE), 'safety', side='offense')
        self.assertEqual(terminal, 'safety')
        self.assertFalse(flags['fumble_lost_to_defense'])
        self.assertEqual(flags['scoring_team'], 'B')

    def test_an_offensive_recovery_that_continues_is_not_a_lost_fumble(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(dict(OWN_EIGHT), 'offense',
                                                                 {'terminal': 'spot', 'end_yl': 90})
        self.assertIsNone(terminal)
        self.assertFalse(flags['fumble_lost_to_defense'])
        self.assertFalse(flags['turnover'])
        self.assertEqual(after['offense'], 'A')


class FullGameFumbleAccounting(unittest.TestCase):
    def assertCompleted(self, record):
        self.assertIn(record['status'], ('complete_regulation', 'complete_overtime'), record.get('blocker'))
        gs.validate_game(record)

    def team(self, record, name):
        return game_stats.team_stats(record['drives'], record['points'])[name]

    def test_defensive_recovery_touchdown_is_a_turnover_for_the_offense_and_the_game_completes(self):
        record = play_game_with(ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown'))
        self.assertCompleted(record)
        fumbles = [p for d in record['drives'] for p in d['plays'] if p['event_type'] == 'sack_fumble_lost']
        self.assertTrue(fumbles)  # the scripted pool fumbles on each fourth down at the own one-yard line
        for play in fumbles:
            self.assertTrue(play['outcome']['fumble_lost_to_defense'])
            self.assertFalse(play['outcome']['turnover'])  # no next-snap possession change
            self.assertEqual(play['outcome']['scoring_team'], play['state_before']['defense_team'])
        for team in ('A', 'B'):
            lost = sum(1 for play in fumbles if play['state_before']['offense_team'] == team)
            self.assertEqual(self.team(record, team).get('fumbles_lost', 0), lost)
            self.assertEqual(self.team(record, team).get('turnovers', 0), lost)

    def test_offensive_recovery_safety_is_not_counted_as_a_lost_fumble(self):
        record = play_game_with(ForcedRecovery('offense_recovers_in_own_end_zone', 'safety'))
        self.assertCompleted(record)
        self.assertFalse(first_event(record, 'sack_fumble_lost')['outcome']['fumble_lost_to_defense'])
        self.assertEqual(self.team(record, 'A').get('fumbles_lost', 0), 0)
        self.assertEqual(self.team(record, 'A').get('turnovers', 0), 0)

    def test_out_of_bounds_in_the_end_zone_is_not_counted_as_a_lost_fumble(self):
        record = play_game_with(ForcedRecovery('out_of_bounds_in_offense_end_zone', 'safety'))
        self.assertCompleted(record)
        self.assertEqual(self.team(record, 'A').get('fumbles_lost', 0), 0)
        self.assertEqual(self.team(record, 'A').get('turnovers', 0), 0)

    def test_an_ordinary_field_fumble_keeps_its_legacy_turnover_count_and_outcome_shape(self):
        record = play_game_with(None, pool=FieldFumbleFirst())
        self.assertCompleted(record)
        play = first_event(record, 'fumble_lost')
        self.assertTrue(play['outcome']['turnover'])
        self.assertNotIn('fumble_lost_to_defense', play['outcome'])  # no modeled recovery, so no new key
        self.assertEqual(self.team(record, 'A').get('fumbles_lost', 0), 1)
        self.assertEqual(self.team(record, 'A').get('turnovers', 0), 1)


if __name__ == '__main__':
    unittest.main()
