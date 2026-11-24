"""Cross-engine translation checks. No historical outcome is supplied to Gridiron."""
import copy
import math

import pytest

import gridiron_bridge as bridge


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
