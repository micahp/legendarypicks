"""Unit tests for the E2 game (game_state.py, game_stats.py, rules_matrix.py): ledger, kickoffs, scoring, clock, matrix.

Run: python3 -m unittest scripts/nfl_sequence/test_game_state.py
"""
import copy
import random
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402
import game_stats  # noqa: E402
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


def ref(pool, kpool, kicks=None, blocked_kicks=None):
    """An observed Reference with no participant lookups, so every play's participants are null."""
    return gs.Reference(pool, kpool, kicks or certain_kicks(), {}, blocked_kicks=blocked_kicks)


def spy_simulate(run):
    """Run `run()` with E1's simulate wrapped. Returns (result, calls), where each call holds the start and the id.
    """
    calls, real = [], gs.e1.simulate

    def spy(start, seed, pool, simulation_id, **kwargs):
        calls.append({'start': dict(start), 'seed': seed, 'simulation_id': simulation_id})
        return real(start, seed, pool, simulation_id, **kwargs)

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

    def test_research_mode_cannot_claim_a_valid_full_pregame_game(self):
        record = gs.play_game(3, ref(_empty_e1_pool(), kickoff_pool()), winner_choice='receive', max_drives=1)
        self.assertEqual(record['mode'], 'legal_game_state_first_piece')
        self.assertFalse(record['valid_full_game'])
        record['valid_full_game'] = True
        record['unsupported_rules'] = gs.active_unsupported_rules(
            record['unmodelled_transitions'], record['blocker'], record['tied'])
        with self.assertRaisesRegex(AssertionError, 'pregame_full_game'):
            gs.validate_game(record)

    def test_a_touchdown_whose_points_disagree_with_its_try_is_refused(self):
        record = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool()), winner_choice='receive', max_drives=1)
        record['drives'][0]['points_scored_on_drive']['points'] = 6  # the try was made, so the points must be 7
        with self.assertRaises(AssertionError):
            gs.validate_game(record)


class PregamePlayerUsage(unittest.TestCase):
    def snapshot(self):
        players = [
            {'gsis_id': 'QB1', 'player_name': 'Starter', 'pos_abb': 'QB', 'pos_rank': 1},
            {'gsis_id': 'QB2', 'player_name': 'Backup', 'pos_abb': 'QB', 'pos_rank': 2},
            {'gsis_id': 'RB1', 'player_name': 'Back', 'pos_abb': 'RB', 'pos_rank': 1},
        ]
        return {
            'snapshot_sha256': 'a' * 64,
            'rosters': {'home': {'team': 'HOM', 'players': players},
                        'away': {'team': 'AWY', 'players': players}},
            'model_reference': {'observed_reference': {
                'receiver_position_usage': {'shares': {'RB': 1.0}},
                'runner_position_usage': {'shares': {'RB': 1.0}},
            }},
        }

    def test_passing_uses_qb1_and_historical_target_mix_can_select_a_running_back(self):
        source = {'game_id': 'G1', 'play_id': 1}
        facts = {'passer_id': 'OLD_QB', 'receiver_id': 'OLD_WR', 'rusher_id': None,
                 'posteam': 'OLD', 'play_type': 'pass', 'timeout': 0, 'timeout_team': '',
                 'out_of_bounds': 0, 'air_yards': 8, 'yards_after_catch': 3}
        reference = gs.Reference({}, [], {}, {('G1', 1): facts})
        play = {'sequence': 1, 'event_type': 'pass_complete', 'outcome': {'sampled_from': source}}
        participants = reference.participants_for(play, 'A', self.snapshot(), seed=1)
        self.assertEqual(participants['passer_id'], 'QB1')
        self.assertEqual(participants['receiver_id'], 'RB1')
        self.assertEqual(participants['passer_side'], 'A')
        self.assertIsNone(participants['posteam'])
        self.assertEqual(participants['sampled_play_context']['posteam'], 'OLD')

    def test_non_scrimmage_play_drops_historical_participant_ids(self):
        source = {'game_id': 'G1', 'play_id': 1}
        facts = {'passer_id': 'OLD_QB', 'receiver_id': 'OLD_WR', 'rusher_id': 'OLD_RB',
                 'posteam': 'OLD', 'play_type': 'kickoff'}
        reference = gs.Reference({}, [], {}, {('G1', 1): facts})
        participants = reference.participants_for(
            {'sequence': 1, 'event_type': 'punt', 'outcome': {'sampled_from': source}},
            'A', self.snapshot(), seed=1)
        self.assertIsNone(participants['passer_id'])
        self.assertIsNone(participants['receiver_id'])
        self.assertIsNone(participants['rusher_id'])

    def test_pregame_player_lines_reconcile_to_team_box_score(self):
        def play(event, yards, participants):
            return {'event_type': event,
                    'outcome': {'yards_gained': yards, 'touchdown': False, 'turnover': False, 'punt': False},
                    'state_before': {'yardline_100': 50}, 'participants': participants}

        plays = [
            play('run', 5, {'attribution': 'pregame_depth_chart_role_sample', 'rusher_id': 'RB1',
                            'rusher_name': 'Back', 'rusher_position': 'RB', 'rusher_team': 'HOM',
                            'rusher_side': 'A'}),
            play('pass_complete', 10, {'attribution': 'pregame_depth_chart_role_sample', 'passer_id': 'QB1',
                                       'passer_name': 'Starter', 'passer_position': 'QB', 'passer_team': 'HOM',
                                       'passer_side': 'A', 'receiver_id': 'RB1', 'receiver_name': 'Back',
                                       'receiver_position': 'RB', 'receiver_team': 'HOM', 'receiver_side': 'A'}),
        ]
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 800, 'terminal': 'punt', 'field_goal_made': None,
                 'plays': plays}
        stats = game_stats.compute([drive], {'A': 0, 'B': 0})
        self.assertEqual(stats['team']['A']['rush_att'], 1)
        self.assertEqual(stats['team']['A']['pass_comp'], 1)
        self.assertEqual(stats['team']['A']['pass_tgt'], 1)


