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


def row(play_id, game='g', qtr=1, seconds=3000, play_type='run'):
    return {'game_id': game, 'play_id': play_id, 'qtr': qtr, 'game_seconds_remaining': seconds, 'play_type': play_type}


class Runoff(unittest.TestCase):
    def test_only_a_row_whose_next_row_is_a_team_timeout_is_followed(self):
        rows = [row(1), row(2, play_type='no_play'), row(3), row(4), row(5, game='h')]
        self.assertEqual(set(td.rows_followed_by_timeout(rows, {('g', 2), ('h', 5)})), {('g', 1)})

    def test_the_runoff_runs_through_the_timeout_row_to_the_next_snap(self):
        # the timeout row repeats the snap clock (3000); the play's 7 seconds show at the next snap
        rows = [row(1, seconds=3000), row(2, seconds=3000, play_type='no_play'), row(3, seconds=2993)]
        self.assertEqual(td.rows_followed_by_timeout(rows, {('g', 2)}), {('g', 1): 7})

    def setUp(self):
        self.followed_row, self.plain_row = row(1), row(3)
        pool = {'cell': [('run', self.followed_row, 6, None)] + [('run', row(10 + i), 38, None) for i in range(25)]}
        self.split = td.RunoffSplit(pool, {('g', 1): 6})

    def test_agreement_keeps_the_source_runoff(self):
        rng = random.Random(1)
        self.assertEqual(self.split.runoff(rng, 'cell', 'run', self.plain_row, 40, False, False), (40, 'source_row'))
        self.assertEqual(self.split.runoff(rng, 'cell', 'run', self.followed_row, 0, True, False),
                         (6, 'source_row_through_timeout'))

    def test_no_timeout_after_a_timeout_row_redraws_a_full_runoff(self):
        self.assertEqual(self.split.runoff(random.Random(1), 'cell', 'run', self.followed_row, 0, False, False),
                         (38, 'cell_event_timeout_status'))

    def test_a_timeout_with_no_supported_short_runoff_refuses(self):
        with self.assertRaises(ValueError):
            self.split.runoff(random.Random(1), 'cell', 'run', self.plain_row, 40, True, False)


if __name__ == '__main__':
    unittest.main()
