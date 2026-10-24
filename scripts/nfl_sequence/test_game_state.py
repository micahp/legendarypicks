"""Unit tests for the E2 game (game_state.py, game_stats.py, rules_matrix.py): ledger, kickoffs, scoring, clock, matrix.

Run: python3 -m unittest scripts/nfl_sequence/test_game_state.py
"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402
import rules_matrix as rm  # noqa: E402


class StaticPool:
    """A pool whose every cell holds the same observed-play entries: (event, row, runoff, spot)."""

    def __init__(self, event, yards, runoff, spot=None):
        row = {'game_id': 'G1', 'play_id': 1.0, 'game_date': '2025-01-01', 'yards_gained': yards,
               'touchdown': 0, 'play_type': 'run' if event == 'run' else event}
        self.entries = [(event, row, runoff, spot)] * 60

    def get(self, key, default=None):
        return self.entries


def kickoff_pool(spot=25, runoff=10):
    return [{'spot': spot, 'runoff': runoff, 'game_id': 'K', 'play_id': 1, 'game_date': '2025-01-01'}]


def certain_kicks(fg_made=True, ep_made=True):
    """A kick table in which every attempt in a cell has the same result. The two-point cell is empty."""
    fg = {b: (60, 0) if fg_made else (0, 60) for b in gs.FG_BUCKETS}
    ep = (60, 0) if ep_made else (0, 60)
    return {'field_goal': fg, 'extra_point': ep, 'two_point': (0, 0), 'source': 'test fixture'}


def ref(pool, kpool, kicks=None):
    """An observed Reference with no participant lookups, so every play's participants are null."""
    return gs.Reference(pool, kpool, kicks or certain_kicks(), {})


def spy_simulate(run):
    """Run `run()` with E1's simulate wrapped. Returns (result, calls), where each call holds the start and the id.
    """
    calls, real = [], gs.e1.simulate

    def spy(start, seed, pool, simulation_id):
        calls.append({'start': dict(start), 'seed': seed, 'simulation_id': simulation_id})
        return real(start, seed, pool, simulation_id)

    gs.e1.simulate = spy
    try:
        result = run()
    finally:
        gs.e1.simulate = real
    return result, calls


class Ledger(unittest.TestCase):
    def test_normal_mode_refuses_kick_and_defend_goal(self):
        for choice in ('kick', 'defend_goal'):
            with self.assertRaises(ValueError, msg=choice):
                gs.CoinTossLedger('A', 'B', choice)

    def test_exception_mode_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            gs.CoinTossLedger('A', 'B', 'receive', mode=gs.EXCEPTION_MODE)

    def test_receive_path_gives_one_kickoff_per_team(self):
        ledger = gs.CoinTossLedger('A', 'B', 'receive')
        kickoffs = ledger.half_start_kickoffs()
        self.assertEqual((kickoffs[0]['kicking_team'], kickoffs[0]['receiving_team']), ('B', 'A'))
        self.assertEqual((kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team']), ('A', 'B'))
        gs.validate_half_start(kickoffs)

    def test_defer_path_gives_one_kickoff_per_team(self):
        ledger = gs.CoinTossLedger('A', 'B', 'defer')
        kickoffs = ledger.half_start_kickoffs()
        self.assertEqual((kickoffs[0]['kicking_team'], kickoffs[0]['receiving_team']), ('A', 'B'))
        self.assertEqual((kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team']), ('B', 'A'))
        gs.validate_half_start(kickoffs)

    def test_second_half_first_choice_follows_the_deferral(self):
        self.assertEqual(gs.CoinTossLedger('A', 'B', 'defer').second_chooser, 'A')
        self.assertEqual(gs.CoinTossLedger('A', 'B', 'receive').second_chooser, 'B')


class Validators(unittest.TestCase):
    def test_same_team_kicking_twice_is_a_hard_failure(self):
        bad = [{'quarter': 1, 'kicking_team': 'A', 'receiving_team': 'B', 'reason': 'half_start'},
               {'quarter': 3, 'kicking_team': 'A', 'receiving_team': 'B', 'reason': 'half_start'}]
        with self.assertRaises(AssertionError):
            gs.validate_half_start(bad)

    def test_recorded_kickoffs_must_match_the_ledger(self):
        record = gs.play_game(3, ref(_empty_e1_pool(), kickoff_pool()), winner_choice='receive')
        record['kickoffs'][0]['kicking_team'] = 'A'
        record['kickoffs'][0]['receiving_team'] = 'B'
        with self.assertRaises(AssertionError):
            gs.validate_game(record)

    def test_the_reference_is_required(self):
        with self.assertRaises(TypeError):
            gs.play_game(3, winner_choice='receive')

    def test_a_touchdown_whose_points_disagree_with_its_try_is_refused(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool()), winner_choice='receive', max_drives=1)
        record['drives'][0]['points_scored_on_drive']['points'] = 6  # the try was made, so the points must be 7
        with self.assertRaises(AssertionError):
            gs.validate_game(record)


class KickoffPool(unittest.TestCase):
    def test_receiving_team_is_posteam_and_its_next_snap_gives_the_spot(self):
        rows = [
            {'game_id': 'g', 'play_id': 1.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 35.0,
             'game_seconds_remaining': 3600.0, 'play_type': 'kickoff', 'game_date': '2025-09-01'},
            {'game_id': 'g', 'play_id': 2.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 75.0,
             'game_seconds_remaining': 3596.0, 'play_type': 'pass', 'game_date': '2025-09-01'},
        ]
        pool, excluded = gs.build_kickoff_pool(rows)
        self.assertEqual([(p['spot'], p['runoff']) for p in pool], [(75, 4)])
        self.assertEqual(sum(excluded.values()), 0)

    def test_a_kickoff_followed_by_the_kicking_team_is_excluded(self):
        rows = [
            {'game_id': 'g', 'play_id': 1.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 35.0,
             'game_seconds_remaining': 3600.0, 'play_type': 'kickoff', 'game_date': '2025-09-01'},
            {'game_id': 'g', 'play_id': 2.0, 'posteam': 'K', 'defteam': 'R', 'qtr': 1.0, 'yardline_100': 60.0,
             'game_seconds_remaining': 3596.0, 'play_type': 'run', 'game_date': '2025-09-01'},
        ]
        pool, excluded = gs.build_kickoff_pool(rows)
        self.assertEqual(pool, [])
        self.assertEqual(excluded['kickoff without a clean receiving snap'], 1)


class FieldGoalBuckets(unittest.TestCase):
    def test_buckets_match_the_published_labels(self):
        cases = {9: '1-9', 10: '10-19', 19.5: '10-19', 20: '20-29', 39: '30-39', 40: '40-49', 49: '40-49', 50: '50+',
                 65: '50+'}
        for yl, label in cases.items():
            self.assertEqual(gs.fg_bucket(yl), label, yl)


class Scoring(unittest.TestCase):
    def test_a_touchdown_takes_its_try_then_the_scoring_team_kicks_off(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool()), winner_choice='receive', max_drives=2)
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score']
        scorer = record['drives'][0]['offense_team']
        self.assertGreaterEqual(len(post), 1)
        self.assertEqual(post[0]['kicking_team'], scorer, 'the team that scored kicks off next')
        self.assertEqual(record['points'][scorer], 7, 'a touchdown and a made extra point')
        self.assertEqual(record['drives'][0]['points_scored_on_drive']['try'],
                         {'kind': 'extra_point', 'made': True, 'extra_point_result': 'good'})
        gs.validate_game(record)

    def test_a_missed_extra_point_scores_six(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), certain_kicks(ep_made=False)),
                              winner_choice='receive', max_drives=1)
        scorer = record['drives'][0]['offense_team']
        self.assertEqual(record['points'][scorer], 6)
        gs.validate_game(record)

    def test_a_two_point_try_scores_eight_when_it_is_chosen_and_made(self):
        kicks = certain_kicks()
        kicks['two_point'], kicks['extra_point'] = (60, 0), (0, 0)  # every post-touchdown attempt is a two-point try
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), kicks), winner_choice='receive',
                              max_drives=1)
        scorer = record['drives'][0]['offense_team']
        self.assertEqual(record['points'][scorer], 8)
        self.assertEqual(record['drives'][0]['points_scored_on_drive']['try']['kind'], 'two_point')
        self.assertEqual(record['drives'][0]['points_scored_on_drive']['try'],
                         {'kind': 'two_point', 'made': True, 'two_point_conv_result': 'success'})
        gs.validate_game(record)


