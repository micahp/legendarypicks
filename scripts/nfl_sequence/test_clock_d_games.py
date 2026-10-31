"""Tests for cutoff-safe full-game clock diagnostics."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
from clock_d_games import comparison_to_holdout, holdout_volume, summarise  # noqa: E402


class HoldoutVolume(unittest.TestCase):
    def test_volume_uses_the_e1_classifier_and_groups_plays_by_quarter_and_drive(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'holdout.sqlite'
            columns = (*e1.COLUMNS, 'drive')
            con = sqlite3.connect(db)
            con.execute(f"CREATE TABLE nfl_pbp ({', '.join(columns)})")
            common = {
                'game_id': '2025_01_A_B', 'season': 2025, 'week': 1, 'qtr': 1, 'down': 1,
                'ydstogo': 10, 'yardline_100': 75, 'posteam': 'A', 'defteam': 'B',
                'touchdown': 0, 'interception': 0, 'fumble_lost': 0, 'sack': 0,
                'qb_scramble': 0, 'penalty': 0, 'two_point_attempt': 0, 'drive': 1,
            }
            rows = []
            for play_id, seconds, play_type, yards, complete in (
                    (1, 850, 'run', 4, None), (2, 820, 'pass', 8, 1), (3, 0, None, None, None)):
                row = {column: None for column in columns}
                row.update(common)
                row.update({'play_id': play_id, 'game_seconds_remaining': seconds, 'play_type': play_type,
                            'yards_gained': yards, 'complete_pass': complete})
                if play_type is None:
                    row.update({'down': None, 'ydstogo': None, 'yardline_100': None, 'posteam': None,
                                'defteam': None, 'drive': None})
                rows.append(tuple(row[column] for column in columns))
            con.executemany(f"INSERT INTO nfl_pbp ({', '.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                            rows)
            con.commit()
            con.close()

            result = holdout_volume(db=db)

        self.assertEqual(result['games'], 1)
        self.assertEqual(result['plays_per_game']['mean'], 2)
        self.assertEqual(result['regulation_drives_per_game']['mean'], 1)
        self.assertEqual(result['plays_by_quarter_per_game']['q1']['mean'], 2)
        self.assertEqual(result['plays_per_drive_game_mean'], 2)
        self.assertEqual(result['event_counts_total'], {'pass_complete': 1, 'run': 1})
        self.assertEqual(len(result['source_rows_sha256']), 64)


class RegulationVolumeDenominator(unittest.TestCase):
    def test_guarded_regulation_end_games_remain_in_volume_metrics_but_not_complete_games(self):
        rows = []
        for status, complete, reached, plays in (
                ('complete_regulation', True, True, 100),
                ('regulation_end_guarded', False, True, 120),
                ('blocked', False, False, 10)):
            rows.append({
                'status': status, 'complete_regulation': complete, 'regulation_end_reached': reached,
                'plays': plays, 'drives': 20, 'regulation_plays': plays, 'regulation_drives': 20,
                'points': 40, 'plays_q1': 25, 'plays_q2': 25, 'plays_q3': 25, 'plays_q4': 25,
                'clamped_plays': 0, 'late_plays': 5, 'plays_per_regulation_drive': plays / 20,
                'quarter_end_events': {}, 'boundaries': {},
            })

        summary = summarise(rows)

        self.assertEqual(summary['games'], 3)
        self.assertEqual(summary['complete_regulation'], 1)
        self.assertEqual(summary['regulation_end_reached'], 2)
        self.assertEqual(summary['plays']['mean'], 110)
        self.assertEqual(summary['blocked'], 1)

        observed = {
            'plays_per_game': {'mean': 100}, 'plays_per_team_game_mean': 50,
            'regulation_drives_per_game': {'mean': 20}, 'regulation_drives_per_team_game_mean': 10,
            'plays_per_drive_game_mean': 5.5,
            'plays_by_quarter_per_game': {f'q{q}': {'mean': 25} for q in range(1, 5)},
            'event_counts_total': {}, 'event_counts_per_game_mean': {}, 'event_share': {}, 'event_runoff_mean_s': {},
        }
        comparison = comparison_to_holdout(rows, observed)
        self.assertEqual(comparison['regulation_end_reached_games'], 2)
        self.assertEqual(comparison['complete_regulation_games'], 1)
        self.assertEqual(comparison['simulated']['plays_per_game'], 110)


if __name__ == '__main__':
    unittest.main()
