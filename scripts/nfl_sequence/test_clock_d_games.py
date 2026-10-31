"""Tests for cutoff-safe full-game clock diagnostics."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
from clock_d_games import holdout_volume  # noqa: E402


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


if __name__ == '__main__':
    unittest.main()
