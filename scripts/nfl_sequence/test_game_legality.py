"""The game validator refuses impossible football states: each corruption of a legal game must be rejected by name."""
import copy
import gzip
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

    def test_a_punt_that_expires_the_clock_with_the_score_untied_ends_the_game(self):
        self.record['drives'][-1]['terminal'] = 'punt'  # the regulation ending, with its clock at 0:00 and the score untied
        self.assertEqual(gl.check(self.record)[0], 'play domain')

    def test_a_punt_with_time_left_does_not_end_the_game(self):
        drive = {'terminal': 'punt', 'end_quarter': 4, 'end_clock': 12, 'points_scored_on_drive': None,
                 'plays': [{'state_after': {'home_score': 20, 'away_score': 26}}]}
        self.assertFalse(gl._ends_the_game({'points': {'A': 20, 'B': 26}}, drive, None))


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


class LateScore(unittest.TestCase):
    """A touchdown that leaves the clock at 0:01 ends the game only when the kickoff that follows runs the clock out."""

    def drive(self, end_clock=1):
        final = {'home_score': 7, 'away_score': 3}
        return {'index': 9, 'terminal': 'touchdown', 'end_quarter': 4, 'end_clock': end_clock,
                'points_scored_on_drive': {'team': 'A', 'points': 7}, 'plays': [{'state_after': final}]}

    record = {'points': {'A': 7, 'B': 3}}

    def kick(self, expired=True, quarter=4, kind='post_score'):
        return {'kind': kind, 'quarter': quarter, 'clock_expired_during_kickoff': expired}

    def test_a_kickoff_that_runs_the_clock_out_ends_the_game(self):
        self.assertTrue(gl._ends_the_game(self.record, self.drive(), self.kick()))

    def test_a_made_field_goal_at_two_seconds_ends_the_game_on_its_kickoff(self):
        self.assertTrue(gl._ends_the_game(self.record, self.drive(), self.kick(kind='post_field_goal')))

    def test_a_kickoff_that_leaves_time_does_not_end_the_game(self):
        self.assertFalse(gl._ends_the_game(self.record, self.drive(), self.kick(expired=False)))

    def test_no_kickoff_at_one_second_does_not_end_the_game(self):
        self.assertFalse(gl._ends_the_game(self.record, self.drive(), None))

    def test_a_zero_clock_ends_the_game_without_a_kickoff(self):
        self.assertTrue(gl._ends_the_game(self.record, self.drive(end_clock=0), None))


class TyingScoreAtRegulationExpiry(unittest.TestCase):
    """A saved real simulation ties on a touchdown and try as the fourth quarter expires."""

    def setUp(self):
        path = Path(__file__).resolve().parent / 'legality_fixtures' / '2026_09_ARI_SEA_seed18.failure.json.gz'
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            self.record = json.load(handle)['record']

    def test_saved_complete_game_passes_full_validator(self):
        import game_state
        self.assertEqual(len(gl.check(self.record)), 10)
        self.assertGreaterEqual(len(game_state.validate_game(self.record)), 10)

    def test_overtime_cannot_follow_an_untied_regulation_score(self):
        last_regulation = _drive(self.record, 27)
        last_regulation['plays'][-1]['state_after']['away_score'] -= 1
        with self.assertRaisesRegex(FootballAssertionError, 'ends regulation untied'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))

    def test_overtime_cannot_start_before_the_regulation_clock_expires(self):
        last_regulation = _drive(self.record, 27)
        last_regulation['end_clock'] = 1
        last_regulation['plays'][-1]['state_after']['clock_seconds'] = 1
        with self.assertRaisesRegex(FootballAssertionError, 'does not end regulation'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))

    def test_overtime_timeouts_are_checked_after_a_tying_score(self):
        _drive(self.record, 28)['plays'][0]['state_before']['home_timeouts'] = 3
        with self.assertRaisesRegex(FootballAssertionError, 'starts overtime with home_timeouts'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))


class MissedFieldGoalAtHalftime(unittest.TestCase):
    """A saved game misses a field goal as the first half expires, then starts the second half."""

    def setUp(self):
        path = Path(__file__).resolve().parent / 'legality_fixtures' / '2026_09_ARI_SEA_dirichlet_seed31.failure.json.gz'
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            self.record = json.load(handle)['record']

    def test_saved_complete_game_passes_full_validator(self):
        import game_state
        self.assertEqual(len(gl.check(self.record)), 10)
        self.assertGreaterEqual(len(game_state.validate_game(self.record)), 10)

    def test_second_half_kickoff_cannot_follow_a_miss_before_the_half_ends(self):
        _drive(self.record, 11)['end_clock'] = 1
        with self.assertRaisesRegex(FootballAssertionError, 'no kickoff can follow'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))

    def test_second_half_kickoff_must_start_at_full_period_clock(self):
        _kick(self.record, 11)['clock_before'] = 899
        with self.assertRaisesRegex(FootballAssertionError, 'starts at 899, not 900'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))

    def test_second_half_timeouts_are_reset(self):
        _drive(self.record, 12)['plays'][0]['state_before']['home_timeouts'] = 2
        with self.assertRaisesRegex(FootballAssertionError, 'starts the second half with home_timeouts'):
            gl._possession_and_clock(self.record, self.record['drives'], gl._kicks_after(self.record))


