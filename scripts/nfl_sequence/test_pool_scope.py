"""The E1 sampling pool and overtime. A regulation-only candidate must not draw outcomes from overtime rows; the default
(regulation_only=False) keeps the accepted E2 pool, and the exclusions are counted rather than dropped silently.

Run: python3 -m unittest scripts/nfl_sequence/test_pool_scope.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402


def play(play_id, qtr, gsr):
    return {'game_id': 'G1', 'play_id': play_id, 'season': 2022, 'week': 1, 'game_date': '2022-09-11', 'posteam': 'A',
            'defteam': 'B', 'qtr': float(qtr), 'down': 1.0, 'ydstogo': 10.0, 'yardline_100': 50.0,
            'game_seconds_remaining': float(gsr), 'play_type': 'run', 'yards_gained': 3.0, 'touchdown': 0,
            'interception': 0, 'fumble_lost': 0, 'sack': 0, 'complete_pass': None, 'qb_scramble': 0, 'penalty': 0,
            'two_point_attempt': 0}


def rows():
    # Quarter 1 then overtime. Each play has a same-quarter next play except the last of each quarter, so two regulation and two
    # overtime plays are classifiable runs.
    return [play(1, 1, 800), play(2, 1, 790), play(3, 5, 500), play(4, 5, 480)]


class PoolScope(unittest.TestCase):
    def test_the_default_keeps_overtime_outcomes_in_the_pool(self):
        pool, excluded = e1.build_pool(rows())
        sampled = [entry[1]['qtr'] for cell in pool.values() for entry in cell]
        self.assertIn(5.0, sampled)
        self.assertNotIn('overtime rows (regulation-only pool)', excluded)

    def test_regulation_only_draws_nothing_from_overtime_and_counts_it(self):
        pool, excluded = e1.build_pool(rows(), regulation_only=True)
        sampled = [entry[1]['qtr'] for cell in pool.values() for entry in cell]
        self.assertTrue(sampled, 'the regulation rows must still be sampled')
        self.assertTrue(all(q <= 4 for q in sampled))
        self.assertEqual(excluded['overtime rows (regulation-only pool)'], 2)

    def test_regulation_only_keeps_every_regulation_outcome(self):
        default, _ = e1.build_pool(rows())
        scoped, _ = e1.build_pool(rows(), regulation_only=True)
        regulation_default = [e for cell in default.values() for e in cell if e[1]['qtr'] <= 4]
        regulation_scoped = [e for cell in scoped.values() for e in cell]
        self.assertEqual(len(regulation_default), len(regulation_scoped))


if __name__ == '__main__':
    unittest.main()