class TryPublisherField(unittest.TestCase):
    """Every extra-point and two-point record carries its publisher result field, with the publisher's value for its made flag.
    No record carries an EPA-derived `success` flag. A try without the field is rejected."""

    def test_every_extra_point_and_two_point_try_carries_its_publisher_field(self):
        two_point_kicks = certain_kicks()
        two_point_kicks['two_point'], two_point_kicks['extra_point'] = (60, 0), (0, 0)
        for kicks, kind, field, value in ((certain_kicks(), 'extra_point', 'extra_point_result', 'good'),
                                          (two_point_kicks, 'two_point', 'two_point_conv_result', 'success')):
            record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), kicks), winner_choice='receive',
                                  max_drives=1)
            t = record['drives'][0]['points_scored_on_drive']['try']
            self.assertEqual((t['kind'], t[field], t['made']), (kind, value, True))
            self.assertNotIn('success', t)
            gs.validate_game(record)

    def test_a_missed_try_carries_the_failed_value(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), certain_kicks(ep_made=False)),
                              winner_choice='receive', max_drives=1)
        t = record['drives'][0]['points_scored_on_drive']['try']
        self.assertEqual(t, {'kind': 'extra_point', 'made': False, 'extra_point_result': 'failed'})

    def test_a_try_without_its_publisher_field_is_rejected(self):
        # Negative fixture: the try is the frozen seed-one shape, {kind, made}, with no publisher field.
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), certain_kicks()),
                              winner_choice='receive', max_drives=1)
        del record['drives'][0]['points_scored_on_drive']['try']['extra_point_result']
        with self.assertRaises(AssertionError):
            gs.validate_game(record)

    def test_an_epa_style_success_flag_in_a_try_is_rejected(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool(), certain_kicks()),
                              winner_choice='receive', max_drives=1)
        record['drives'][0]['points_scored_on_drive']['try']['success'] = True  # negative fixture
        with self.assertRaises(AssertionError):
            gs.validate_game(record)

    def test_a_made_field_goal_scores_three_and_the_kicker_kicks_off(self):
        fg = ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(), certain_kicks(fg_made=True))
        record = gs.play_game(1, fg,
                              winner_choice='receive', max_drives=2)
        kicker = record['drives'][0]['offense_team']
        self.assertTrue(record['drives'][0]['field_goal_made'])
        self.assertEqual(record['points'][kicker], 3)
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_field_goal']
        self.assertEqual(post[0]['kicking_team'], kicker)
        gs.validate_game(record)

    def test_a_missed_field_goal_gives_the_other_team_the_spot_of_the_kick(self):
        # The kickoff lands at the 25, so the snap is at the 25 and the kick is from the holder's spot, the 32. The other team
        # starts at yardline_100 68 (100 - 32), not 75, which would be the snap-based value.
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), certain_kicks(fg_made=False)),
            winner_choice='receive', max_drives=2))
        self.assertFalse(record['drives'][0]['field_goal_made'])
        self.assertEqual(record['points'], {'A': 0, 'B': 0})
        self.assertEqual(calls[0]['start']['yl'], 25)
        self.assertEqual(calls[1]['start']['offense'], calls[0]['start']['defense'])
        self.assertEqual(calls[1]['start']['yl'], 68)
        gs.validate_game(record)

    def test_a_thin_published_cell_blocks_the_game_and_is_not_filled(self):
        kicks = certain_kicks()
        kicks['field_goal']['20-29'] = (5, 5)  # 10 attempts, below the floor
        record = gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), kicks),
                              winner_choice='receive')
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'thin_kick_cell:field_goal:20-29')
        self.assertFalse(record['valid_full_game'])
        gs.validate_game(record)


