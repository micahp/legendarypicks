"""Systematic producer/validator accounting invariants for every legal field spot.

Pure deterministic tests: no NFL database, network, random samples, or model fit.
The assertions do not calibrate any rate. They reject impossible emitted states.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reducer
import game_legality


def state(yardline=50):
    return {'offense': 'DEN', 'defense': 'CAR', 'down': 4,
            'togo': min(8, yardline), 'yl': yardline}


def next_snap(role, spot, *, distance=1, down=1, kick='punt'):
    # A zero source-relative delta lets us enumerate all 99 projected spots.
    # Reversing the field's perspective is explicit for the receiving side.
    before = state(100 - spot if role == 'receiving_team' else spot)
    source = {
        'classification_status': 'classified_next_snap',
        'kick_type': kick,
        'possession_after_role': role,
        'next_snap_yards_from_los': 0,
        'next_snap_yardline_100': 1,
        'next_snap_down': down,
        'next_snap_ydstogo': distance,
    }
    return before, source


class NewPossessionAccounting(unittest.TestCase):
    def test_all_legal_spots_on_punts_and_turnovers(self):
        for spot in range(1, 100):
            for event in ('punt', 'interception', 'fumble_lost'):
                with self.subTest(spot=spot, event=event):
                    after, terminal, flags = reducer.apply_play(state(), event, None, spot=spot)
                    self.assertEqual((after['offense'], after['defense']), ('CAR', 'DEN'))
                    self.assertEqual((after['yl'], after['down'], after['togo']),
                                     (spot, 1, min(10, spot)))
                    reducer._validate_transition_output(state(), after, event)

    def test_all_legal_spots_on_turnover_on_downs(self):
        for new_spot in range(1, 100):
            # On a 4th down, an unsuccessful gain gives the other side possession.
            # A loss on 4th-and-1 is always short of the line to gain.
            before = state(100 - new_spot)
            before['togo'] = 1
            after, terminal, flags = reducer.apply_play(before, 'run', -1)
            # The gain shifts the spot by one before the field is flipped.
            flipped_spot = 100 - (before['yl'] + 1)
            if flipped_spot < 1:  # own end zone: safety, not a possession handover
                self.assertEqual(terminal, 'safety')
                continue
            self.assertEqual(terminal, 'turnover_on_downs')
            self.assertEqual((after['down'], after['yl'], after['togo']),
                             (1, flipped_spot, min(10, flipped_spot)))

    def test_receiving_team_blocked_kick_all_99_spots_and_source_distances(self):
        for spot in range(1, 100):
            for source_togo in (1, 2, 3, 5, 10):
                for kick, event in (('punt', 'blocked_punt'),
                                    ('field_goal', 'blocked_field_goal')):
                    with self.subTest(spot=spot, original_togo=source_togo, event=event):
                        before, original = next_snap('receiving_team', spot,
                                                     distance=source_togo, kick=kick)
                        projected = reducer.project_blocked_kick_next_snap(original, before)
                        self.assertEqual(original['next_snap_ydstogo'], source_togo)
                        after, terminal, flags = reducer.apply_blocked_kick(before, event, projected)
                        self.assertEqual((after['offense'], after['defense']), ('CAR', 'DEN'))
                        self.assertEqual((after['down'], after['togo'], after['yl']),
                                         (1, min(10, spot), spot))
                        self.assertTrue(flags['turnover'])

    def test_same_team_new_first_down_all_99_spots(self):
        for spot in range(1, 100):
            before, original = next_snap('kicking_team', spot, distance=1)
            projected = reducer.project_blocked_kick_next_snap(original, before)
            after, terminal, flags = reducer.apply_blocked_kick(
                before, 'blocked_punt', projected)
            self.assertEqual((after['offense'], after['defense']), ('DEN', 'CAR'))
            self.assertEqual((after['down'], after['togo'], after['yl']),
                             (1, min(10, spot), spot))
            self.assertIsNone(terminal)
            self.assertTrue(flags['first_down'])

    def test_same_team_later_down_retains_observed_distance(self):
        for spot in range(4, 100):
            before, original = next_snap('kicking_team', spot, distance=4, down=2)
            projected = reducer.project_blocked_kick_next_snap(original, before)
            after, terminal, flags = reducer.apply_blocked_kick(before, 'blocked_punt', projected)
            self.assertEqual((after['down'], after['togo'], after['yl']), (2, 4, spot))

    def test_normal_new_first_down_does_not_keep_old_goal_distance(self):
        for spot in range(2, 98):
            before = {'offense': 'DEN', 'defense': 'CAR',
                      'down': 2, 'togo': 1, 'yl': spot + 1}
            after, terminal, _ = reducer.apply_play(before, 'run', 1)
            self.assertEqual((after['down'], after['togo'], after['yl']),
                             (1, min(10, spot), spot))


class CorruptionMustFailAtProducer(unittest.TestCase):
    def test_unprojected_receiving_kick_bad_distance_is_refused(self):
        before = state(73)
        bad = {'kick_type': 'punt', 'classification_status': 'classified_next_snap',
               'possession_after_role': 'receiving_team', 'next_snap_yardline_100': 3,
               'next_snap_down': 1, 'next_snap_ydstogo': 1}
        with self.assertRaisesRegex(ValueError, 'possession change must be first-and-10'):
            reducer.apply_blocked_kick(before, 'blocked_punt', bad)

    def test_receiving_second_down_and_wrong_team_are_refused(self):
        before = state(73)
        for bad in (
            {'offense': 'CAR', 'defense': 'DEN', 'down': 2, 'togo': 3, 'yl': 3},
            {'offense': 'OTHER', 'defense': 'DEN', 'down': 1, 'togo': 3, 'yl': 3},
            {'offense': 'CAR', 'defense': 'OTHER', 'down': 1, 'togo': 3, 'yl': 3},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reducer._validate_transition_output(before, bad, 'blocked_punt')

    def test_same_team_first_down_bad_distance_is_refused(self):
        before = state(73)
        bad = {'offense': 'DEN', 'defense': 'CAR', 'down': 1, 'togo': 1, 'yl': 3}
        with self.assertRaisesRegex(ValueError, 'new first down must be'):
            reducer._validate_transition_output(before, bad, 'run')

    def test_validator_remains_independent_and_rejects_old_seed_300786_state(self):
        before = {'offense_team': 'B', 'down': 4,
                  'yards_to_go': 8, 'yardline_100': 73}
        bad = {'offense_team': 'A', 'down': 1,
               'yards_to_go': 1, 'yardline_100': 3}
        play = {'sequence': 102, 'state_before': before, 'state_after': bad,
                'outcome': {'blocked_kick': {'blocked': True}, 'turnover': True}}
        with self.assertRaisesRegex(game_legality.FootballAssertionError,
                                    'blocked kick hands over a first down'):
            game_legality._down_and_distance({'index': 12}, play)
        good = dict(bad, yards_to_go=3)
        game_legality._down_and_distance({'index': 12},
                                         dict(play, state_after=good))


if __name__ == '__main__':
    unittest.main()
