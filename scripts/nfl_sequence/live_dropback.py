"""Restricted live dropback through the existing possession reducer.

All movement, decisions, throws and catch decisions are caller-supplied. This
slice stops at the whistle; it does not invent a dead-ball clock or run after
the catch. Unsupported continuations fail explicitly.
"""
import math

import ball_flight
import game_stats
import live_qb
import reducer


def play(state, observations, qb_policy, *, offense_ids, defense_ids, throw=None, catch=None, scramble=None):
    """Run one live dropback with a geometrically resolved pass and reducer result.

    Coordinates are yards from the line of scrimmage, increasing toward the
    opponent's goal. `throw(current_observation, decision)` supplies a BallFlight
    and MovingPlayers at release. `catch(player_id, time, state)` is a supplied
    player-data-backed catch decision. A caught ball is supported only if a
    defender is already in tackling reach; returns and later tackles block.
    """
    last = {}
    def tracked():
        for item in observations:
            last.clear()
            last.update(item)
            yield item

    decision = live_qb.decide(tracked(), qb_policy, offense_ids=offense_ids, defense_ids=defense_ids)
    action = decision['action']
    qb = last['qb']['player_id']
    elapsed = decision['seconds']
    receiver = None
    rusher = None
    interception_spot = None
    if action == 'sack':
        event, yards = 'sack', math.floor(last['qb']['x'])
    elif action == 'throwaway':
        event, yards = 'pass_incomplete', 0
    elif action == 'scramble':
        if scramble is None:
            raise ValueError('live_scramble_tackle_transition_unavailable')
        previous_time = None
        prior_defenders = {p['player_id'] for p in last['defenders']}
        for frame in scramble(last, decision):
            when, runner = frame['seconds'], frame['runner']
            if (not math.isfinite(when) or (previous_time is None and when != decision['seconds'])
                    or (previous_time is not None and when <= previous_time)):
                raise ValueError('live_scramble_non_increasing_time')
            if runner.get('player_id') != qb or not all(math.isfinite(runner[k]) for k in ('x', 'y')):
                raise ValueError('live_scramble_invalid_runner')
            if previous_time is None and (runner['x'], runner['y']) != (last['qb']['x'], last['qb']['y']):
                raise ValueError('live_scramble_start_position_mismatch')
            defenders = frame['defenders']
            if {p.get('player_id') for p in defenders} != prior_defenders:
                raise ValueError('live_scramble_defenders_changed')
            if any(p['player_id'] not in defense_ids or not all(math.isfinite(p[k]) for k in ('x', 'y', 'reach'))
                   or p['reach'] < 0 for p in defenders):
                raise ValueError('live_scramble_invalid_defender')
            if previous_time is None:
                before = {p['player_id']: p for p in last['defenders']}
                if any((p['x'], p['y']) != (before[p['player_id']]['x'], before[p['player_id']]['y']) for p in defenders):
                    raise ValueError('live_scramble_defender_position_mismatch')
            previous_time = when
            if (runner['x'] >= state['yl'] or runner['x'] <= state['yl'] - 100
                    or any(math.hypot(p['x'] - runner['x'], p['y'] - runner['y']) <= p['reach'] for p in defenders)):
                event, yards, rusher, elapsed = 'run', max(state['yl'] - 100, min(state['yl'], math.floor(runner['x']))), qb, when
                break
        else:
            raise ValueError('live_scramble_tackle_transition_unavailable')
    else:
        if throw is None or catch is None:
            raise ValueError('live_throw_inputs_missing')
        flight, players = throw(last, decision)
        ids = [p.player_id for p in players]
        if offense_ids & defense_ids:
            raise ValueError('live_rosters_overlap')
        if any(pid not in offense_ids and pid not in defense_ids for pid in ids):
            raise ValueError('live_throw_ineligible_participant')
        if not (math.isclose(flight.release_x, last['qb']['x'], abs_tol=1e-9)
                and math.isclose(flight.release_y, last['qb']['y'], abs_tol=1e-9)):
            raise ValueError('live_throw_release_position_mismatch')
        at_release = {p['player_id']: p for p in last['receivers'] + last['defenders']}
        if set(ids) != set(at_release):
            raise ValueError('live_throw_missing_player_trajectory')
        for player in players:
            prior = at_release.get(player.player_id)
            if prior is None or not (math.isclose(player.x, prior['x'], abs_tol=1e-9)
                                     and math.isclose(player.y, prior['y'], abs_tol=1e-9)):
                raise ValueError('live_throw_player_position_mismatch:' + player.player_id)
        hit = ball_flight.first_reach(flight, players)
        elapsed += flight.duration if hit is None else hit[0]
        receiver = decision['target']
        if hit is None:
            event, yards = 'pass_incomplete', 0
        else:
            when, reaching = hit
            if len(reaching) != 1:
                raise ValueError('live_catch_contest_unavailable')
            player = reaching[0]
            caught = catch(player, when, last)
            if type(caught) is not bool:
                raise ValueError('live_catch_decision_not_boolean')
            if not caught:
                raise ValueError('live_failed_catch_continuation_unavailable')
            x, y, _height = flight.position(when)
            if player in offense_ids:
                if player != receiver:
                    raise ValueError('live_nontarget_catch_unavailable')
                defenders = [p for p in players if p.player_id in defense_ids]
                if not any(math.hypot(p.x + p.vx * when - x, p.y + p.vy * when - y) <= p.reach_radius
                           for p in defenders):
                    raise ValueError('live_after_catch_tackle_unavailable')
                event, yards = 'pass_complete', math.floor(x)
            else:
                attackers = [p for p in players if p.player_id in offense_ids]
                if not any(math.hypot(p.x + p.vx * when - x, p.y + p.vy * when - y) <= p.reach_radius
                           for p in attackers):
                    raise ValueError('live_interception_return_unavailable')
                interception_spot = 100 - state['yl'] + math.floor(x)
                if not 1 <= interception_spot <= 99:
                    raise ValueError('live_interception_boundary_unavailable')
                event, yards = 'interception', 0
    charged_seconds = math.ceil(elapsed)
    if not 0 <= elapsed or charged_seconds >= state['clock']:
        raise ValueError('live_period_expiry_unavailable')
    if state['quarter'] in (2, 4) and state['clock'] > 120 >= state['clock'] - charged_seconds:
        raise ValueError('live_two_minute_warning_unavailable')
    after, terminal, flags = reducer.apply_play(state, event, yards, interception_spot)
    record = {'event_type': event, 'state_before': {'yardline_100': state['yl']},
              'participants': {'passer_id': None if rusher else qb, 'receiver_id': receiver, 'rusher_id': rusher,
                               'attribution': 'live_play'},
              'outcome': {'yards_gained': yards, **flags}}
    return {'decision': decision, 'play': record, 'state_at_whistle': after, 'terminal': terminal,
            'clock_at_whistle': state['clock'] - charged_seconds,
            'player_statistics': game_stats.player_lines([{'plays': [record]}])}