class Clock(unittest.TestCase):
    def test_a_touchdown_on_the_last_play_of_q1_kicks_off_to_open_q2(self):
        # Opening kickoff runs 10s, so Q1 has 890s left. The first play runs them out with a touchdown.
        record = gs.play_game(1, ref(StaticPool('run', 80, 890), kickoff_pool(runoff=10)), winner_choice='receive',
                              max_drives=2)
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score'][0]
        self.assertEqual((post['quarter'], post['clock_before']), (2, 900), 'the post-score kickoff opens Q2')
        self.assertEqual(post['clock_rule'], gs.PRACTICE_RULE, 'a practice-sourced rule, labelled as such')
        self.assertEqual({r['label'] for r in record['provisional_rules']}, {gs.PRACTICE_RULE, gs.AUTHORED_RULE})
        self.assertTrue(all(r['status'] == gs.PENDING_2026 for r in record['provisional_rules']))
        self.assertEqual(record['boundaries'][0]['kind'], 'change_of_ends')
        self.assertEqual(record['drives'][1]['quarter_start'], 2)
        gs.validate_game(record)

    def test_a_score_that_expires_the_half_is_followed_by_the_second_half_kickoff_only(self):
        # Q1 ends on a score (kickoff opens Q2), then the Q2 drive scores on its last play: no post-score kick at
        # halftime.
        record = gs.play_game(1, ref(StaticPool('run', 80, 890), kickoff_pool(runoff=10)), winner_choice='receive',
                              max_drives=3)
        kinds = [(k['kind'], k['quarter']) for k in record['kickoffs']]
        self.assertEqual(kinds[:2], [('half_start', 1), ('post_score', 2)])
        self.assertEqual(record['drives'][1]['end_quarter'], 2)
        self.assertEqual(record['drives'][1]['end_clock'], 0)
        self.assertIn(('half_start', 3), kinds)
        skipped = [b for b in record['boundaries'] if b['kind'] == 'skipped_post_score_kick']
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]['clock_rule'], gs.PRACTICE_RULE)
        self.assertEqual(record['provisional_counts']['skipped_post_score_kicks_at_halftime'], 1)
        self.assertNotIn(('post_score', 2), kinds[2:], 'a score that expired Q2 has no post-score kickoff')
        gs.validate_game(record)

    def test_a_punt_that_expires_q1_keeps_the_receiving_team_and_its_spot(self):
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('punt', 0, 890, spot=40), kickoff_pool(runoff=10)), winner_choice='receive',
            max_drives=2))
        self.assertEqual(record['drives'][0]['terminal'], 'punt')
        self.assertEqual(record['drives'][0]['end_quarter'], 1)
        self.assertEqual(calls[1]['start']['quarter'], 2)
        self.assertEqual(calls[1]['start']['clock'], 900)
        self.assertEqual(calls[1]['start']['offense'], calls[0]['start']['defense'], 'the punt receiver keeps the ball')
        self.assertEqual(calls[1]['start']['yl'], 40)
        self.assertEqual(len([k for k in record['kickoffs'] if k['quarter'] == 2]), 0,
                         'a change of ends has no kickoff')
        gs.validate_game(record)

    def test_a_kick_that_runs_the_clock_out_ends_the_quarter_on_the_return(self):
        # Opening 20s, Q1 TD leaves 10s, and the post-score kickoff runs 20s: the quarter ends during the return.
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('run', 80, 870), kickoff_pool(runoff=20)), winner_choice='receive', max_drives=2))
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score'][0]
        self.assertEqual((post['quarter'], post['clock_before'], post['clock_expired_during_kickoff'],
                          post['runoff_overrun_seconds'], post['clock_clamped_to_zero']), (1, 10, True, 10, False))
        self.assertEqual(calls[1]['start']['quarter'], 2)
        self.assertEqual(calls[1]['start']['clock'], 900)
        self.assertEqual(calls[1]['start']['offense'], post['receiving_team'])
        gs.validate_game(record)


class HalfStart(unittest.TestCase):
    def test_halftime_ends_the_first_half_and_the_second_half_kickoff_is_generated(self):
        # Each play runs 450 seconds, so Q1 and then Q2 expire inside the same drive. The drive ends at halftime.
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        self.assertIn('halftime', [d['terminal'] for d in record['drives']])
        half = [k for k in record['kickoffs'] if k['kind'] == 'half_start']
        self.assertEqual(sorted(k['quarter'] for k in half), [1, 3])
        self.assertEqual(half[1]['kicking_team'], record['ledger']['winner'])
        gs.validate_game(record)


class ProfileId(unittest.TestCase):
    def test_the_game_uses_one_simulation_id_and_global_play_sequence(self):
        record, calls = spy_simulate(lambda: gs.play_game(
            3, ref(StaticPool('run', 10, 30), kickoff_pool()), winner_choice='receive', max_drives=2))
        ids = [c['simulation_id'] for c in calls]
        self.assertEqual(ids, [record['simulation_id']] * len(calls))
        self.assertEqual(record['simulation_id'], f'e2-{gs.e1.MODEL_VERSION}-seed3')
        plays = [play for drive in record['drives'] for play in drive['plays']]
        self.assertEqual([play['sequence'] for play in plays], list(range(1, len(plays) + 1)))
        self.assertEqual([play['id'] for play in plays],
                         [f'{record["simulation_id"]}:{sequence}' for sequence in range(1, len(plays) + 1)])
        self.assertGreater(record['drives'][1]['plays'][0]['sequence'], record['drives'][0]['plays'][-1]['sequence'])
        gs.validate_game(record)

        broken = copy.deepcopy(record)
        broken['drives'][1]['plays'][0]['sequence'] = 1
        broken['drives'][1]['plays'][0]['id'] = f'{record["simulation_id"]}:1'
        with self.assertRaisesRegex(AssertionError, 'game-wide id'):
            gs.validate_game(broken)


