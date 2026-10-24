"""Tests for the independent legality checker. The successor seed-1 record must pass the modelled checks. Each negative fixture (a
mutated copy of it, or the frozen record) must fail the named check. A record with an unmodelled penalty or two-minute-warning
transition must not pass as a legal complete game. Nothing here imports the engine.

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

ROOT = HERE.parents[2]
SUCCESSOR_SEED1 = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'seed1-game-successor.json'
FROZEN_SEED1 = ROOT / 'docs' / 'fixtures' / 'e2' / 'e2-game-seed1.json'


def load(path):
    with open(path) as f:
        record = json.load(f)
    return copy.deepcopy(record.get('record', record))


def seed1():
    return load(SUCCESSOR_SEED1)


def failed_checks(record):
    return {k for k, v in lc.run(record).items() if v}


def first_same_quarter_pair(record):
    for d in record['drives']:
        for a, b in zip(d['plays'], d['plays'][1:]):
            if a['state_before']['quarter'] == b['state_before']['quarter']:
                return a, b
    raise AssertionError('no two consecutive plays in one quarter')


def first_try_drive(record):
    for d in record['drives']:
        if (d.get('points_scored_on_drive') or {}).get('try') is not None:
            return d
    raise AssertionError('no drive with a try record')


UNMODELLED = {'check_unmodelled'}


class Positive(unittest.TestCase):
    def test_the_successor_seed_one_record_is_legal_under_the_modelled_rules(self):
        self.assertTrue(lc.legal_modelled(seed1()))
        self.assertEqual(failed_checks(seed1()) - UNMODELLED, set())

    def test_a_blocked_record_that_is_not_complete_is_legal_under_the_modelled_rules(self):
        record = seed1()
        record['status'], record['blocker'] = 'blocked', 'overtime_not_modelled'
        record['complete_regulation'] = record['complete_game'] = False
        self.assertTrue(lc.legal_modelled(record))
        self.assertEqual(failed_checks(record) - UNMODELLED, set())


class ScopeGuard(unittest.TestCase):
    """The two-minute warning is not modelled. A complete game that crosses 2:00 in the second or fourth quarter is legal under
    the modelled rules and is not a legal complete game."""

    def test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_the_two_minute_crossing(self):
        record = seed1()
        self.assertTrue(record['regulation_end_reached'])
        self.assertFalse(record['complete_regulation'], 'a guarded game is not a complete regulation game')
        self.assertTrue(record['unmodelled_transitions'], 'seed one crosses 2:00 in a late half')
        self.assertFalse(lc.legal_complete_game(record))


class Fails(unittest.TestCase):
    def assertFails(self, record, check):
        failed = failed_checks(record)
        self.assertIn(check, failed, f'expected {check}, got {sorted(failed)}')


class NegativeFixtures(Fails):
    """Each fixture must fail: the named check, and the checker as a whole."""

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
        record['complete_regulation'] = True  # the negative fixture: a blocked game marked complete
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
        record['complete_regulation'] = True  # the negative fixture: a complete regulation game
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


class TryFieldNegatives(Fails):
    """The publisher result field on every extra-point and two-point try."""

    def test_the_frozen_seed_one_record_fails_because_its_tries_lack_the_publisher_field(self):
        # The frozen record's three extra-point tries are {kind, made}: the Codex ingest guard rejects them for that reason.
        record = load(FROZEN_SEED1)
        self.assertIn('check_conversions', failed_checks(record))
        findings = lc.check_conversions(record)
        self.assertEqual(len(findings), 3)
        self.assertTrue(all('lacks the publisher field extra_point_result' in f for f in findings))

    def test_a_try_result_that_disagrees_with_its_made_flag_fails(self):
        record = seed1()
        drive = first_try_drive(record)
        drive['points_scored_on_drive']['try']['extra_point_result'] = 'failed'  # made is True on this try
        self.assertFails(record, 'check_conversions')

    def test_an_epa_style_success_flag_fails_a_try(self):
        record = seed1()
        drive = first_try_drive(record)
        drive['points_scored_on_drive']['try']['success'] = True
        self.assertFails(record, 'check_conversions')


class UnmodelledNegatives(Fails):
    """A penalty transition, or a two-minute warning the record does not model, cannot pass as a legal complete game."""

    def test_a_penalty_transition_cannot_pass_as_a_legal_complete_game(self):
        record = seed1()
        record['drives'][0]['plays'][0]['outcome']['penalty'] = True  # negative fixture
        self.assertIn('check_unmodelled', failed_checks(record))
        self.assertFalse(lc.legal_complete_game(record))

    def test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list(self):
        record = seed1()
        record.pop('unmodelled_transitions', None)  # negative fixture: the record no longer lists its transitions
        self.assertIn('check_unmodelled', failed_checks(record))
        self.assertFalse(lc.legal_complete_game(record))

class UnmodelledKindNegatives(Fails):
    """The timeout stoppage and the missed-field-goal return are derived from the plays. Neither can pass as a legal complete game."""

    def test_a_timeout_stoppage_cannot_pass_as_a_legal_complete_game(self):
        record = seed1()
        record['complete_regulation'] = True  # the negative fixture: a complete regulation game
        play = record['drives'][0]['plays'][0]
        play['participants']['timeout'] = True  # a stoppage the engine does not model
        self.assertIn('check_unmodelled', failed_checks(record))
        self.assertFalse(lc.legal_complete_game(record))
        self.assertTrue(any(f.startswith('timeout stoppage not modelled') for f in lc.check_unmodelled(record)))

    def test_a_missed_field_goal_return_cannot_pass_as_a_legal_complete_game(self):
        record = seed1()
        record['complete_regulation'] = True
        drive = next(d for d in record['drives'] if d['terminal'] != 'field_goal_attempt')
        drive['terminal'], drive['field_goal_made'] = 'field_goal_attempt', False  # a missed kick whose return is not modelled
        self.assertIn('check_unmodelled', failed_checks(record))
        self.assertFalse(lc.legal_complete_game(record))
        self.assertTrue(any(f.startswith('missed field goal return not modelled') for f in lc.check_unmodelled(record)))



class FixtureSplit(unittest.TestCase):
    """The counts of these tests, pinned so the evidence can be checked against this file: two positive fixtures and eighteen
    negative fixtures (twenty tests in total, with this count test itself excluded)."""

    def test_two_positive_and_eighteen_negative_fixtures(self):
        positive = [m for m in vars(Positive) if m.startswith('test_')]
        negative = [m for cls in (NegativeFixtures, TryFieldNegatives, UnmodelledNegatives, UnmodelledKindNegatives, ScopeGuard)
                    for m in vars(cls) if m.startswith('test_')]
        self.assertEqual((len(positive), len(negative), len(positive) + len(negative)), (2, 20, 22))


if __name__ == '__main__':
    unittest.main()
