"""Fail-closed V2 adapters for selected historical event facts.

The frozen E1 loop does not call this module.  It is an opt-in rules adapter
for ceg-play-2 records on the event-expansion branch, so the released V2 path
and its source-row filters remain unchanged until an integration is reviewed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import ceg_contract as contract
import penalty_enforcement
import reducer
from event_expansion import FROZEN_CONTROL, EventExpansionSwitches
from penalty_event_mapping import (PenaltyTypeMappingError, classify_penalty_type,
                                   nominal_yards_for)


class UnsupportedEventTransition(ValueError):
    """A typed event lacks enough facts or a supported V2 transition."""


@dataclass(frozen=True)
class AppliedEvent:
    state_after: object
    terminal: object
    flags: dict
    scoring_team: object = None
    penalty_enforcement: object = None


def _require_switch(switches, name):
    if not getattr(switches, name):
        raise UnsupportedEventTransition('event_switch_disabled:' + name)


def _int_spot(value, label):
    if type(value) is not int or not 0 <= value <= 100:
        raise UnsupportedEventTransition(label + '_must_be_integer_yardline_for_frozen_v2')
    return value


def _down_state(state, possession=None):
    try:
        return penalty_enforcement.DownState(
            down=state['down'], to_go=float(state['togo']),
            yardline_100=float(state['yl']), possession=possession or state['offense'])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnsupportedEventTransition('penalty_state_invalid:' + str(exc)) from exc


def _state_from_down_state(before, result):
    if result.possession == before['offense']:
        offense, defense = before['offense'], before['defense']
    elif result.possession == before['defense']:
        offense, defense = before['defense'], before['offense']
    else:
        raise UnsupportedEventTransition('penalty_transition_changed_to_unknown_team')
    yardline, to_go = result.yardline_100, result.to_go
    if not float(yardline).is_integer() or not float(to_go).is_integer():
        raise UnsupportedEventTransition('fractional_penalty_state_not_supported_by_integer_game_state')
    return {'offense': offense, 'defense': defense, 'down': result.down,
            'togo': int(to_go), 'yl': int(yardline)}


def _apply_penalty(before, after, play, switches):
    penalty = play.penalty
    if penalty is None:
        return after, None
    switch = 'pre_snap_penalties' if penalty.phase == 'pre_snap' else 'live_ball_penalties'
    _require_switch(switches, switch)
    if penalty.disposition == 'offsetting':
        raise UnsupportedEventTransition('offsetting_penalty_rules_not_yet_integrated')
    if penalty.phase == 'pre_snap' and penalty.disposition != 'accepted':
        raise UnsupportedEventTransition('pre_snap_no_play_penalty_must_be_accepted')
    if len(penalty.fouls) != 1:
        raise UnsupportedEventTransition('multiple_penalty_fouls_need_joint_ruling')
    foul = penalty.fouls[0]
    if foul.team not in ('offense', 'defense'):
        raise UnsupportedEventTransition('scrimmage_penalty_team_role_unsupported:' + foul.team)
    try:
        classification = classify_penalty_type(
            foul.penalty_type, foul.team, block_subtype=foul.block_subtype)
        nominal_yards = nominal_yards_for(classification)
    except PenaltyTypeMappingError as exc:
        raise UnsupportedEventTransition(str(exc)) from exc
    if foul.yards_assessed != nominal_yards:
        raise UnsupportedEventTransition(
            f'penalty_nominal_yards_disagree_with_rule:{foul.team}:'
            f'{classification.penalty_type}:expected={nominal_yards}:got={foul.yards_assessed}')
    state_before = _down_state(before)
    if penalty.phase == 'live_ball' and after is None:
        raise UnsupportedEventTransition('live_penalty_after_terminal_play_needs_scoring_rules_integration')
    state_after = state_before if penalty.phase == 'pre_snap' else _down_state(after)
    if penalty.phase == 'live_ball' and play.call.intent in ('punt', 'field_goal', 'kickoff'):
        raise UnsupportedEventTransition('scrimmage_kick_penalty_requires_special_teams_enforcement')
    play_class = ('run' if play.call and play.call.intent in ('designed_run', 'kneel') else
                  'dropback' if play.call and play.call.intent == 'dropback' else None)
    if penalty.phase == 'live_ball' and play_class is None:
        raise UnsupportedEventTransition('penalty_play_class_unsupported')
    if penalty.disposition not in ('accepted', 'declined'):
        raise UnsupportedEventTransition('penalty_disposition_unsupported:' + str(penalty.disposition))
    enforcement = penalty_enforcement.enforce(
        before=state_before,
        after_play=state_after,
        phase=penalty.phase,
        offender=foul.team,
        foul=classification.penalty_type,
        accepted=(penalty.disposition == 'accepted'),
        foul_yardline_100=foul.foul_spot,
        play_class=play_class,
        pass_outcome=('complete' if play.event == 'pass_complete' else
                      'incomplete' if play.event == 'pass_incomplete' else None),
        block_subtype=classification.block_subtype,
        defense_team=before['defense'])
    if (penalty.automatic_first_down is not None
            and penalty.automatic_first_down != enforcement.automatic_first_down):
        raise UnsupportedEventTransition('penalty_first_down_fact_disagrees_with_rules')
    return _state_from_down_state(before, enforcement.state), asdict(enforcement)


def _defensive_recovery(before, play):
    possession = play.possession
    if possession is None or possession.team != 'defense':
        raise UnsupportedEventTransition('defensive_return_requires_defense_possession')
    if possession.how == 'interception':
        _int_spot(possession.turnover_spot_yardline_100, 'interception_spot')
        recovery_spot = possession.turnover_spot_yardline_100
    elif possession.how == 'fumble_recovery':
        fumble_spot = _int_spot(possession.fumble_spot_yardline_100, 'fumble_spot')
        if possession.turnover_spot_yardline_100 != fumble_spot:
            raise UnsupportedEventTransition('fumble_turnover_spot_disagrees_with_fumble_spot')
        recovery_spot = _int_spot(possession.recovery_spot_yardline_100, 'fumble_recovery_spot')
    else:
        raise UnsupportedEventTransition('defensive_recovery_kind_unsupported')
    dead_spot = _int_spot(possession.dead_ball_yardline_100, 'return_dead_ball_spot')
    return_yards = possession.return_yards or 0
    if return_yards > 100 - recovery_spot:
        raise UnsupportedEventTransition('defensive_return_yards_cross_goal_line')
    expected_dead_spot = recovery_spot + return_yards
    if not 0 <= expected_dead_spot <= 100:
        raise UnsupportedEventTransition('defensive_return_crosses_goal_line_without_endpoint')
    if dead_spot != expected_dead_spot:
        raise UnsupportedEventTransition('defensive_return_yards_disagree_with_dead_ball_spot')
    if play.event == 'interception' and possession.how != 'interception':
        raise UnsupportedEventTransition('interception_recovery_fact_mismatch')
    if play.event != 'interception' and possession.how == 'interception':
        raise UnsupportedEventTransition('non_interception_has_interception_recovery')

    flags = {'turnover': True, 'interception': possession.how == 'interception',
             'fumble': possession.how == 'fumble_recovery', 'return_yards': return_yards,
             'return_team': before['defense']}
    if play.event == 'sack':
        flags['sack'] = True
    if dead_spot == 100:
        if play.scoring is None or play.scoring.kind != 'touchdown' or play.scoring.team != 'defense':
            raise UnsupportedEventTransition('defensive_return_goal_line_needs_touchdown_fact')
        flags['touchdown'] = True
        return AppliedEvent(None, 'touchdown', flags, before['defense'])
    if possession.touchback:
        if dead_spot != 0 or play.scoring is not None:
            raise UnsupportedEventTransition('defensive_touchback_fact_disagrees_with_dead_ball')
        restart = possession.next_possession_yardline_100
        after = {'offense': before['defense'], 'defense': before['offense'], 'down': 1,
                 'togo': min(10, restart), 'yl': restart}
        flags['touchback'] = True
        return AppliedEvent(after, 'turnover', flags)
    if dead_spot == 0:
        if play.scoring is None or play.scoring.kind != 'safety' or play.scoring.team != 'offense':
            raise UnsupportedEventTransition('defensive_return_own_goal_line_needs_safety_fact')
        flags['safety'] = True
        return AppliedEvent(None, 'safety', flags, before['offense'])
    if play.scoring is not None:
        raise UnsupportedEventTransition('nonterminal_defensive_return_has_scoring_fact')
    receiving_spot = 100 - dead_spot
    after = {'offense': before['defense'], 'defense': before['offense'], 'down': 1,
             'togo': min(10, receiving_spot), 'yl': receiving_spot}
    return AppliedEvent(after, 'turnover', flags)


def _apply_base_play(state, play):
    event = {'scramble': 'run', 'kneel': 'run', 'spike': 'pass_incomplete'}.get(play.event, play.event)
    if event not in ('run', 'pass_complete', 'pass_incomplete', 'sack', 'field_goal_attempt'):
        raise UnsupportedEventTransition('base_event_transition_unavailable:' + str(play.event))
    if event == 'field_goal_attempt':
        return None, 'field_goal_attempt', {'field_goal_attempt': True}
    try:
        after, terminal, flags = reducer.apply_play(state, event, play.yards_gained)
    except (AssertionError, ValueError) as exc:
        raise UnsupportedEventTransition('base_event_reducer_rejected:' + str(exc)) from exc
    if play.scoring is not None:
        scorer = state['offense'] if play.scoring.team == 'offense' else state['defense']
        if play.scoring.kind == 'touchdown' and (terminal != 'touchdown' or scorer != state['offense']):
            raise UnsupportedEventTransition('offensive_touchdown_fact_disagrees_with_transition')
        if play.scoring.kind == 'safety' and (terminal != 'safety' or scorer != state['defense']):
            raise UnsupportedEventTransition('safety_fact_disagrees_with_transition')
    if play.event == 'sack':
        flags['sack'] = True
    if play.event == 'scramble':
        flags['scramble'] = True
    if play.event == 'spike':
        flags['spike'] = True
    return after, terminal, flags


def apply_scrimmage_play(state, play, switches=FROZEN_CONTROL):
    """Validate and apply a non-kick ceg-play-2 fact against an E1-style state.

    This does not mutate the released runner, random streams, or stats.  The
    returned facts are intended to be reviewed against V1 Complete and CEG
    before a caller admits newly classified source rows.
    """
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    contract.validate_v2(state, play)
    if play.event in ('punt', 'field_goal_attempt', 'kickoff'):
        raise UnsupportedEventTransition('kick_transition_not_integrated_in_scrimmage_adapter')
    if play.event == 'no_play':
        after, enforcement = _apply_penalty(state, state, play, switches)
        foul = play.penalty.fouls[0]
        flags = {'no_play': True, 'snap_occurred': False, 'penalty': True,
                 'penalty_accepted': enforcement['accepted'], 'penalty_yards': enforcement['yards'],
                 'penalty_type': foul.penalty_type, 'penalty_offender_team': foul.team,
                 'automatic_first_down': enforcement['automatic_first_down'],
                 'first_down': enforcement['automatic_first_down']}
        return AppliedEvent(after, None, flags, penalty_enforcement=enforcement)

    if play.event == 'kneel':
        _require_switch(switches, 'kneel_events')
    if play.event == 'spike':
        _require_switch(switches, 'spike_events')

    if play.event == 'interception' and play.possession.return_yards:
        _require_switch(switches, 'interception_returns')
    if play.event == 'interception' and play.scoring is not None:
        _require_switch(switches, 'interception_returns')
    if play.possession is not None and play.possession.touchback:
        _require_switch(switches, 'turnover_terminal_events')
    if play.fumble:
        if play.event == 'sack':
            _require_switch(switches, 'sack_fumble_transitions')
        else:
            _require_switch(switches, 'fumble_returns')
        if play.possession and any(spot in (0, 100) for spot in (
                play.possession.turnover_spot_yardline_100,
                play.possession.recovery_spot_yardline_100,
                play.possession.dead_ball_yardline_100)):
            _require_switch(switches, 'own_end_zone_recovery')
        if play.event != 'sack' and play.possession and play.possession.team == 'defense' and (
                play.possession.return_yards or play.scoring is not None):
            _require_switch(switches, 'fumble_returns')

    if play.event == 'interception' or (play.fumble and play.possession.team == 'defense'):
        result = _defensive_recovery(state, play)
    elif play.fumble and play.possession.team == 'offense':
        after, terminal, flags = _apply_base_play(state, play)
        dead_spot = _int_spot(play.possession.dead_ball_yardline_100, 'offense_fumble_dead_ball_spot')
        if terminal == 'touchdown' and dead_spot != 0:
            raise UnsupportedEventTransition('offensive_fumble_touchdown_spot_mismatch')
        if terminal == 'safety' and dead_spot != 100:
            raise UnsupportedEventTransition('offensive_fumble_safety_spot_mismatch')
        if after is not None and after['yl'] != dead_spot:
            raise UnsupportedEventTransition('offense_recovery_spot_disagrees_with_play_yards')
        flags['fumble'] = True
        flags['recovered_by'] = 'offense'
        result = AppliedEvent(after, terminal, flags,
                              state['offense'] if terminal == 'touchdown' else
                              state['defense'] if terminal == 'safety' else None)
    else:
        after, terminal, flags = _apply_base_play(state, play)
        result = AppliedEvent(after, terminal, flags,
                              state['offense'] if terminal == 'touchdown' else
                              state['defense'] if terminal == 'safety' else None)

    if play.penalty is not None:
        after, enforcement = _apply_penalty(state, result.state_after, play, switches)
        flags = dict(result.flags)
        foul = play.penalty.fouls[0]
        flags.update({
            'penalty': True,
            'penalty_accepted': enforcement['accepted'],
            'penalty_yards': enforcement['yards'],
            'penalty_type': foul.penalty_type,
            'penalty_offender_team': foul.team,
            'automatic_first_down': enforcement['automatic_first_down'],
            'first_down': flags.get('first_down', False) or enforcement['automatic_first_down'],
        })
        result = AppliedEvent(after, result.terminal, flags, result.scoring_team, enforcement)
    return result


def apply_punt_play(state, play, switches=FROZEN_CONTROL):
    """Apply classified punt, return, touchback or muff facts in one field frame."""
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    contract.validate_v2(state, play)
    if play.event != 'punt' or play.kick is None or play.kick.kind != 'punt':
        raise UnsupportedEventTransition('punt_transition_requires_typed_punt_record')
    kick = play.kick
    if (kick.kicking_team, kick.receiving_team) != (state['offense'], state['defense']):
        raise UnsupportedEventTransition('punt_team_roles_disagree_with_pre_kick_state')
    if kick.kick_spot_yardline_100 != state['yl']:
        raise UnsupportedEventTransition('punt_spot_disagrees_with_pre_kick_state')
    if kick.result in ('return', 'muff', 'touchback'):
        _require_switch(switches, 'punt_return_events')
    if kick.result == 'period_expired':
        return AppliedEvent(None, 'end_of_period', {'punt_attempt': True, 'period_expired': True})
    if kick.result == 'blocked':
        raise UnsupportedEventTransition('blocked_punt_requires_existing_classified_blocked_kick_path')
    if kick.result not in ('return', 'touchback', 'muff'):
        raise UnsupportedEventTransition('punt_result_not_supported:' + str(kick.result))

    dead_spot = _int_spot(kick.dead_ball_yardline_100, 'punt_dead_ball_spot')
    return_yards = kick.return_yards or 0
    possession_side = kick.possession_after
    flags = {'punt': True, 'punt_attempt': True,
             'return_yards': return_yards, 'returner_id': kick.returner.stat_player_id}

    if kick.result == 'return':
        if possession_side != 'receiving_team':
            raise UnsupportedEventTransition('ordinary_punt_return_must_end_with_receiving_team')
        start = _int_spot(kick.return_start_yardline_100, 'punt_return_start_spot')
        if start < kick.kick_spot_yardline_100:
            raise UnsupportedEventTransition('punt_return_start_or_distance_is_impossible')
        expected_dead = start + return_yards
        if not 0 <= expected_dead <= 100 or dead_spot != expected_dead:
            raise UnsupportedEventTransition('punt_return_yards_disagree_with_dead_ball_spot')
    elif kick.result == 'muff':
        recovery = _int_spot(kick.recovery_yardline_100, 'punt_recovery_spot')
        fumble_spot = _int_spot(kick.fumble_spot_yardline_100, 'punt_fumble_spot')
        if kick.recovery_team not in ('kicking_team', 'receiving_team'):
            raise UnsupportedEventTransition('punt_muff_recovery_team_missing')
        if possession_side == 'receiving_team':
            if kick.recovery_team != 'receiving_team':
                raise UnsupportedEventTransition('receiving_muff_recovery_team_mismatch')
            expected_dead = recovery + return_yards
            if (kick.recovery_team != 'receiving_team' or not 0 <= expected_dead <= 100
                    or dead_spot != expected_dead):
                raise UnsupportedEventTransition('receiving_muff_recovery_facts_disagree')
        else:
            if kick.recovery_team != 'kicking_team':
                raise UnsupportedEventTransition('punt_possession_role_mismatch')
            if recovery <= kick.kick_spot_yardline_100:
                raise UnsupportedEventTransition('behind_line_punt_recovery_uses_blocked_kick_path')
            if kick.receiving_team_touched_beyond_line is not True:
                raise UnsupportedEventTransition('kicking_team_punt_recovery_needs_receiving_touch')
            expected_dead = recovery - return_yards
            if not 0 <= expected_dead <= 100 or dead_spot != expected_dead:
                raise UnsupportedEventTransition('kicking_team_return_yards_disagree_with_dead_ball_spot')
    elif possession_side != 'receiving_team':
        raise UnsupportedEventTransition('punt_touchback_must_award_receiving_team')

    if play.scoring is not None:
        if play.scoring.kind == 'touchdown':
            scorer = {'kicking_team': state['offense'], 'receiving_team': state['defense']}.get(play.scoring.team)
            if scorer is None or possession_side != play.scoring.team \
                    or dead_spot != (0 if play.scoring.team == 'kicking_team' else 100):
                raise UnsupportedEventTransition('punt_touchdown_scorer_or_spot_mismatch')
            flags['touchdown'] = True
            flags['return_touchdown'] = True
            return AppliedEvent(None, 'touchdown', flags, scorer)
        if play.scoring.kind == 'safety':
            if play.scoring.team != 'kicking_team' or dead_spot != 0 or possession_side != 'receiving_team':
                raise UnsupportedEventTransition('punt_safety_scorer_or_spot_mismatch')
            flags['safety'] = True
            return AppliedEvent(None, 'safety', flags, state['offense'])
        raise UnsupportedEventTransition('punt_cannot_score_field_goal')
    if dead_spot in (0, 100):
        raise UnsupportedEventTransition('punt_goal_line_endpoint_needs_touchdown_or_safety_fact')

    if possession_side == 'kicking_team':
        after = {'offense': state['offense'], 'defense': state['defense'], 'down': 1,
                 'togo': min(10, dead_spot), 'yl': dead_spot}
        flags['possession_retained'] = True
    else:
        after = {'offense': state['defense'], 'defense': state['offense'], 'down': 1,
                 'togo': min(10, 100 - dead_spot), 'yl': 100 - dead_spot}
        flags['turnover'] = True
    return AppliedEvent(after, 'punt', flags)
