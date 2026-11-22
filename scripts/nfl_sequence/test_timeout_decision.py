"""Timeout decision at the whistle: the table rate, the backoff, the no-timeouts rule and one caller at most."""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_timeout_decisions as table  # noqa: E402
import timeout_decision as td  # noqa: E402


def cell(period='q4', clock='2:00_or_less', state='running', score='trailing_1_to_8', left='3', role='defense'):
    return (period, clock, state, score, left, role)


class Buckets(unittest.TestCase):
    def test_score_and_clock_buckets(self):
        self.assertEqual([table.score_bucket(m) for m in (0, 3, -8, 9, -14)],
                         ['tied', 'leading_1_to_8', 'trailing_1_to_8', 'leading_9_plus', 'trailing_9_plus'])
        self.assertEqual([table.clock_bucket(s) for s in (301, 300, 121, 120)],
                         ['over_5:00', '2:01_to_5:00', '2:01_to_5:00', '2:00_or_less'])
        self.assertEqual(table.clock_state('pass', True, False, False), 'stopped')
        self.assertEqual(table.clock_state('run', False, False, False), 'running')


class Probability(unittest.TestCase):
    def test_a_supported_key_uses_its_own_rate(self):
        model = td.TimeoutModel({cell(): (100, 30)}, 'x')
        key = dict(zip(table.KEY, cell()))
        self.assertEqual(model.probability(key), (0.3, 'full', 100))

    def test_a_thin_key_backs_off_and_says_so(self):
        model = td.TimeoutModel({cell(score='tied'): (10, 10), cell(score='leading_1_to_8'): (90, 0)}, 'x')
        p, level, support = model.probability(dict(zip(table.KEY, cell(score='tied'))))
        self.assertEqual((round(p, 3), level, support), (0.1, 'no_score', 100))

    def test_no_supported_key_refuses(self):
        model = td.TimeoutModel({cell(): (5, 1)}, 'x')
        with self.assertRaises(ValueError):
            model.probability(dict(zip(table.KEY, cell())))


class Decide(unittest.TestCase):
    def setUp(self):
        self.model = td.TimeoutModel({cell(role='defense', score='leading_1_to_8'): (100, 100),
                                      cell(role='offense', score='trailing_1_to_8'): (100, 100)}, 'x')
        self.kw = dict(quarter=4, snap_clock=90, clock_state='running', offense='A', defense='B', margin=-3)

    def test_a_team_with_no_timeouts_left_never_calls(self):
        caller, record = self.model.decide(random.Random(1), timeouts_left={'offense': 0, 'defense': 0}, **self.kw)
        self.assertIsNone(caller)
        self.assertEqual(record['teams']['offense']['level'], 'no_timeouts_left')

    def test_at_most_one_team_calls_and_the_first_band_wins(self):
        caller, record = self.model.decide(random.Random(1), timeouts_left={'offense': 3, 'defense': 3}, **self.kw)
        self.assertEqual(caller, 'offense')
        self.assertEqual(record['caller'], 'offense')

    def test_the_real_table_loads_and_matches_its_manifest(self):
        model = td.TimeoutModel.load()
        p, level, _ = model.probability(dict(zip(table.KEY, cell())))
        self.assertGreater(p, 0.0)
        self.assertEqual(level, 'full')


if __name__ == '__main__':
    unittest.main()