class RulesMatrix(unittest.TestCase):
    def _halftime_record(self):
        return gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)

    def test_a_clean_game_has_no_failing_row(self):
        rows = rm.check(self._halftime_record())
        self.assertEqual([r for r in rows if r['status'] == 'FAIL'], [])

    def test_the_same_team_kicking_both_half_openers_is_a_failure(self):
        record = self._halftime_record()
        q3 = next(k for k in record['kickoffs'] if k['kind'] == 'half_start' and k['quarter'] == 3)
        q1 = next(k for k in record['kickoffs'] if k['kind'] == 'half_start' and k['quarter'] == 1)
        q3['kicking_team'] = q1['kicking_team']
        row = next(r for r in rm.check(record) if r['case'].startswith('Both half-opening'))
        self.assertEqual(row['status'], 'FAIL')

    def test_a_points_total_that_disagrees_with_the_drives_is_a_failure(self):
        record = copy.deepcopy(self._halftime_record())
        record['points']['A'] += 3
        row = next(r for r in rm.check(record) if r['case'].startswith('Points equal'))
        self.assertEqual(row['status'], 'FAIL')

    def test_a_clock_that_rises_inside_a_quarter_is_a_failure(self):
        record = copy.deepcopy(self._halftime_record())
        play = record['drives'][0]['plays'][0]
        play['state_after']['clock_seconds'] = play['state_before']['clock_seconds'] + 5
        play['state_after']['quarter'] = play['state_before']['quarter']
        row = next(r for r in rm.check(record) if r['case'].startswith('Clock'))
        self.assertEqual(row['status'], 'FAIL')

    def test_unsupported_rules_are_named_not_passed(self):
        rows = rm.check(self._halftime_record())
        for case in ('Timeouts', 'Two-minute warning', 'Penalties', 'Onside kick', 'Player lineups'):
            row = next(r for r in rows if r['case'].startswith(case))
            self.assertEqual(row['status'], 'UNSUPPORTED', case)


class TossSymmetry(unittest.TestCase):
    """Both toss winners and both choices, sampled and verified. Nothing is fixed to team A."""

    def _game(self, winner, choice):
        return gs.play_game(3, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice=choice, max_drives=3,
                            winner=winner)

    def test_every_winner_and_choice_gives_the_matrix_kickoffs(self):
        for winner in ('A', 'B'):
            for choice in ('receive', 'defer'):
                record = self._game(winner, choice)
                gs.validate_game(record)
                rows = {r['case']: r['status'] for r in rm.check(record)}
                self.assertNotIn('FAIL', rows.values(), (winner, choice))
                self.assertEqual(record['ledger']['winner'], winner)

    def test_the_defer_and_receive_kickoffs_follow_the_matrix(self):
        # Matrix section 7: a receive gives the winner the Q1 receive and the loser the Q3 receive; a defer is the reverse.
        receive = self._game('A', 'receive')
        defer = self._game('A', 'defer')
        recv_q1 = next(k for k in receive['kickoffs'] if k['kind'] == 'half_start' and k['quarter'] == 1)
        defer_q1 = next(k for k in defer['kickoffs'] if k['kind'] == 'half_start' and k['quarter'] == 1)
        self.assertEqual(recv_q1['receiving_team'], 'A')
        self.assertEqual(defer_q1['receiving_team'], 'B')

    def test_sampling_covers_both_winners_and_both_choices(self):
        seen = set()
        for seed in range(1, 41):
            record = gs.play_game(seed, ref(StaticPool('run', 10, 450), kickoff_pool()), max_drives=1)
            seen.add((record['ledger']['winner'], record['ledger']['winner_choice']))
        self.assertEqual(seen, {('A', 'receive'), ('A', 'defer'), ('B', 'receive'), ('B', 'defer')})

    def test_a_ledger_that_disagrees_with_the_kickoffs_is_rejected(self):
        # Negative fixture: the ledger says B won, but the kickoffs were built for A.
        record = self._game('A', 'receive')
        record['ledger']['winner'], record['ledger']['loser'] = 'B', 'A'
        with self.assertRaises(AssertionError):
            gs.validate_game(record)