class BlockedKickIntegration(unittest.TestCase):
    def observed_block(self, kick_type):
        return {
            'kick_type': kick_type, 'game_id': '2025_01_TEST', 'play_id': 50,
            'source_file': 'play_by_play_2025.parquet', 'source_sha256': 'a' * 64,
            'classification_status': 'classified_recovery', 'posteam': 'KC', 'defteam': 'SEA',
            'recovery_role': 'receiving_team', 'recovery_spot_yardline_100': 55,
            'return_endpoint_yardline_100': 50, 'return_yards': 5, 'crossed_line': 0,
            'clock_runoff_seconds': 1,
        }

    def test_blocked_punt_uses_the_shared_reducer_and_team_stats(self):
        blocked = {'records': {'field_goal': [], 'punt': [self.observed_block('punt')]},
                   'rates': {'punt_blocked': {'attempts': 1, 'blocked': 1}}, 'sha256': 'b' * 64}
        record = gs.play_game(5, ref(StaticPool('punt', 0, 5, 25), kickoff_pool(), blocked_kicks=blocked),
                              winner_choice='receive', max_drives=1)
        play = record['drives'][0]['plays'][-1]
        kicking_side = play['state_before']['offense_team']
        receiving_side = play['state_before']['defense_team']
        self.assertEqual(play['event_type'], 'blocked_punt')
        self.assertTrue(play['outcome']['punt_attempt'])
        self.assertEqual(play['state_after']['offense_team'], receiving_side)
        self.assertEqual(record['stats']['team'][kicking_side]['blocked_punts'], 1)
        self.assertEqual(record['stats']['team'][receiving_side]['blocked_kick_return_yards'], 5)
        self.assertEqual(rm._blocked_kicks(record)[0], rm.PASS)
        gs.validate_game(record)

    def test_blocked_field_goal_is_an_attempt_but_neither_a_make_nor_a_miss(self):
        kicks = certain_kicks()
        kicks['field_goal_outcomes'] = {bucket: (0, 0, 60) for bucket in gs.FG_BUCKETS}
        blocked = {'records': {'field_goal': [self.observed_block('field_goal')], 'punt': []},
                   'rates': {'punt_blocked': {'attempts': 1, 'blocked': 0}}, 'sha256': 'b' * 64}
        record = gs.play_game(7, ref(StaticPool('field_goal_attempt', 0, 5), kickoff_pool(), kicks,
                                     blocked_kicks=blocked), winner_choice='receive', max_drives=1)
        play = record['drives'][0]['plays'][-1]
        kicking_side = play['state_before']['offense_team']
        self.assertEqual(play['event_type'], 'blocked_field_goal')
        self.assertEqual(play['outcome']['field_goal_result'], 'blocked')
        self.assertTrue(play['outcome']['field_goal_attempt'])
        self.assertIsNone(record['drives'][0]['field_goal_made'])
        self.assertEqual(record['stats']['team'][kicking_side]['fg_att'], 1)
        self.assertEqual(record['stats']['team'][kicking_side]['fg_made'], 0)
        self.assertEqual(record['stats']['team'][kicking_side]['blocked_field_goals'], 1)
        self.assertEqual(rm._blocked_kicks(record)[0], rm.PASS)
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

    def test_a_score_after_the_two_minute_warning_keeps_the_actual_clock_and_kickoff_expiry(self):
        # The Q2 touchdown down starts at 15:00 and ends at 0:20. The warning follows the down at 0:20; it does not rewind the
        # clock to 2:00, and the sampled post-score kickoff starts from 0:20.
        g = gs._Game(1, ref(StaticPool('run', 80, 880), kickoff_pool(runoff=10)),
                     gs.CoinTossLedger('A', 'B', 'receive'), random.Random(1))
        g.quarter, g.clock, g.offense, g.defense, g.yl, g.down, g.togo = 2, 900, 'A', 'B', 50, 1, 10
        g._drive_body()
        self.assertEqual(g.drives[0]['end_clock'], 20)
        self.assertEqual(g.drives[0]['plays'][-1]['outcome']['two_minute_warning'], True)
        self.assertEqual(g.events[0]['clock_before'], 20)
        self.assertFalse(g.events[0]['clock_expired_during_kickoff'])

    def test_a_punt_that_expires_q1_keeps_the_receiving_team_and_its_spot(self):
        record, calls = spy_simulate(lambda: gs.play_game(
            1, ref(StaticPool('punt', 0, 890, spot=40), kickoff_pool(runoff=10)), winner_choice='receive',
            max_drives=2))
        self.assertEqual(record['drives'][0]['terminal'], 'punt')
        self.assertEqual(record['drives'][0]['end_quarter'], 2, 'the quarter changes on the punt, which ends the drive')
        self.assertEqual(calls[1]['start']['quarter'], 2)
        self.assertEqual(calls[1]['start']['clock'], 900)
        self.assertEqual(calls[1]['start']['offense'], calls[0]['start']['defense'], 'the punt receiver keeps the ball')
        self.assertEqual(calls[1]['start']['yl'], 40)
        self.assertEqual(len([k for k in record['kickoffs'] if k['quarter'] == 2]), 0,
                         'a change of ends has no kickoff')
        rows = {r['case']: r for r in rm.check(record)}
        self.assertEqual(rows['Q1->Q2 change of ends']['status'], 'PASS')
        gs.validate_game(record)

    def test_a_q1_turnover_on_downs_at_the_boundary_is_not_misclassified_as_q2(self):
        record = gs.play_game(1, ref(StaticPool('run', 0, 223), kickoff_pool(runoff=10)), winner_choice='receive',
                              max_drives=2)
        drive = record['drives'][0]
        self.assertEqual(drive['terminal'], 'turnover_on_downs')
        self.assertEqual(drive['end_quarter'], 2)
        self.assertEqual(drive['plays'][-1]['state_before']['quarter'], 1)
        rows = {r['case']: r for r in rm.check(record)}
        self.assertEqual(rows['Q1->Q2 change of ends']['status'], 'PASS')
        first_drive_only = dict(record, drives=record['drives'][:1])
        self.assertEqual(rm._turnover_on_downs_q2(first_drive_only)[0], 'NOT_APPLICABLE')

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

    def test_rule_matrix_separates_taken_paths_from_capability_limits(self):
        rows = rm.check(self._halftime_record())
        expected = {'Clock running/stopped': rm.PASS, 'Timeouts': rm.PASS, 'Penalties': rm.PASS,
                    'Onside kick': rm.NOT_APPLICABLE, 'Player lineups': rm.PARTIAL}
        for case, status in expected.items():
            row = next(r for r in rows if r['case'].startswith(case))
            self.assertEqual(row['status'], status, case)
        warning = next(r for r in rows if r['case'] == 'Two-minute warning crossing marker')
        self.assertIn(warning['status'], ('PASS', 'NOT_APPLICABLE'))
        clock_state = next(r for r in rows if r['case'] == 'Clock running/stopped and restart state')
        self.assertEqual(clock_state['status'], rm.PASS)


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
        self.assertEqual(set(record['rule_capability_limitations']), set(gs.UNSUPPORTED_RULES))
        rows = {r['case']: r['status'] for r in rm.check(record)}
        self.assertIn(rows['Unmodelled rules: each carries a named guard'], (rm.PARTIAL, rm.UNSUPPORTED))
        self.assertEqual(rows['Timeouts: three per team per half'], rm.PASS)

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

    def _game(self):
        reference = ref(StaticPool('run', 10, 30), kickoff_pool())
        ledger = gs.CoinTossLedger('A', 'B', 'receive')
        game = gs._Game(1, reference, ledger, random.Random(1))
        game.offense, game.defense = 'A', 'B'
        return game

    @staticmethod
    def timeout_play():
        return {'participants': {'timeout': True, 'sampled_play_context': {
                    'timeout_team': 'HOME', 'posteam': 'HOME', 'defteam': 'AWAY'}},
                'state_before': {'home_timeouts': None, 'away_timeouts': None},
                'state_after': {'home_timeouts': None, 'away_timeouts': None, 'clock_seconds': 500},
                'outcome': {}}

    def test_a_fourth_timeout_attempt_blocks_after_three_charges(self):
        game = self._game()
        for _ in range(3):
            play = self.timeout_play()
            game._apply_timeouts([play])
            self.assertTrue(play['participants']['timeout_applied'])
        self.assertEqual(game.timeouts, {'A': 0, 'B': 3})
        game._apply_timeouts([self.timeout_play()])
        self.assertEqual(game.timeouts, {'A': 0, 'B': 3})
        self.assertEqual(game.blocker, 'timeout_limit_exceeded')

    def test_timeouts_reset_at_halftime(self):
        game = self._game()
        game.quarter, game.clock = 2, 0
        game.timeouts = {'A': 0, 'B': 1}
        game._half_start()
        self.assertEqual(game.quarter, 3)
        self.assertEqual(game.timeouts, {'A': 3, 'B': 3})


