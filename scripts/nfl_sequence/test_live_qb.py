import pytest

import live_qb


def state(seconds, defender_x=10):
    return {'seconds': seconds, 'qb': {'player_id': 'qb', 'x': 0, 'y': 0},
            'defenders': [{'player_id': 'def', 'x': defender_x, 'y': 0, 'reach': 0.5}],
            'receivers': [{'player_id': 'wr', 'x': 10, 'y': 5}], 'ratings': {'qb': {'source': 'fixture'}}}


def test_wait_then_sack_preempts_another_decision():
    observed = []
    def wait(s):
        observed.append(s['seconds'])
        return {'action': 'wait'}
    result = live_qb.decide([state(0), state(1), state(2, defender_x=0.5)], wait)
    assert result['action'] == 'sack'
    assert result['defenders'] == ['def']
    assert observed == [0, 1]


@pytest.mark.parametrize('action', ['scramble', 'throwaway', 'throw'])
def test_decision_stops_without_observing_future_states(action):
    def states():
        yield state(0)
        yield state(1)
        raise AssertionError('future state read')
    def policy(s):
        return {'action': 'wait'} if s['seconds'] == 0 else {'action': action, 'target': 'wr'}
    result = live_qb.decide(states(), policy)
    assert result['action'] == action
    assert result['seconds'] == 1


def test_invalid_target_and_nonincreasing_time_fail():
    with pytest.raises(ValueError, match='live_qb_invalid_target'):
        live_qb.decide([state(0)], lambda _: {'action': 'throw', 'target': 'unknown'})
    with pytest.raises(ValueError, match='live_qb_non_increasing_time'):
        live_qb.decide([state(0), state(0)], lambda _: {'action': 'wait'})


def test_live_participants_must_belong_to_resolved_rosters():
    with pytest.raises(ValueError, match='live_qb_ineligible_defender:def'):
        live_qb.decide([state(0)], lambda _: {'action': 'wait'}, offense_ids={'qb', 'wr'}, defense_ids=set())
    with pytest.raises(ValueError, match='live_qb_ineligible_receiver:wr'):
        live_qb.decide([state(0)], lambda _: {'action': 'wait'}, offense_ids={'qb'}, defense_ids={'def'})
