import pytest

from ball_flight import BallFlight, MovingPlayer
import live_dropback


STATE = {'quarter': 1, 'clock': 600, 'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50}


def observation(seconds=0, defender_x=20, qb_x=-3, receiver_x=5):
    return {'seconds': seconds, 'qb': {'player_id': 'qb', 'x': qb_x, 'y': 0},
            'defenders': [{'player_id': 'def', 'x': defender_x, 'y': 0, 'reach': 0.3}],
            'receivers': [{'player_id': 'wr', 'x': receiver_x, 'y': 0}]}


def test_completion_reaches_reducer_clock_and_player_statistics():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    players = [MovingPlayer('wr', 5, 0, 0, 0, 0.2, 4), MovingPlayer('def', 5, 0, 0, 0, 0.3, 0)]
    result = live_dropback.play(
        STATE, [observation(defender_x=5, qb_x=0)], lambda _: {'action': 'throw', 'target': 'wr'},
        offense_ids={'qb', 'wr'}, defense_ids={'def'}, throw=lambda *_: (flight, players), catch=lambda *_: True)
    assert result['play']['event_type'] == 'pass_complete'
    assert result['state_at_whistle']['down'] == 2
    assert result['state_at_whistle']['yl'] == 46
    assert result['clock_at_whistle'] == 599
    lines = {p['player_id']: p for p in result['player_statistics']}
    assert lines['qb']['passing']['comp'] == 1
    assert lines['wr']['receiving']['rec'] == 1
    assert result == live_dropback.play(
        STATE, [observation(defender_x=5, qb_x=0)], lambda _: {'action': 'throw', 'target': 'wr'},
        offense_ids={'qb', 'wr'}, defense_ids={'def'}, throw=lambda *_: (flight, players), catch=lambda *_: True)


def test_uncatchable_throw_and_throwaway_are_incomplete():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    players = [MovingPlayer('wr', 30, 0, 0, 0, 0.1, 3), MovingPlayer('def', 20, 0, 0, 0, 0.1, 3)]
    miss = live_dropback.play(STATE, [observation(qb_x=0, receiver_x=30)], lambda _: {'action': 'throw', 'target': 'wr'},
                              offense_ids={'qb', 'wr'}, defense_ids={'def'},
                              throw=lambda *_: (flight, players), catch=lambda *_: True)
    away = live_dropback.play(STATE, [observation()], lambda _: {'action': 'throwaway'},
                              offense_ids={'qb', 'wr'}, defense_ids={'def'})
    assert miss['play']['event_type'] == away['play']['event_type'] == 'pass_incomplete'
    assert miss['state_at_whistle']['down'] == away['state_at_whistle']['down'] == 2


def test_sack_uses_live_quarterback_location():
    result = live_dropback.play(STATE, [observation(defender_x=-3)], lambda _: {'action': 'wait'},
                                offense_ids={'qb', 'wr'}, defense_ids={'def'})
    assert result['play']['event_type'] == 'sack'
    assert result['state_at_whistle']['yl'] == 53
    assert result['player_statistics'][0]['passing']['sacked'] == 1


def test_interception_transfers_possession_at_live_catch_spot():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    players = [MovingPlayer('wr', 5, 0, 0, 0, 0.3, 0), MovingPlayer('def', 5, 0, 0, 0, 0.2, 4)]
    result = live_dropback.play(
        STATE, [observation(defender_x=5, qb_x=0)], lambda _: {'action': 'throw', 'target': 'wr'},
        offense_ids={'qb', 'wr'}, defense_ids={'def'}, throw=lambda *_: (flight, players), catch=lambda *_: True)
    assert result['play']['event_type'] == 'interception'
    assert result['terminal'] == 'turnover'
    assert result['state_at_whistle']['offense'] == 'B'
    assert result['state_at_whistle']['yl'] == 54


def test_scramble_requires_a_live_tackle_transition():
    with pytest.raises(ValueError, match='live_scramble_tackle_transition_unavailable'):
        live_dropback.play(STATE, [observation()], lambda _: {'action': 'scramble'},
                           offense_ids={'qb', 'wr'}, defense_ids={'def'})


def test_scramble_moves_until_defender_reaches_the_quarterback():
    def motion(_state, _decision):
        return [
            {'seconds': 0, 'runner': {'player_id': 'qb', 'x': -3, 'y': 0},
             'defenders': [{'player_id': 'def', 'x': 20, 'y': 0, 'reach': 0.3}]},
            {'seconds': 2, 'runner': {'player_id': 'qb', 'x': 3, 'y': 0},
             'defenders': [{'player_id': 'def', 'x': 3, 'y': 0, 'reach': 0.3}]},
        ]
    result = live_dropback.play(STATE, [observation()], lambda _: {'action': 'scramble'},
                                offense_ids={'qb', 'wr'}, defense_ids={'def'}, scramble=motion)
    assert result['play']['event_type'] == 'run'
    assert result['state_at_whistle']['yl'] == 47
    assert result['clock_at_whistle'] == 598
    assert result['player_statistics'][0]['rushing']['yds'] == 3


def test_throw_cannot_teleport_players_or_omit_a_defender():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    policy = lambda _: {'action': 'throw', 'target': 'wr'}
    with pytest.raises(ValueError, match='live_throw_missing_player_trajectory'):
        live_dropback.play(STATE, [observation(qb_x=0)], policy, offense_ids={'qb', 'wr'}, defense_ids={'def'},
                           throw=lambda *_: (flight, [MovingPlayer('wr', 5, 0, 0, 0, 0.2, 4)]), catch=lambda *_: True)
    players = [MovingPlayer('wr', 6, 0, 0, 0, 0.2, 4), MovingPlayer('def', 20, 0, 0, 0, 0.3, 0)]
    with pytest.raises(ValueError, match='live_throw_player_position_mismatch:wr'):
        live_dropback.play(STATE, [observation(qb_x=0)], policy, offense_ids={'qb', 'wr'}, defense_ids={'def'},
                           throw=lambda *_: (flight, players), catch=lambda *_: True)