class UnmodelledTransitions(unittest.TestCase):
    """Penalties are guarded; two-minute warnings have explicit stop and restart transitions."""

    def test_a_sampled_penalty_blocks_the_game_and_is_not_completed(self):
        pool = StaticPool('run', 10, 30)
        for entry in pool.entries:
            entry[1]['penalty'] = 1  # every sampled play is a penalty play: negative fixture
        record = gs.play_game(1, ref(pool, kickoff_pool()), winner_choice='receive', max_drives=3)
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'penalty_not_modelled')
        self.assertFalse(record['complete_regulation'])
        self.assertFalse(record['valid_full_game'])

    def test_a_two_minute_crossing_is_recorded_without_rewinding_the_clock(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 100), kickoff_pool()), winner_choice='receive')
        stops = [t for d in record['drives'] for p in d['plays'] for t in [p] if p['outcome'].get('two_minute_warning')]
        self.assertTrue(stops, 'a 100-second runoff crosses 2:00 in a late half')
        self.assertTrue(all(0 < p['state_after']['clock_seconds'] < 120 for p in stops))
        self.assertTrue(all(p['state_before']['quarter'] in (2, 4) for p in stops))
        self.assertFalse(any(t['kind'] == 'two_minute_warning' for t in record['unmodelled_transitions']))
        for play in stops:
            self.assertIn({'kind': 'automatic_two_minute_warning', 'team': None},
                          play['outcome']['clock_transition']['stoppages'])
            self.assertEqual(play['outcome']['clock_transition']['restart_trigger'], 'next_snap')
        self.assertNotIn('clock_start_stop', record['unsupported_rules'])
        self.assertIn('clock_start_stop', record['guards'])
        self.assertFalse(record['valid_full_game'])
        gs.validate_game(record)

    def test_a_missing_two_minute_guard_event_is_refused(self):
        record = gs.play_game(1, ref(StaticPool('run', 10, 100), kickoff_pool()), winner_choice='receive')
        play = next(p for d in record['drives'] for p in d['plays'] if p['outcome'].get('two_minute_warning'))
        play['outcome']['two_minute_warning'] = False
        play['outcome']['clock_transition']['stoppages'] = [
            item for item in play['outcome']['clock_transition']['stoppages']
            if item['kind'] != 'automatic_two_minute_warning']
        with self.assertRaisesRegex(AssertionError, 'two-minute warning'):
            gs.validate_game(record)

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

    FLAGGED = {('G1', 1): {'timeout': 1, 'timeout_team': 'A', 'posteam': 'A', 'defteam': 'B'}}

    def game(self, facts):
        pool = StaticPool('run', 10, 30)
        pool.entries = [(event, {**row, 'play_id': index + 1}, runoff, spot)
                        for index, (event, row, runoff, spot) in enumerate(pool.entries)]
        reference = gs.Reference(pool, kickoff_pool(), certain_kicks(), facts)
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
        flagged_plays = self.plays(flagged)
        applied = [p for p in flagged_plays if p['participants']['timeout_applied']]
        self.assertTrue(applied)
        for play in applied:
            self.assertEqual(play['state_after']['clock_seconds'],
                             play['state_before']['clock_seconds'] - play['outcome']['clock_runoff_seconds'])
            self.assertIn({'kind': 'team_timeout', 'team': play['participants']['timeout_charged_to']},
                          play['outcome']['clock_transition']['stoppages'])
            self.assertEqual(play['outcome']['clock_transition']['restart_trigger'], 'next_snap')
        self.assertLessEqual(sum(len(d['plays']) for d in flagged['drives']),
                             sum(len(d['plays']) for d in plain['drives']))

    def test_a_defensive_timeout_uses_the_sampled_defensive_team(self):
        facts = {('G1', 1): {'timeout': True, 'timeout_team': 'B', 'posteam': 'A', 'defteam': 'B'}}
        record = self.game(facts)
        play = next(p for d in record['drives'] for p in d['plays'] if p['participants']['timeout'])
        self.assertTrue(play['participants']['timeout_applied'])
        self.assertEqual(play['participants']['timeout_charged_to'], play['state_before']['defense_team'])


