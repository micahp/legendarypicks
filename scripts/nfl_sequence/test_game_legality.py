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
        self.assertEqual(gl.check(self.record), ['play domain', 'play clock and score', 'play chain and downs',
                                                 'drive headers', 'scoring side', 'drive points',
                                                 'possession and kickoffs', 'quarter boundaries', 'timeouts',
                                                 'final score'])

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
        self.assertRefused('but B scored')  # the touchdown's kick belongs to the scoring team, so the reversed kick is refused

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


def _play(before, after, runoff=10, penalty=False):
    """A synthetic play from (quarter, clock) to (quarter, clock), with scores and the other fields the checks read."""
    state = lambda q, c: {'quarter': q, 'clock_seconds': c, 'home_score': 0, 'away_score': 0}  # noqa: E731
    return {'sequence': 1, 'state_before': state(*before), 'state_after': state(*after),
            'outcome': {'clock_runoff_seconds': runoff, 'penalty': penalty}}


class PlayClock(unittest.TestCase):
    drive = {'index': 3}

    def test_the_clock_falls_by_the_runoff_inside_a_quarter(self):
        gl._play_clock(self.drive, _play((1, 500), (1, 490), runoff=10))

    def test_the_clock_stops_at_zero_when_the_runoff_is_longer(self):
        gl._play_clock(self.drive, _play((1, 4), (1, 0), runoff=9))

    def test_the_clock_cannot_rise_inside_a_quarter(self):
        with self.assertRaisesRegex(FootballAssertionError, 'leaves the clock at 490, not 505'):
            gl._play_clock(self.drive, _play((1, 500), (1, 505), runoff=10))

    def test_a_quarter_cannot_end_with_time_left(self):
        with self.assertRaisesRegex(FootballAssertionError, '260 seconds left'):
            gl._play_clock(self.drive, _play((1, 300), (2, 900), runoff=40))

    def test_a_new_quarter_opens_at_its_full_length(self):
        with self.assertRaisesRegex(FootballAssertionError, 'opens at 800, not 900'):
            gl._play_clock(self.drive, _play((1, 30), (2, 800), runoff=40))
        gl._play_clock(self.drive, _play((1, 30), (2, 900), runoff=40))

    def test_overtime_opens_at_ten_minutes(self):
        gl._play_clock(self.drive, _play((4, 30), (5, 600), runoff=40))
        with self.assertRaisesRegex(FootballAssertionError, 'opens at 900, not 600'):
            gl._play_clock(self.drive, _play((4, 30), (5, 900), runoff=40))

    def test_a_penalty_is_not_clock_checked(self):
        gl._play_clock(self.drive, _play((1, 500), (1, 400), runoff=10, penalty=True))

    def test_a_play_without_a_runoff_cannot_be_checked(self):
        with self.assertRaisesRegex(FootballAssertionError, 'carries no clock runoff'):
            gl._play_clock(self.drive, _play((1, 500), (1, 490), runoff=None))


class PlayScore(unittest.TestCase):
    def test_a_score_cannot_fall_within_a_play(self):
        play = _play((1, 500), (1, 490))
        play['state_before']['home_score'], play['state_after']['home_score'] = 7, 3
        with self.assertRaisesRegex(FootballAssertionError, 'home_score fell from 7 to 3'):
            gl._play_scores({'index': 3}, play)


class ScoringSide(unittest.TestCase):
    def drive(self, terminal, team, points=7, offense='A'):
        scored = {'team': team, 'points': points} if team else None
        return {'index': 4, 'offense_team': offense, 'terminal': terminal, 'points_scored_on_drive': scored}

    def test_the_offense_scores_a_touchdown_or_a_field_goal(self):
        gl._scoring_team(self.drive('touchdown', 'A'))
        gl._scoring_team(self.drive('field_goal_attempt', 'A', points=3))

    def test_the_defense_scores_on_a_turnover_return_a_punt_return_or_a_safety(self):
        gl._scoring_team(self.drive('turnover', 'B'))
        gl._scoring_team(self.drive('punt', 'B'))
        gl._scoring_team(self.drive('safety', 'B', points=2))

    def test_the_offense_cannot_score_on_a_turnover(self):
        with self.assertRaisesRegex(FootballAssertionError, 'only the defense, team B, can score'):
            gl._scoring_team(self.drive('turnover', 'A'))

    def test_the_defense_cannot_score_a_touchdown_on_offense(self):
        with self.assertRaisesRegex(FootballAssertionError, 'only the offense, team A, can score'):
            gl._scoring_team(self.drive('touchdown', 'B'))

    def test_a_drive_that_is_not_a_scoring_terminal_cannot_score(self):
        with self.assertRaisesRegex(FootballAssertionError, 'scores 3 for A on a turnover_on_downs drive'):
            gl._scoring_team(self.drive('turnover_on_downs', 'A', points=3))

    def test_a_defensive_score_on_a_turnover_is_followed_by_a_kickoff(self):
        self.assertTrue(gl._expects_kickoff(self.drive('turnover', 'B')))
        self.assertTrue(gl._expects_kickoff(self.drive('punt', 'B')))
        self.assertFalse(gl._expects_kickoff(self.drive('turnover', None)))
        self.assertFalse(gl._expects_kickoff(self.drive('punt', None)))


class Domain(unittest.TestCase):
    def test_the_offense_and_defense_must_be_the_two_teams(self):
        record = json.loads(FIXTURE.read_text(encoding='utf-8'))
        _drive(record, 1)['plays'][0]['state_before']['defense_team'] = 'A'
        with self.assertRaisesRegex(FootballAssertionError, 'are not the two teams'):
            gl.check(record)


if __name__ == '__main__':
    unittest.main()
