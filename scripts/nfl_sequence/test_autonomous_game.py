import sys
import random
import json
import re
import tempfile
from types import SimpleNamespace
from contextlib import contextmanager
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autonomous_game  # noqa: E402
import ceg_contract  # noqa: E402
import ceg_contract_v3  # noqa: E402
import event_expansion_rules  # noqa: E402
import gridiron_bridge  # noqa: E402
import game_state  # noqa: E402
import roster_preflight  # noqa: E402
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


class AutonomousPossessionHistoryTests(unittest.TestCase):
    def test_defensive_fumble_return_uses_endpoint_yards_after_raw_coordinate_check(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.event_manifest_sha256 = 'f' * 64
        call = {
            'play_id': 'fumble-return-endpoint-quantization', 'seed': '300015',
            'offense': {'team': 'GB', 'lineup': {'QB': 'qb1', 'RB': 'fumbler'},
                        'call': {'family': 'run', 'concept': 'inside_zone'}},
        }
        fumble = {
            'fumbler_id': 'fumbler', 'recoverer_id': 'recoverer',
            'recovery_side': 'D', 'recovery_team': 'LAR',
            'fumble_spot': {'x': 32.298354409535946, 'y': 27.634532709169928},
            'recovery_spot': {'x': 32.528160532074864, 'y': 27.18059331740051},
            'dead_ball_spot': {'x': 35.25672075085281, 'y': 27.444130240879},
            'return_yards': 2.728560218777943,
        }
        result = {
            'schema_version': 'gridiron.autonomous-result.v1',
            'result': {'event': 'tackle', 'possession_team': 'LAR', 'carrier_id': 'recoverer',
                       'yards_gained': -3.257, 'is_touchdown': False, 'turnover': True,
                       'elapsed_seconds': 3.867, 'fumble': fumble},
            'participants': {'sackers': []}, 'events': [],
        }
        state = {'offense': 'B', 'defense': 'A', 'down': 3, 'togo': 12, 'yl': 32}

        generated = source._ceg_play(
            call, result, 'run', -3, state, -1, 32, 35.25672075085281, 'tackle',
            None, None, None)

        self.assertEqual(generated.possession.recovery_spot_yardline_100, 33)
        self.assertEqual(generated.possession.dead_ball_yardline_100, 35)
        self.assertEqual(generated.possession.return_yards, 2)
        applied = event_expansion_rules.apply_scrimmage_play(
            state, generated, switches=EventExpansionSwitches())
        self.assertEqual(applied.state_after['offense'], 'A')
        self.assertEqual(applied.flags['return_yards'], 2)

        result['result']['fumble'] = {**fumble, 'return_yards': 2.4}
        with self.assertRaisesRegex(ValueError, 'gridiron_fumble_return_yards_disagree_with_raw_endpoints'):
            source._ceg_play(
                call, result, 'run', -3, state, -1, 32, 35.25672075085281, 'tackle',
                None, None, None)

    def test_interception_return_fumble_recovered_by_original_offense_maps_by_history(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.event_manifest_sha256 = 'f' * 64
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.event_switches = EventExpansionSwitches()
        source.snapshot = {
            'schedule': {'game_id': 'fixture', 'home_team': 'AAA', 'away_team': 'BBB'},
            'rosters': {
                'home': {'players': [
                    {'gsis_id': 'qb1', 'player_name': 'Quarterback', 'pos_abb': 'QB', 'team': 'AAA'},
                    {'gsis_id': 'wr1', 'player_name': 'Receiver', 'pos_abb': 'WR', 'team': 'AAA'},
                    {'gsis_id': 'ol1', 'player_name': 'Center', 'pos_abb': 'C', 'team': 'AAA'},
                ]},
                'away': {'players': [
                    {'gsis_id': 'db1', 'player_name': 'Defender', 'pos_abb': 'CB', 'team': 'BBB'},
                ]},
            },
        }
        call = {
            'play_id': 'interception-return-offense-recovery', 'seed': '19',
            'offense': {'team': 'AAA', 'lineup': {'QB': 'qb1'},
                        'call': {'family': 'pass', 'concept': 'assigned'}},
            'situation': {'yardline_100': 40},
        }
        result = {
            'schema_version': 'gridiron.autonomous-result.v1',
            'result': {'event': 'tackle', 'possession_team': 'AAA', 'carrier_id': 'ol1',
                       'yards_gained': 10, 'is_touchdown': False, 'turnover': False,
                       'final_ball_spot': {'x_yards': 50, 'y_yards': 20}, 'elapsed_seconds': 6,
                       'fumble': {'fumbler_id': 'db1', 'fumble_spot': {'x': 47, 'y': 20},
                                  'recovery_team': 'AAA', 'recovery_side': 'O',
                                  'recoverer_id': 'ol1', 'recovery_spot': {'x': 48, 'y': 20},
                                  'dead_ball_spot': {'x': 50, 'y': 20}, 'return_yards': 2}},
            'events': [
                {'type': 'throw', 'target_id': 'wr1'},
                {'type': 'interception', 'player_id': 'db1', 'at': {'x': 45, 'y': 20}},
                {'type': 'fumble', 'fumbler_id': 'db1', 'fumble_spot': {'x': 47, 'y': 20}},
                {'type': 'fumble_recovery', 'fumbler_id': 'db1', 'recoverer_id': 'ol1',
                 'team': 'O', 'recovery_team': 'AAA', 'recovery_spot': {'x': 48, 'y': 20}},
            ],
            'participants': {'interceptor': 'db1', 'sackers': []},
        }
        state = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 7, 'yl': 60}
        generated = source._map_scrimmage_result(
            call, result, {'execution_time_ms': 1}, {}, state,
            {'play_index': 8, 'direction': 1}, {'selection': 'pass'}, 'pass')

        self.assertEqual(generated['execution']['classification'], {
            'original_offensive_action': {'family': 'pass', 'concept': 'assigned'},
            'snap_event': 'interception',
            'possession_history': [
                {'type': 'interception', 'player_id': 'db1', 'at': {'x': 45, 'y': 20}},
                {'type': 'fumble', 'fumbler_id': 'db1', 'fumble_spot': {'x': 47, 'y': 20}},
                {'type': 'fumble_recovery', 'fumbler_id': 'db1', 'recoverer_id': 'ol1',
                 'team': 'O', 'recovery_team': 'AAA', 'recovery_spot': {'x': 48, 'y': 20}},
            ],
            'final_possession_team': 'AAA', 'scoring': None, 'dead_ball_reason': 'tackle',
        })
        self.assertIsInstance(generated['event_record'], ceg_contract_v3.GeneratedPlayV3)
        applied = source.apply_event(state, generated['event_record'])
        self.assertEqual(applied.state_after, {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50})
        self.assertTrue(applied.flags['interception'])
        self.assertFalse(applied.flags['possession_change'])


class AutonomousTryExecutionTests(unittest.TestCase):
    def test_live_extra_point_uses_named_opponent_and_does_not_raise(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.current_team = 'A'
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.teams = ('AAA', 'BBB')
        source.play_index = 1
        source.coaching_profiles = {}
        source._decision_seed = lambda *_args: 1
        source._execute_live_special_teams = lambda *args: {
            'participants': {'kicker_name': 'Named Kicker'},
            'execution': {'call': {'lineups': {'kicking': {'kicker': 'AAA-K'}}},
                          'result': {'result': {'result': 'made'}}},
        }

        class FixedRandom:
            def __init__(self, *_args):
                pass

            def random(self):
                return 0.99

        with patch.object(autonomous_game.random, 'Random', FixedRandom):
            points, record, blocker = source.try_after_touchdown(
                {'margin': 7, 'quarter': 1, 'clock': 600, 'offense_direction': 1})

        self.assertEqual((points, record['kind'], blocker), (1, 'extra_point', None))

    def test_two_point_branch_reads_participants_from_generated_row(self):
        source = object.__new__(autonomous_game.AutonomousGameExecution)
        source.current_team = 'A'
        source.team_by_side = {'A': 'AAA', 'B': 'BBB'}
        source.teams = ('AAA', 'BBB')
        source.play_index = 4
        source.coaching_profiles = {'AAA': {'two_point_tendency': 1.0}}
        source.coaching_quality = lambda *_args: 1
        source._decision_seed = lambda *_args: 11
        source._choose_family = lambda *_args: 'run'
        source.snapshot_path = 'fixture-snapshot.json'
        source.field = object()
        source.participation_sha256 = 'a' * 64
        source.profile_paths = {}
        source.playbook_manifest = 'fixture-playbook-manifest.json'
        source._rating_profile_path = lambda: 'fixture-ratings.json'
        source.session = SimpleNamespace(play=lambda _call: ({'live': 'result'}, {'elapsed': 1}))
        participants = {'rusher_id': 'AAA-RB', 'receiver_id': None, 'passer_id': None}
        generated = {'row': {'participants': participants}, 'execution': {'trace': 'live'},
                     'event_record': object()}
        source._map_scrimmage_result = lambda *_args: generated
        source.apply_event = lambda *_args: SimpleNamespace(terminal='touchdown', scoring_team='A')
        observed = {}

        def build_call(*_args, **kwargs):
            observed['direction'] = kwargs['state']['offense_direction']
            return {'offense': {'call': {'concept': 'inside_zone'}}}, {}, {}

        class FixedRandom:
            def __init__(self, *_args):
                pass

            def random(self):
                return 0.0

        with patch.object(gridiron_bridge, 'build_call', side_effect=build_call), \
                patch.object(autonomous_game.random, 'Random', FixedRandom):
            points, record, blocker = source.try_after_touchdown(
                {'margin': 0, 'quarter': 3, 'clock': 400, 'offense_direction': -1})

        self.assertIsNone(blocker)
        self.assertEqual(points, 2)
        self.assertEqual(observed['direction'], -1)
        self.assertEqual(record['try_actor_ids'], ['AAA-RB'])
        self.assertEqual(record['execution']['player_ids'], participants)


class AutonomousSpecialTeamsOutcomeAudit(unittest.TestCase):
    def test_gridiron_emitted_result_inventory_has_one_explicit_v3_handler_each(self):
        source = AutonomousSpecialTeamsTests()._source()
        handlers = autonomous_game.GRIDIRON_SPECIAL_TEAMS_RESULT_HANDLERS
        emitted = autonomous_game.GRIDIRON_SPECIAL_TEAMS_EMITTED_RESULTS
        for kind, results in emitted.items():
            self.assertTrue(set(results) <= set(handlers[kind]))
        self.assertEqual(set(handlers['kickoff']) - set(emitted['kickoff']), {'fair_catch'})
        special_teams = (Path(source.engine_root) / 'engine' / 'autonomous' / 'special-teams.js').read_text()
        literal_results = set(re.findall(r"\bresult:\s*'([^']+)'", special_teams))
        self.assertEqual(literal_results, {'muff', 'touchback', 'fair_catch', 'return', 'blocked'})
        self.assertIn('result: deadReason', special_teams)
        self.assertIn("deadReason === 'downed' || deadReason === 'out_of_bounds'", special_teams)
        self.assertIn('result: resultName', special_teams)
        self.assertIn("resultName = made ? 'made' : 'missed'", special_teams)
        self.assertIn("resultName = 'blocked'", special_teams)
        for kind, results in autonomous_game.GRIDIRON_SPECIAL_TEAMS_EMITTED_RESULTS.items():
            for result in results:
                with self.subTest(kind=kind, result=result):
                    self.assertTrue(
                        f"'{result}'" in special_teams,
                        f'GridIron source no longer emits the inventoried {kind} result {result}')
        passing = (Path(source.engine_root) / 'engine' / 'autonomous' / 'passing.js').read_text()
        terminal_literals = set(re.findall(r"finish\('([^']+)'", passing))
        self.assertEqual(autonomous_game.GRIDIRON_SCRIMMAGE_DEAD_BALL_REASONS,
                         terminal_literals | {'tackle'})
        self.assertIn("interception ? 'interception' : 'catch'", passing)
        for event in ('fumble', 'fumble_recovery', 'pass_interference'):
            self.assertIn(f"W.event('{event}'", passing)
class TryDirectionTests(unittest.TestCase):
    def test_try_situation_includes_current_offense_direction(self):
        game = object.__new__(game_state._Game)
        game.ledger = SimpleNamespace(teams=('A', 'B'), attacks_x100=lambda _team, _quarter: -1)
        game.points = {'A': 7, 'B': 0}
        game.quarter = 3
        game.clock = 100
        game.offense = 'A'
        game.drives = [{'offense_team': 'A', 'touchdown_scored_by': 'A'}]
        self.assertEqual(game._try_situation('A')['offense_direction'], -1)


class AutonomousSpecialTeamsTests(unittest.TestCase):
    @contextmanager
    def _valid_preflight(self, source, ineligible=()):
        resolved = {}
        for side in ('home', 'away'):
            players = {p['gsis_id'] for p in source.snapshot['rosters'][side]['players']}
            resolved[side] = {
                'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'roles': [],
                'players': [
                    {'gsis_id': pid, 'official_eligible': pid not in ineligible,
                     'membership': 'RESERVE' if pid in ineligible else 'ACTIVE_ROSTER',
                     'exclusion_reason': 'membership_reserve' if pid in ineligible else None}
                    for pid in sorted(players)
                ],
            }
        with patch.object(roster_preflight, 'check', return_value=([], resolved)), \
                patch.object(roster_preflight, 'exclusions_applied',
                             return_value=('exclusions reach the engine as Out', 'PASS', 'all excluded players Out')):
            yield

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
            'CTH', 'CAR', 'BCV', 'ELU', 'TRK', 'PRC', 'KPW', 'KAC', 'BTK', 'FMV', 'PMV')}
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

    def test_goal_line_interception_touchback_uses_the_turnover_spot_not_offensive_yards(self):
        source = self._source()
        source.snapshot['schedule']['game_id'] = 'goal-line-interception-touchback'
        call = {
            'play_id': 'goal-line-interception-touchback', 'seed': '17',
            'offense': {'team': 'AAA', 'lineup': {'QB': 'AAA-P0'},
                        'call': {'family': 'pass', 'concept': 'assigned'}},
            'situation': {'yardline_100': 8},
        }
        result = {
            'schema_version': 'gridiron.autonomous-pass.v1',
            'result': {'yards_gained': 8, 'elapsed_seconds': 4.5,
                       'final_ball_spot': {'x_yards': 0}, 'event': 'tackle',
                       'turnover': True, 'is_touchdown': False,
                       'carrier_id': 'BBB-P0', 'possession_team': 'BBB', 'fumble': None},
            'events': [
                {'type': 'throw', 'target_id': 'AAA-P1'},
                {'type': 'interception', 'player_id': 'BBB-P0',
                 'at': {'x': 0, 'y': 13}},
            ],
            'participants': {'interceptor': 'BBB-P0', 'sackers': []},
        }
        state = {'offense': 'A', 'defense': 'B', 'down': 2, 'togo': 8, 'yl': 8}
        generated = source._map_scrimmage_result(
            call, result, {}, {}, state, {'play_index': 1, 'direction': -1},
            {'selection': 'pass'}, 'pass')

        self.assertTrue(generated['event_record'].possession.touchback)
        self.assertEqual(generated['event_record'].yards_gained, 0)
        self.assertEqual(generated['row']['yards_gained'], 0)
        applied = source.apply_event(state, generated['event_record'])
        self.assertEqual(applied.state_after, {'offense': 'B', 'defense': 'A',
                                               'down': 1, 'togo': 10, 'yl': 20})

    def test_live_gridiron_punt_enters_slc_adapter_with_22_executed_players(self):
        source = self._source()
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 12, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                    return_value=(source.rating_rows, {'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                generated = source.special_teams(
                    'punt', {'offense': 'A', 'defense': 'B', 'yl': 45}, row, 4, None, random.Random(3))
            source.session.close()
        self.assertNotIn('blocker', generated)
        event_record = generated['event_record']
        self.assertEqual(event_record.event, 'punt')
        self.assertEqual(event_record.contract, ceg_contract_v3.CONTRACT_V3_VERSION)
        self.assertEqual(event_record.kick.return_facts.returner.status, 'named')
        self.assertEqual(len(generated['execution']['result']['trajectory']['roster']), 22)
        self.assertEqual(generated['execution']['result']['diagnostics']['assignments_executed'], 22)
        self.assertTrue(all('BTK' not in p['ratings']
                            for p in generated['execution']['call']['player_profiles'].values()))
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 5, 'yl': 45}, event_record)
        self.assertIn(applied.terminal, (None, 'punt', 'touchdown', 'safety'))
        if applied.state_after is not None:
            self.assertIn(applied.state_after['offense'], ('A', 'B'))
        self.assertIn('punt_return', applied.flags)
        self.assertEqual(generated['execution']['result']['diagnostics']['outcome_inputs'], [])

    def test_generated_scrimmage_fumble_recovery_crosses_gridiron_slc_runtime(self):
        source = self._source()
        source.snapshot['schedule']['game_id'] = 'generated-fumble-test'
        offense_ids = [f'AAA-P{i}' for i in range(11)]
        defense_ids = [f'BBB-P{i}' for i in range(11)]
        offense_lineup = dict(zip(('QB', 'RB', 'LT', 'LG', 'C', 'RG', 'RT', 'TE', 'WR1', 'WR2', 'WR3'),
                                  offense_ids))
        defense_lineup = dict(zip(('LEDGE', 'LDT', 'RDT', 'REDGE', 'MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS'),
                                  defense_ids))
        ratings = {name: 70 for name in (
            'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'RBK', 'IBL', 'PBK', 'BSH', 'PMV',
            'FMV', 'TAK', 'BTK', 'ELU', 'BCV', 'TRK', 'PUR', 'CAR', 'PRC', 'CTH', 'CIT')}
        profiles = {pid: {'ratings': dict(ratings), 'physics': {}} for pid in offense_ids + defense_ids}
        profiles[offense_lineup['RB']]['ratings']['CAR'] = 1
        for pid in defense_ids:
            profiles[pid]['ratings'].update({'TAK': 99, 'STR': 99, 'PRC': 99})
        state = {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 60}
        generated = None
        with gridiron_bridge.GridironSession(source.engine_root) as session:
            front_check = {
                'schema_version': 'gridiron.autonomous-play.v1',
                'mode': 'autonomous_from_snap', 'play_id': 'even-front-assignment-check',
                'seed': 'even-front-assignment-check', 'output_mode': 'result_only',
                'situation': {'quarter': 1, 'clock_seconds': 600, 'down': 1,
                              'yards_to_go': 10, 'yardline_100': 40,
                              'offense_direction': 1, 'ball_lateral_yards': 26.67},
                'offense': {'team': 'AAA', 'formation': 'singleback_11',
                            'call': {'family': 'run', 'concept': 'inside_zone',
                                     'direction': 'right', 'snap_type': 'under_center'},
                            'lineup': offense_lineup},
                'defense': {'team': 'BBB', 'call': {'front': 'even', 'coverage': 'cover_3',
                            'run_fit': 'spill_force'}, 'lineup': defense_lineup},
                'player_profiles': profiles,
            }
            front_result, _ = session.play(front_check)
            self.assertEqual(len(front_result['trajectory']['roster']), 22)
            self.assertEqual({p['id'] for p in front_result['trajectory']['roster']},
                             set(offense_ids + defense_ids))
            self.assertEqual(sum(event['type'] == 'assignment_executed'
                                 for event in front_result['events']), 22)
            for seed in range(12):
                call = {
                    'schema_version': 'gridiron.autonomous-play.v1',
                    'mode': 'autonomous_from_snap', 'play_id': f'generated-fumble-test:{seed}',
                    'seed': str(seed), 'output_mode': 'result_only',
                    'situation': {'quarter': 1, 'clock_seconds': 600, 'down': 1,
                                  'yards_to_go': 10, 'yardline_100': 40,
                                  'offense_direction': 1, 'ball_lateral_yards': 26.67},
                    'offense': {'team': 'AAA', 'formation': 'singleback_11',
                                'call': {'family': 'run', 'concept': 'inside_zone',
                                         'direction': 'right', 'snap_type': 'under_center'},
                                'lineup': offense_lineup},
                    'defense': {'team': 'BBB', 'call': {'front': 'nickel_over', 'coverage': 'cover_3',
                                'run_fit': 'spill_force'}, 'lineup': defense_lineup},
                    'player_profiles': profiles,
                }
                result, timing = session.play(call)
                if (result['result'].get('fumble') or {}).get('recovery_side') == 'D':
                    generated = source._map_scrimmage_result(
                        call, result, timing, {}, state,
                        {'direction': 1, 'play_index': seed},
                        {'selection': 'controlled live fumble scenario'}, 'run')
                    break
        self.assertIsNotNone(generated, 'seeded 22-player execution must generate a defensive recovery')
        execution = generated['execution']['result']
        self.assertEqual(len(execution['trajectory']['roster']), 22)
        self.assertTrue(any(event['type'] == 'fumble' for event in execution['events']))
        self.assertTrue(any(event['type'] == 'fumble_recovery' for event in execution['events']))
        self.assertEqual(generated['event_record'].possession.how, 'fumble_recovery')
        self.assertTrue(generated['event_record'].fumble)
        applied = source.apply_event(state, generated['event_record'])
        self.assertEqual(applied.terminal, 'turnover')
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertTrue(applied.flags['fumble'])

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
                               'STR': 90, 'BSH': 99, 'CAR': 99, 'BCV': 99, 'ELU': 99,
                               'TRK': 99, 'PRC': 99})
            elif pid.startswith('BBB-'):
                values.update({'SPD': 99, 'ACC': 99, 'AGI': 99, 'STR': 99,
                               'RBK': 99, 'IBL': 99, 'BSH': 99})
            row['ratings'] = values
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 12, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            try:
                with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                        return_value=(source.rating_rows, {'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
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

    def test_generated_field_goal_executes_22_players_and_enters_slc_adapter(self):
        source = self._source()
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 15, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            try:
                with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                        return_value=(source.rating_rows, {'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                    generated = source.special_teams(
                        'field_goal_attempt', {'offense': 'A', 'defense': 'B', 'yl': 35},
                        row, 4, None, random.Random(3))
            finally:
                source.session.close()
        self.assertNotIn('blocker', generated)
        self.assertEqual(generated['event_record'].event, 'field_goal_attempt')
        self.assertEqual(generated['event_record'].kick.result, generated['execution']['result']['result']['result'])
        self.assertIn(generated['event_record'].kick.result, ('made', 'missed', 'blocked'))
        execution = generated['execution']['result']
        self.assertEqual(execution['diagnostics']['assignments_executed'], 22)
        self.assertEqual(len(execution['trajectory']['roster']), 22)
        self.assertEqual(execution['diagnostics']['outcome_inputs'], [])
        call = generated['execution']['call']
        kicker_id = call['lineups']['kicking']['kicker']
        kicker_ratings = call['player_profiles'][kicker_id]['ratings']
        field_goal_evidence = generated['metadata']['special_teams_execution']['field_goal_execution']
        self.assertEqual(field_goal_evidence['kick_power_rating'], kicker_ratings['KPW'])
        self.assertEqual(field_goal_evidence['kick_accuracy_rating'], kicker_ratings['KAC'])
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 1, 'yl': 35}, generated['event_record'])
        if generated['event_record'].kick.result == 'blocked':
            self.assertIn(applied.terminal, ('turnover', 'turnover_on_downs', None, 'touchdown', 'safety'))
        else:
            self.assertEqual(applied.terminal, 'field_goal_attempt')

    def test_generated_blocked_field_goal_recovery_enters_slc_transition(self):
        source = self._source()
        source._decision_seed = lambda _play_index, _purpose: 0
        for pid, row in source.rating_rows.items():
            row['ratings'].update({'SPD': 76, 'ACC': 75, 'AGI': 75, 'BSH': 70, 'IBL': 70})
            if pid.startswith('AAA-'):
                row['ratings']['IBL'] = 1
            else:
                row['ratings'].update({'SPD': 99, 'ACC': 99, 'AGI': 99, 'BSH': 99})
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            row = {'play_id': 16, 'live_elapsed_seconds': 4, 'decision_note': {},
                   'participants': {'attribution': 'autonomous_execution'}}
            try:
                with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                        return_value=(source.rating_rows, {'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                    generated = source.special_teams(
                        'field_goal_attempt', {'offense': 'A', 'defense': 'B', 'yl': 35},
                        row, 4, None, random.Random(3))
            finally:
                source.session.close()
        self.assertNotIn('blocker', generated)
        self.assertEqual(generated['event_record'].kick.result, 'blocked')
        execution = generated['execution']['result']
        self.assertEqual(execution['diagnostics']['assignments_executed'], 22)
        self.assertEqual(sum(e['type'] == 'kick_blocked' for e in execution['events']), 1)
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 1, 'yl': 35},
            generated['event_record'])
        self.assertIn(applied.terminal, ('turnover', 'turnover_on_downs', None, 'touchdown', 'safety'))
        self.assertIsNotNone(applied.flags['blocked_kick'])
        self.assertEqual(applied.scoring_team, 'A' if generated['event_record'].kick.result == 'made' else None)

    def test_generated_out_of_bounds_punt_uses_v3_dead_spot_and_next_possession(self):
        source = self._source()
        source.snapshot['rosters']['away']['players'][-1]['pos_abb'] = 'PK'
        source._decision_seed = lambda _play_index, purpose: 5 if purpose == 'gridiron_punt' else 12
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
                    with self._valid_preflight(source):
                        record = source.special_teams(
                            'punt', {'offense': 'A', 'defense': 'B', 'yl': 40},
                            {'play_id': 84, 'participants': {'attribution': 'autonomous_execution'}},
                            4, None, random.Random(3))
            finally:
                source.close()
        self.assertNotIn('blocker', record)
        kick = record['event_record'].kick
        self.assertEqual(kick.result, 'out_of_bounds')
        self.assertIsNotNone(kick.out_of_bounds_spot)
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': 1, 'yl': 40},
            record['event_record'])
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.state_after['yl'], 100 - kick.dead_ball_spot.yardline_100)
        self.assertFalse(applied.flags.get('punt_return'))
        execution = record['execution']['result']
        self.assertEqual(execution['status'], 'complete')
        self.assertEqual(execution['result']['result'], 'out_of_bounds')
        self.assertIsNone(execution['result']['returner_id'])
        self.assertEqual(execution['diagnostics']['assignments_executed'], 22)

    def test_generated_kickoff_out_of_bounds_enforces_selected_v3_restart(self):
        source = self._source()
        original_call = source._special_teams_call

        def near_sideline(kind, *args):
            call, players, provenance = original_call(kind, *args)
            if kind == 'kickoff':
                call['ball_lateral_yards'] = 1.01
            return call, players, provenance

        source._special_teams_call = near_sideline
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            try:
                with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                        return_value=(source.rating_rows, {'dataset': 'test-ratings.json',
                                                           'source': 'test_estimates'})):
                    generated = None
                    for seed in range(12):
                        candidate = source._execute_live_special_teams(
                            'kickoff', 'A', 'B', 65, 1001 + seed, free_kick_kind='kickoff')
                        self.assertNotIn('blocker', candidate)
                        if candidate['event_record'].kick.result == 'out_of_bounds':
                            generated = candidate
                            break
            finally:
                source.close()
        self.assertIsNotNone(generated, 'seeded live kicks must expose the sideline enforcement path')
        kick = generated['event_record'].kick
        self.assertEqual(kick.kind, 'kickoff')
        self.assertEqual(kick.kickoff_oob.cause, 'kicking_team_out_of_bounds')
        self.assertIn(kick.kickoff_oob.choice, ('at_out_of_bounds_spot', 'at_distance_from_kick'))
        applied = source.apply_event(
            {'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 65},
            generated['event_record'])
        self.assertEqual(applied.state_after['offense'], 'B')
        self.assertEqual(applied.state_after['yl'], kick.kickoff_oob.restart_spot.yardline_100)
        self.assertTrue(applied.flags['kickoff_out_of_bounds'])
        self.assertTrue(applied.flags['penalty_accepted'])
        self.assertEqual(generated['execution']['result']['diagnostics']['assignments_executed'], 22)

    def test_missing_named_specialist_fails_closed(self):
        source = self._source()
        source.snapshot['rosters']['home']['players'] = [
            p for p in source.snapshot['rosters']['home']['players'] if p['pos_abb'] != 'P']
        source.ratings_path = '/tmp/irrelevant-ratings.json'
        with self._valid_preflight(source):
            generated = source.special_teams(
                'punt', {'offense': 'A', 'defense': 'B', 'yl': 45},
                {'play_id': 13, 'participants': {}}, 4, None, random.Random(3))
        self.assertEqual(generated['blocker'], 'autonomous_eligible_punter_missing:AAA')

    def test_ineligible_named_punter_is_not_selected_as_specialist(self):
        source = self._source()
        with self._valid_preflight(source, ineligible={'AAA-P0'}):
            with self.assertRaisesRegex(ValueError, 'autonomous_eligible_punter_missing:AAA'):
                source._special_teams_call('punt', 'AAA', 'BBB', 45, 1)

    def test_field_goal_without_a_named_rated_kicker_fails_closed(self):
        source = self._source()
        source.rating_rows['AAA-P1']['ratings'].pop('KAC')
        row = {'play_id': 14, 'live_elapsed_seconds': 4,
               'participants': {'attribution': 'autonomous_execution'}}
        with tempfile.TemporaryDirectory() as tmp:
            rating_path = Path(tmp) / 'ratings.json'
            rating_path.write_text(json.dumps({'players': {}}))
            source.ratings_path = str(rating_path)
            source.session = gridiron_bridge.GridironSession(source.engine_root)
            try:
                with self._valid_preflight(source), patch.object(gridiron_bridge, '_ratings',
                        return_value=(source.rating_rows, {'dataset': 'test-ratings.json', 'source': 'test_estimates'})):
                    generated = source.special_teams(
                        'field_goal_attempt', {'offense': 'A', 'defense': 'B', 'yl': 40},
                        row, 4, None, random.Random(9))
            finally:
                source.session.close()
        self.assertIn('AAA-P1.ratings_missing:KAC', generated['blocker'])


if __name__ == '__main__':
    unittest.main()