class FirstDownClockTransition(unittest.TestCase):
    @staticmethod
    def play(quarter, clock_before, clock_after, offense_after='A', down_before=2, turnover=False):
        return {
            'event_type': 'interception' if turnover else 'run',
            'participants': {},
            'state_before': {'quarter': quarter, 'clock_seconds': clock_before,
                             'offense_team': 'A', 'down': down_before},
            'state_after': {'quarter': quarter, 'clock_seconds': clock_after,
                            'offense_team': offense_after, 'down': 1},
            'outcome': {'clock_runoff_seconds': clock_before - clock_after, 'turnover': turnover},
        }

    def test_first_down_restarts_at_referee_signal_outside_late_game_windows(self):
        game = object.__new__(gs._Game)
        play = self.play(1, 700, 690)
        game._record_clock_transitions([play])
        transition = play['outcome']['clock_transition']
        self.assertIn({'kind': 'first_down', 'team': None}, transition['stoppages'])
        self.assertEqual(transition['restart_trigger'], 'referee_signal')

    def test_first_down_restarts_at_snap_inside_late_game_windows(self):
        game = object.__new__(gs._Game)
        play = self.play(4, 310, 290)
        game._record_clock_transitions([play])
        self.assertEqual(play['outcome']['clock_transition']['restart_trigger'], 'next_snap')

    def test_possession_change_is_not_misclassified_as_a_first_down(self):
        game = object.__new__(gs._Game)
        play = self.play(3, 500, 490, offense_after='B', turnover=True)
        game._record_clock_transitions([play])
        transition = play['outcome']['clock_transition']
        self.assertNotIn({'kind': 'first_down', 'team': None}, transition['stoppages'])
        self.assertIn({'kind': 'possession_change', 'team': None}, transition['stoppages'])


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
        self.assertIn('sampled', guard)
        self.assertIn('return touchdown', guard)


