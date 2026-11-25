import sys
import random
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autonomous_game  # noqa: E402
import ceg_contract  # noqa: E402
import event_expansion_rules  # noqa: E402
from event_expansion import EventExpansionSwitches  # noqa: E402


class AutonomousPassInterferenceTests(unittest.TestCase):
    def test_live_interference_becomes_a_spot_foul_before_scheduling_or_result_is_reused(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.event_manifest_sha256 = 'f' * 64
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.snapshot = {
            'schedule': {'game_id': 'fixture', 'home_team': 'AAA', 'away_team': 'BBB'},
            'rosters': {
                'home': {'players': [
                    {'gsis_id': 'qb1', 'player_name': 'Quarterback', 'pos_abb': 'QB', 'team': 'AAA'},
                    {'gsis_id': 'wr1', 'player_name': 'Receiver', 'pos_abb': 'WR', 'team': 'AAA'},
                ]},
                'away': {'players': [
                    {'gsis_id': 'cb1', 'player_name': 'Defender', 'pos_abb': 'CB', 'team': 'BBB'},
                ]},
            },
        }
        call = {
            'play_id': 'fixture-pass', 'seed': '17',
            'offense': {'team': 'AAA', 'lineup': {'QB': 'qb1'},
                        'call': {'family': 'pass', 'concept': 'assigned'}},
            'situation': {'yardline_100': 60},
        }
        result = {
            'schema_version': 'gridiron.autonomous-pass.v1',
            'result': {'yards_gained': 8, 'elapsed_seconds': 2.4,
                       'final_ball_spot': {'x_yards': 68}, 'event': 'incomplete',
                       'turnover': False, 'is_touchdown': False, 'carrier_id': None},
            'events': [
                {'type': 'throw', 'target_id': 'wr1'},
                {'type': 'pass_interference', 'defender_id': 'cb1', 'receiver_id': 'wr1',
                 'spot': {'x': 68, 'y': 17}},
            ],
            'participants': {'sackers': []},
        }
        for direction, los_x, foul_x in ((1, 60, 68), (-1, 40, 32)):
            with self.subTest(direction=direction):
                call['situation']['yardline_100'] = los_x
                result['result']['final_ball_spot']['x_yards'] = foul_x
                result['events'][1]['spot']['x'] = foul_x
                generated = source._map_scrimmage_result(
                    call, result, {}, {},
                    {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 40},
                    {'play_index': 1, 'direction': direction}, {'selection': 'pass'}, 'pass')

                self.assertEqual(generated['event'], 'pass_incomplete')
                self.assertEqual(generated['row']['yards_gained'], 0)
                self.assertEqual(generated['row']['participants']['penalty_offender_id'], 'cb1')
                foul = generated['event_record'].penalty.fouls[0]
                self.assertEqual((foul.penalty_type, foul.team, foul.yards_assessed, foul.foul_spot),
                                 ('defensive_pass_interference', 'defense', 0, 32))
                applied = event_expansion_rules.apply_scrimmage_play(
                    {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 40},
                    generated['event_record'], switches=EventExpansionSwitches())
                self.assertEqual(applied.state_after,
                                 {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 32})
                self.assertTrue(applied.flags['penalty'])


class AutonomousSpecialTeamsTests(unittest.TestCase):
    def _source(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.seed = 7
        source.play_index = 11
        source.event_manifest_sha256 = 'f' * 64
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.ratings_path = None
        source.event_switches = EventExpansionSwitches()
        source.snapshot = {
            'schedule': {'home_team': 'AAA', 'away_team': 'BBB'},
            'rosters': {
                'home': {'players': [
                    {'gsis_id': 'punter-a', 'player_name': 'Punter A', 'pos_abb': 'P',
                     'pos_rank': 1, 'team': 'AAA'},
                    {'gsis_id': 'kicker-a', 'player_name': 'Kicker A', 'pos_abb': 'PK',
                     'pos_rank': 1, 'team': 'AAA'},
                ]},
                'away': {'players': [
                    {'gsis_id': 'returner-b', 'player_name': 'Returner B', 'pos_abb': 'WR',
                     'pos_rank': 1, 'team': 'BBB'},
                    {'gsis_id': 'back-b', 'player_name': 'Back B', 'pos_abb': 'RB',
                     'pos_rank': 2, 'team': 'BBB'},
                ]},
            },
        }
        return source

    def test_generated_punt_uses_typed_spot_and_named_returner(self):
        source = self._source()
        row = {'play_id': 12, 'live_elapsed_seconds': 4,
               'participants': {'attribution': 'autonomous_execution'}}
        generated = source.special_teams(
            'punt', {'offense': 'A', 'defense': 'B', 'yl': 65}, row, 4, None, random.Random(3))
        event_record = generated['event_record']
        self.assertEqual(event_record.event, 'punt')
        self.assertEqual(event_record.kick.returner.player_id, 'returner-b')
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 65}, event_record)
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.flags['punt_return'], True)
        self.assertEqual(applied.flags['return_yards'], 0)

    def test_generated_punt_touchback_uses_kicking_frame_restart(self):
        source = self._source()
        row = {'play_id': 13, 'live_elapsed_seconds': 4,
               'participants': {'attribution': 'autonomous_execution'}}
        generated = source.special_teams(
            'punt', {'offense': 'A', 'defense': 'B', 'yl': 35}, row, 4, None, random.Random(3))
        self.assertEqual(generated['event_record'].kick.result, 'touchback')
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 35},
            generated['event_record'])
        self.assertEqual((applied.state_after['offense'], applied.state_after['yl']), ('B', 80))

    def test_generated_field_goal_result_is_applied_by_shared_adapter(self):
        source = self._source()
        row = {'play_id': 14, 'live_elapsed_seconds': 4,
               'participants': {'attribution': 'autonomous_execution'}}
        generated = source.special_teams(
            'field_goal_attempt', {'offense': 'A', 'defense': 'B', 'yl': 40},
            row, 4, None, random.Random(9))
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 40},
            generated['event_record'])
        self.assertEqual(applied.flags['field_goal_result'], generated['metadata']['field_goal_result'])
        self.assertTrue(applied.flags['field_goal_attempt'])


if __name__ == '__main__':
    unittest.main()
