import sqlite3
import sys
import tempfile
import unittest
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_slc_drive_distributions as comparison  # noqa: E402


class ActualDriveExtraction(unittest.TestCase):
    def make_database(self):
        connection = sqlite3.connect(':memory:')
        connection.executescript('''
            CREATE TABLE nfl_schedule (
                game_id TEXT, season INTEGER, week INTEGER, game_type TEXT,
                home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER
            );
            CREATE TABLE nfl_pbp (
                game_id TEXT, season INTEGER, week INTEGER, play_id INTEGER,
                drive REAL, posteam TEXT, qtr INTEGER, play_type TEXT,
                series_result TEXT, yardline_100 REAL, yards_gained REAL,
                interception INTEGER, fumble_lost INTEGER, touchdown INTEGER
            );
        ''')
        connection.executemany('INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?)', [
            ('regular', 2022, 1, 'REG', 'DET', 'MIN', 24, 17),
            ('preseason', 2022, 1, 'PRE', 'DET', 'MIN', 20, 10),
        ])
        plays = [
            ('regular', 2022, 1, 1, 1, 'DET', 1, 'run', 'First down', 70, 5, 0, 0, 0),
            ('regular', 2022, 1, 2, 1, 'DET', 1, 'pass', 'First down', 75, 7, 0, 0, 0),
            ('regular', 2022, 1, 3, 1, 'DET', 1, 'punt', 'Punt', 68, 0, 0, 0, 0),
            ('regular', 2022, 1, 4, 2, 'DET', 1, 'pass', 'Touchdown', 30, 30, 0, 0, 1),
            ('regular', 2022, 1, 5, 3, 'DET', 2, 'pass', 'Opp touchdown', 20, 0, 1, 0, 1),
            ('regular', 2022, 1, 6, 4, 'DET', 2, 'field_goal', 'Missed field goal', 35, 0, 0, 0, 0),
            ('regular', 2022, 1, 7, 5, 'DET', 2, 'run', 'Turnover on downs', 45, 2, 0, 0, 0),
            ('regular', 2022, 1, 8, 6, 'DET', 2, 'run', 'End of half', 50, -1, 0, 0, 0),
            ('preseason', 2022, 1, 1, 1, 'DET', 1, 'run', 'Touchdown', 20, 20, 0, 0, 1),
        ]
        connection.executemany('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', plays)
        return connection

    def test_uses_regular_season_and_last_series_result_with_defensive_td_credit(self):
        connection = self.make_database()
        try:
            team_games, drives, meta = comparison.load_actual_data(connection, 2022, 2025)
        finally:
            connection.close()

        self.assertEqual({row['game_id'] for row in team_games}, {'regular'})
        self.assertEqual({row['team'] for row in team_games}, {'DET', 'MIN'})
        self.assertEqual((meta['completed_games'], meta['team_games']), (1, 2))
        det_drives = [row for row in drives if row['team'] == 'DET']
        by_terminal = {row['terminal']: row for row in det_drives}
        self.assertEqual(len(det_drives), 6)
        self.assertEqual((by_terminal['punt']['event_count'], by_terminal['punt']['scrimmage_plays']), (3, 2))
        self.assertEqual((by_terminal['punt']['start_yardline_100'], by_terminal['punt']['net_yards']), (70, 12))
        offensive_td = [row for row in det_drives if row['terminal_raw'] == 'Touchdown'][0]
        self.assertTrue(offensive_td['offensive_scoring'])
        defensive_td = [row for row in det_drives if row['terminal_raw'] == 'Opp touchdown'][0]
        self.assertEqual(defensive_td['terminal'], 'touchdown')
        self.assertFalse(defensive_td['offensive_scoring'])
        self.assertTrue(defensive_td['defensive_scoring'])
        self.assertTrue(defensive_td['turnovers'])
        self.assertEqual(by_terminal['field_goal_attempt']['field_goal_attempts'], 1)
        self.assertEqual(by_terminal['turnover_on_downs']['terminal'], 'turnover_on_downs')
        self.assertEqual(by_terminal['period_end']['terminal_raw'], 'End of half')

    def test_team_game_summary_keeps_drive_terminals_separate_from_play_volume(self):
        connection = self.make_database()
        try:
            team_games, drives, _meta = comparison.load_actual_data(connection, 2022, 2025)
        finally:
            connection.close()
        _rows, metrics = comparison.summarize_team_games('historical', team_games, drives)
        indexed = {(row['cohort'], row['metric']): row for row in metrics
                   if row['unit'] == 'team_game' and row['terminal'] == 'ALL'}
        self.assertEqual(indexed[('DET', 'punt_drives_per_game')]['mean'], 1)
        self.assertEqual(indexed[('DET', 'recorded_events_per_game')]['mean'], 8)
        self.assertEqual(indexed[('DET', 'scrimmage_plays_per_game')]['mean'], 6)
        self.assertEqual(indexed[('DET', 'offensive_scoring_drives_per_game')]['mean'], 1)

    def test_score_only_overtime_counts_as_outcome_but_not_modeled_drive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'drive-summaries.csv'
            rows = [
                {'seed': 1, 'game_id': 'TEN_CIN', 'drive_index': 1, 'offense_team': 'DET',
                 'play_count': 5, 'net_yards': 45, 'start_yardline_100': 75, 'terminal': 'touchdown',
                 'points': 7, 'scoring_team': 'DET', 'turnovers': 0},
                {'seed': 1, 'game_id': 'TEN_CIN', 'drive_index': 2, 'offense_team': 'MIN',
                 'play_count': 0, 'net_yards': 0, 'start_yardline_100': '', 'terminal': 'end_of_overtime',
                 'points': 3, 'scoring_team': 'MIN', 'turnovers': 0},
            ]
            with path.open('w', encoding='utf-8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            team_games, drives = comparison.load_simulated_data(path, expected_games=1)
        game_rows, metrics = comparison.summarize_team_games('SLC 10K', team_games, drives)
        by_team = {row['team']: row for row in game_rows}
        self.assertEqual(by_team['MIN']['offensive_scoring_drives_per_game'], 1)
        self.assertEqual(by_team['MIN']['unmodeled_drives_per_game'], 1)
        self.assertEqual(by_team['MIN']['recorded_events_per_game'], 0)
        metric = next(row for row in metrics if row['cohort'] == 'MIN'
                      and row['unit'] == 'modeled_drive' and row['terminal'] == 'ALL'
                      and row['metric'] == 'net_yards_per_drive')
        self.assertEqual(metric['sample_n'], 0)


if __name__ == '__main__':
    unittest.main()
