"""Hard SLC checks for QB scramble, sack, and pass-result semantics."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_stats  # noqa: E402
import slc_engine  # noqa: E402


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
    return {
        'sequence': 1,
        'event_type': event,
        'state_before': {'yardline_100': 50, 'offense_team': 'A'},
        'state_after': {'yardline_100': 50, 'offense_team': 'A'},
        'participants': part,
        'outcome': {'yards_gained': yards, 'touchdown': False, 'turnover': turnover, 'punt': False},
    }


def decision(event, *, intent, outcome_intent, action=None, selected=None):
    return {
        'event': event, 'intent': intent, 'outcome_intent': outcome_intent,
        'qb_action': action, 'participants': selected or {}, 'artifact_sha256': 'a' * 64,
    }


def one_play_record(play_row):
    return {'drives': [{'index': 1, 'offense_team': 'A', 'plays': [play_row]}]}


class QBPlayTypeInvariants(unittest.TestCase):
    def test_scramble_decision_must_be_a_rostered_qb_rush_without_a_target(self):
        row = play('run', 6, participants(rusher='QB1', play_type='run'))
        record = one_play_record(row)
        valid = decision('run', intent='dropback', outcome_intent='run', action='scramble',
                         selected={'passer': 'QB1', 'rusher': 'QB1'})
        result = slc_engine.validate_decision_outcomes(
            record, [valid], seed=17,
            snapshot={'snapshot_sha256': 'b' * 64, 'schedule': {'game_id': '2025_01_AAA_BBB'}})
        self.assertEqual(result, {'status': 'passed', 'plays_checked': 1})

    def test_mutated_scramble_to_pass_fails_as_illegal_state_with_seed_context(self):
        row = play('pass_complete', 6, participants(passer='QB1', receiver='WR1', play_type='pass'))
        record = one_play_record(row)
        invalid = decision('pass_complete', intent='dropback', outcome_intent='run', action='scramble',
                           selected={'passer': 'QB1', 'rusher': 'QB1'})
        with self.assertRaisesRegex(AssertionError, r'ILLEGAL_STATE:.*game_id.*2025_01_AAA_BBB.*seed.*17'):
            slc_engine.validate_decision_outcomes(
                record, [invalid], seed=17,
                snapshot={'snapshot_sha256': 'b' * 64, 'schedule': {'game_id': '2025_01_AAA_BBB'}})

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


if __name__ == '__main__':
    unittest.main()
