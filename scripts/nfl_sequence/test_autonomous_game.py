import sys
import random
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autonomous_game  # noqa: E402
import ceg_contract  # noqa: E402
import event_expansion_rules  # noqa: E402
import gridiron_bridge  # noqa: E402
import game_state  # noqa: E402
from event_expansion import EventExpansionSwitches  # noqa: E402


class AutonomousPassInterferenceTests(unittest.TestCase):
    def test_live_interference_becomes_a_spot_foul_before_scheduling_or_result_is_reused(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.event_manifest_sha256 = 'f' * 64
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.coaching_profiles = {}
        source.seed = 17
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
        source.engine_root = str(Path(__file__).resolve().parents[3] / 'gridiron-v1-complete-implementation')
        source.event_switches = EventExpansionSwitches()
        source.teams = ('AAA', 'BBB')
        source.coaching_profiles = {}
        source.session = None
        source.ratings_path = None
        ratings = {name: 70 for name in (
            'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'PUR', 'TAK', 'BSH', 'RBK', 'IBL',
            'CTH', 'CAR', 'BCV', 'ELU', 'TRK', 'PRC', 'KPW', 'KAC')}
        def player(team, index, position):
            pid = f'{team}-P{index}'
            return {'gsis_id': pid, 'player_name': f'Player {pid}', 'pos_abb': position,
                    'pos_rank': index + 1, 'team': team}
        source.snapshot = {
            'schedule': {'home_team': 'AAA', 'away_team': 'BBB'},
            'rosters': {
                'home': {'players': [player('AAA', i, 'P' if i == 0 else 'PK' if i == 1 else 'RB')
                                     for i in range(11)]},
                'away': {'players': [player('BBB', i, 'PR' if i == 0 else 'WR')
                                     for i in range(11)]},
            },
        }
        source.rating_rows = {
            p['gsis_id']: {'ratings': dict(ratings), 'physics': {}}
            for side in ('home', 'away') for p in source.snapshot['rosters'][side]['players']}
        return source

    def test_live_gridiron_punt_enters_slc_adapter_with_22_executed_players(self):
        source = self._source()
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 12, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            with patch.object(gridiron_bridge, '_ratings', return_value=(source.rating_rows, {
                    'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                generated = source.special_teams(
                    'punt', {'offense': 'A', 'defense': 'B', 'yl': 45}, row, 4, None, random.Random(3))
            source.session.close()
        self.assertNotIn('blocker', generated)
        event_record = generated['event_record']
        self.assertEqual(event_record.event, 'punt')
        self.assertEqual(event_record.kick.returner.status, 'named')
        self.assertEqual(len(generated['execution']['result']['trajectory']['roster']), 22)
        self.assertEqual(generated['execution']['result']['diagnostics']['assignments_executed'], 22)
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 45}, event_record)
        self.assertIn(applied.terminal, (None, 'punt', 'touchdown', 'safety'))
        if applied.state_after is not None:
            self.assertIn(applied.state_after['offense'], ('A', 'B'))
        self.assertIn('punt_return', applied.flags)
        self.assertEqual(generated['execution']['result']['diagnostics']['outcome_inputs'], [])

    def test_generated_punt_return_touchdown_crosses_gridiron_slc_runtime(self):
        source = self._source()
        source._decision_seed = lambda _play_index, _purpose: 1
        for pid, row in source.rating_rows.items():
            values = {'SPD': 30, 'ACC': 70, 'AGI': 70, 'STR': 40, 'AWR': 30,
                      'PUR': 20, 'TAK': 20, 'BSH': 20, 'RBK': 20, 'IBL': 20,
                      'CTH': 60, 'CAR': 60, 'BCV': 60, 'ELU': 60, 'TRK': 60,
                      'PRC': 30, 'KPW': 70, 'KAC': 70}
            if pid == 'AAA-P0':
                values.update({'SPD': 60, 'ACC': 60, 'AGI': 60, 'STR': 55, 'AWR': 65})
            if pid == 'BBB-P0':
                values.update({'SPD': 99, 'ACC': 99, 'AGI': 99, 'AWR': 99, 'CTH': 99,
                               'CAR': 99, 'BCV': 99, 'ELU': 99, 'TRK': 99, 'PRC': 99})
            row['ratings'] = values
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 12, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            try:
                with patch.object(gridiron_bridge, '_ratings', return_value=(source.rating_rows, {
                        'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                    generated = source.special_teams(
                        'punt', {'offense': 'A', 'defense': 'B', 'yl': 99}, row, 4, None,
                        random.Random(3))
            finally:
                source.session.close()
        execution = generated['execution']['result']
        self.assertEqual(execution['result']['scoring'], 'touchdown')
        self.assertEqual(execution['diagnostics']['assignments_executed'], 22)
        self.assertIn('touchdown', [event['type'] for event in execution['events']])
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 1, 'yl': 99},
            generated['event_record'])
        self.assertEqual((applied.terminal, applied.scoring_team), ('touchdown', 'B'))
        self.assertTrue(applied.flags['return_touchdown'])

    def test_generated_out_of_bounds_punt_reaches_the_full_slc_lifecycle(self):
        source = self._source()
        source.snapshot['rosters']['away']['players'][-1]['pos_abb'] = 'PK'
        source._decision_seed = lambda _play_index, purpose: 5 if purpose == 'gridiron_punt' else 12
        source.event_source = lambda state, context: {
            'event': 'punt', 'clock_runoff_seconds': 1,
            'row': {'game_id': 'gridiron-out-of-bounds-punt', 'play_id': context['play_index'],
                    'play_type': 'punt', 'yards_gained': None, 'live_elapsed_seconds': 4,
                    'dead_ball_seconds': 0, 'clock_stopped': True,
                    'participants': {'attribution': 'autonomous_execution',
                                     'timeout': False, 'out_of_bounds': False}},
        }
        original_call = source._special_teams_call

        def near_sideline(kind, *args):
            call, players, provenance = original_call(kind, *args)
            if kind == 'punt':
                call['ball_lateral_yards'] = 1.01
            return call, players, provenance

        source._special_teams_call = near_sideline
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            try:
                with patch.object(gridiron_bridge, '_ratings', return_value=(source.rating_rows, {
                        'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                    reference = type('Reference', (), {
                        'contextual_sampler': None, 'participants': {}, 'pool': []})()
                    record = game_state.play_game(
                        84, reference, winner_choice='receive', winner='A',
                        execution_source=source, max_drives=1)
            finally:
                source.close()
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'drive_limit')
        punt = record['drives'][0]['plays'][-1]
        self.assertTrue(punt['participants']['out_of_bounds'])
        result = punt['autonomous_execution']['result']
        self.assertTrue(result['result']['out_of_bounds'])
        self.assertIsNone(result['result']['returner_id'])
        self.assertFalse(punt['outcome']['punt_return'])
        self.assertEqual(punt['state_after']['offense_team'], 'B')
        self.assertEqual(punt['state_after']['yardline_100'],
                         100 - result['result']['dead_ball_yardline_100'])

    def test_missing_named_specialist_fails_closed(self):
        source = self._source()
        source.snapshot['rosters']['home']['players'] = [
            p for p in source.snapshot['rosters']['home']['players'] if p['pos_abb'] != 'P']
        source.ratings_path = '/tmp/irrelevant-ratings.json'
        generated = source.special_teams(
            'punt', {'offense': 'A', 'defense': 'B', 'yl': 45},
            {'play_id': 13, 'participants': {}}, 4, None, random.Random(3))
        self.assertEqual(generated['blocker'], 'autonomous_eligible_punter_missing:AAA')

    def test_field_goal_without_a_named_rated_kicker_fails_closed(self):
        source = self._source()
        row = {'play_id': 14, 'live_elapsed_seconds': 4,
               'participants': {'attribution': 'autonomous_execution'}}
        generated = source.special_teams(
            'field_goal_attempt', {'offense': 'A', 'defense': 'B', 'yl': 40},
            row, 4, None, random.Random(9))
        self.assertEqual(generated['blocker'], 'autonomous_player_rating_missing:AAA-P1:KAC')


if __name__ == '__main__':
    unittest.main()
