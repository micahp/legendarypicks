"""Cross-engine translation checks. No historical outcome is supplied to Gridiron."""
import copy
import json
import math
import os
import subprocess
from pathlib import Path

import pytest

import autonomous_game
import gridiron_bridge as bridge
import participation_field

ENGINE = Path(os.environ.get('GRIDIRON_ENGINE_TEST_ROOT', '/root/gridiron-v1-player-state'))

@pytest.fixture
def play():
    state = {'quarter': 1, 'clock': 600, 'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 50}
    call = {'situation': {'offense_direction': 1, 'yardline_100': 50, 'quarter': 1,
                          'clock_seconds': 600, 'down': 1, 'yards_to_go': 10},
            'offense': {'team': 'MIN', 'lineup': {'QB': 'qb', 'WR1': 'wr'}, 'call': {'family': 'pass'}},
            'defense': {'team': 'SF'}}
    result = {'result': {'event': 'tackle', 'yards_gained': 12.3, 'final_ball_spot': {'x_yards': 62.3},
                         'elapsed_seconds': 3.5, 'turnover': False, 'possession_team': 'MIN',
                         'is_touchdown': False, 'carrier_id': 'wr'},
              'events': [{'type': 'throw', 'target_id': 'wr'}, {'type': 'catch', 'player_id': 'wr'}]}
    return call, result, state


def test_completion_updates_downs_clock_and_player_statistics(play):
    call, result, state = play
    reduced = bridge.reduce_result(call, result, state)
    assert reduced['state_at_whistle'] == {'offense': 'MIN', 'defense': 'SF', 'down': 1, 'togo': 10, 'yl': 38}
    assert reduced['clock_at_whistle'] == 596
    assert reduced['play']['outcome']['yards_gained'] == 12
    assert reduced['play']['participants']['receiver_id'] == 'wr'
    stats = {p['player_id']: p for p in reduced['player_statistics']}
    assert stats['qb']['passing']['yds'] == 12
    assert stats['wr']['receiving']['yds'] == 12


def test_interception_changes_possession_at_defense_relative_spot(play):
    call, result, state = play
    result['events'] = [{'type': 'throw', 'target_id': 'wr'}, {'type': 'interception'}]
    result['result'].update(turnover=True, possession_team='SF', carrier_id='db')
    reduced = bridge.reduce_result(call, result, state)
    assert reduced['terminal'] == 'turnover'
    assert reduced['state_at_whistle']['offense'] == 'SF'
    assert reduced['state_at_whistle']['yl'] == 62
    stats = {p['player_id']: p for p in reduced['player_statistics']}
    assert stats['qb']['passing']['int'] == 1


def test_mirrored_direction_completion_reduces_forward_gain(play):
    call, result, state = play
    state.update(yl=40, offense_direction=-1)
    call['situation'].update(offense_direction=-1, yardline_100=40)
    result['result'].update(yards_gained=12.3, final_ball_spot={'x_yards': 27.7})

    reduced = bridge.reduce_result(call, result, state)

    assert reduced['play']['event_type'] == 'pass_complete'
    assert reduced['state_at_whistle']['yl'] == 28
    assert reduced['player_statistics'][0]['passing']['yds'] == 12


def test_mirrored_direction_interception_uses_defense_relative_spot(play):
    call, result, state = play
    state.update(yl=40, offense_direction=-1)
    call['situation'].update(offense_direction=-1, yardline_100=40)
    result['result'].update(event='interception', yards_gained=5.0,
                            final_ball_spot={'x_yards': 35.0}, turnover=True,
                            possession_team='SF', carrier_id='db')
    result['events'] = [{'type': 'throw', 'target_id': 'wr'}, {'type': 'interception'}]

    reduced = bridge.reduce_result(call, result, state)

    assert reduced['terminal'] == 'turnover'
    assert reduced['state_at_whistle']['offense'] == 'SF'
    assert reduced['state_at_whistle']['yl'] == 65
    stats = {row['player_id']: row for row in reduced['player_statistics']}
    assert stats['qb']['passing']['int'] == 1


def test_reject_mismatch_and_unsupported_boundaries(play):
    call, result, state = play
    changed = copy.deepcopy(result)
    changed['result']['final_ball_spot']['x_yards'] += 1
    with pytest.raises(ValueError, match='gridiron_final_spot_mismatch'):
        bridge.reduce_result(call, changed, state)
    changed = copy.deepcopy(result)
    changed['result']['possession_team'] = 'SF'
    with pytest.raises(ValueError, match='gridiron_possession_mismatch'):
        bridge.reduce_result(call, changed, state)
    changed = copy.deepcopy(result)
    changed['result']['yards_gained'] = math.nan
    with pytest.raises(ValueError, match='gridiron_nonfinite_or_invalid_result'):
        bridge.reduce_result(call, changed, state)
    changed = copy.deepcopy(result)
    changed['result']['elapsed_seconds'] = 600
    with pytest.raises(ValueError, match='gridiron_clock_boundary_unsupported'):
        bridge.reduce_result(call, changed, state)
    altered = dict(state, down=2)
    with pytest.raises(ValueError, match='gridiron_situation_contract_mismatch'):
        bridge.reduce_result(call, result, altered)


def test_incomplete_gridiron_result_preserves_exact_call_and_compact_terminal_state():
    call = {'seed': '300022', 'situation': {'quarter': 2, 'clock_seconds': 512},
            'offense': {'team': 'CHI', 'lineup': {'QB': 'qb'}}}
    result = {
        'schema_version': 'gridiron.autonomous-result.v1', 'status': 'failed',
        'seed': '300022', 'failure': {'reason': 'simulation_time_cap', 'time_limit_seconds': 12},
        'carrier_id': 'rb',
        'trajectory': {'roster': [{'id': 'rb', 'team': 'O', 'roleKey': 'O.RB'}],
                       'stride': 12,
                       'frames': [[40.0, 22.0, 0.0, 3.0, 1.0, 1.0, 40.2, 22.0, 0.1, 0, 0, 0]]},
        'events': [{'type': 'decision', 't': 11.9, 'player_id': 'rb', 'decision': 'advance'}],
        'diagnostics': {'blockers': [{'player_id': 'lt', 'won': False}],
                        'failure_state': {'active_engagements': [{'a': 'lt', 'b': 'de'}]}},
    }

    with pytest.raises(ValueError, match='replay_diagnostic=') as error:
        bridge._validate_result(call, result)

    diagnostic = json.loads(str(error.value).split('replay_diagnostic=', 1)[1])
    assert diagnostic['call'] == call
    assert diagnostic['ball_state'] == {'x_yards': 40.2, 'y_yards': 22.0, 'height': 0.1}
    assert diagnostic['players_at_timeout'][0]['player_id'] == 'rb'
    assert diagnostic['players_at_timeout'][0]['has_ball'] is True
    assert diagnostic['last_transition']['decision'] == 'advance'
    assert diagnostic['failure_state']['active_engagements'] == [{'a': 'lt', 'b': 'de'}]


@pytest.mark.parametrize(('team', 'playbook_team'), [
    ('LA', 'LA'), ('LAR', 'LA'), ('WAS', 'WAS'), ('WSH', 'WAS'),
])
def test_canonical_and_nflverse_team_codes_resolve_the_same_pinned_playbook(
        team, playbook_team, tmp_path, monkeypatch):
    import hashlib
    import json

    profile_path = tmp_path / f'{playbook_team}-2025.json'
    profile_path.write_text(json.dumps({
        'team_id': playbook_team, 'season': 2025,
        'offense': {'profile': {'run_pass': {'categories': {'pass': {'rate': 0.61}}}}},
    }))
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps({'team_seasons': [{
        'team': playbook_team, 'season': 2025, 'output': profile_path.name,
        'output_sha256': hashlib.sha256(profile_path.read_bytes()).hexdigest(),
    }]}))
    monkeypatch.setattr(bridge, 'PLAYBOOK_MANIFEST_SHA256',
                        hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    prior = bridge._profile(str(profile_path), str(manifest_path), 2026, team)
    assert prior['team'] == team
    assert prior['playbook_team_code'] == playbook_team
    assert 0 <= prior['pass_rate'] <= 1


@pytest.mark.skipif(not (ENGINE / 'data/playbooks/v1-runtime-manifest.json').is_file(),
                    reason='pinned GridIron runtime playbook bundle unavailable')
@pytest.mark.parametrize(('team', 'playbook_team'), [
    ('LA', 'LA'), ('LAR', 'LA'), ('WAS', 'WAS'), ('WSH', 'WAS'),
])
def test_checked_in_runtime_manifest_resolves_both_team_code_vocabularies(team, playbook_team):
    manifest = ENGINE / 'data/playbooks/v1-runtime-manifest.json'
    profile = ENGINE / 'data/playbooks' / f'{playbook_team}-2025.json'
    prior = bridge._profile(str(profile), str(manifest), 2026, team)
    assert prior['playbook_team_code'] == playbook_team
    assert prior['sha256'] == bridge._sha(str(profile))


@pytest.mark.parametrize(('schedule_code', 'playbook_code'), [
    ('LA', 'LA'), ('LAR', 'LA'), ('WAS', 'WAS'), ('WSH', 'WAS'),
])
def test_autonomous_profile_path_uses_nflverse_team_code(schedule_code, playbook_code, tmp_path):
    assert autonomous_game.playbook_profile_path(str(tmp_path), schedule_code) == str(
        tmp_path / f'{playbook_code}-2025.json')


def test_participation_field_team_keys_resolve_both_alias_directions():
    keyed = participation_field.TeamKeyed([('LAR', 1), ('WSH', 2)])
    assert keyed['LA'] == keyed['LAR'] == 1
    assert keyed['WAS'] == keyed['WSH'] == 2

    keyed_tuple = participation_field.TeamKeyed(
        [(('LAR', 'cell', 'START'), 3), (('WSH', 'cell', 'START'), 4)], team_at=0)
    assert keyed_tuple[('LA', 'cell', 'START')] == keyed_tuple[('LAR', 'cell', 'START')] == 3
    assert keyed_tuple[('WAS', 'cell', 'START')] == keyed_tuple[('WSH', 'cell', 'START')] == 4


def test_scrimmage_profiles_send_only_ratings_supported_by_the_selected_executor():
    ratings = {name: 70 for name in (
        'SPD', 'ACC', 'AGI', 'STR', 'AWR', 'THA', 'THP', 'KAC', 'KPW',
        'IBL', 'BCV', 'TRK', 'CIT', 'BTK', 'CTH', 'PRC')}

    passing_qb = bridge._scrimmage_ratings(
        ratings, family='pass', player_id='qb', quarterback_id='qb')
    assert 'THA' in passing_qb
    assert not {'THP', 'KAC', 'KPW', 'IBL', 'BCV', 'TRK', 'CIT'} & passing_qb.keys()
    assert {'BTK', 'CTH', 'PRC'} <= passing_qb.keys()

    passing_receiver = bridge._scrimmage_ratings(
        ratings, family='pass', player_id='wr', quarterback_id='qb')
    assert 'THA' not in passing_receiver
    running_qb = bridge._scrimmage_ratings(
        ratings, family='run', player_id='qb', quarterback_id='qb')
    assert 'THA' not in running_qb
    assert {'IBL', 'BCV', 'TRK', 'CIT'} <= running_qb.keys()


@pytest.mark.parametrize(('role', 'missing_rating'), [
    ('WLB', 'PRC'), ('LEDGE', 'PMV'),
])
def test_defensive_player_roles_require_position_specific_ratings(role, missing_rating, monkeypatch):
    offense_positions = {
        'o-qb': 'QB', 'o-rb': 'RB', 'o-te': 'TE', 'o-wr1': 'WR',
        'o-wr2': 'WR', 'o-wr3': 'WR', 'o-lt': 'LT', 'o-lg': 'LG',
        'o-c': 'C', 'o-rg': 'RG', 'o-rt': 'RT',
    }
    offense_roster = [
        {'gsis_id': player_id, 'pos_abb': position, 'pos_rank': 1}
        for player_id, position in offense_positions.items()
    ]
    defense_ids = [f'd-{slot}' for slot in bridge.DEFENSE_SLOTS]
    defense_lineup = dict(zip(defense_ids, bridge.DEFENSE_SLOTS))
    selected = {
        'qb1': 'o-qb',
        'slots': {'o-rb': 'RB', 'o-te': 'TE', 'o-wr1': 'WR',
                  'o-wr2': 'WR', 'o-wr3': 'WR'},
    }
    snapshot = {
        'schedule': {'home_team': 'HOM', 'away_team': 'AWY', 'season': 2026,
                     'week': 2, 'game_id': '2026_02_AWY_HOM'},
        'as_of': '2026-09-10T12:00:00Z',
        'rosters': {'home': {'players': offense_roster},
                    'away': {'players': [{'gsis_id': pid} for pid in defense_ids]},
                    },
    }
    all_ratings = {name: 70 for name in (
        *bridge.COMMON_LIVE_RATINGS, 'THA', 'CTH', 'PBK', 'RBK', 'IBL',
        'BSH', 'FMV', 'PMV', 'PRC', 'PUR', 'TAK', 'BTK', 'BCV', 'CAR', 'ELU',
    )}
    ratings = {
        player_id: {'ratings': dict(all_ratings), 'physics': {'mass': 90}}
        for player_id in [*offense_positions, *defense_ids]
    }
    ratings[f'd-{role}']['ratings'].pop(missing_rating)
    monkeypatch.setattr(bridge.pregame_snapshot, 'load_frozen_snapshot', lambda _path: snapshot)
    monkeypatch.setattr(bridge.roster_preflight, 'check', lambda _snapshot: ([], {'home': {'side': 'home'}, 'away': {'side': 'away'}}))
    monkeypatch.setattr(bridge.roster_preflight, 'failed', lambda _checks: False)
    monkeypatch.setattr(bridge.roster_preflight, 'exclusions_applied',
                        lambda _snapshot, _resolved: ([], 'PASS'))
    monkeypatch.setattr(bridge.v1_complete_roster, 'eligible_ids',
                        lambda _resolved: set(offense_positions))
    monkeypatch.setattr(bridge.v1_complete_roster, 'eligible_rows',
                        lambda resolved: offense_roster if resolved['side'] == 'home' else ())
    monkeypatch.setattr(bridge.participation_field.Field, 'load',
                        lambda _path, _field_hash: object())
    monkeypatch.setattr(bridge.live_participation, 'advance', lambda _field, **_kwargs: selected)
    monkeypatch.setattr(bridge, '_defensive_lineup',
                        lambda _resolved, _roster: defense_lineup)
    monkeypatch.setattr(bridge, '_profile', lambda *_args: {})
    monkeypatch.setattr(bridge, '_ratings', lambda _path: (ratings, {'schema': 'fixture'}))

    state = {'quarter': 1, 'clock': 600, 'offense': 'A', 'defense': 'B',
             'down': 1, 'togo': 10, 'yl': 50, 'offense_direction': 1}
    with pytest.raises(ValueError, match=f'gridiron_bridge_player_rating_missing:d-{role}:{missing_rating}'):
        bridge.build_call(
            'snapshot.json', 'participation.json', 'field-hash', 'profile.json',
            'manifest.json', seed=1, family='pass', state=state, ratings_path='ratings.json')


def test_nickel_front_resolves_second_interior_role_from_an_eligible_three_four_end():
    roster = [
        {'gsis_id': 'EDGE1', 'pos_abb': 'LDE', 'pos_rank': 1},
        {'gsis_id': 'DT1', 'pos_abb': 'NT', 'pos_rank': 1},
        {'gsis_id': 'EDGE2', 'pos_abb': 'LDE', 'pos_rank': 2},
        {'gsis_id': 'EDGE3', 'pos_abb': 'RDE', 'pos_rank': 1},
        {'gsis_id': 'LB', 'pos_abb': 'MLB', 'pos_rank': 1},
        {'gsis_id': 'WLB', 'pos_abb': 'WLB', 'pos_rank': 1},
        {'gsis_id': 'NB', 'pos_abb': 'NB', 'pos_rank': 1},
        {'gsis_id': 'LCB', 'pos_abb': 'LCB', 'pos_rank': 1},
        {'gsis_id': 'RCB', 'pos_abb': 'RCB', 'pos_rank': 1},
        {'gsis_id': 'SS', 'pos_abb': 'SS', 'pos_rank': 1},
        {'gsis_id': 'FS', 'pos_abb': 'FS', 'pos_rank': 1},
    ]
    resolved = {
        'schema': 'lp-nfl-resolved-roster-2', 'blocks': [],
        'players': [{'gsis_id': row['gsis_id'], 'official_eligible': True,
                     'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None}
                    for row in roster],
        'roles': [],
    }
    lineup = bridge._defensive_lineup(resolved, roster)
    assert len(lineup) == len(set(lineup)) == 11
    assert lineup['DT1'] == 'LDT'
    assert lineup['EDGE2'] == 'RDT'
    assert lineup['EDGE1'] == 'LEDGE'
    assert lineup['EDGE3'] == 'REDGE'


def test_fourth_down_incompletion_changes_possession(play):
    call, result, state = play
    state['down'] = call['situation']['down'] = 4
    result['events'] = [{'type': 'throw', 'target_id': 'wr'}]
    result['result'].update(event='incomplete', yards_gained=0,
                            final_ball_spot={'x_yards': 50}, carrier_id=None)
    reduced = bridge.reduce_result(call, result, state)
    assert reduced['terminal'] == 'turnover_on_downs'
    assert reduced['state_at_whistle']['offense'] == 'SF'
    assert reduced['state_at_whistle']['yl'] == 50
    assert reduced['play']['event_type'] == 'pass_incomplete'


@pytest.mark.skipif(not (ENGINE / 'engine/autonomous/slc-server.js').exists(),
                    reason='optional pinned Gridiron research checkout unavailable')
def test_persistent_session_reuses_process_and_recovers_from_bad_request():
    with bridge.GridironSession(str(ENGINE)) as session:
        pid = session.proc.pid
        with pytest.raises(ValueError, match='gridiron_executor_failed'):
            session.request('invalid_operation')
        first = session.request('example_assignments', concept='curls', coverage='man')['value']
        second = session.request('example_assignments', concept='curls', coverage='man')['value']
        assert session.proc.pid == pid
        assert first == second
        assert first['offense']['WR1']['route'] == 'curl'
        run_assignments = session.request('example_run_assignments', direction='right')['value']
        assert len(run_assignments['offense']) == 11
        assert len(run_assignments['defense']) == 11
        assert run_assignments['offense']['RB']['aiming_gap'] == 'play_side_a'


def _coverage_assignment_fixture(coverage):
    defense = {slot: {'kind': 'rush'} for slot in ('LEDGE', 'LDT', 'RDT', 'REDGE')}
    if coverage == 'man':
        defense.update({slot: {'kind': 'man', 'target_slot': target} for slot, target in (
            ('LCB', 'WR1'), ('RCB', 'WR2'), ('NB', 'WR3'), ('MLB', 'RB'),
        )})
        defense.update({slot: {'kind': 'zone', 'bounds': [1, 2, 1, 2]} for slot in ('WLB', 'SS', 'FS')})
    else:
        defense.update({slot: {'kind': 'zone', 'bounds': [1, 2, 1, 2]}
                        for slot in ('MLB', 'WLB', 'NB', 'LCB', 'RCB', 'SS', 'FS')})
    return {'schema_version': 'gridiron.assignments.v1', 'offense': {}, 'defense': defense}


@pytest.mark.parametrize(('coverage', 'assignment_coverage'), [
    ('cover_1', 'man'), ('cover_3', 'zone'),
])
def test_assigned_pass_requests_assignments_matching_declared_coverage(
        coverage, assignment_coverage, monkeypatch):
    session = object.__new__(bridge.GridironSession)
    session.commit = 'test-engine'
    requests = []
    assignments = _coverage_assignment_fixture(assignment_coverage)

    def request(op, **kwargs):
        requests.append((op, kwargs))
        if op == 'example_assignments':
            return {'value': assignments}
        return {'value': {'status': 'complete'}, 'engine_ms': 1.0}

    session.request = request
    monkeypatch.setattr(bridge, '_validate_result', lambda _call, result: result)
    call = {
        'offense': {'call': {'family': 'pass', 'concept': 'assigned', 'direction': 'left'}},
        'defense': {'call': {'coverage': coverage}},
    }

    session.play(call)

    assert requests[0] == ('example_assignments', {
        'concept': 'slant_flat', 'coverage': assignment_coverage, 'direction': 'left',
    })
    assert requests[1][0] == 'play'
    assert call['assignments'] is assignments


def test_assigned_pass_rejects_coverage_without_example_assignment_mapping():
    session = object.__new__(bridge.GridironSession)
    session.request = lambda *_args, **_kwargs: pytest.fail('unsupported coverage must fail before RPC')
    call = {
        'offense': {'call': {'family': 'pass', 'concept': 'assigned'}},
        'defense': {'call': {'coverage': 'unsupported'}},
    }

    with pytest.raises(ValueError, match='gridiron_bridge_example_assignment_coverage_unsupported'):
        session.play(call)


def test_session_requests_and_checks_shared_evaluation(monkeypatch):
    session = object.__new__(bridge.GridironSession)
    session.commit = 'test-engine'
    session.player_evaluation_mode = 'shared_snapshot'
    monkeypatch.setattr(bridge, '_validate_result', lambda _call, result: result)
    call = {'offense': {'call': {'family': 'pass', 'concept': 'assigned'}},
            'defense': {'call': {'coverage': 'cover_1'}},
            'assignments': _coverage_assignment_fixture('man')}
    requests = []
    def request(op, **kwargs):
        requests.append((op, copy.deepcopy(kwargs)))
        return {'value': {'diagnostics': {'player_evaluation_mode': 'shared_snapshot'}}, 'engine_ms': 0}
    session.request = request
    session.play(call)
    assert requests[0][1]['call']['player_evaluation_mode'] == 'shared_snapshot'
    session.request = lambda *_args, **_kwargs: {'value': {'diagnostics': {}}, 'engine_ms': 0}
    with pytest.raises(ValueError, match='gridiron_player_evaluation_mode_mismatch'):
        session.play(call)


@pytest.mark.skipif(not (ENGINE / 'test/autonomous-fixtures.mjs').exists(),
                    reason='pinned Gridiron fixture unavailable')
@pytest.mark.parametrize('family', ['run', 'pass'])
def test_shared_session_executes_pinned_gridiron_scrimmage(family):
    script = ("import {buildSampleCall} from './test/autonomous-fixtures.mjs';"
              "const family=process.argv[1];"
              "const options=family==='run'?{family,concept:'inside_zone',direction:'right'}:"
              "{family,concept:'assigned',snap_type:'shotgun',coverage:'cover_1'};"
              "console.log(JSON.stringify(buildSampleCall(options))); ")
    call = json.loads(subprocess.check_output(
        ['node', '--input-type=module', '-e', script, family], cwd=str(ENGINE), text=True))
    with bridge.GridironSession(str(ENGINE), player_evaluation_mode='shared_snapshot') as session:
        result, timing = session.play(call)
    assert result['status'] == 'complete'
    assert result['diagnostics']['assignments_executed'] == 22
    assert result['diagnostics']['player_evaluation_mode'] == 'shared_snapshot'
    assert result['diagnostics']['reconciliation']['ok'] is True
    assert timing['engine_commit'] == bridge.ENGINE_COMMIT


@pytest.mark.parametrize(('coverage', 'wrong_kind', 'required_kind'), [
    ('cover_1', 'zone', 'man'), ('cover_3', 'man', 'zone'),
])
def test_assigned_pass_rejects_explicit_assignments_that_contradict_coverage(
        coverage, wrong_kind, required_kind):
    session = object.__new__(bridge.GridironSession)
    session.request = lambda *_args, **_kwargs: pytest.fail('mismatched assignments must fail before RPC')
    call = {
        'offense': {'call': {'family': 'pass', 'concept': 'assigned'}},
        'defense': {'call': {'coverage': coverage}},
        'assignments': {
            'offense': {},
            'defense': {slot: {'kind': wrong_kind} for slot in bridge.DEFENSE_SLOTS},
        },
    }

    with pytest.raises(ValueError, match=(
            f'gridiron_bridge_coverage_assignment_mismatch:{coverage}:{required_kind}_count_0')):
        session.play(call)


@pytest.mark.skipif(not (ENGINE / 'engine/autonomous/slc-server.js').exists(),
                    reason='optional pinned Gridiron research checkout unavailable')
@pytest.mark.parametrize('evaluation_mode', [None, 'shared_snapshot'])
def test_persistent_session_executes_generated_punt_return_with_all_22_players(evaluation_mode):
    ids = ['P', *[f'C{i}' for i in range(10)], 'PR', *[f'R{i}' for i in range(10)]]
    call = {
        'schema_version': 'gridiron.autonomous-special-teams.v1', 'kind': 'punt', 'seed': 42,
        'kicking_team': 'MIN', 'receiving_team': 'SF', 'yardline_100': 45,
        'lineups': {'kicking': {'punter': 'P', 'coverage': ids[1:11]},
                    'receiving': {'returner': 'PR', 'blockers': ids[12:]}},
        'player_profiles': {pid: {'ratings': {'SPD': 76, 'ACC': 75, 'AGI': 75, 'STR': 68,
            'AWR': 70, 'PUR': 75, 'TAK': 70, 'BSH': 70, 'RBK': 70, 'IBL': 70,
            'CTH': 78, 'CAR': 78, 'BCV': 75, 'ELU': 75, 'TRK': 65, 'PRC': 70,
            'KPW': 70, 'KAC': 70}} for pid in ids},
    }
    with bridge.GridironSession(str(ENGINE), player_evaluation_mode=evaluation_mode) as session:
        result, timing = session.special_teams(call)
    assert result['status'] == 'complete'
    assert result['diagnostics']['assignments_executed'] == 22
    assert result['events'][-1]['type'] == 'whistle'
    assert result['result']['result'] in ('return', 'touchback', 'muff', 'downed', 'fair_catch', 'out_of_bounds')
    assert timing['engine_ms'] >= 0
    if evaluation_mode:
        assert result['diagnostics']['player_evaluation_mode'] == evaluation_mode
        assert timing['engine_commit'] == bridge.ENGINE_COMMIT


@pytest.mark.skipif(not (ENGINE / 'engine/autonomous/slc-server.js').exists(),
                    reason='optional pinned Gridiron research checkout unavailable')
@pytest.mark.parametrize('evaluation_mode', [None, 'shared_snapshot'])
def test_persistent_session_executes_generated_field_goal_with_all_22_players(evaluation_mode):
    ids = ['K', *[f'O{i}' for i in range(10)], 'R', *[f'D{i}' for i in range(10)]]
    call = {
        'schema_version': 'gridiron.autonomous-special-teams.v1', 'kind': 'field_goal', 'seed': 42,
        'kicking_team': 'MIN', 'receiving_team': 'SF', 'yardline_100': 35,
        'lineups': {'kicking': {'kicker': 'K', 'coverage': ids[1:11]},
                    'receiving': {'returner': 'R', 'blockers': ids[12:]}},
        'player_profiles': {pid: {'ratings': {'SPD': 76, 'ACC': 75, 'AGI': 75, 'STR': 68,
            'AWR': 70, 'PUR': 75, 'TAK': 70, 'BSH': 70, 'RBK': 70, 'IBL': 70,
            'CTH': 78, 'CAR': 78, 'BCV': 75, 'ELU': 75, 'TRK': 65, 'PRC': 70,
            'KPW': 70, 'KAC': 70}} for pid in ids},
    }
    with bridge.GridironSession(str(ENGINE), player_evaluation_mode=evaluation_mode) as session:
        result, timing = session.special_teams(call)
    assert result['status'] == 'complete'
    assert result['diagnostics']['assignments_executed'] == 22
    assert result['events'][-1]['type'] == 'whistle'
    assert result['result']['result'] in ('made', 'missed', 'blocked')
    assert len(result['trajectory']['roster']) == 22
    assert timing['engine_ms'] >= 0
    if evaluation_mode:
        assert result['diagnostics']['player_evaluation_mode'] == evaluation_mode
        assert timing['engine_commit'] == bridge.ENGINE_COMMIT