class Guards(unittest.TestCase):
    def test_every_unmodelled_rule_carries_a_guard_and_is_never_pass(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        self.assertEqual(set(record['guards']), set(gs.UNSUPPORTED_RULES))
        rows = {r['case']: r['status'] for r in rm.check(record)}
        self.assertEqual(rows['Unmodelled rules: each carries a named guard'], 'UNSUPPORTED')
        self.assertEqual(rows['Timeouts: three per team per half'], 'UNSUPPORTED')

    def test_a_record_without_the_timeout_guard_is_rejected(self):
        # Negative fixture: removing a guard must fail the validator and the matrix.
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        del record['guards']['timeouts']
        with self.assertRaises(AssertionError):
            gs.validate_game(record)
        row = next(r for r in rm.check(record) if r['case'].startswith('Unmodelled rules'))
        self.assertEqual(row['status'], 'FAIL')


class ProvisionalIsNeverPass(unittest.TestCase):
    def test_a_score_that_expires_q1_marks_its_rows_provisional(self):
        # A touchdown on the last play of Q1 is kicked off in Q2 under the practice rule: the rows must say PROVISIONAL.
        record = gs.play_game(1, ref(StaticPool('run', 80, 890), kickoff_pool(runoff=10)), winner_choice='receive',
                              max_drives=2)
        rows = {r['case']: r for r in rm.check(record)}
        self.assertEqual(rows['Q1->Q2 change of ends']['status'], 'PROVISIONAL')
        self.assertEqual(rows['Touchdown: six points, a distinct try, post-score kickoff']['status'], 'PROVISIONAL')
        self.assertIn('provisional practice rule', rows['Q1->Q2 change of ends']['evidence'])


class ScopedOut(unittest.TestCase):
    def test_a_tied_regulation_game_is_scoped_out_as_overtime(self):
        # A zero-yard run game ends regulation 0-0: overtime is not modelled, so the game is not complete.
        record = gs.play_game(1, ref(StaticPool('run', 0, 450), kickoff_pool()), winner_choice='receive', max_drives=80)
        self.assertTrue(record['tied'], 'seed 1 of this fixture is a 0-0 regulation tie')
        self.assertFalse(record['complete_game'])
        self.assertEqual(record['scope_out'][0]['reason'], 'overtime')
        gs.validate_game(record)

    def test_a_thin_cell_is_scoped_out_as_a_rare_kick_outcome(self):
        kicks = certain_kicks()
        kicks['field_goal']['20-29'] = (5, 5)
        record = gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), kicks),
                              winner_choice='receive')
        self.assertFalse(record['complete_game'])
        self.assertEqual(record['scope_out'][0]['reason'], 'rare kick outcome')


class DriveIndex(unittest.TestCase):
    def test_every_play_state_carries_its_drive_index(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        for d in record['drives']:
            for play in d['plays']:
                self.assertEqual(play['state_before']['drive_index'], d['index'])
                self.assertEqual(play['state_after']['drive_index'], d['index'])
        gs.validate_game(record)

    def test_a_mismatched_state_after_index_is_rejected_by_the_validator(self):
        # Negative fixture: one play's state_after points at another drive.
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        record['drives'][1]['plays'][0]['state_after']['drive_index'] = 1
        with self.assertRaises(AssertionError):
            gs.validate_game(record)

    def test_a_mismatched_state_before_index_fails_the_matrix(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)
        record['drives'][1]['plays'][0]['state_before']['drive_index'] = 99
        row = next(r for r in rm.check(record) if r['case'].startswith('Drive index'))
        self.assertEqual(row['status'], 'FAIL')


class MissedFieldGoalSpot(unittest.TestCase):
    """Rule 11-4-2 as cited in the review: the spot of the kick, or the receiving team's own 20 when the spot is inside it."""

    def test_the_spot_of_the_kick_when_it_is_outside_the_receivers_20(self):
        self.assertEqual(gs.missed_field_goal_spot(35), 65)
        self.assertEqual(gs.missed_field_goal_spot(25), 75)

    def test_the_receivers_own_20_when_the_kick_spot_is_inside_its_20(self):
        self.assertEqual(gs.missed_field_goal_spot(15), 80)
        self.assertEqual(gs.missed_field_goal_spot(5), 80)

    def test_the_boundary_at_the_20_gives_the_20_either_way(self):
        self.assertEqual(gs.missed_field_goal_spot(20), 80)
        self.assertEqual(gs.missed_field_goal_spot(21), 79)

    def test_the_20_exception_applies_to_the_kick_spot_not_the_snap(self):
        # A snap at the 14 is kicked from the 21 (holder offset 7). The 21 is outside the receiver's 20, so the spot is the 79.
        # The snap-based value, 80, is the wrong answer for this kick.
        self.assertEqual(gs.kick_spot_yardline_100(14), 21)
        self.assertEqual(gs.missed_field_goal_spot(gs.kick_spot_yardline_100(14)), 79)
        self.assertEqual(gs.missed_field_goal_spot(14), 80)

    def test_the_engine_boundary_at_the_20_on_the_kick_spot(self):
        # A snap at the 13 is kicked from the 20: the receiver's own 20 (80). A snap at the 14 is kicked from the 21: the 79.
        for snap, expected in ((13, 80), (14, 79)):
            _, calls = spy_simulate(lambda: gs.play_game(
                1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=snap), certain_kicks(fg_made=False)),
                winner_choice='receive', max_drives=2))
            self.assertEqual(calls[1]['start']['yl'], expected, f'a missed kick from a snap at the {snap}')

    def test_the_matrix_rejects_the_snap_based_value_for_a_kick_from_the_21(self):
        # Negative fixture: a snap at the 14 is kicked from the 21, so the receiver must start at the 79. The 80, which the
        # snap-based rule would give, must fail.
        record, _ = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=14), certain_kicks(fg_made=False)),
            winner_choice='receive', max_drives=2))
        self.assertEqual(record['drives'][1]['plays'][0]['state_before']['yardline_100'], 79)
        record['drives'][1]['plays'][0]['state_before']['yardline_100'] = 80
        row = next(r for r in rm.check(record) if r['case'].startswith('Missed field goal'))
        self.assertEqual(row['status'], 'FAIL')

    def test_the_engine_snap_and_kick_spot_differ_and_the_receiver_starts_at_the_kick_spot_rule(self):
        # The snap is the 15 and the kick is from the 22: the receiver's spot is 78. The snap is not the kick spot.
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=15), certain_kicks(fg_made=False)),
            winner_choice='receive', max_drives=2))
        drive = record['drives'][0]
        self.assertEqual((drive['snap_yardline_100'], drive['kick_spot_yardline_100']), (15, 22))
        self.assertEqual(calls[1]['start']['yl'], 78, 'a snap at the 15 is kicked from the 22: the receiver starts at the 78')
        gs.validate_game(record)

    def test_the_matrix_rejects_a_next_drive_at_the_kick_spot_inside_the_20(self):
        # Negative fixture: a snap at the 15 is kicked from the 22, so the receiver must start at the 78. Starting at 85 must
        # fail.
        record, _ = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=15), certain_kicks(fg_made=False)),
            winner_choice='receive', max_drives=2))
        record['drives'][1]['plays'][0]['state_before']['yardline_100'] = 85
        row = next(r for r in rm.check(record) if r['case'].startswith('Missed field goal'))
        self.assertEqual(row['status'], 'FAIL')


