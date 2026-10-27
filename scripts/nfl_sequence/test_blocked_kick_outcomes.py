import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_blocked_kick_outcomes as builder  # noqa: E402
import reducer  # noqa: E402


def source_row(**overrides):
    row = {key: None for key in builder.READ_COLUMNS}
    row.update({
        'season_type': 'REG', 'season': 2022, 'week': 13, 'game_id': '2022_13_GB_CHI',
        'play_id': 2861, 'play_type': 'field_goal', 'posteam': 'CHI', 'defteam': 'GB',
        'yardline_100': 22, 'field_goal_result': 'blocked', 'punt_blocked': 0,
        'return_team': None, 'return_yards': None, 'return_touchdown': None,
        'desc': '(11:44) 2-C.Santos 40 yard field goal is BLOCKED (94-D.Lowry), Center-48-P.Scales, Holder-16-T.Gill.',
        'series_result': None, 'td_team': None, 'extra_point_result': None,
        'down': 4, 'ydstogo': 8, 'qtr': 4, 'game_seconds_remaining': 704,
        'two_point_attempt': 0, 'penalty': 0,
    })
    row.update(overrides)
    return row


def next_snap(**overrides):
    row = {key: None for key in builder.READ_COLUMNS}
    row.update({'game_id': '2022_13_GB_CHI', 'play_id': 2862, 'play_type': 'run', 'posteam': 'GB',
                'defteam': 'CHI', 'yardline_100': 70, 'down': 1, 'ydstogo': 10, 'qtr': 4,
                'two_point_attempt': 0, 'game_seconds_remaining': 690})
    row.update(overrides)
    return row


class BlockedKickHistoricalEvidence(unittest.TestCase):
    def test_untouched_blocked_field_goal_takes_the_receivers_first_snap_as_its_outcome(self):
        # The kick is at the CHI 22 (yardline_100 22): the holder is 29 from GB's goal, so Rule 11-4-2 puts GB at 71.
        result = builder.build_record(source_row(), [source_row(), next_snap()], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'classified_next_snap')
        self.assertEqual(result['possession_after_role'], 'receiving_team')
        self.assertEqual(result['next_snap_yardline_100'], 70)
        self.assertEqual((result['next_snap_down'], result['next_snap_ydstogo']), (1, 10))
        self.assertEqual(result['clock_runoff_seconds'], 14)

    def test_receivers_first_snap_far_from_the_rule_spot_is_refused_with_a_reason(self):
        result = builder.build_record(source_row(), [source_row(), next_snap(yardline_100=90)], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'unclassified')
        self.assertIn('next_snap_spot_disagrees_with_rule_11_4_2', result['classification_note'])

    def test_block_that_uses_up_the_half_is_a_period_end_with_the_rest_of_the_half_as_runoff(self):
        half_end = source_row(qtr=2, game_seconds_remaining=1809)  # quarter clock 9
        second_half = next_snap(qtr=3, game_seconds_remaining=1790)
        result = builder.build_record(half_end, [half_end, second_half], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'period_expired')
        self.assertEqual(result['clock_runoff_seconds'], 9)

    def test_receivers_kneel_that_runs_out_the_game_is_a_period_end(self):
        block = source_row(qtr=4, game_seconds_remaining=11)
        kneel = next_snap(play_type='qb_kneel', qtr=4, game_seconds_remaining=8, down=1, ydstogo=10)
        end = next_snap(play_type=None, qtr=4, game_seconds_remaining=0, down=None, ydstogo=None, posteam=None)
        result = builder.build_record(block, [block, kneel, end], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'period_expired')
        self.assertEqual(result['clock_runoff_seconds'], 11)

    def test_a_snap_left_in_the_half_is_a_next_snap_outcome_not_a_period_end(self):
        block = source_row(qtr=2, game_seconds_remaining=1809)  # quarter clock 9
        snap = next_snap(qtr=2, game_seconds_remaining=1805)  # quarter clock 5, the receivers still have the half
        result = builder.build_record(block, [block, snap], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'classified_next_snap')
        self.assertEqual(result['clock_runoff_seconds'], 4)

    def test_described_out_of_bounds_spot_is_stored_relative_to_los(self):
        punt = source_row(play_type='punt', field_goal_result=None, punt_blocked=1,
                          posteam='ARI', defteam='ATL', yardline_100=86,
                          desc='(2:00) 14-A.Lee punt is BLOCKED by 27-R.Grant, Center-48-H.Bradley, '
                               'ball out of bounds at ARI 5.')
        nxt = next_snap(posteam='ATL', defteam='ARI', yardline_100=5)
        result = builder.build_record(punt, [punt, nxt], 0, 'source.parquet', 'b' * 64)
        self.assertEqual(result['classification_status'], 'classified_dead_ball_spot')
        self.assertEqual(result['dead_ball_spot_source'], 'description_out_of_bounds')
        self.assertEqual(result['dead_ball_yards_from_los'], -9)
        self.assertEqual(result['next_snap_yardline_100'], 5)


class BlockedKickStates(unittest.TestCase):
    STATE = {'offense': 'CHI', 'defense': 'GB', 'down': 4, 'togo': 8, 'yl': 22}

    def test_next_snap_outcome_hands_the_ball_to_the_receivers_at_the_observed_spot(self):
        outcome = {'kick_type': 'field_goal', 'classification_status': 'classified_next_snap',
                   'possession_after_role': 'receiving_team', 'next_snap_yardline_100': 70,
                   'next_snap_down': 1, 'next_snap_ydstogo': 10}
        after, terminal, flags = reducer.apply_blocked_kick(self.STATE, 'blocked_field_goal', outcome)
        self.assertEqual(after, {'offense': 'GB', 'defense': 'CHI', 'down': 1, 'togo': 10, 'yl': 70})
        self.assertEqual(terminal, 'turnover')
        self.assertTrue(flags['turnover'])
        self.assertTrue(flags['field_goal_attempt'])

    def test_next_snap_outcome_without_an_observed_start_is_refused(self):
        outcome = {'kick_type': 'field_goal', 'classification_status': 'classified_next_snap',
                   'possession_after_role': 'receiving_team', 'next_snap_yardline_100': None,
                   'next_snap_down': 1, 'next_snap_ydstogo': 10}
        with self.assertRaisesRegex(ValueError, 'observed start spot'):
            reducer.apply_blocked_kick(self.STATE, 'blocked_field_goal', outcome)

    def test_period_end_passes_no_possession_and_leaves_the_clock_to_the_engine(self):
        outcome = {'kick_type': 'field_goal', 'classification_status': 'period_expired'}
        after, terminal, flags = reducer.apply_blocked_kick(self.STATE, 'blocked_field_goal', outcome)
        self.assertIsNone(after)
        self.assertIsNone(terminal)
        self.assertFalse(flags['turnover'])


if __name__ == '__main__':
    unittest.main()
