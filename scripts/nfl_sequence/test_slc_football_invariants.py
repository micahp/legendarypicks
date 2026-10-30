"""Hard SLC checks for QB scramble, sack, and pass-result semantics."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_stats  # noqa: E402
import slc_engine  # noqa: E402
import football_assertions  # noqa: E402


def participants(*, passer=None, rusher=None, receiver=None, play_type=None):
    part = {
        'passer_id': passer, 'rusher_id': rusher, 'receiver_id': receiver,
        'passer_name': 'Quarterback' if passer else None, 'passer_position': 'QB' if passer else None,
        'passer_team': 'AAA' if passer else None, 'passer_side': 'A' if passer else None,
        'rusher_name': 'Quarterback' if rusher == 'QB1' else 'Running back' if rusher else None,
        'rusher_position': 'QB' if rusher == 'QB1' else 'RB' if rusher else None,
        'rusher_team': 'AAA' if rusher else None, 'rusher_side': 'A' if rusher else None,
        'receiver_name': 'Receiver' if receiver else None, 'receiver_position': 'WR' if receiver else None,
        'receiver_team': 'AAA' if receiver else None, 'receiver_side': 'A' if receiver else None,
        'attribution': 'pre_event_selection',
        'sampled_play_context': {'play_type': play_type},
    }
    return part


def play(event, yards, part, *, turnover=False, passing_yards=None, receiving_yards=None):
    context = part['sampled_play_context']
    if passing_yards is not None:
        context['passing_yards'] = passing_yards
    if receiving_yards is not None:
        context['receiving_yards'] = receiving_yards
    after_offense, after_defense = ('B', 'A') if event in ('interception', 'fumble_lost') else ('A', 'B')
    return {
        'sequence': 1,
        'event_type': event,
        'state_before': {'quarter': 1, 'clock_seconds': 900, 'down': 2, 'yards_to_go': 10,
                         'yardline_100': 50, 'offense_team': 'A', 'defense_team': 'B',
                         'home_score': 0, 'away_score': 0},
        'state_after': {'quarter': 1, 'clock_seconds': 890, 'down': 1 if event in ('interception', 'fumble_lost') else 2,
                        'yards_to_go': 10, 'yardline_100': 50,
                        'offense_team': after_offense, 'defense_team': after_defense,
                        'home_score': 0, 'away_score': 0},
        'participants': part,
        'outcome': {'yards_gained': yards, 'touchdown': False, 'turnover': turnover, 'punt': False},
    }


def decision(event, *, intent, outcome_intent, action=None, selected=None):
    return {
        'event': event, 'intent': intent, 'outcome_intent': outcome_intent,
        'qb_action': action, 'participants': selected or {}, 'artifact_sha256': 'a' * 64,
        'decision_timing': 'pre_outcome_sample',
        'state': {'quarter': 1, 'clock': 900, 'down': 2, 'togo': 10, 'yardline_100': 50,
                  'score_diff': 0, 'offense': 'A', 'defense': 'B', 'team': 'AAA'},
    }


def one_play_record(play_row):
    return {
        'pregame_snapshot': {
            'snapshot_sha256': 'b' * 64,
            'schedule': {'game_id': '2025_01_AAA_BBB'},
        },
        'drives': [{'index': 1, 'offense_team': 'A', 'plays': [play_row]}],
    }


class QBPlayTypeInvariants(unittest.TestCase):
    def assert_full_evidence(self, failure, record, row, call, seed, failure_class):
        context = failure.context
        snapshot = record.get('pregame_snapshot') or {}
        expected_game = ((snapshot.get('schedule') or {}).get('game_id')
                         or record.get('game_id') or 'unknown')
        self.assertEqual(failure.failure_class, failure_class)
        self.assertEqual(context['game_id'], expected_game)
        self.assertEqual(context['seed'], seed)
        self.assertEqual(context['play_index'], 1)
        self.assertEqual(context['state_before'], row['state_before'])
        self.assertEqual(context['decision'], call)
        self.assertEqual(context['outcome']['event_type'], row['event_type'])
        self.assertEqual(context['state_after'], row['state_after'])
        self.assertTrue(context['violated_assertion'])
        self.assertEqual(context['source_artifact_hashes']['snapshot_sha256'],
                         snapshot.get('snapshot_sha256', 'unavailable'))
        self.assertEqual(context['source_artifact_hashes']['playcall_artifact_sha256'], 'a' * 64)

    def test_pregame_decision_evidence_rejects_future_state_and_keeps_full_context(self):
        row = play('run', 4, participants(rusher='RB1', play_type='run'))
        call = decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'})
        call['state']['next_play_outcome'] = 'touchdown'
        record = one_play_record(row)
        record['pregame_snapshot'] = {
            'snapshot_sha256': 'b' * 64, 'schedule': {'game_id': '2025_01_AAA_BBB'},
        }

        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=31)

        failure = raised.exception
        self.assertEqual(failure.failure_class, 'NONCAUSAL_INFORMATION')
        self.assert_full_evidence(failure, record, row, call, 31, 'NONCAUSAL_INFORMATION')
        self.assertEqual(failure.context['source_artifact_hashes']['snapshot_sha256'], 'b' * 64)

    def test_scramble_decision_must_be_a_rostered_qb_rush_without_a_target(self):
        row = play('run', 6, participants(rusher='QB1', play_type='run'))
        record = one_play_record(row)
        valid = decision('run', intent='dropback', outcome_intent='run', action='scramble',
                         selected={'passer': 'QB1', 'rusher': 'QB1'})
        result = slc_engine.validate_decision_outcomes(
            record, [valid], seed=17,
            snapshot={'snapshot_sha256': 'b' * 64, 'schedule': {'game_id': '2025_01_AAA_BBB'}})
        self.assertEqual(result, {'status': 'passed', 'plays_checked': 1})

    def test_designed_qb_run_is_not_relabelled_as_a_scramble(self):
        row = play('run', 4, participants(rusher='QB1', play_type='run'))
        called_run = decision('run', intent='run', outcome_intent='run', selected={'rusher': 'QB1'})
        result = slc_engine.validate_decision_outcomes(one_play_record(row), [called_run], seed=18)
        self.assertEqual(result, {'status': 'passed', 'plays_checked': 1})

    def test_mutated_scramble_to_pass_fails_as_illegal_state_with_seed_context(self):
        row = play('pass_complete', 6, participants(passer='QB1', receiver='WR1', play_type='pass'))
        record = one_play_record(row)
        snapshot = {'snapshot_sha256': 'b' * 64, 'schedule': {'game_id': '2025_01_AAA_BBB'}}
        record['pregame_snapshot'] = snapshot
        invalid = decision('pass_complete', intent='dropback', outcome_intent='run', action='scramble',
                           selected={'passer': 'QB1', 'rusher': 'QB1'})
        with self.assertRaises(AssertionError) as raised:
            slc_engine.validate_decision_outcomes(
                record, [invalid], seed=17, snapshot=snapshot)

        message = str(raised.exception)
        self.assertIsInstance(raised.exception, football_assertions.FootballAssertionError)
        self.assert_full_evidence(raised.exception, record, row, invalid, 17, 'ILLEGAL_STATE')
        for field in ('ILLEGAL_STATE', 'game_id', '2025_01_AAA_BBB', 'seed', '17', 'play_index',
                      'state_before', 'decision', 'outcome', 'state_after', 'source_artifact_hashes',
                      'snapshot_sha256', 'playcall_artifact_sha256', 'a' * 64, 'b' * 64):
            with self.subTest(field=field):
                self.assertIn(field, message)

    def test_sacks_are_not_pass_attempts_and_scrambles_are_rushes(self):
        plays = [
            play('run', 6, participants(rusher='QB1', play_type='run')),
            play('run', 2, participants(rusher='RB1', play_type='run')),
            play('sack', -5, participants(passer='QB1', play_type='pass')),
            play('pass_complete', 12, participants(passer='QB1', receiver='WR1', play_type='pass'),
                 passing_yards=12, receiving_yards=12),
            play('pass_incomplete', 0, participants(passer='QB1', receiver='WR1', play_type='pass')),
            play('interception', 0, participants(passer='QB1', receiver='WR1', play_type='pass'), turnover=True),
        ]
        for index, row in enumerate(plays, 1):
            row['sequence'] = index
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 700, 'terminal': 'punt', 'field_goal_made': None,
                 'plays': plays}
        stats = game_stats.compute([drive], {'A': 0, 'B': 0})
        home = stats['team']['A']
        self.assertEqual((home['rush_att'], home['pass_att'], home['pass_comp'], home['sacks_taken']), (2, 3, 1, 1))
        self.assertEqual((home['interceptions'], home['turnovers'], home['pass_tgt']), (1, 1, 3))
        qb = next(row for row in stats['player'] if row['player_id'] == 'QB1')
        self.assertEqual(qb['rushing']['att'], 1)
        self.assertEqual(qb['passing']['att'], 3)
        self.assertEqual(qb['passing']['sacked'], 1)
        self.assertEqual(qb['passing']['sack_yds'], -5)

    def test_incomplete_pass_and_interception_mutations_fail_with_rule_context(self):
        cases = (
            (play('pass_incomplete', 5, participants(passer='QB1', receiver='WR1', play_type='pass')),
             decision('pass_incomplete', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'}), 'zero gain'),
            (play('interception', 0, participants(passer='QB1', receiver='WR1', play_type='pass'), turnover=False),
             decision('interception', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'}), 'change of possession'),
        )
        cases[0][0]['participants']['sampled_play_context']['receiving_yards'] = 12
        for row, call, expected in cases:
            with self.subTest(event=row['event_type'], expected=expected):
                record = one_play_record(row)
                with self.assertRaises(football_assertions.FootballAssertionError) as raised:
                    slc_engine.validate_decision_outcomes(record, [call], seed=44)
                self.assert_full_evidence(raised.exception, record, row, call, 44, 'ILLEGAL_STATE')
                self.assertIn(expected, str(raised.exception))

    def test_fourth_down_incompletion_may_legally_cause_turnover_on_downs(self):
        row = play('pass_incomplete', 0, participants(passer='QB1', receiver='WR1', play_type='pass'))
        row['state_before']['down'] = 4
        row['outcome']['turnover'] = True
        row['outcome']['turnover_on_downs'] = True
        row['state_after'].update({
            'down': 1, 'yards_to_go': 10, 'yardline_100': 70,
            'offense_team': 'B', 'defense_team': 'A',
        })
        call = decision('pass_incomplete', intent='dropback', outcome_intent='dropback',
                        selected={'passer': 'QB1', 'receiver': 'WR1'})
        call['state']['down'] = 4
        result = slc_engine.validate_decision_outcomes(one_play_record(row), [call], seed=45)
        self.assertEqual(result, {'status': 'passed', 'plays_checked': 1})

    def test_incomplete_pass_cannot_claim_turnover_on_downs_before_fourth_down(self):
        row = play('pass_incomplete', 0, participants(passer='QB1', receiver='WR1', play_type='pass'))
        row['outcome'].update({'turnover': True, 'turnover_on_downs': True})
        call = decision('pass_incomplete', intent='dropback', outcome_intent='dropback',
                        selected={'passer': 'QB1', 'receiver': 'WR1'})
        record = one_play_record(row)
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=46)
        self.assert_full_evidence(raised.exception, record, row, call, 46, 'ILLEGAL_STATE')
        self.assertIn('turnover on downs', str(raised.exception))

    def test_scrimmage_play_turnover_on_downs_requires_possession_transfer(self):
        row = play('sack', -5, participants(passer='QB1', play_type='pass'))
        row['state_before']['down'] = 4
        row['outcome'].update({'turnover': True, 'turnover_on_downs': True})
        call = decision('sack', intent='dropback', outcome_intent='dropback', selected={'passer': 'QB1'})
        call['state']['down'] = 4
        record = one_play_record(row)
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=47)
        self.assert_full_evidence(raised.exception, record, row, call, 47, 'ILLEGAL_STATE')
        self.assertIn('transfer', str(raised.exception))

    def test_legal_fourth_down_failure_is_allowed_for_each_supported_scrimmage_result(self):
        cases = (
            ('run', participants(rusher='RB1', play_type='run'),
             decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'}), 0),
            ('pass_complete', participants(passer='QB1', receiver='WR1', play_type='pass'),
             decision('pass_complete', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'}), 0),
            ('pass_incomplete', participants(passer='QB1', receiver='WR1', play_type='pass'),
             decision('pass_incomplete', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'}), 0),
            ('sack', participants(passer='QB1', play_type='pass'),
             decision('sack', intent='dropback', outcome_intent='dropback', selected={'passer': 'QB1'}), -5),
        )
        for event, part, call, yards in cases:
            with self.subTest(event=event):
                row = play(event, yards, part)
                row['state_before']['down'] = 4
                row['outcome'].update({'turnover': True, 'turnover_on_downs': True})
                row['state_after'].update({'down': 1, 'offense_team': 'B', 'defense_team': 'A'})
                call['state']['down'] = 4
                self.assertEqual(
                    slc_engine.validate_decision_outcomes(one_play_record(row), [call], seed=48),
                    {'status': 'passed', 'plays_checked': 1},
                )

    def test_blocked_scrimmage_kick_may_resolve_the_selected_kick_action(self):
        for selected_event, realized_event in (
                ('punt', 'blocked_punt'), ('field_goal_attempt', 'blocked_field_goal')):
            with self.subTest(selected_event=selected_event):
                row = play(realized_event, 0, participants(play_type='punt' if selected_event == 'punt'
                                                           else 'field_goal'))
                call = decision(selected_event, intent='kick', outcome_intent='kick')
                self.assertEqual(
                    slc_engine.validate_decision_outcomes(one_play_record(row), [call], seed=49),
                    {'status': 'passed', 'plays_checked': 1},
                )

    def test_blocked_attempt_play_decisions_are_counted_and_kept_in_event_order(self):
        committed = play('run', 3, participants(rusher='RB1', play_type='run'))
        partial = play('pass_complete', 4, participants(passer='QB1', receiver='WR1', play_type='pass'))
        partial['sequence'] = 2
        record = one_play_record(committed)
        record['blocked_attempt'] = {'plays_before_block': [partial]}
        calls = [
            decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'}),
            decision('pass_complete', intent='dropback', outcome_intent='dropback',
                     selected={'passer': 'QB1', 'receiver': 'WR1'}),
        ]
        self.assertEqual(slc_engine.validate_decision_outcomes(record, calls, seed=50),
                         {'status': 'passed', 'plays_checked': 1})

        calls[1]['event'] = 'pass_incomplete'
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, calls, seed=51)
        self.assertIn('blocked-attempt decision event', str(raised.exception))

    def test_unresolved_blocked_attempt_keeps_its_unrepresented_decision(self):
        committed = play('run', 3, participants(rusher='RB1', play_type='run'))
        partial = play('pass_complete', 4, participants(passer='QB1', receiver='WR1', play_type='pass'))
        partial['sequence'] = 2
        blocked_decision = decision('punt', intent='kick', outcome_intent='kick')
        record = one_play_record(committed)
        record['blocked_attempt'] = {
            'blocker': 'blocked_kick_outcome_unresolved:punt:unclassified',
            'plays_before_block': [partial],
            'unrepresented_decisions': [blocked_decision],
        }
        calls = [
            decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'}),
            decision('pass_complete', intent='dropback', outcome_intent='dropback',
                     selected={'passer': 'QB1', 'receiver': 'WR1'}),
            blocked_decision,
        ]

        self.assertEqual(slc_engine.validate_decision_outcomes(record, calls, seed=52),
                         {'status': 'passed', 'plays_checked': 1})

        del record['blocked_attempt']['unrepresented_decisions']
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, calls, seed=53)
        self.assertIn('unresolved decisions', str(raised.exception))

    def test_interception_flag_without_possession_transfer_is_rejected(self):
        row = play('interception', 0, participants(passer='QB1', receiver='WR1', play_type='pass'),
                   turnover=True)
        row['state_after']['offense_team'] = 'A'
        row['state_after']['defense_team'] = 'B'
        call = decision('interception', intent='dropback', outcome_intent='dropback',
                        selected={'passer': 'QB1', 'receiver': 'WR1'})
        record = one_play_record(row)

        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=53)

        self.assert_full_evidence(raised.exception, record, row, call, 53, 'ILLEGAL_STATE')
        self.assertIn('transfer possession', str(raised.exception))

    def test_credited_receiver_must_match_the_pre_outcome_target_selection(self):
        cases = (
            (participants(passer='QB1', receiver='WR2', play_type='pass'),
             {'passer': 'QB1', 'receiver': 'WR1'}),
            (participants(passer='QB1', receiver='WR1', play_type='pass'),
             {'passer': 'QB1'}),
        )
        for part, selected in cases:
            with self.subTest(credited_receiver=part['receiver_id'], selected=selected):
                row = play('interception', 0, part, turnover=True)
                call = decision('interception', intent='dropback', outcome_intent='dropback',
                                selected=selected)
                record = one_play_record(row)

                with self.assertRaises(football_assertions.FootballAssertionError) as raised:
                    slc_engine.validate_decision_outcomes(record, [call], seed=54)

                failure = raised.exception
                self.assert_full_evidence(failure, record, row, call, 54, 'STAT_ACCOUNTING')
                self.assertIn('disagrees with credited participant', str(failure))

    def test_interception_and_fumble_return_touchdowns_are_explicitly_unsupported(self):
        cases = (
            ('interception', participants(passer='QB1', receiver='WR1', play_type='pass'),
             decision('interception', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'})),
            ('fumble_lost', participants(rusher='RB1', play_type='run'),
             decision('fumble_lost', intent='run', outcome_intent='run',
                      selected={'rusher': 'RB1'})),
        )
        for event, part, call in cases:
            with self.subTest(event=event):
                row = play(event, 0, part, turnover=True)
                row['outcome'].update(touchdown=True, scoring_team='B')
                record = one_play_record(row)
                with self.assertRaises(football_assertions.FootballAssertionError) as raised:
                    slc_engine.validate_decision_outcomes(record, [call], seed=55)

                failure = raised.exception
                self.assert_full_evidence(failure, record, row, call, 55, 'UNSUPPORTED_RULE')
                self.assertIn('outside the supported transition model',
                              failure.context['violated_assertion'])

    def test_completion_yardage_must_reconcile_and_spike_is_explicitly_unsupported(self):
        completed = play('pass_complete', 12,
                         participants(passer='QB1', receiver='WR1', play_type='pass'),
                         passing_yards=12, receiving_yards=11)
        call = decision('pass_complete', intent='dropback', outcome_intent='dropback',
                        selected={'passer': 'QB1', 'receiver': 'WR1'})
        record = one_play_record(completed)
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=45)
        self.assert_full_evidence(raised.exception, record, completed, call, 45, 'ILLEGAL_STATE')
        self.assertIn('must equal', str(raised.exception))

        spike = play('spike', 0, participants(passer='QB1', play_type='pass'))
        spike_call = decision('spike', intent='dropback', outcome_intent='dropback',
                              selected={'passer': 'QB1'})
        record = one_play_record(spike)
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [spike_call], seed=46)
        self.assert_full_evidence(raised.exception, record, spike, spike_call, 46, 'UNSUPPORTED_RULE')

        fumble = play('fumble', 0, participants(rusher='RB1', play_type='run'))
        fumble_call = decision('fumble', intent='run', outcome_intent='run', selected={'rusher': 'RB1'})
        record = one_play_record(fumble)
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [fumble_call], seed=52)
        self.assert_full_evidence(raised.exception, record, fumble, fumble_call, 52, 'UNSUPPORTED_RULE')

    def test_lateral_completion_is_explicitly_unsupported_until_attribution_is_modeled(self):
        part = participants(passer='QB1', receiver='WR1', play_type='pass')
        part['sampled_play_context'].update({
            'passing_yards': -20, 'receiving_yards': -13,
            'lateral_receiver_player_id': 'LATERAL1', 'lateral_receiving_yards': -4,
        })
        row = play('pass_complete', -20, part)
        call = decision('pass_complete', intent='dropback', outcome_intent='dropback',
                        selected={'passer': 'QB1', 'receiver': 'WR1'})
        record = one_play_record(row)

        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(record, [call], seed=56)

        self.assert_full_evidence(raised.exception, record, row, call, 56, 'UNSUPPORTED_RULE')
        self.assertIn('lateral source outcomes are unsupported', str(raised.exception))

    def test_touchdown_scorer_must_match_legal_carrier_and_safety_must_reach_own_end_zone(self):
        td = play('run', 50, participants(rusher='RB1', play_type='run'))
        td['state_before']['yardline_100'] = 50
        td['outcome']['touchdown'] = True
        td_record = one_play_record(td)
        td_record['drives'][0].update({
            'terminal': 'touchdown', 'offense_team': 'A', 'touchdown_scored_by': 'B',
            'points_scored_on_drive': {'team': 'B', 'points': 6},
        })
        td_call = decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'})
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(td_record, [td_call], seed=48)
        self.assert_full_evidence(raised.exception, td_record, td, td_call, 48, 'ILLEGAL_STATE')
        self.assertIn('scoring offense', str(raised.exception))

        for event, part, call in (
            ('run', participants(rusher='RB1', play_type='run'),
             decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'})),
            ('pass_complete', participants(passer='QB1', receiver='WR1', play_type='pass'),
             decision('pass_complete', intent='dropback', outcome_intent='dropback',
                      selected={'passer': 'QB1', 'receiver': 'WR1'})),
        ):
            overrun = play(event, 51, part)
            overrun['outcome']['touchdown'] = True
            with self.subTest(touchdown_event=event):
                record = one_play_record(overrun)
                with self.assertRaises(football_assertions.FootballAssertionError) as raised:
                    slc_engine.validate_decision_outcomes(record, [call], seed=50)
                self.assert_full_evidence(raised.exception, record, overrun, call, 50, 'ILLEGAL_STATE')
                self.assertIn('without exceeding credited yards', str(raised.exception))

        safety = play('run', -2, participants(rusher='RB1', play_type='run'))
        safety['state_before']['yardline_100'] = 95
        safety['outcome']['safety'] = True
        safety_record = one_play_record(safety)
        safety_record['drives'][0].update({
            'terminal': 'safety', 'offense_team': 'A', 'points_scored_on_drive': {'team': 'B', 'points': 2},
        })
        safety_call = decision('run', intent='run', outcome_intent='run', selected={'rusher': 'RB1'})
        safety_call['state']['yardline_100'] = 95
        safety_play = safety_record['drives'][0]['plays'][0]
        with self.assertRaises(football_assertions.FootballAssertionError) as raised:
            slc_engine.validate_decision_outcomes(safety_record, [safety_call], seed=49)
        self.assert_full_evidence(raised.exception, safety_record, safety_play, safety_call, 49, 'ILLEGAL_STATE')
        self.assertIn('own end zone', str(raised.exception))

        sack = play('sack', -5, participants(passer='QB1', play_type='pass'))
        sack['state_before'].update({'yardline_100': 95, 'defense_team': 'B'})
        sack['outcome']['safety'] = True
        sack_record = one_play_record(sack)
        sack_record['drives'][0].update({
            'terminal': 'safety', 'offense_team': 'A', 'points_scored_on_drive': {'team': 'B', 'points': 2},
        })
        sack_call = decision('sack', intent='dropback', outcome_intent='dropback',
                             selected={'passer': 'QB1'})
        sack_call['state']['yardline_100'] = 95
        self.assertEqual(slc_engine.validate_decision_outcomes(sack_record, [sack_call], seed=51)['status'], 'passed')

    def test_scramble_fumble_is_a_rush_and_a_lost_turnover(self):
        row = play('fumble_lost', 2, participants(rusher='QB1', play_type='run'), turnover=True)
        call = decision('fumble_lost', intent='dropback', outcome_intent='run', action='scramble',
                        selected={'passer': 'QB1', 'rusher': 'QB1'})
        slc_engine.validate_decision_outcomes(one_play_record(row), [call], seed=47)

        stats = game_stats.compute([{'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                                     'end_quarter': 1, 'end_clock': 890, 'terminal': 'turnover',
                                     'field_goal_made': None, 'plays': [row]}], {'A': 0, 'B': 0})
        team = stats['team']['A']
        qb = next(player for player in stats['player'] if player['player_id'] == 'QB1')
        self.assertEqual((team['rush_att'], team['rush_yds'], team['turnovers'], team['fumbles_lost']),
                         (1, 2, 1, 1))
        self.assertEqual((qb['rushing']['att'], qb['rushing']['yds'], qb['miscellaneous']['fumbles_lost']),
                         (1, 2, 1))


if __name__ == '__main__':
    unittest.main()
