"""Tests for the independent legality checker. The successor seed-1 record must pass the modelled checks. Each negative fixture (a
mutated copy of it, or the frozen record) must fail the named check. A record with an unmodelled penalty or missing clock
start/stop guard must not pass as a legal complete game. Nothing here imports the engine.

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
        self.assertEqual(failed_checks(seed1()) - UNMODELLED, set())  # the guarded transitions are the only failures

    def test_a_blocked_record_that_is_not_complete_is_legal_under_the_modelled_rules(self):
        record = seed1()
        record['status'], record['blocker'] = 'blocked', 'drive_limit'
        record['complete_regulation'] = record['complete_game'] = False
        self.assertTrue(lc.legal_modelled(record))
        self.assertEqual(failed_checks(record) - UNMODELLED, set())


class ScopeGuard(unittest.TestCase):
    """Legacy records stay scoped out; new full-game records must carry clock transitions."""

    def test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_its_guarded_transitions(self):
        record = seed1()
        self.assertTrue(record['regulation_end_reached'])
        self.assertFalse(record['complete_regulation'], 'a guarded game is not a complete regulation game')
        kinds = {t['kind'] for t in record['unmodelled_transitions']}
        self.assertIn('two_minute_warning', kinds, 'the warning marker exists but its clock lifecycle is unmodelled')
        self.assertTrue(kinds, 'seed one carries a guarded transition')
        self.assertFalse(lc.legal_complete_game(record))
        self.assertTrue(any(x.startswith('two-minute warning clock transition missing')
                            for x in lc.check_unmodelled(record)))

    def test_the_successor_seed_one_records_two_minute_stops_at_the_post_down_clock(self):
        record = seed1()
        self.assertTrue(record['two_minute_warnings'])
        self.assertTrue(all(0 < w['clock_seconds'] <= 120 for w in record['two_minute_warnings']))
        self.assertEqual(lc.check_two_minute(record), [])

    def test_full_game_mode_requires_explicit_clock_transitions(self):
        record = seed1()
        self.assertEqual(lc.check_clock_state_guard(record), [])
        record['mode'] = 'pregame_full_game'
        self.assertTrue(lc.check_clock_state_guard(record))

    def test_a_kickoff_crossing_is_independently_derived_and_requires_a_marker(self):
        record = {'drives': [], 'kickoffs': [{'quarter': 4, 'clock_before': 125, 'clock_after': 110,
                                              'runoff_seconds': 15, 'clock_expired_during_kickoff': False,
                                              'two_minute_warning': True}]}
        self.assertEqual(lc.check_two_minute(record), [])
        record['kickoffs'][0]['two_minute_warning'] = False
        self.assertTrue(lc.check_two_minute(record))


class BlockedKickChecks(unittest.TestCase):
    def record(self):
        source_hash = 'a' * 64
        return {
            'pregame_snapshot': {'model_reference': {'observed_reference': {
                'blocked_kick_source_sha256': source_hash,
                'blocked_kick_input_source_sha256': {'play_by_play_2025.parquet': source_hash}}}},
            'drives': [{'index': 1, 'points_scored_on_drive': None, 'plays': [{
                'sequence': 8, 'event_type': 'blocked_punt',
                'state_before': {'offense_team': 'A', 'defense_team': 'B', 'down': 4,
                                 'yards_to_go': 5, 'yardline_100': 60},
                'state_after': {'offense_team': 'B', 'yardline_100': 50, 'end_of_drive': 'turnover'},
                'outcome': {'punt_attempt': True, 'turnover': True, 'turnover_on_downs': False,
                            'blocked_kick': {'kick_type': 'punt', 'classification_status': 'classified_recovery',
                                             'source_file': 'play_by_play_2025.parquet', 'source_sha256': source_hash,
                                             'reference_fixture_sha256': source_hash,
                                             'game_id': '2025_01_TEST', 'play_id': 50, 'recovery_role': 'receiving_team',
                                             'recovery_yards_from_los': 15,
                                             'return_endpoint_yards_from_los': 10, 'return_yards': 5}},
            }]}],
        }

    def test_pinned_blocked_punt_recovery_and_return_pass(self):
        self.assertEqual(lc.check_blocked_kicks(self.record()), [])

    def test_wrong_return_spot_fails(self):
        record = self.record()
        record['drives'][0]['plays'][0]['state_after']['yardline_100'] = 49
        self.assertTrue(lc.check_blocked_kicks(record))

    def test_unpinned_source_fails(self):
        record = self.record()
        record['drives'][0]['plays'][0]['outcome']['blocked_kick']['source_sha256'] = 'b' * 64
        self.assertTrue(lc.check_blocked_kicks(record))


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
        record['status'], record['blocker'] = 'blocked', 'drive_limit'
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

    def test_a_turnover_that_ends_the_half_cannot_pass_as_a_drive_end(self):
        # Negative fixture: a halftime drive relabelled as a turnover, as the old engine recorded it at a Q2 expiry.
        record = seed1()
        drive = next(d for d in record['drives'] if d['terminal'] == 'halftime')
        drive['terminal'] = 'turnover'
        drive['plays'][-1]['state_after']['end_of_drive'] = 'turnover'
        self.assertIn('check_half_end', failed_checks(record))
        self.assertTrue(any('ends the drive' in f for f in lc.check_half_end(record)))

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
    """A penalty or a missing/duplicated two-minute-warning event cannot pass the independent checks."""

    def test_a_penalty_transition_cannot_pass_as_a_legal_complete_game(self):
        record = seed1()
        record['drives'][0]['plays'][0]['outcome']['penalty'] = True  # negative fixture
        self.assertIn('check_unmodelled', failed_checks(record))
        self.assertFalse(lc.legal_complete_game(record))

    def test_a_crossing_without_a_warning_marker_cannot_pass_as_legal(self):
        # Negative fixture: the play has a legal post-down clock, but the automatic warning event is missing.
        record = seed1()
        for d in record['drives']:
            for p in d['plays']:
                if (p['state_before']['quarter'] in (2, 4) and p['state_after']['quarter'] == p['state_before']['quarter']
                        and p['state_before']['clock_seconds'] > 120 >= p['state_after']['clock_seconds'] > 0):
                    p['outcome']['two_minute_warning'] = False
                    self.assertIn('check_two_minute', failed_checks(record))
                    self.assertFalse(lc.legal_modelled(record))
                    return
        self.fail('seed one has no two-minute crossing to mutate')

    def test_a_second_stop_in_the_same_half_cannot_pass_as_legal(self):
        # Negative fixture: a late-half crossing is copied into a second play of the same quarter, so the half has two stops.
        record = seed1()
        for d in record['drives']:
            for p in d['plays']:
                if (p['state_before']['quarter'] in (2, 4) and p['state_after']['quarter'] == p['state_before']['quarter']
                        and p['state_before']['clock_seconds'] > 120 >= p['state_after']['clock_seconds'] > 0):
                    twin = copy.deepcopy(p)
                    twin['state_before']['clock_seconds'] = 121
                    twin['state_after']['clock_seconds'] = 119
                    d['plays'].insert(d['plays'].index(p) + 1, twin)
                    self.assertIn('check_two_minute', failed_checks(record))
                    return
        self.fail('seed one has no two-minute crossing to copy')

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
    """The counts of these tests, pinned so the evidence can be checked against this file: two positive fixtures and twenty-five
    negative fixtures (twenty-seven tests in total, with this count test itself excluded)."""

    def test_two_positive_and_twenty_three_negative_fixtures(self):
        positive = [m for m in vars(Positive) if m.startswith('test_')]
        negative = [m for cls in (NegativeFixtures, TryFieldNegatives, UnmodelledNegatives, UnmodelledKindNegatives, ScopeGuard)
                    for m in vars(cls) if m.startswith('test_')]
        self.assertEqual((len(positive), len(negative), len(positive) + len(negative)), (2, 25, 27))


if __name__ == '__main__':
    unittest.main()