class MissedFieldGoalTransition(unittest.TestCase):
    def game(self, pool, quarter=1, clock=500):
        game = object.__new__(gs._Game)
        sample = {'spot_adjustment_yards': -2, 'source': {'game_id': 'G1', 'play_id': 10,
                                                           'next_drive_index': 4, 'next_play_id': 11}}
        game.ref = gs.Reference({}, [], {}, {}, pool)
        game.rng = random.Random(7)
        game.quarter, game.clock = quarter, clock
        game.blocker = None
        game.block = lambda reason: setattr(game, 'blocker', reason)
        return game, sample

    def test_a_missed_kick_uses_the_historical_receiving_start_adjustment(self):
        sample = {'spot_adjustment_yards': -2, 'source': {'game_id': 'G1', 'play_id': 10,
                                                           'next_drive_index': 4, 'next_play_id': 11}}
        game, _ = self.game({'30-39': [sample] * gs.MIN_KICK_N})
        result = game._missed_field_goal_transition(35, 42)
        self.assertEqual(result['baseline_yardline_100'], 58)
        self.assertEqual(result['receiving_start_yardline_100'], 56)
        self.assertEqual(result['spot_adjustment_yards'], -2)
        self.assertEqual(result['pool_sample_count'], gs.MIN_KICK_N)
        self.assertEqual(result['source']['next_play_id'], 11)

    def test_a_missed_kick_at_halftime_records_period_expiry_without_a_next_drive_spot(self):
        game, _ = self.game({}, quarter=2, clock=0)
        result = game._missed_field_goal_transition(35, 42)
        self.assertEqual(result['status'], 'period_expired')
        self.assertIsNone(result['receiving_start_yardline_100'])


