import sys
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


if __name__ == '__main__':
    unittest.main()
