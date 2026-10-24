"""Tests for the independent legality checker: the frozen seed-1 record must pass, and each negative fixture (a mutated copy
of it) must fail the named check. Nothing here imports the engine.

Run: python3 -m unittest scripts/nfl_sequence/evidence_e2/test_legality.py
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import legality_check as lc  # noqa: E402

SEED1 = HERE.parents[2] / 'docs' / 'fixtures' / 'e2' / 'e2-game-seed1.json'


def seed1():
    with open(SEED1) as f:
        record = json.load(f)
    return copy.deepcopy(record.get('record', record))


def failed_checks(record):
    return {k for k, v in lc.run(record).items() if v}


def first_same_quarter_pair(record):
    for d in record['drives']:
        for a, b in zip(d['plays'], d['plays'][1:]):
            if a['state_before']['quarter'] == b['state_before']['quarter']:
                return a, b
    raise AssertionError('no two consecutive plays in one quarter')


class Positive(unittest.TestCase):
    def test_the_frozen_seed_one_record_is_legal(self):
        self.assertEqual(failed_checks(seed1()), set())

    def test_a_blocked_record_that_is_not_complete_is_legal(self):
        record = seed1()
        record['status'], record['blocker'] = 'blocked', 'overtime_not_modelled'
        record['complete_regulation'] = record['complete_game'] = False
        self.assertEqual(failed_checks(record), set())


class NegativeFixtures(unittest.TestCase):
    """Each fixture must fail: the named check, and the checker as a whole."""

    def assertFails(self, record, check):
        failed = failed_checks(record)
        self.assertIn(check, failed, f'expected {check}, got {sorted(failed)}')

    def test_a_clock_that_rises_inside_a_quarter(self):
        record = seed1()
        a, b = first_same_quarter_pair(record)
        b['state_before']['clock_seconds'] = a['state_before']['clock_seconds'] + 1
        self.assertFails(record, 'check_clock_and_quarter')

    def test_a_quarter_that_falls(self):
        record = seed1()
        for d in record['drives']:
            for a, b in zip(d['plays'], d['plays'][1:]):
                if a['state_before']['quarter'] == 2 and b['state_before']['quarter'] == 2:
                    b['state_before']['quarter'] = 1
                    self.assertFails(record, 'check_clock_and_quarter')
                    return
        self.fail('seed one has no Q2 pair to mutate')

    def test_points_that_disagree_with_the_drives(self):
        record = seed1()
        record['points']['A'] += 3
        self.assertFails(record, 'check_points')

    def test_a_drive_index_out_of_sequence(self):
        record = seed1()
        record['drives'][3]['index'] = 9
        self.assertFails(record, 'check_drives')

    def test_a_timeout_count_of_four(self):
        record = seed1()
        record['drives'][0]['plays'][0]['state_before']['home_timeouts'] = 4
        self.assertFails(record, 'check_timeouts')

    def test_timeouts_that_do_not_reset_at_halftime(self):
        record = seed1()
        for d in record['drives']:
            for p in d['plays']:
                if p['state_before']['quarter'] == 3:
                    p['state_before']['home_timeouts'] = 2
                    self.assertFails(record, 'check_timeouts')
                    return
        self.fail('seed one has no Q3 play to mutate')

    def test_a_blocked_record_marked_as_a_complete_game(self):
        record = seed1()
        record['status'], record['blocker'] = 'blocked', 'overtime_not_modelled'
        self.assertFails(record, 'check_blocked')

    def test_a_down_of_five(self):
        record = seed1()
        record['drives'][0]['plays'][0]['state_before']['down'] = 5
        self.assertFails(record, 'check_downs_and_field')

    def test_a_field_position_outside_the_field(self):
        record = seed1()
        record['drives'][0]['plays'][0]['state_before']['yardline_100'] = 120
        self.assertFails(record, 'check_downs_and_field')

    def test_a_punt_that_hands_the_ball_back_to_the_punting_side(self):
        record = seed1()
        for i, d in enumerate(record['drives'][:-1]):
            if d['terminal'] == 'punt' and d['index'] not in {b['drive_index'] for b in record['boundaries']}:
                record['drives'][i + 1]['offense_team'] = d['offense_team']
                self.assertFails(record, 'check_possession')
                return
        self.fail('seed one has no punt to mutate')

    def test_a_complete_game_that_does_not_end_at_zero(self):
        record = seed1()
        record['final_clock_seconds'] = 5
        self.assertFails(record, 'check_completion')

    def test_a_score_recorded_without_its_points(self):
        record = seed1()
        for d in record['drives']:
            if d['terminal'] == 'touchdown':
                d['points_scored_on_drive']['points'] = 3
                self.assertFails(record, 'check_events')
                return
        self.fail('seed one has no touchdown drive to mutate')


if __name__ == '__main__':
    unittest.main()