class TimeoutCharges(unittest.TestCase):
    """An observed timeout flag charges the side it names, at most three per half, and the count never goes negative."""

    def test_flags_charge_at_most_three_per_half_and_reset_at_halftime(self):
        # Every sampled play is flagged with a timeout called by the offense (A). The count must reach zero and stop there.
        facts = {('G1', 1.0): {'timeout': 1, 'timeout_team': 'A', 'posteam': 'A'}}
        reference = gs.Reference(StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), facts)
        record = gs.play_game(3, reference, winner_choice='receive')  # the default drive cap, so the game reaches halftime
        self.assertIn(3, {q for d in record['drives'] for p in d['plays'] for q in (p['state_before']['quarter'],)},
                      'the game must reach the third quarter for the halftime reset to be checked')
        states = [(state['quarter'], state['home_timeouts'], state['away_timeouts'])
                  for d in record['drives'] for p in d['plays'] for state in (p['state_before'], p['state_after'])]
        self.assertTrue(all(0 <= home <= 3 and 0 <= away <= 3 for _, home, away in states), 'counts stay in 0..3')
        first_half = [home for quarter, home, _ in states if quarter in (1, 2)]
        self.assertIn(0, first_half, 'a flagged side runs out of timeouts in the first half')
        self.assertEqual(min(first_half), 0)
        second_half = [home for quarter, home, _ in states if quarter in (3, 4)]
        self.assertIn(3, second_half, 'the count resets to three at halftime')


class UnmodelledTransitions(unittest.TestCase):
    """Penalties and the two-minute warning are not modelled. A sampled penalty blocks the game; a two-minute crossing is listed in
    the record, so the record cannot be read as a complete game without it."""

    def test_a_sampled_penalty_blocks_the_game_and_is_not_completed(self):
        pool = StaticPool('run', 10, 30)
        for entry in pool.entries:
            entry[1]['penalty'] = 1  # every sampled play is a penalty play: negative fixture
        record = gs.play_game(1, ref(pool, kickoff_pool()), winner_choice='receive', max_drives=3)
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'penalty_not_modelled')
        self.assertFalse(record['complete_regulation'])
        self.assertFalse(record['valid_full_game'])

    def test_a_two_minute_crossing_is_listed_in_the_record(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 100), kickoff_pool()), winner_choice='receive')
        crossings = [t for t in record['unmodelled_transitions'] if t['kind'] == 'two_minute_warning']
        self.assertTrue(crossings, 'a 100-second runoff crosses 2:00 in a late half')
        self.assertTrue(all(t['quarter'] in (2, 4) for t in crossings))
        self.assertFalse(record['valid_full_game'])


class FiveSecondKick(unittest.TestCase):
    """A made field goal takes at most KICK_DURATION_SECONDS of clock. The observed runoff beyond that is not charged to the
    kick: the kickoff subsystem starts from its own runoff."""

    def game(self, runoff, made):
        return gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, runoff), kickoff_pool(spot=25),
                                   certain_kicks(fg_made=made)), winner_choice='receive', max_drives=2)

    def test_a_made_kick_with_a_long_observed_runoff_is_charged_five_seconds(self):
        record = self.game(40, True)
        kick = record['drives'][0]['plays'][-1]
        self.assertEqual(kick['outcome']['clock_runoff_seconds'], gs.KICK_DURATION_SECONDS)
        self.assertEqual(kick['outcome']['clock_runoff_seconds'], 5)
        self.assertEqual(kick['state_after']['clock_seconds'], kick['state_before']['clock_seconds'] - 5)
        self.assertEqual(kick['outcome']['ordinary_runoff_not_charged'], 35)

    def test_a_made_kick_with_a_short_observed_runoff_keeps_it(self):
        kick = self.game(3, True)['drives'][0]['plays'][-1]
        self.assertEqual(kick['outcome']['clock_runoff_seconds'], 3)
        self.assertEqual(kick['outcome']['ordinary_runoff_not_charged'], 0)

    def test_the_kickoff_after_a_made_kick_starts_from_the_charged_clock(self):
        record = self.game(40, True)
        kick = record['drives'][0]['plays'][-1]
        kickoff = next(k for k in record['kickoffs'] if k['kind'] == 'post_field_goal')
        self.assertEqual(kickoff['clock_before'], kick['state_after']['clock_seconds'])
        self.assertEqual(record['drives'][0]['end_clock'], kick['state_after']['clock_seconds'])
        gs.validate_game(record)

    def test_a_missed_kick_keeps_its_observed_runoff(self):
        kick = self.game(40, False)['drives'][0]['plays'][-1]
        self.assertEqual(kick['outcome']['clock_runoff_seconds'], 40)

    def test_the_matrix_rejects_a_made_kick_charged_over_five_seconds(self):
        record = self.game(40, True)
        record['drives'][0]['plays'][-1]['outcome']['clock_runoff_seconds'] = 12  # negative fixture
        row = next(r for r in rm.check(record) if r['case'].startswith('Field goal made'))
        self.assertEqual(row['status'], 'FAIL')


