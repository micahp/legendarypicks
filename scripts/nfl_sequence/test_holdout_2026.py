import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402


class HoldoutSeason(unittest.TestCase):
    def test_reference_seasons_exclude_the_holdout(self):
        self.assertEqual(e1.POOL_SEASONS, (2022, 2023, 2024, 2025))
        self.assertEqual(er.KICKOFF_SEASONS, (2022, 2023, 2024, 2025))
        self.assertLess(max(e1.POOL_SEASONS), e1.HOLDOUT_SEASON)

    def test_loaders_return_no_2026_rows_and_refuse_the_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'pbp.sqlite3')
            con = sqlite3.connect(db)
            con.execute(f"CREATE TABLE nfl_pbp ({', '.join(e1.COLUMNS)})")
            for season in (2025, 2026):
                con.execute('INSERT INTO nfl_pbp (game_id, play_id, season, week) VALUES (?, ?, ?, ?)',
                            (f'g{season}', 1, season, 1))
            con.commit()
            con.close()
            self.assertEqual({row['season'] for row in e1.load(db)}, {2025})
            with self.assertRaises(ValueError):
                e1.load(db, eligible_before=(2026, 5))
            with self.assertRaises(ValueError):
                e1.load_seasons(db, (2025, 2026))


if __name__ == '__main__':
    unittest.main()
