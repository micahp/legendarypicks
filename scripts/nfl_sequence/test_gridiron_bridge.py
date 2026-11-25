"""Cross-engine translation checks. No historical outcome is supplied to Gridiron."""
import copy
import math
from pathlib import Path

import pytest

import gridiron_bridge as bridge

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
    assert result['result']['result'] in ('return', 'touchback', 'muff')
    assert timing['engine_ms'] >= 0
