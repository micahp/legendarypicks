"""The game validator refuses impossible football states: each corruption of a legal game must be rejected by name."""
import copy
import json
import unittest
from pathlib import Path

import game_legality as gl
from football_assertions import FootballAssertionError

FIXTURE = Path(__file__).resolve().parent / 'legality_fixtures' / 'full_game_seed7.json'


def _drive(record, index):
    return next(d for d in record['drives'] if d['index'] == index)


def _kick(record, after_drive):
    return next(k for k in record['kickoffs'] if k['after_drive'] == after_drive)


class LegalGame(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_the_seed_seven_game_passes_every_check(self):
        self.assertEqual(gl.check(self.record), ['play domain', 'play chain and downs', 'drive headers',
                                                 'drive points', 'possession and kickoffs', 'quarter boundaries',
                                                 'timeouts', 'final score'])

    def test_the_fixture_is_a_full_game_with_halftime_and_both_quarter_changes(self):
        self.assertTrue(self.record['complete_regulation'])
        self.assertEqual(sorted({b['kind'] for b in self.record['boundaries']}),
                         ['change_of_ends_mid_drive', 'halftime'])


class Corruption(unittest.TestCase):
    """Each test changes one fact of the legal game and expects an ILLEGAL_STATE refusal that names it."""

    def setUp(self):
        self.record = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def assertRefused(self, phrase):
        with self.assertRaises(FootballAssertionError) as raised:
            gl.check(self.record)
        self.assertEqual(raised.exception.failure_class, 'ILLEGAL_STATE')
        self.assertIn(phrase, str(raised.exception))

    def test_next_down_becomes_five(self):
        _drive(self.record, 1)['plays'][1]['state_after']['down'] = 5
        self.assertRefused('became down 5')  # a loss of a yard cannot reach down 5

    def test_ball_moves_to_the_wrong_yard_line(self):
        _drive(self.record, 1)['plays'][1]['state_after']['yardline_100'] += 7
        self.assertRefused('moved the ball')

    def test_distance_becomes_seventy_seven_yards(self):
        _drive(self.record, 1)['plays'][1]['state_after']['yards_to_go'] = 77
        self.assertRefused('to go from')

    def test_points_appear_on_a_drive_that_did_not_score(self):
        # the last play of drive 1 adds 99 to team A, and every later state carries it, so only the drive can refuse it
        marked = False
        for drive in self.record['drives']:
            for play in drive['plays']:
                if marked:
                    play['state_before']['home_score'] += 99
                    play['state_after']['home_score'] += 99
                elif play is _drive(self.record, 1)['plays'][-1]:
                    play['state_after']['home_score'] += 99
                    marked = True
        self.assertRefused('but the drive scored 3')  # drive 1 is a made field goal, worth 3

    def test_both_teams_keep_four_timeouts_through_regulation(self):
        for drive in self.record['drives']:
            for play in drive['plays']:
                for tag in ('state_before', 'state_after'):
                    play[tag]['home_timeouts'] = 4
                    play[tag]['away_timeouts'] = 4
        self.assertRefused('is outside 0..3')

    def test_timeouts_refill_in_the_middle_of_a_half(self):
        drive = _drive(self.record, 2)
        drive['plays'][1]['state_before']['home_timeouts'] = 1
        drive['plays'][1]['state_after']['home_timeouts'] = 3
        drive['plays'][2]['state_before']['home_timeouts'] = 3
        self.assertRefused('home_timeouts')

    def test_the_kickoff_goes_to_the_team_that_kicked(self):
        kick = _kick(self.record, 2)
        kick['receiving_team'], kick['kicking_team'] = kick['kicking_team'], kick['receiving_team']
        self.assertRefused('but the kickoff went to')

    def test_the_opening_kickoff_goes_to_the_wrong_team(self):
        kick = _kick(self.record, 0)
        kick['receiving_team'], kick['kicking_team'] = kick['kicking_team'], kick['receiving_team']
        self.assertRefused('opening kickoff receiver')

    def test_a_drive_with_no_plays_cannot_score(self):
        _drive(self.record, 5)['plays'] = []
        self.assertRefused('has no plays')

    def test_the_game_ends_on_a_punt_before_the_clock_expires(self):
        last = self.record['drives'][-1]
        last['terminal'] = 'punt'
        self.assertRefused('does not end the game')


if __name__ == '__main__':
    unittest.main()