class OvertimeReturnTouchdown(unittest.TestCase):
    """Article 5(a): a return touchdown in overtime is a touchdown terminal scored by the defense, and only when the
    record names that drive as the return touchdown."""

    drive = {'index': 12, 'offense_team': 'A', 'terminal': 'touchdown', 'points_scored_on_drive': {'team': 'B', 'points': 6}}

    def test_the_defense_scores_on_a_named_return_touchdown(self):
        gl._scoring_team(self.drive, frozenset({12}))

    def test_the_defense_cannot_score_a_touchdown_the_record_does_not_name(self):
        with self.assertRaisesRegex(FootballAssertionError, 'only the offense, team A, can score'):
            gl._scoring_team(self.drive, frozenset({11}))
        with self.assertRaisesRegex(FootballAssertionError, 'only the offense, team A, can score'):
            gl._scoring_team(self.drive)


class BlockedKickTouchdown(unittest.TestCase):
    """A blocked kick returned for a touchdown scores for the side its classified outcome names, either side."""

    def drive(self, scorer, kick='blocked_field_goal'):
        last = {'event_type': kick, 'outcome': {'touchdown': True, 'scoring_team': scorer}}
        return {'index': 12, 'offense_team': 'A', 'terminal': 'touchdown', 'plays': [last],
                'points_scored_on_drive': {'team': scorer, 'points': 7}}

    def test_the_defense_scores_on_a_blocked_kick_it_returns(self):
        gl._scoring_team(self.drive('B'))

    def test_the_kicking_team_scores_on_a_blocked_kick_it_recovers_and_returns(self):
        gl._scoring_team(self.drive('A', kick='blocked_punt'))

    def test_the_scorer_must_be_the_side_the_kick_was_classified_for(self):
        drive = self.drive('B')
        drive['points_scored_on_drive']['team'] = 'A'
        with self.assertRaisesRegex(FootballAssertionError, 'classified for B'):
            gl._scoring_team(drive)


class FirstHalfExpiry(unittest.TestCase):
    """A post-score kickoff that runs the first half out is followed by the second-half kickoff, not by a quarter change."""

    def kick(self, kind='post_field_goal', after_drive=12, quarter=2, expired=True, **extra):
        return dict({'after_drive': after_drive, 'kind': kind, 'quarter': quarter, 'kicking_team': 'A',
                     'receiving_team': 'B', 'clock_before': 5, 'clock_after': 0, 'clock_clamped_to_zero': False,
                     'clock_expired_during_kickoff': expired}, **extra)

    def record(self, *kicks):
        return {'kickoffs': list(kicks)}

    def test_the_second_half_kickoff_is_paired_with_the_first_half_expiry(self):
        kicks = gl._kicks_after(self.record(self.kick(), self.kick(kind='half_start', quarter=3, clock_before=900,
                                                                   clock_after=895, expired=False)))
        self.assertEqual(kicks[12]['half_start']['kind'], 'half_start')

    def test_a_safety_free_kick_that_expires_the_half_is_followed_by_the_second_half_kickoff(self):
        kicks = gl._kicks_after(self.record(self.kick(kind='safety_free_kick'),
                                            self.kick(kind='half_start', quarter=3, clock_before=900, clock_after=895,
                                                      expired=False)))
        self.assertEqual(kicks[12]['half_start']['kind'], 'half_start')

    def test_two_kickoffs_without_a_first_half_expiry_are_still_refused(self):
        with self.assertRaisesRegex(FootballAssertionError, 'two kickoffs follow drive 12'):
            gl._kicks_after(self.record(self.kick(expired=False), self.kick(kind='half_start', quarter=3)))

    def test_a_first_half_expiry_without_a_second_half_kickoff_is_not_paired(self):
        self.assertNotIn('half_start', gl._kicks_after(self.record(self.kick()))[12])