class SafetyFreeKickRefusal(unittest.TestCase):
    def safety_record(self):
        return gs.play_game(23, ref(StaticPool('run', -30, 10), kickoff_pool(spot=75)),
                            winner_choice='receive', max_drives=5)

    def test_safety_is_recorded_then_blocked_without_sampling_the_ordinary_kickoff_pool(self):
        record = self.safety_record()
        self.assertEqual(record['drives'][0]['terminal'], 'safety')
        self.assertEqual(record['drives'][0]['points_scored_on_drive'],
                         {'team': record['drives'][0]['plays'][-1]['state_before']['defense_team'],
                          'points': gs.SAFETY_POINTS, 'try': None})
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'safety_free_kick_not_modelled')
        self.assertFalse(record['complete_game'])
        self.assertFalse(record['valid_full_game'])
        self.assertFalse(any(k['kind'] == 'safety_free_kick' for k in record['kickoffs']))
        self.assertTrue(any(reason['reason'] == 'safety free kick' for reason in record['scope_out']))
        gs.validate_game(record)
        matrix_row = next(row for row in rm.check(record)
                          if row['case'] == 'Made field goal (3) and safety (2), with the correct post-score kick')
        self.assertEqual(matrix_row['status'], rm.BLOCKED)

    def test_a_safety_free_kick_fabricated_from_an_ordinary_kickoff_is_rejected(self):
        record = self.safety_record()
        record['kickoffs'].append({**record['kickoffs'][0], 'kind': 'safety_free_kick', 'after_drive': 1})
        with self.assertRaisesRegex(AssertionError, 'separate observed safety-kick outcome table'):
            gs.validate_game(record)

    def test_a_safety_at_halftime_skips_the_free_kick_and_uses_the_q3_ledger_kick(self):
        record = gs.play_game(23, ref(StaticPool('run', -30, 900), kickoff_pool(spot=75, runoff=900)),
                              winner_choice='receive', max_drives=5)
        self.assertEqual((record['drives'][0]['terminal'], record['drives'][0]['end_quarter'],
                          record['drives'][0]['end_clock']), ('safety', 2, 0))
        self.assertTrue(any(boundary['kind'] == 'skipped_post_score_kick'
                            and boundary['skipped_kind'] == 'safety_free_kick'
                            for boundary in record['boundaries']))
        self.assertTrue(any(kick['kind'] == 'half_start' and kick['quarter'] == 3 for kick in record['kickoffs']))
        self.assertFalse(any(kick['kind'] == 'safety_free_kick' for kick in record['kickoffs']))
        gs.validate_game(record)


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

    def test_a_timeout_flag_is_applied_and_recorded_as_a_clock_stoppage(self):
        observed = gs.Reference(StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), {
            ('G1', 1): {'timeout': True, 'timeout_team': 'A', 'posteam': 'A', 'defteam': 'B', 'passer_id': None,
                        'rusher_id': None, 'receiver_id': None, 'air_yards': None, 'yards_after_catch': None,
                        'out_of_bounds': 0}})
        record = gs.play_game(1, observed, winner_choice='receive', max_drives=2)
        play = next(p for d in record['drives'] for p in d['plays'] if p['participants']['timeout'])
        self.assertTrue(play['participants']['timeout_applied'])
        self.assertIn({'kind': 'team_timeout', 'team': play['participants']['timeout_charged_to']},
                      play['outcome']['clock_transition']['stoppages'])
        self.assertNotIn('timeout', self.kinds(record))
        self.assertFalse(record['complete_game'])

    def test_a_guarded_game_described_as_complete_is_refused(self):
        # Adversarial: a missed field goal awarded under Rule 11-4-2 is guarded (its touch exception is unmodelled); the record's
        # status is relabelled as a complete regulation game, and validate_game refuses it.
        record = gs.play_game(1, ref(StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25),
                                     certain_kicks(fg_made=False)), winner_choice='receive', max_drives=2)
        self.assertIn('missed_field_goal_return', self.kinds(record))
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


