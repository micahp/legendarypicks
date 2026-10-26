import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_blocked_kick_outcomes as builder  # noqa: E402


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
    def test_next_snap_spot_does_not_classify_an_unlocated_blocked_field_goal(self):
        result = builder.build_record(source_row(), [source_row(), next_snap()], 0, 'source.parquet', 'a' * 64)
        self.assertEqual(result['classification_status'], 'unclassified')
        self.assertIsNone(result['return_endpoint_yardline_100'])
        self.assertIsNone(result['return_endpoint_yards_from_los'])
        self.assertEqual(result['next_snap_yardline_100'], 70)

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


if __name__ == '__main__':
    unittest.main()
