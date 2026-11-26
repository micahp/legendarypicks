"""Cross-engine translation checks. No historical outcome is supplied to Gridiron."""
import copy
import math
from pathlib import Path

import pytest

import autonomous_game
import gridiron_bridge as bridge
import participation_field

ENGINE = Path('/root/gridiron-v1-complete-implementation')

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


@pytest.mark.skipif(not (ENGINE / 'engine/autonomous/slc-server.js').exists(),
                    reason='optional pinned Gridiron research checkout unavailable')
def test_persistent_session_executes_generated_punt_return_with_all_22_players():
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
    with bridge.GridironSession(str(ENGINE)) as session:
        result, timing = session.special_teams(call)
    assert result['status'] == 'complete'
    assert result['diagnostics']['assignments_executed'] == 22
    assert result['events'][-1]['type'] == 'whistle'
    assert result['result']['result'] in ('return', 'touchback', 'muff', 'downed', 'fair_catch', 'out_of_bounds')
    assert timing['engine_ms'] >= 0


@pytest.mark.skipif(not (ENGINE / 'engine/autonomous/slc-server.js').exists(),
                    reason='optional pinned Gridiron research checkout unavailable')
def test_persistent_session_executes_generated_field_goal_with_all_22_players():
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
    with bridge.GridironSession(str(ENGINE)) as session:
        result, timing = session.special_teams(call)
    assert result['status'] == 'complete'
    assert result['diagnostics']['assignments_executed'] == 22
    assert result['events'][-1]['type'] == 'whistle'
    assert result['result']['result'] in ('made', 'missed', 'blocked')
    assert len(result['trajectory']['roster']) == 22
    assert timing['engine_ms'] >= 0