class TimeoutTransition(unittest.TestCase):
    """A timeout is a transition: the count is written once, in state_after; the clock stops for it and the next play
    restarts from the clock the flagged play leaves."""

    FLAGGED = {('G1', 1.0): {'timeout': 1, 'timeout_team': 'A', 'posteam': 'A'}}

    def game(self, facts):
        reference = gs.Reference(StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), facts)
        return gs.play_game(3, reference, winner_choice='receive')

    @staticmethod
    def plays(record):
        return [p for d in record['drives'] for p in d['plays']]

    def test_the_count_is_written_once_in_state_after_and_only_for_the_charged_side(self):
        record = self.game(self.FLAGGED)
        applied = 0
        for p in self.plays(record):
            part = p['participants']
            charged_key = None
            if part['timeout_applied']:
                charged_key = f"{'home' if part['timeout_charged_to'] == 'A' else 'away'}_timeouts"
                applied += 1
            for key in ('home_timeouts', 'away_timeouts'):
                drop = p['state_before'][key] - p['state_after'][key]
                self.assertEqual(drop, 1 if key == charged_key else 0, f'{key} on play {p["sequence"]}')
        self.assertGreater(applied, 0, 'the fixture must charge at least one timeout')

    def test_a_timeout_stops_the_clock_and_the_next_play_restarts_from_that_clock(self):
        record = self.game(self.FLAGGED)
        checked = 0
        for d in record['drives']:
            for a, b in zip(d['plays'], d['plays'][1:]):
                if a['participants']['timeout_applied']:
                    checked += 1
                    # the clock moves by the sampled runoff only: the charge adds no time
                    self.assertEqual(a['state_after']['clock_seconds'],
                                     a['state_before']['clock_seconds'] - a['outcome']['clock_runoff_seconds'])
                # the next play restarts from the clock and counts that the flagged play left
                self.assertEqual(b['state_before']['clock_seconds'], a['state_after']['clock_seconds'])
                self.assertEqual(b['state_before']['home_timeouts'], a['state_after']['home_timeouts'])
                self.assertEqual(b['state_before']['away_timeouts'], a['state_after']['away_timeouts'])
        self.assertGreater(checked, 0)

    def test_a_timeout_changes_the_counts_and_nothing_on_the_clock(self):
        flagged, plain = self.game(self.FLAGGED), self.game({})
        clock = lambda rec: [(p['state_before']['quarter'], p['state_before']['clock_seconds'],
                              p['outcome']['clock_runoff_seconds']) for p in self.plays(rec)]
        self.assertEqual(clock(flagged), clock(plain))
        self.assertEqual(flagged['points'], plain['points'])
        self.assertNotEqual([p['state_after']['home_timeouts'] for p in self.plays(flagged)],
                            [p['state_after']['home_timeouts'] for p in self.plays(plain)])


class DriveIndexFindings(unittest.TestCase):
    """The drive-index finding. The archived 5fcaa6bc record (regression/) has drive_index 1 on every play state of drives 2
    to 24: 23 drives and 280 play states. Every one must be counted and rejected, not just the first."""

    REGRESSION = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'regression' / 'lp-e2-game-seed1-5fcaa6bc.json'
    CURRENT = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'e2-game-seed1.json'

    def regression_record(self):
        with open(self.REGRESSION) as f:
            return json.load(f)['record']

    def test_the_archived_record_is_counted_in_full(self):
        bad, states, examples = gs.drive_index_mismatches(self.regression_record())
        self.assertEqual(len(bad), 23)
        self.assertEqual((bad[0], bad[-1]), (2, 24))
        self.assertEqual(states, 280)
        self.assertTrue(examples[0].startswith('drive 2: play'))

    def test_the_validator_rejects_it_and_states_every_count(self):
        with self.assertRaises(AssertionError) as caught:
            gs.validate_game(self.regression_record())
        self.assertIn('23 drive-index mismatches', str(caught.exception))
        self.assertIn('280 play states', str(caught.exception))

    def test_the_matrix_row_fails_with_the_same_count(self):
        row = next(r for r in rm.check(self.regression_record()) if r['case'].startswith('Drive index'))
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn('23 drive-index mismatches', row['evidence'])

    def test_the_committed_seed_one_record_has_no_mismatch(self):
        with open(self.CURRENT) as f:
            record = json.load(f)
        record = record.get('record', record)
        self.assertEqual(gs.drive_index_mismatches(record)[0], [])


def _empty_e1_pool():
    return StaticPool('run', 0, 1)



class MissedFieldGoalBoundaries(unittest.TestCase):
    """Rule 11-4-2 (a) and (b), as printed: a missed field goal is the receivers' ball at their 20-yard line when the spot of the
    kick is inside their 20, and at the spot of the kick when the spot is at or beyond their 20. In the receivers' yardline_100
    their 20 is 80, so a kick spot of 19 is inside it and a kick spot of 21 is beyond it."""

    def test_one_yard_inside_the_receivers_20_gives_their_20(self):
        self.assertEqual(gs.missed_field_goal_spot(19), 80)

    def test_exactly_on_the_receivers_20_gives_the_20_either_way(self):
        self.assertEqual(gs.missed_field_goal_spot(20), 80)

    def test_one_yard_outside_the_receivers_20_gives_the_spot_of_the_kick(self):
        self.assertEqual(gs.missed_field_goal_spot(21), 79)

    def test_a_snap_at_the_95_is_kicked_from_the_99_and_gives_the_receivers_the_1(self):
        # The holder cap: the kick spot is at most the kicking team's own 1-yard line (99).
        self.assertEqual(gs.kick_spot_yardline_100(95), 99)
        self.assertEqual(gs.missed_field_goal_spot(gs.kick_spot_yardline_100(95)), 1)

    def test_every_kick_spot_gives_a_spot_on_the_field_no_deeper_than_the_receivers_20(self):
        for kick in range(1, 100):
            self.assertTrue(1 <= gs.missed_field_goal_spot(kick) <= 80, kick)


class MissedFieldGoalReturn(unittest.TestCase):
    def test_the_return_exception_is_a_named_unsupported_rule_with_a_guard(self):
        self.assertIn('missed_field_goal_return', gs.UNSUPPORTED_RULES)
        guard = gs.GUARDS['missed_field_goal_return']['guard']
        self.assertIn('touch', guard)
        self.assertIn('line of scrimmage', guard)