class BlockedKickIsLive(unittest.TestCase):
    """A blocked field goal sets field_goal_attempt but does not end the drive: the ball stays live."""

    def test_a_blocked_field_goal_does_not_end_the_drive(self):
        self.assertFalse(gl._ends_drive_flag({'field_goal_attempt': True, 'field_goal_result': 'blocked'}, 'field_goal_attempt'))

    def test_a_made_or_missed_field_goal_still_ends_the_drive(self):
        self.assertTrue(gl._ends_drive_flag({'field_goal_attempt': True, 'field_goal_result': 'made'}, 'field_goal_attempt'))
        self.assertTrue(gl._ends_drive_flag({'field_goal_attempt': True, 'field_goal_result': 'missed'}, 'field_goal_attempt'))

    def test_a_blocked_kick_touchdown_still_ends_the_drive_through_its_flag(self):
        self.assertTrue(gl._ends_drive_flag({'touchdown': True, 'field_goal_result': 'blocked'}, 'touchdown'))

    def blocked_play(self, after_team, down=1, togo=10, yardline=63, penalty=False):
        """A blocked field goal from A's 29: `after_team` takes the ball at the spot after the block."""
        before = {'down': 4, 'yards_to_go': 6, 'yardline_100': 29, 'offense_team': 'A'}
        after = {'down': down, 'yards_to_go': togo, 'yardline_100': yardline, 'offense_team': after_team}
        outcome = {'field_goal_attempt': True, 'field_goal_result': 'blocked', 'yards_gained': None}
        if penalty:
            outcome['penalty'] = True
        return {'state_before': before, 'state_after': after, 'outcome': outcome, 'sequence': 1}

    def test_a_blocked_kick_that_changes_hands_hands_over_a_first_down(self):
        gl._down_and_distance({'index': 4}, self.blocked_play('B'))

    def test_a_blocked_kick_handover_with_impossible_distance_is_refused(self):
        with self.assertRaises(gl.FootballAssertionError):
            gl._down_and_distance({'index': 4}, self.blocked_play('B', togo=99))

    def test_a_kicking_team_recovery_keeps_its_observed_next_snap(self):
        gl._down_and_distance({'index': 4}, self.blocked_play('A', down=2, togo=7, yardline=36))

    def test_a_kicking_team_recovery_is_still_checked_for_the_state_domain(self):
        play = self.blocked_play('A', down=5, togo=7, yardline=36)
        for state in (play['state_before'], play['state_after']):
            state.update({'quarter': 1, 'clock_seconds': 500, 'home_score': 0, 'away_score': 0,
                          'home_timeouts': 3, 'away_timeouts': 3, 'defense_team': 'B' if state['offense_team'] == 'A' else 'A'})
        with self.assertRaises(gl.FootballAssertionError):
            gl._state_domain({'index': 4}, play)

    def test_a_penalty_on_a_blocked_kick_is_exempt_from_the_first_down_rule(self):
        gl._down_and_distance({'index': 4}, self.blocked_play('B', down=1, togo=5, yardline=44, penalty=True))

    def test_a_final_blocked_kick_is_checked_through_the_play_chain(self):
        with self.assertRaises(gl.FootballAssertionError):
            gl._play_chain({'index': 4}, [self.blocked_play('B', togo=99)])


class MissedKickAtZero(unittest.TestCase):
    """A missed field goal that expires the fourth quarter with the score untied ends the game."""

    def test_a_missed_field_goal_at_zero_untied_ends_the_game(self):
        record = {'points': {'A': 30, 'B': 27}}
        drive = {'terminal': 'field_goal_attempt', 'end_quarter': 4, 'end_clock': 0, 'points_scored_on_drive': None,
                 'plays': [{'state_after': {'home_score': 30, 'away_score': 27}}]}
        self.assertTrue(gl._ends_the_game(record, drive, None))


class HalftimeSkip(unittest.TestCase):
    """A score whose clock expires in Q2 takes no post-score kick, whichever team and whichever kind of score."""

    def drive(self, terminal, end_quarter=2, end_clock=0, points=True):
        return {'terminal': terminal, 'end_quarter': end_quarter, 'end_clock': end_clock,
                'points_scored_on_drive': {'team': 'A', 'points': 7} if points else None}

    def test_a_touchdown_field_goal_or_safety_ending_the_first_half_skips_the_kick(self):
        for terminal in ('touchdown', 'field_goal_attempt', 'safety'):
            self.assertTrue(gl._skips_post_score_kick(self.drive(terminal)), terminal)

    def test_a_score_that_leaves_time_or_is_not_scored_cannot_skip_the_kick(self):
        self.assertFalse(gl._skips_post_score_kick(self.drive('touchdown', end_clock=12)))
        self.assertFalse(gl._skips_post_score_kick(self.drive('touchdown', end_quarter=3)))
        self.assertFalse(gl._skips_post_score_kick(self.drive('turnover', points=False)))


class Domain(unittest.TestCase):
    def test_the_offense_and_defense_must_be_the_two_teams(self):
        record = json.loads(FIXTURE.read_text(encoding='utf-8'))
        _drive(record, 1)['plays'][0]['state_before']['defense_team'] = 'A'
        with self.assertRaisesRegex(FootballAssertionError, 'are not the two teams'):
            gl.check(record)


if __name__ == '__main__':
    unittest.main()