class TwoMinuteWarning(unittest.TestCase):
    """Rule 3 Section 41: the warning follows the last pre-2:00 down at its actual dead-ball clock value."""

    def test_a_play_ending_at_2_01_does_not_stop_the_clock(self):
        self.assertEqual(gs.two_minute_stop(2, 125, 121, set()), (121, False))

    def test_a_play_ending_at_2_00_warns_at_2_00(self):
        self.assertEqual(gs.two_minute_stop(2, 121, 120, set()), (120, True))

    def test_a_crossing_keeps_the_actual_post_down_clock(self):
        self.assertEqual(gs.two_minute_stop(4, 125, 110, set()), (110, True))

    def test_a_period_expiry_does_not_trigger_a_warning(self):
        self.assertEqual(gs.two_minute_stop(2, 125, 0, set()), (0, False))

    def test_a_second_dead_ball_in_the_same_half_does_not_stop_again(self):
        self.assertEqual(gs.two_minute_stop(2, 118, 100, {2}), (100, False))

    def test_the_warning_resets_at_halftime_so_the_fourth_quarter_warns_too(self):
        self.assertEqual(gs.two_minute_stop(4, 125, 110, {2}), (110, True), 'the fourth quarter is a new half')

    def test_a_kickoff_warning_keeps_the_observed_post_kick_clock(self):
        g = gs._Game(7, ref(StaticPool('run', 5, 10), kickoff_pool(runoff=15)),
                     gs.CoinTossLedger('A', 'B', 'receive'), random.Random(7))
        g.quarter, g.clock = 2, 125
        g._kick('post_score', 'A', 'B')
        event = g.events[0]
        self.assertEqual(event['clock_after'], 110)
        self.assertTrue(event['two_minute_warning'])
        self.assertEqual(g.clock, 110)

    def test_quarters_one_and_three_never_stop_for_the_warning(self):
        self.assertEqual(gs.two_minute_stop(1, 125, 110, set()), (110, False))
        self.assertEqual(gs.two_minute_stop(3, 125, 110, set()), (110, False))

    def test_a_crossing_play_in_q2_keeps_its_observed_runoff(self):
        g = gs._Game(7, ref(StaticPool('run', 5, 10), kickoff_pool()), gs.CoinTossLedger('A', 'B', 'receive'), random.Random(7))
        g.quarter, g.clock, g.offense, g.defense, g.yl, g.down, g.togo = 2, 125, 'A', 'B', 50, 1, 10
        g._drive_body()
        stop = next(p for d in g.drives for p in d['plays'] if p['outcome'].get('two_minute_warning'))
        self.assertEqual((stop['state_before']['clock_seconds'], stop['state_after']['clock_seconds']), (125, 115))
        self.assertEqual(stop['outcome']['clock_runoff_seconds'], 10)
        self.assertEqual(g.warned_quarters, {2})

    def test_a_play_ending_at_2_01_in_q2_is_not_stopped(self):
        g = gs._Game(7, ref(StaticPool('run', 5, 4), kickoff_pool()), gs.CoinTossLedger('A', 'B', 'receive'), random.Random(7))
        g.quarter, g.clock, g.offense, g.defense, g.yl, g.down, g.togo = 2, 125, 'A', 'B', 50, 1, 10
        g._drive_body()
        first = g.drives[0]['plays'][0]
        self.assertEqual(first['state_after']['clock_seconds'], 121, 'the first play ends at 2:01')
        self.assertFalse(first['outcome'].get('two_minute_warning'), 'a dead ball at 2:01 is not the warning')
        stop = next(p for d in g.drives for p in d['plays'] if p['outcome'].get('two_minute_warning'))
        self.assertEqual(stop['state_after']['clock_seconds'], 117, 'the warning keeps the post-down clock value')



