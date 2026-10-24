"""Transition tests for the E1 generator, from the rules matrix in docs/rules/NFL-2026-GAME-STATE-RULES.md (section 7).

Run: python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py

The generator is driven by a fake pool that always returns one observed play, so each test controls the outcome
and the derived clock runoff. These tests cover transition legality, not the football distribution.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import reducer  # noqa: E402


class FakePool:
    """Returns one observed-play cell per call. Call 1 gives `first`; later calls give `then`.

    Each entry is (event, row, runoff, spot), which is what build_pool stores for a usable observed play.
    """

    def __init__(self, first, then=None):
        self.calls = 0
        self.first = first
        self.then = then or first

    def get(self, key, default=None):
        self.calls += 1
        event, yards, runoff, spot = self.first if self.calls == 1 else self.then
        row = {'game_id': 'G1', 'play_id': 1.0, 'game_date': '2025-01-01', 'yards_gained': yards,
               'touchdown': 0, 'play_type': 'run' if event == 'run' else 'punt'}
        return [(event, row, runoff, spot)] * (e1.MIN_POOL + 5)


def start(quarter, clock, yl=75, down=1, togo=10, dir_=1):
    return {'quarter': quarter, 'clock': clock, 'offense': 'OFF', 'defense': 'DEF', 'yl': yl, 'down': down,
            'togo': togo, 'dir': dir_}


class QuarterTransitions(unittest.TestCase):
    def test_q1_expiry_continues_the_series_without_a_kickoff(self):
        # The first run outlasts the 100 seconds left, so Q1 expires on it. The drive goes on in Q2 and ends on a punt.
        pool = FakePool(('run', 4, 300, None), ('punt', 0, 10, 22))
        plays, terminal = e1.simulate(start(1, 100), 1, pool)
        self.assertEqual(terminal, 'punt')
        self.assertEqual(len(plays), 2)
        first = plays[0]
        self.assertTrue(first['outcome']['quarter_change'])
        self.assertEqual(first['state_after']['quarter'], 2)
        self.assertEqual(first['state_after']['clock_seconds'], e1.QUARTER_LENGTH)
        self.assertEqual(first['state_after']['offense_team'], 'OFF')
        self.assertEqual(first['state_after']['yardline_100'], 71)
        self.assertEqual(first['state_after']['down'], 2)
        self.assertNotIn('end_of_drive', first['state_after'])
        self.assertEqual(first['field']['before']['dir'], 1)
        self.assertEqual(first['field']['after']['dir'], -1)
        self.assertEqual(first['field']['after']['los'], 71)
        self.assertEqual(plays[1]['state_before']['quarter'], 2)
        e1.check_drive(plays, terminal)

    def test_q2_expiry_is_halftime_and_not_a_turnover_on_downs(self):
        plays, terminal = e1.simulate(start(2, 100), 1, FakePool(('run', 4, 300, None)))
        self.assertEqual(terminal, 'halftime')
        last = plays[-1]['state_after']
        self.assertEqual(last['end_of_drive'], 'halftime')
        self.assertEqual(last['quarter'], 2)
        self.assertEqual(last['clock_seconds'], 0)
        self.assertIsNone(last['yardline_100'])
        self.assertFalse(plays[-1]['outcome']['turnover'])
        self.assertIsNone(plays[-1]['field']['after']['dir'], 'no scrimmage endpoint at halftime (schema 1.1)')
        self.assertIsNone(plays[-1]['field']['after']['los'])
        self.assertIsNotNone(plays[-1]['outcome']['final_play_yardline_100'], 'the final play position is kept in outcome')
        e1.check_drive(plays, terminal)

    def test_q4_expiry_is_regulation_end(self):
        plays, terminal = e1.simulate(start(4, 100), 1, FakePool(('run', 4, 300, None)))
        self.assertEqual(terminal, 'end_of_regulation')
        self.assertEqual(plays[-1]['state_after']['quarter'], 4)
        e1.check_drive(plays, terminal)

    def test_no_drive_terminates_at_q1_or_q3_expiry(self):
        for q in (1, 3):
            pool = FakePool(('run', 4, 300, None), ('punt', 0, 10, 22))
            plays, terminal = e1.simulate(start(q, 100), 1, pool)
            self.assertEqual(terminal, 'punt')
            self.assertTrue(plays[0]['outcome']['quarter_change'])
            self.assertNotIn(terminal, ('end_of_period', 'halftime', 'end_of_regulation'))


class Reducer(unittest.TestCase):
    def test_turnover_on_downs_complements_field_position(self):
        # Second quarter, fourth and 5 at the own 40 (yardline 60), a 2-yard gain: the other team takes over at 42.
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 60}, 'run', 2)
        self.assertEqual(terminal, 'turnover_on_downs')
        self.assertTrue(flags['turnover_on_downs'])
        self.assertEqual(after['offense'], 'B')
        self.assertEqual(after['yl'], 42)
        self.assertEqual(after['down'], 1)

    def test_unknown_event_is_refused(self):
        with self.assertRaises(ValueError):
            reducer.apply_play({'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50}, 'kickoff', 0)

    def test_punt_gives_the_receiving_spot(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 3, 'yl': 40}, 'punt', 0, spot=22)
        self.assertEqual(terminal, 'punt')
        self.assertEqual(after['offense'], 'B')
        self.assertEqual(after['yl'], 22)

    def test_field_goal_attempt_has_no_result_and_no_next_spot(self):
        after, terminal, flags = reducer.apply_play(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 3, 'yl': 15}, 'field_goal_attempt', 0)
        self.assertIsNone(after)
        self.assertEqual(terminal, 'field_goal_attempt')
        self.assertTrue(flags['field_goal_attempt'])


FIXTURE_DIR = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e1'


class Vocabulary(unittest.TestCase):
    def test_terminals_constant_is_the_e1_vocabulary(self):
        self.assertEqual(
            reducer.TERMINALS,
            ('touchdown', 'safety', 'turnover', 'turnover_on_downs', 'punt', 'field_goal_attempt',
             'halftime', 'end_of_regulation'))
        self.assertNotIn('end_of_period', reducer.TERMINALS)

    def test_pinned_records_use_exactly_the_terminals_in_the_constant(self):
        used = set()
        for path in FIXTURE_DIR.glob('*.json'):
            record = json.loads(path.read_text())
            terminal = record['plays'][-1]['state_after'].get('end_of_drive')
            self.assertIsNotNone(terminal, path.name)
            used.add(terminal)
            for play in record['plays'][:-1]:
                self.assertNotIn('end_of_drive', play['state_after'], path.name)
        self.assertEqual(used, set(reducer.TERMINALS))
        self.assertNotIn('end_of_period', used)


if __name__ == '__main__':
    unittest.main()
