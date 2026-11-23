"""Chronological quarterback decisions over externally supplied live field states.

This module does not generate routes, movement, ratings or outcomes. The caller
must supply those from the live field model and cutoff-safe player data.
"""
import math


def decide(observations, policy, *, offense_ids=None, defense_ids=None):
    """Consume live observations until a sack or a decision ends the pocket.

    `policy` sees only the current observation. It returns an action of `wait`,
    `throw`, `throwaway`, or `scramble`, and `target` for a throw. Defender and
    receiver records have a GSIS `player_id`, x and y; defenders also have a
    data-backed reach in yards. The caller is responsible for player motion and
    roster validation. A throw is a decision, not a completed pass.
    """
    previous = -1.0
    history = []
    for state in observations:
        now = state['seconds']
        if not math.isfinite(now) or now < 0 or now <= previous:
            raise ValueError('live_qb_non_increasing_time')
        previous = now
        qb = state['qb']
        if not qb.get('player_id') or not all(math.isfinite(qb[key]) for key in ('x', 'y')):
            raise ValueError('live_qb_invalid_quarterback')
        if offense_ids is not None and qb['player_id'] not in offense_ids:
            raise ValueError('live_qb_ineligible_quarterback:' + qb['player_id'])
        for receiver in state['receivers']:
            if not receiver.get('player_id') or (offense_ids is not None and receiver['player_id'] not in offense_ids):
                raise ValueError('live_qb_ineligible_receiver:' + str(receiver.get('player_id')))
        contacts = []
        for defender in state['defenders']:
            if (not defender.get('player_id') or not all(math.isfinite(defender[key]) for key in ('x', 'y', 'reach'))
                    or defender['reach'] < 0):
                raise ValueError('live_qb_invalid_defender')
            if defense_ids is not None and defender['player_id'] not in defense_ids:
                raise ValueError('live_qb_ineligible_defender:' + defender['player_id'])
            if math.hypot(defender['x'] - qb['x'], defender['y'] - qb['y']) <= defender['reach']:
                contacts.append(defender['player_id'])
        if contacts:
            return {'action': 'sack', 'seconds': now, 'defenders': sorted(contacts), 'history': history}
        decision = policy(state)
        action = decision.get('action')
        if action not in ('wait', 'throw', 'throwaway', 'scramble'):
            raise ValueError('live_qb_invalid_action')
        if action == 'throw':
            targets = {p['player_id'] for p in state['receivers']}
            if decision.get('target') not in targets:
                raise ValueError('live_qb_invalid_target')
        history.append({'seconds': now, 'action': action})
        if action != 'wait':
            return {'action': action, 'seconds': now, 'target': decision.get('target'), 'history': history}
    raise ValueError('live_qb_observations_exhausted')