class TimeoutStop(unittest.TestCase):
    """A timeout is an explicit stop. state_before carries the count before the call; state_after carries the count after it; the
    stop records the counts, the clock at the stop, and the restart. A corrupted pre-call count is refused."""

    def timed_game(self):
        observed = gs.Reference(StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), {
            ('G1', 1.0): {'timeout': True, 'timeout_team': 'A', 'posteam': 'A', 'passer_id': None, 'rusher_id': None,
                          'receiver_id': None, 'air_yards': None, 'yards_after_catch': None, 'out_of_bounds': 0}})
        return gs.play_game(1, observed, winner_choice='receive', max_drives=2)

    def flagged(self, record):
        return next(p for d in record['drives'] for p in d['plays'] if p['participants'].get('timeout'))

    def test_the_flagged_play_carries_its_pre_call_count_and_one_fewer_on_the_charged_side(self):
        play = self.flagged(self.timed_game())
        side = {'A': 'home', 'B': 'away'}[play['participants']['timeout_charged_to']]
        self.assertEqual(play['state_before'][f'{side}_timeouts'] - 1, play['state_after'][f'{side}_timeouts'])
        other = 'away' if side == 'home' else 'home'
        self.assertEqual(play['state_before'][f'{other}_timeouts'], play['state_after'][f'{other}_timeouts'])

    def test_the_stop_is_explicit_with_its_counts_and_its_clock(self):
        play = self.flagged(self.timed_game())
        stop = play['outcome']['timeout_stop']
        self.assertEqual(stop['counts_before'], {'home': play['state_before']['home_timeouts'],
                                                 'away': play['state_before']['away_timeouts']})
        self.assertEqual(stop['counts_after'], {'home': play['state_after']['home_timeouts'],
                                                'away': play['state_after']['away_timeouts']})
        self.assertEqual(stop['clock_at_stop'], play['state_after']['clock_seconds'])
        self.assertTrue(stop['applied'])

    def test_a_corrupted_pre_call_count_is_refused(self):
        record = copy.deepcopy(self.timed_game())
        play = self.flagged(record)
        side = {'A': 'home', 'B': 'away'}[play['participants']['timeout_charged_to']]
        play['state_before'][f'{side}_timeouts'] = play['state_after'][f'{side}_timeouts']  # the post-call value, written pre-call
        with self.assertRaisesRegex(AssertionError, 'timeout count breaks|disagrees with its states'):
            gs.validate_game(record)



if __name__ == '__main__':
    unittest.main()
