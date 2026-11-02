"""Parsing, bucketing and shrinkage rules for the participation model."""
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_tables as bt  # noqa: E402
import participation_model as pm  # noqa: E402


class Personnel(unittest.TestCase):
    def test_group_code_counts_backfield_and_tight_ends(self):
        counts, defensive = bt.parse_personnel('1 RB, 1 TE, 3 WR, 1 QB, 5 OL')
        self.assertEqual(bt.group_code(counts), '11')
        self.assertFalse(defensive)

    def test_fullback_counts_as_a_running_back(self):
        counts, _ = bt.parse_personnel('1 FB, 1 RB, 2 TE, 2 WR')
        self.assertEqual(bt.group_code(counts), '22')

    def test_defensive_labels_are_flagged_not_counted_as_offense(self):
        counts, defensive = bt.parse_personnel('2 CB, 1 FB, 1 FS, 1 ILB, 1 TE')
        self.assertTrue(defensive)

    def test_blank_personnel_is_empty_not_a_default(self):
        self.assertEqual(bt.parse_personnel(''), ({}, False))


class Cells(unittest.TestCase):
    def test_missing_situation_is_an_explicit_na_cell(self):
        row = {'down': '', 'ydstogo': '', 'yardline_100': ''}
        self.assertEqual(pm.cell_of(row), 'na|na|na')

    def test_distance_and_field_buckets(self):
        self.assertEqual(pm.cell_of({'down': '3', 'ydstogo': '7', 'yardline_100': '18'}), '3|long|red')
        self.assertEqual(pm.cell_of({'down': '1', 'ydstogo': '10', 'yardline_100': '75'}), '1|xl|own')


class Shrinkage(unittest.TestCase):
    def test_usage_share_moves_toward_the_current_season_with_uses(self):
        prior = {'uses': {'carry': defaultdict(float, {('KC', 'a'): 6.0, ('KC', 'b'): 4.0})},
                 'totals': {'carry': defaultdict(float, {'KC': 10.0})}}
        before = pm.usage_share(prior, 'carry', 'KC', 'a')
        after = pm.usage_share(prior, 'carry', 'KC', 'a', {('KC', 'a'): 20.0}, {'KC': 20.0})
        self.assertAlmostEqual(before, 0.6)
        self.assertAlmostEqual(after, 44 / 60)  # (20 + 40 * 0.6) / (20 + 40)
        self.assertGreater(after, before)

    def test_unseen_player_gets_a_finite_floor(self):
        prior = {'uses': {'target': defaultdict(float)}, 'totals': {'target': defaultdict(float, {'KC': 50.0})}}
        share = pm.usage_share(prior, 'target', 'KC', 'rookie')
        self.assertGreater(share, 0.0)
        self.assertLess(share, 0.05)

    def test_weekly_best_follows_current_season_counts_when_they_are_large(self):
        model = {'league': {'1|mid|own': Counter({'11': 10, '12': 10})},
                 'team': {('KC', '1|mid|own'): Counter({'11': 1})}}
        self.assertEqual(pm.weekly_best(model, 'KC', '1|mid|own', Counter({'12': 30})), '12')


if __name__ == '__main__':
    unittest.main()