class ScopeRefusals(unittest.TestCase):
    """Overtime and rare kick outcomes are scoped out, and the validator refuses any record that calls them complete."""

    def test_a_tied_game_with_its_overtime_block_removed_is_refused(self):
        # R07, adversarial: a tie that is described as a complete regulation game, with the block taken away.
        record = gs.play_game(1, ref(StaticPool('run', 0, 450), kickoff_pool()), winner_choice='receive', max_drives=80)
        self.assertTrue(record['tied'], 'seed 1 of this fixture is a 0-0 regulation tie')
        tampered = {**record, 'blocker': None, 'status': 'complete_regulation', 'complete_regulation': True,
                    'complete_game': True, 'scope_out': [], 'unmodelled_transitions': []}  # isolate the tie refusal
        with self.assertRaisesRegex(AssertionError, 'tied regulation game'):
            gs.validate_game(tampered)

    def test_a_blocked_overtime_game_described_as_complete_is_refused(self):
        record = gs.play_game(1, ref(StaticPool('run', 0, 450), kickoff_pool()), winner_choice='receive', max_drives=80)
        self.assertEqual(record['blocker'], 'overtime_not_modelled')
        with self.assertRaisesRegex(AssertionError, 'never described as a complete game'):
            gs.validate_game({**record, 'complete_regulation': True})

    def test_a_rare_kick_outcome_described_as_complete_is_refused(self):
        kicks = certain_kicks()
        kicks['field_goal']['20-29'] = (5, 5)  # 10 attempts, below the floor
        record = gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), kicks),
                              winner_choice='receive')
        self.assertEqual(record['blocker'], 'thin_kick_cell:field_goal:20-29')
        with self.assertRaisesRegex(AssertionError, 'never described as a complete game'):
            gs.validate_game({**record, 'complete_game': True})


class UnmodelledKinds(unittest.TestCase):
    """Each unmodelled transition type is a named kind in the record. A game that contains one is guarded, and is never a
    complete game. A kickoff kind outside the engine's vocabulary (an onside kick) is refused."""

    def kinds(self, record):
        return {t['kind'] for t in record['unmodelled_transitions']}

    def test_a_missed_field_goal_is_an_unmodelled_return(self):
        record = gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25),
                                     certain_kicks(fg_made=False)), winner_choice='receive', max_drives=2)
        self.assertIn('missed_field_goal_return', self.kinds(record))
        self.assertFalse(record['complete_game'])
        gs.validate_game(record)

    def test_a_timeout_flag_is_an_unmodelled_stoppage(self):
        observed = gs.Reference(StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), {
            ('G1', 1.0): {'timeout': True, 'timeout_team': 'A', 'posteam': 'A', 'passer_id': None, 'rusher_id': None,
                          'receiver_id': None, 'air_yards': None, 'yards_after_catch': None, 'out_of_bounds': 0}})
        record = gs.play_game(1, observed, winner_choice='receive', max_drives=2)
        self.assertIn('timeout', self.kinds(record))
        self.assertFalse(record['complete_game'])

    def test_a_guarded_game_described_as_complete_is_refused(self):
        # Adversarial: a two-minute crossing, with the record's status relabelled as a complete regulation game.
        record = gs.play_game(1, ref(StaticPool('run', 10, 100), kickoff_pool()), winner_choice='receive')
        self.assertIn('two_minute_warning', self.kinds(record))
        with self.assertRaisesRegex(AssertionError, 'never described as a complete game'):
            gs.validate_game({**record, 'status': 'complete_regulation'})

    def test_a_guarded_game_with_its_complete_flag_set_is_refused(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 100), kickoff_pool()), winner_choice='receive')
        with self.assertRaisesRegex(AssertionError, 'never described as a complete game'):
            gs.validate_game({**record, 'complete_game': True})

    def test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 30), kickoff_pool()), winner_choice='receive', max_drives=2)
        tampered = {**record, 'kickoffs': record['kickoffs'] + [{**record['kickoffs'][0], 'kind': 'onside'}]}
        with self.assertRaisesRegex(AssertionError, 'onside kicks are not modelled'):
            gs.validate_game(tampered)


class KickoffClock(unittest.TestCase):
    """A kickoff is charged its observed runoff when that fits in the clock. A runoff that does not fit expires the quarter, with
    the overrun recorded. No kickoff clamps a clock, and a negative clock is refused by validate_game."""

    def test_a_kickoff_that_fits_is_charged_its_runoff_in_full(self):
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('run', 80, 870), kickoff_pool(runoff=5)), winner_choice='receive', max_drives=2))
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score'][0]
        self.assertEqual((post['runoff_seconds'], post['clock_expired_during_kickoff']), (5, False))
        self.assertEqual(calls[1]['start']['clock'], post['clock_before'] - 5, 'the kickoff takes exactly its runoff off the clock')
        gs.validate_game(record)

    def test_a_kickoff_longer_than_the_clock_expires_the_quarter_and_records_the_overrun(self):
        record, _ = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('run', 80, 870), kickoff_pool(runoff=20)), winner_choice='receive', max_drives=2))
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score'][0]
        self.assertTrue(post['clock_expired_during_kickoff'])
        self.assertEqual(post['runoff_overrun_seconds'], 10)
        self.assertFalse(post['clock_clamped_to_zero'])
        gs.validate_game(record)

    def test_a_negative_clock_is_refused_so_no_clamp_can_hide_one(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 870), kickoff_pool(runoff=5)), winner_choice='receive', max_drives=2)
        tampered = copy.deepcopy(record)
        tampered['drives'][0]['plays'][0]['state_after']['clock_seconds'] = -3
        with self.assertRaisesRegex(AssertionError, 'negative game clock'):
            gs.validate_game(tampered)

if __name__ == '__main__':
    unittest.main()
