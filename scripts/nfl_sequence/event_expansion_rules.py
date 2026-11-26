"""Fail-closed V2 adapters for selected historical event facts.

The frozen E1 loop does not call this module.  It is an opt-in rules adapter
for ceg-play-2 records on the event-expansion branch, so the released V2 path
and its source-row filters remain unchanged until an integration is reviewed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import ceg_contract as contract
import ceg_contract_v3 as contract_v3
import game_state
import penalty_enforcement
import reducer
from event_expansion import EXPANDED_DEFAULT, EventExpansionSwitches
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
        return after, None, True
    switch = 'pre_snap_penalties' if penalty.phase == 'pre_snap' else 'live_ball_penalties'
    _require_switch(switches, switch)
    if penalty.phase == 'pre_snap' and penalty.disposition != 'accepted':
        if penalty.disposition != 'offsetting':
            raise UnsupportedEventTransition('pre_snap_no_play_penalty_must_be_accepted')

    classifications = []
    for index, foul in enumerate(penalty.fouls):
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
        classifications.append((foul, classification))

    if penalty.disposition == 'offsetting':
        if {foul.team for foul, _ in classifications} != {'offense', 'defense'}:
            raise UnsupportedEventTransition('offsetting_penalties_need_opposing_teams')
        if penalty.phase == 'pre_snap' and play.event != 'no_play':
            raise UnsupportedEventTransition('offsetting_pre_snap_penalty_requires_no_play_event')
        if (play.event in ('interception', 'fumble_lost')
                and after is not None and after.get('offense') != before.get('offense')):
            raise UnsupportedEventTransition('offsetting_penalty_turnover_sequence_needs_foul_order')
        state = _down_state(before)
        enforcement = {'state': asdict(state), 'accepted': False, 'yards': 0,
                       'rule_basis': 'offsetting live-ball fouls; replay down',
                       'play_counts': False, 'replay_down': True,
                       'automatic_first_down': False, 'loss_of_down': False,
                       'turnover_on_downs': False, 'clock_action': 'replay_down',
                       'enforcement_spot': 'previous', 'safety': False,
                       'offsetting': True,
                       'fouls': [{'penalty_type': foul.penalty_type, 'team': foul.team,
                                  'foul_spot': foul.foul_spot,
                                  'offender_id': foul.player.stat_player_id}
                                 for foul, _ in classifications]}
        return _state_from_down_state(before, state), enforcement, False

    if penalty.disposition == 'accepted' and len(penalty.fouls) != 1:
        raise UnsupportedEventTransition('multiple_accepted_fouls_need_shared_ceg_play_2_rules')
    selected_index = 0
    foul, classification = classifications[selected_index]
    state_before = _down_state(before)
    terminal_play = penalty.phase == 'live_ball' and (
        after is None or (penalty.disposition == 'accepted' and after.get('offense') != before.get('offense')))
    state_after = (state_before if penalty.phase == 'pre_snap' or terminal_play
                   else _down_state(after))
    if penalty.phase == 'live_ball' and play.call.intent in ('punt', 'field_goal', 'kickoff'):
        raise UnsupportedEventTransition('scrimmage_kick_penalty_requires_special_teams_enforcement')
    play_class = ('run' if play.call and play.call.intent in ('designed_run', 'kneel') else
                  'dropback' if play.call and play.call.intent == 'dropback' else None)
    if penalty.phase == 'live_ball' and play_class is None and play.event == 'interception':
        play_class = 'dropback'
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
                      'incomplete' if play.event in ('pass_incomplete', 'interception') else None),
        block_subtype=classification.block_subtype,
        defense_team=before['defense'])
    if (penalty.automatic_first_down is not None
            and penalty.automatic_first_down != enforcement.automatic_first_down):
        raise UnsupportedEventTransition('penalty_first_down_fact_disagrees_with_rules')
    enforcement_record = asdict(enforcement)
    enforcement_record['selected_foul_index'] = selected_index
    enforcement_record['offender_team'] = foul.team
    enforcement_record['offender_id'] = foul.player.stat_player_id
    enforcement_record['penalty_type'] = foul.penalty_type
    if len(classifications) > 1:
        enforcement_record['nullified_fouls'] = [
            {'penalty_type': other_foul.penalty_type, 'team': other_foul.team,
             'offender_id': other_foul.player.stat_player_id}
            for index, (other_foul, _) in enumerate(classifications) if index != selected_index]
    if enforcement.safety:
        enforcement_record['scoring_team'] = before['defense']
        enforcement_record['play_counts'] = False
        return None, enforcement_record, False
    if terminal_play and enforcement.accepted and not enforcement.play_counts:
        return _state_from_down_state(before, enforcement.state), enforcement_record, False
    return (after if terminal_play and not enforcement.accepted else
            None if terminal_play and enforcement.play_counts else
            _state_from_down_state(before, enforcement.state),
            enforcement_record, True)


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
             'return_team': before['defense'],
             'returner_id': possession.returner.stat_player_id,
             'recoverer_id': possession.recovered_by.stat_player_id}
    if play.event == 'sack':
        flags['sack'] = True
    if dead_spot == 100:
        if play.scoring is None or play.scoring.kind != 'touchdown' or play.scoring.team != 'defense':
            raise UnsupportedEventTransition('defensive_return_goal_line_needs_touchdown_fact')
        flags['touchdown'] = True
        flags['return_touchdown'] = True
        return AppliedEvent(None, 'touchdown', flags, before['defense'])
    if possession.touchback:
        if dead_spot != 0 or play.scoring is not None:
            raise UnsupportedEventTransition('defensive_touchback_fact_disagrees_with_dead_ball')
        restart = possession.next_yardline_100
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


def _apply_base_play(state, play, yards_override=None):
    event = {'scramble': 'run', 'kneel': 'run', 'spike': 'pass_incomplete'}.get(play.event, play.event)
    if event not in ('run', 'pass_complete', 'pass_incomplete', 'sack', 'field_goal_attempt'):
        raise UnsupportedEventTransition('base_event_transition_unavailable:' + str(play.event))
    if event == 'field_goal_attempt':
        return None, 'field_goal_attempt', {'field_goal_attempt': True}
    try:
        after, terminal, flags = reducer.apply_play(
            state, event, play.yards_gained if yards_override is None else yards_override)
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


def apply_scrimmage_play(state, play, switches=EXPANDED_DEFAULT):
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
        after, enforcement, _ = _apply_penalty(state, state, play, switches)
        foul_index = 0
        foul = play.penalty.fouls[foul_index]
        flags = {'no_play': True, 'snap_occurred': False, 'penalty': True,
                 'penalty_accepted': enforcement['accepted'], 'penalty_yards': enforcement['yards'],
                 'penalty_type': foul.penalty_type, 'penalty_offender_team': foul.team,
                 'penalty_offender_id': foul.player.stat_player_id,
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
        dead_spot = _int_spot(play.possession.dead_ball_yardline_100, 'offense_fumble_dead_ball_spot')
        net_yards = state['yl'] - dead_spot
        after, terminal, flags = _apply_base_play(state, play, yards_override=net_yards)
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
        after, enforcement, play_counts = _apply_penalty(state, result.state_after, play, switches)
        flags = dict(result.flags)
        foul_index = enforcement.get('selected_foul_index', 0)
        foul = play.penalty.fouls[foul_index]
        terminal = result.terminal if not enforcement.get('accepted') or enforcement.get('play_counts') else None
        scoring_team = result.scoring_team if terminal is not None else None
        if enforcement.get('safety'):
            terminal = 'safety'
            scoring_team = state['defense']
            for name in ('touchdown', 'turnover', 'interception', 'fumble', 'touchback',
                         'punt_return', 'return_touchdown', 'possession_retained', 'first_down',
                         'scoring_team'):
                if name in flags:
                    flags[name] = False if name != 'scoring_team' else None
            for name in ('return_yards', 'return_team', 'returner_id', 'recovered_by'):
                flags.pop(name, None)
            flags['safety'] = True
            flags['scoring_team'] = state['defense']
        elif enforcement.get('accepted') and not play_counts:
            terminal = 'turnover_on_downs' if enforcement['turnover_on_downs'] else None
            scoring_team = None
            for name in ('touchdown', 'safety', 'turnover', 'interception', 'fumble', 'touchback',
                         'punt_return', 'return_touchdown', 'possession_retained', 'first_down',
                         'scoring_team'):
                if name in flags:
                    flags[name] = False if name != 'scoring_team' else None
            for name in ('return_yards', 'return_team', 'returner_id', 'recovered_by'):
                flags.pop(name, None)
            flags['turnover_on_downs'] = enforcement['turnover_on_downs']
            flags['first_down'] = enforcement['automatic_first_down']
        if enforcement.get('offsetting'):
            for name in ('touchdown', 'safety', 'turnover', 'interception', 'fumble', 'touchback',
                         'punt_return', 'return_touchdown', 'possession_retained', 'first_down',
                         'scoring_team'):
                if name in flags:
                    flags[name] = False if name != 'scoring_team' else None
            for name in ('return_yards', 'return_team', 'returner_id', 'recovered_by'):
                flags.pop(name, None)
            flags['turnover_on_downs'] = False
            flags['first_down'] = False
        flags.update({
            'penalty': True,
            'penalty_accepted': enforcement['accepted'],
            'penalty_yards': enforcement['yards'],
            'penalty_type': foul.penalty_type,
            'penalty_offender_team': foul.team,
            'penalty_offender_id': foul.player.stat_player_id,
            'automatic_first_down': enforcement['automatic_first_down'],
            'first_down': flags.get('first_down', False) or enforcement['automatic_first_down'],
        })
        result = AppliedEvent(after, terminal, flags, scoring_team, enforcement)
    return result


def apply_punt_play(state, play, switches=EXPANDED_DEFAULT):
    """Apply classified punt, return, touchback or muff facts in one field frame."""
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    if play.kick is not None and play.kick.result in ('downed', 'fair_catch', 'out_of_bounds'):
        raise UnsupportedEventTransition(
            'punt_result_requires_ceg_play_2_extension:' + play.kick.result)
    contract.validate_v2(state, play)
    if play.event != 'punt' or play.kick is None or play.kick.kind != 'punt':
        raise UnsupportedEventTransition('punt_transition_requires_typed_punt_record')
    kick = play.kick
    if (kick.kicking_team, kick.receiving_team) != (state['offense'], state['defense']):
        raise UnsupportedEventTransition('punt_team_roles_disagree_with_pre_kick_state')
    if kick.kick_spot_yardline_100 != state['yl']:
        raise UnsupportedEventTransition('punt_spot_disagrees_with_pre_kick_state')
    if kick.result in ('return', 'muff', 'touchback', 'downed', 'fair_catch', 'out_of_bounds'):
        _require_switch(switches, 'punt_return_events')
    if kick.result == 'period_expired':
        return AppliedEvent(None, 'end_of_period', {'punt_attempt': True, 'period_expired': True})
    if kick.result == 'blocked':
        raise UnsupportedEventTransition('blocked_punt_requires_existing_classified_blocked_kick_path')
    if kick.result not in ('return', 'touchback', 'muff', 'downed', 'fair_catch', 'out_of_bounds'):
        raise UnsupportedEventTransition('punt_result_not_supported:' + str(kick.result))

    dead_spot = _int_spot(kick.dead_ball_yardline_100, 'punt_dead_ball_spot')
    return_yards = kick.return_yards or 0
    possession_side = kick.possession_after
    flags = {'punt': True, 'punt_attempt': True,
             'punt_return': kick.result == 'return' and kick.returner.status != 'none',
             'fair_catch': kick.result == 'fair_catch' or bool(play.probabilities.get('fair_catch'))}
    if kick.result in ('return', 'muff'):
        flags.update({'return_yards': kick.return_yards or 0,
                      'returner_id': kick.returner.stat_player_id})
    if kick.result == 'muff':
        flags['fumble'] = True

    if kick.result == 'return':
        if possession_side != 'receiving_team':
            raise UnsupportedEventTransition('ordinary_punt_return_must_end_with_receiving_team')
        start = _int_spot(kick.return_start_yardline_100, 'punt_return_start_spot')
        if start > kick.kick_spot_yardline_100:
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
            if recovery >= kick.kick_spot_yardline_100:
                raise UnsupportedEventTransition('behind_line_punt_recovery_uses_blocked_kick_path')
            if kick.receiving_team_touched_beyond_line is not True:
                raise UnsupportedEventTransition('kicking_team_punt_recovery_needs_receiving_touch')
            expected_dead = recovery + return_yards
            if not 0 <= expected_dead <= 100 or dead_spot != expected_dead:
                raise UnsupportedEventTransition('kicking_team_return_yards_disagree_with_dead_ball_spot')
    elif kick.result in ('downed', 'fair_catch', 'out_of_bounds'):
        if possession_side != 'receiving_team':
            raise UnsupportedEventTransition('nonreturn_punt_must_award_receiving_team')
        if kick.result == 'fair_catch':
            start = _int_spot(kick.return_start_yardline_100, 'fair_catch_spot')
            if kick.returner.status == 'none' or start != dead_spot:
                raise UnsupportedEventTransition('fair_catch_spot_or_catcher_invalid')
        elif kick.returner.status != 'none' or kick.return_yards is not None:
            raise UnsupportedEventTransition('downed_or_out_of_bounds_punt_has_returner_or_yards')
        if kick.result == 'out_of_bounds' and not kick.out_of_bounds:
            raise UnsupportedEventTransition('punt_out_of_bounds_flag_missing')
    elif possession_side != 'receiving_team':
        raise UnsupportedEventTransition('punt_touchback_must_award_receiving_team')
    elif dead_spot != 20:
        raise UnsupportedEventTransition('punt_touchback_spot_must_be_20_in_kicking_team_frame')

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


def apply_field_goal_play(state, play, switches=EXPANDED_DEFAULT):
    """Validate and classify a generated field-goal attempt for the E1 game loop."""
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    contract.validate_v2(state, play)
    if play.event != 'field_goal_attempt' or play.kick is None or play.kick.kind != 'field_goal':
        raise UnsupportedEventTransition('field_goal_transition_requires_typed_field_goal_record')
    kick = play.kick
    if (kick.kicking_team, kick.receiving_team) != (state['offense'], state['defense']):
        raise UnsupportedEventTransition('field_goal_team_roles_disagree_with_pre_kick_state')
    if kick.result not in ('made', 'missed', 'period_expired'):
        if kick.result != 'blocked':
            raise UnsupportedEventTransition('field_goal_result_not_supported:' + str(kick.result))
        _require_switch(switches, 'blocked_kick_transitions')
        if kick.recovery_team not in ('kicking_team', 'receiving_team'):
            raise UnsupportedEventTransition('blocked_field_goal_recovery_team_missing')
        recovery_spot = _int_spot(kick.recovery_yardline_100, 'blocked_field_goal_recovery_spot')
        dead_spot = _int_spot(kick.dead_ball_yardline_100, 'blocked_field_goal_dead_ball_spot')
        flags = {'field_goal_attempt': True, 'field_goal_result': 'blocked',
                 'blocked_kick': {'kick_type': 'field_goal',
                                  'recovery_role': kick.recovery_team,
                                  'recovery_yardline_100': recovery_spot,
                                  'dead_ball_yardline_100': dead_spot,
                                  'return_yards': kick.return_yards,
                                  'recoverer_id': kick.recoverer.stat_player_id,
                                  'returner_id': kick.returner.stat_player_id,
                                  'execution_source': 'gridiron_live_player_execution'}}
        if play.scoring is not None:
            if dead_spot not in (0, 100):
                raise UnsupportedEventTransition('blocked_field_goal_score_needs_goal_line_endpoint')
            scoring_team = (state['offense'] if play.scoring.team == 'kicking_team' else
                            state['defense'] if play.scoring.team == 'receiving_team' else None)
            if scoring_team is None:
                raise UnsupportedEventTransition('blocked_field_goal_scoring_role_invalid')
            flags['touchdown' if play.scoring.kind == 'touchdown' else 'safety'] = True
            flags['return_touchdown'] = play.scoring.kind == 'touchdown'
            flags['scoring_team'] = scoring_team
            return AppliedEvent(None, play.scoring.kind, flags, scoring_team)
        if dead_spot in (0, 100):
            raise UnsupportedEventTransition('blocked_field_goal_goal_line_endpoint_needs_score_fact')
        if recovery_spot in (0, 100):
            raise UnsupportedEventTransition('blocked_field_goal_recovery_goal_line_needs_explicit_score')
        if kick.recovery_team == 'receiving_team':
            if (kick.return_yards is None or recovery_spot + kick.return_yards != dead_spot):
                raise UnsupportedEventTransition('blocked_field_goal_return_geometry_mismatch')
            after = {'offense': state['defense'], 'defense': state['offense'], 'down': 1,
                     'togo': min(10, 100 - dead_spot), 'yl': 100 - dead_spot}
            flags['turnover'] = True
            flags['return_yards'] = kick.return_yards
            flags['return_team'] = 'defense'
            flags['returner_id'] = kick.returner.stat_player_id
            return AppliedEvent(after, 'turnover', flags)
        outcome = {'kick_type': 'field_goal', 'classification_status': 'classified_recovery',
                   'recovery_role': 'kicking_team',
                   'recovery_yards_from_los': state['yl'] - recovery_spot,
                   'return_endpoint_yards_from_los': state['yl'] - dead_spot,
                   'receiving_team_touched_beyond_line': kick.receiving_team_touched_beyond_line}
        try:
            after, terminal, reducer_flags = reducer.apply_blocked_kick(
                state, 'blocked_field_goal', outcome)
        except (AssertionError, ValueError) as exc:
            raise UnsupportedEventTransition('blocked_field_goal_reducer_rejected:' + str(exc)) from exc
        flags.update(reducer_flags)
        return AppliedEvent(after, terminal, flags,
                            state['offense'] if terminal == 'touchdown' else
                            state['defense'] if terminal == 'safety' else None)
    flags = {'field_goal_attempt': True, 'field_goal_result': kick.result}
    if kick.result == 'period_expired':
        flags['period_expired'] = True
        return AppliedEvent(None, 'field_goal_attempt', flags)
    if (kick.result == 'made') != (play.scoring is not None):
        raise UnsupportedEventTransition('field_goal_scoring_fact_disagrees_with_kick_result')
    return AppliedEvent(None, 'field_goal_attempt', flags,
                        state['offense'] if kick.result == 'made' else None)


def apply_kickoff_play(state, play, switches=EXPANDED_DEFAULT):
    """Apply an autonomous free kick in the kicking team's yardline frame."""
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    if play.kick is not None and play.kick.result == 'out_of_bounds':
        raise UnsupportedEventTransition('kickoff_out_of_bounds_requires_ceg_play_2_extension')
    contract.validate_v2(state, play)
    if play.event != 'kickoff' or play.kick is None or play.kick.kind != 'kickoff':
        raise UnsupportedEventTransition('kickoff_transition_requires_typed_kickoff_record')
    kick = play.kick
    if (kick.kicking_team, kick.receiving_team) != (state['offense'], state['defense']):
        raise UnsupportedEventTransition('kickoff_team_roles_disagree_with_pre_kick_state')
    if kick.kick_spot_yardline_100 != state.get('yl'):
        raise UnsupportedEventTransition('kickoff_spot_disagrees_with_pre_kick_state')
    _require_switch(switches, 'punt_return_events')
    dead_spot = kick.dead_ball_yardline_100
    if dead_spot is not None:
        dead_spot = _int_spot(dead_spot, 'kickoff_dead_ball_spot')
    flags = {'kickoff': True, 'return_yards': kick.return_yards or 0,
             'returner_id': kick.returner.stat_player_id}
    if kick.result == 'period_expired':
        return AppliedEvent(None, 'end_of_period', {**flags, 'period_expired': True})
    if kick.result == 'touchback':
        expected_dead = 20 if kick.kick_spot_yardline_100 == 80 else 35
        if dead_spot != expected_dead or kick.possession_after != 'receiving_team':
            raise UnsupportedEventTransition('kickoff_touchback_spot_disagrees_with_free_kick_type')
        after = {'offense': state['defense'], 'defense': state['offense'], 'down': 1,
                 'togo': 10, 'yl': 100 - expected_dead}
        flags['touchback'] = True
        flags['turnover'] = True
        return AppliedEvent(after, 'kickoff', flags)
    if kick.result == 'out_of_bounds':
        out_spot = _int_spot(kick.out_of_bounds_spot_yardline_100, 'kickoff_out_of_bounds_spot')
        yards_from_kick = 30 if kick.restart_option == '30_yards_from_safety_kick' else 25
        expected_dead = (out_spot if kick.restart_option == 'inbounds_spot'
                         else kick.kick_spot_yardline_100 - yards_from_kick)
        if (not kick.out_of_bounds or kick.possession_after != 'receiving_team'
                or dead_spot != expected_dead):
            raise UnsupportedEventTransition('kickoff_out_of_bounds_enforcement_spot_mismatch')
        if (kick.restart_option == '30_yards_from_safety_kick') != (kick.kick_spot_yardline_100 == 80):
            raise UnsupportedEventTransition('kickoff_out_of_bounds_restart_distance_mismatch')
        flags.update({'kickoff_out_of_bounds': True, 'penalty': True,
                      'penalty_accepted': True,
                      'penalty_enforcement': {'accepted': True, 'play_counts': False,
                                              'offender_team': 'offense', 'yards': 0,
                                              'rule_basis': 'NFL Rule 6-2-4',
                                              'restart_option': kick.restart_option,
                                              'out_of_bounds_spot_yardline_100': out_spot}})
        after = {'offense': state['defense'], 'defense': state['offense'], 'down': 1,
                 'togo': min(10, 100 - dead_spot), 'yl': 100 - dead_spot}
        return AppliedEvent(after, 'kickoff', flags)
    if kick.result == 'return':
        start = _int_spot(kick.return_start_yardline_100, 'kickoff_return_start_spot')
        yards = kick.return_yards
        if kick.possession_after != 'receiving_team' or start > kick.kick_spot_yardline_100:
            raise UnsupportedEventTransition('kickoff_return_geometry_or_possession_invalid')
        if start + yards != dead_spot:
            raise UnsupportedEventTransition('kickoff_return_yards_disagree_with_dead_ball_spot')
    elif kick.result == 'muff':
        recovery = _int_spot(kick.recovery_yardline_100, 'kickoff_recovery_spot')
        if kick.recovery_team != kick.possession_after or kick.recovery_team not in (
                'kicking_team', 'receiving_team'):
            raise UnsupportedEventTransition('kickoff_muff_recovery_team_mismatch')
        if kick.recovery_team == 'receiving_team':
            if recovery != dead_spot:
                raise UnsupportedEventTransition('receiving_kickoff_muff_dead_ball_spot_mismatch')
        else:
            if recovery >= kick.kick_spot_yardline_100:
                raise UnsupportedEventTransition('kicking_team_kickoff_recovery_before_ten_yards')
            if kick.receiving_team_touched_beyond_line is not True:
                raise UnsupportedEventTransition('kicking_team_kickoff_recovery_needs_touch_or_ten_yards')
            if recovery != dead_spot:
                raise UnsupportedEventTransition('kicking_kickoff_muff_dead_ball_spot_mismatch')
        flags['fumble'] = True
        flags['recovered_by'] = kick.recovery_team
    elif kick.result in ('kicking_team_recovery', 'onside_recovery'):
        recovery = _int_spot(kick.recovery_yardline_100, 'kickoff_recovery_spot')
        if kick.recovery_team != 'kicking_team' or kick.possession_after != 'kicking_team':
            raise UnsupportedEventTransition('onside_recovery_possession_mismatch')
        if recovery > kick.kick_spot_yardline_100:
            raise UnsupportedEventTransition('onside_recovery_behind_kick_spot')
        if (kick.kick_spot_yardline_100 - recovery < 10
                and kick.receiving_team_touched_beyond_line is not True):
            raise UnsupportedEventTransition('onside_recovery_before_ten_yards_without_receiving_touch')
        after = {'offense': state['offense'], 'defense': state['defense'], 'down': 1,
                 'togo': min(10, recovery), 'yl': recovery}
        flags.update({'possession_retained': True, 'onside_recovery': True})
        return AppliedEvent(after, 'kickoff', flags)
    else:
        raise UnsupportedEventTransition('kickoff_result_not_supported:' + str(kick.result))

    if play.scoring is not None:
        if (play.scoring.kind != 'touchdown' or play.scoring.team != 'receiving_team'
                or kick.result != 'return' or dead_spot != 100):
            raise UnsupportedEventTransition('kickoff_touchdown_fact_disagrees_with_return')
        flags.update({'touchdown': True, 'return_touchdown': True})
        return AppliedEvent(None, 'touchdown', flags, state['defense'])
    if dead_spot in (0, 100):
        raise UnsupportedEventTransition('kickoff_goal_line_endpoint_needs_scoring_fact')
    if kick.possession_after == 'kicking_team':
        after = {'offense': state['offense'], 'defense': state['defense'], 'down': 1,
                 'togo': min(10, dead_spot), 'yl': dead_spot}
        flags['turnover'] = True
    else:
        after = {'offense': state['defense'], 'defense': state['offense'], 'down': 1,
                 'togo': min(10, 100 - dead_spot), 'yl': 100 - dead_spot}
    return AppliedEvent(after, 'kickoff', flags)


def apply_v3_play(state, play, switches=EXPANDED_DEFAULT):
    """Apply a frozen ceg-play-3 kick result or ordered turnover-return chain."""
    if not isinstance(switches, EventExpansionSwitches):
        raise ValueError('event expansion switches must be typed')
    contract_v3.validate_v3(state, play)
    if play.kick is None:
        return _apply_v3_turnover_chain(state, play, switches)
    return _apply_v3_kick(state, play, switches)


def _v3_spot(spot, team_frame, label):
    try:
        return contract_v3._in_frame(spot, team_frame)
    except (TypeError, ValueError) as exc:
        raise UnsupportedEventTransition(label + '_spot_frame_invalid') from exc


def _v3_team(role, state):
    if role in ('offense', 'kicking_team'):
        return state['offense']
    if role in ('defense', 'receiving_team'):
        return state['defense']
    raise UnsupportedEventTransition('ceg_play_3_team_role_invalid:' + str(role))


def _v3_next_state(state, offense, yardline, label):
    if type(yardline) is not int or not 1 <= yardline <= 99:
        raise UnsupportedEventTransition(label + '_restart_spot_out_of_bounds_without_score')
    defense = state['defense'] if offense == state['offense'] else state['offense']
    return {'offense': offense, 'defense': defense, 'down': 1,
            'togo': min(10, yardline), 'yl': yardline}


def _apply_v3_turnover_chain(state, play, switches):
    chain = play.turnover_chain
    _require_switch(switches, 'interception_returns' if chain.initial_turnover == 'interception'
                    else 'fumble_returns')
    _require_switch(switches, 'fumble_returns')
    dead_offense = _v3_spot(chain.dead_ball_spot, 'offense', 'turnover_chain_dead_ball')
    final_offense = _v3_team(chain.final_possession_team, state)
    flags = {'turnover': True, 'interception': chain.initial_turnover == 'interception',
             'fumble': True, 'turnover_chain': {
                 'initial_turnover': chain.initial_turnover,
                 'initial_possession_team': _v3_team(chain.initial_possession_team, state),
                 'turnover_spot_yardline_100': _v3_spot(chain.turnover_spot, 'offense', 'turnover'),
                 'initial_returner_id': chain.initial_returner.stat_player_id,
                 'initial_return_yards': chain.initial_return_yards,
                 'fumbler_id': chain.fumbler.stat_player_id,
                 'fumble_spot_yardline_100': _v3_spot(chain.fumble_spot, 'offense', 'fumble'),
                 'recoverer_id': chain.recoverer.stat_player_id,
                 'recovery_team': _v3_team(chain.recovery_team, state),
                 'recovery_spot_yardline_100': _v3_spot(chain.recovery_spot, 'offense', 'recovery'),
                 'returner_id': chain.post_recovery_returner.stat_player_id,
                 'return_yards': chain.post_recovery_return_yards,
                 'dead_ball_yardline_100': dead_offense,
                 'final_possession_team': final_offense,
             }, 'return_yards': chain.post_recovery_return_yards,
             'returner_id': chain.post_recovery_returner.stat_player_id,
             'recoverer_id': chain.recoverer.stat_player_id,
             'fumbler_id': chain.fumbler.stat_player_id,
             'fumble_recovery_team': final_offense,
             'fumble_return_yards': chain.post_recovery_return_yards,
             'fumble_lost_team': (_v3_team(chain.initial_possession_team, state)
                                  if final_offense != _v3_team(chain.initial_possession_team, state) else None),
             'possession_change': final_offense != state['offense']}
    if chain.scoring_kind == 'touchdown':
        scorer = _v3_team(chain.scoring_team, state)
        flags.update({'touchdown': True, 'return_touchdown': True, 'scoring_team': scorer})
        return AppliedEvent(None, 'touchdown', flags, scorer)
    if chain.scoring_kind == 'safety':
        scorer = _v3_team(chain.scoring_team, state)
        flags.update({'safety': True, 'scoring_team': scorer})
        return AppliedEvent(None, 'safety', flags, scorer)
    return AppliedEvent(_v3_next_state(state, final_offense,
                                       dead_offense if final_offense == state['offense'] else 100 - dead_offense,
                                       'turnover_chain'),
                        'turnover' if final_offense != state['offense'] else None, flags)


def _apply_v3_kick(state, play, switches):
    kick = play.kick
    if (kick.kicking_team, kick.receiving_team) != (state['offense'], state['defense']):
        raise UnsupportedEventTransition('kick_v3_team_roles_disagree_with_pre_kick_state')
    kick_spot = _v3_spot(kick.kick_spot, 'kicking_team', 'kick')
    if kick_spot != state['yl']:
        raise UnsupportedEventTransition('kick_v3_spot_disagrees_with_pre_kick_state')
    is_punt = kick.kind == 'punt'
    is_field_goal = kick.kind == 'field_goal'
    flags = ({'punt': True, 'punt_attempt': True, 'punt_return': False,
              'fair_catch': False} if is_punt else
             {'field_goal_attempt': True, 'field_goal_result': kick.result} if is_field_goal else
             {'kickoff': True, 'kickoff_return': False, 'fair_catch': False})
    if kick.result in ('return', 'muff', 'fair_catch', 'downed', 'out_of_bounds',
                       'short_of_landing_zone', 'touchback', 'onside_recovery',
                       'kicking_team_recovery', 'blocked'):
        _require_switch(switches, 'punt_return_events' if is_punt or kick.kind in ('kickoff', 'safety_kick')
                        else 'blocked_kick_transitions')
    if kick.result == 'period_expired':
        flags['period_expired'] = True
        return AppliedEvent(None, 'end_of_period', flags)

    if kick.result == 'made':
        if not is_field_goal:
            raise UnsupportedEventTransition('non_field_goal_cannot_be_made')
        return AppliedEvent(None, 'field_goal_attempt', flags, state['offense'])

    if kick.result == 'missed':
        if not is_field_goal:
            raise UnsupportedEventTransition('non_field_goal_cannot_be_missed')
        flags['field_goal_restart_yardline_100'] = _v3_spot(
            kick.receiving_restart_spot, 'receiving_team', 'missed_field_goal_restart')
        return AppliedEvent(None, 'field_goal_attempt', flags)

    if kick.result == 'blocked':
        if not is_field_goal:
            raise UnsupportedEventTransition('blocked_punt_live_recovery_not_supported')
        facts = kick.blocked_field_goal_return
        recovery_team = _v3_team(facts.recovery_team, state)
        dead_kicking = _v3_spot(facts.dead_ball_spot, 'kicking_team', 'blocked_field_goal_dead')
        flags.update({'field_goal_result': 'blocked', 'blocked_kick': {
            'kick_type': 'field_goal', 'recovery_role': facts.recovery_team,
            'recovery_yardline_100': _v3_spot(facts.recovery_spot, 'kicking_team', 'blocked_field_goal_recovery'),
            'dead_ball_yardline_100': dead_kicking, 'return_yards': facts.return_yards,
            'recoverer_id': facts.recoverer.stat_player_id,
            'returner_id': facts.post_block_returner.stat_player_id,
            'execution_source': 'gridiron_live_player_execution'}})
        if facts.scoring_kind:
            scorer = _v3_team(facts.scoring_team, state)
            flags.update({'touchdown': facts.scoring_kind == 'touchdown',
                          'safety': facts.scoring_kind == 'safety',
                          'return_touchdown': facts.scoring_kind == 'touchdown',
                          'scoring_team': scorer})
            return AppliedEvent(None, facts.scoring_kind, flags, scorer)
        if recovery_team != state['offense']:
            next_yard = 100 - dead_kicking
            return AppliedEvent(_v3_next_state(state, recovery_team, next_yard, 'blocked_field_goal'),
                                'turnover', flags)
        # A same-team recovery keeps the down series live and can still turn
        # fourth down over if the carrier does not reach the line to gain.
        net_yards = state['yl'] - dead_kicking
        next_team = state['offense']
        if net_yards >= state['togo']:
            next_down, next_togo = 1, min(10, dead_kicking)
        elif state['down'] >= 4:
            next_team = state['defense']
            next_down, next_togo = 1, min(10, 100 - dead_kicking)
            flags.update({'turnover': True, 'turnover_on_downs': True,
                          'possession_change': True})
        else:
            next_down, next_togo = state['down'] + 1, state['togo'] - net_yards
        after = {'offense': next_team,
                 'defense': state['defense'] if next_team == state['offense'] else state['offense'],
                 'down': next_down, 'togo': next_togo,
                 'yl': dead_kicking if next_team == state['offense'] else 100 - dead_kicking}
        return AppliedEvent(after, 'turnover_on_downs' if next_team != state['offense'] else None, flags)

    return_facts = kick.return_facts
    if return_facts is not None:
        start = return_facts.recovery_spot if kick.result == 'muff' else return_facts.return_start_spot
        return_team = _v3_team(return_facts.returning_team, state)
        returner = (return_facts.post_recovery_returner if kick.result == 'muff'
                    else return_facts.returner)
        flags.update({'return_yards': return_facts.return_yards,
                      'returner_id': returner.stat_player_id,
                      'recoverer_id': return_facts.recoverer.stat_player_id if kick.result == 'muff' else None,
                      'punt_return': bool(is_punt and kick.result == 'return'),
                      'kickoff_return': bool(not is_punt and kick.result == 'return'),
                      'fumble': kick.result == 'muff',
                      'fumbler_id': return_facts.muffing_returner.stat_player_id
                      if kick.result == 'muff' else None,
                      'fumble_return_yards': return_facts.return_yards
                      if kick.result == 'muff' else None,
                      'fair_catch': kick.result == 'fair_catch'})
        if start is not None:
            flags['return_start_yardline_100'] = _v3_spot(start, 'kicking_team', 'kick_return_start')
    if kick.result == 'fair_catch':
        flags.update({'fair_catch': True, 'returner_id': kick.fair_catcher.stat_player_id})
    dead = kick.dead_ball_spot
    if kick.result in ('out_of_bounds', 'short_of_landing_zone') and kick.kickoff_oob is not None:
        dead = kick.kickoff_oob.restart_spot
        flags['kickoff_out_of_bounds'] = True
        flags['penalty'] = True
        flags['penalty_accepted'] = True
        flags['kickoff_out_of_bounds_enforcement'] = {
            'cause': kick.kickoff_oob.cause, 'choice': kick.kickoff_oob.choice,
            'restart_yardline_100': kick.kickoff_oob.restart_spot.yardline_100,
            'rule_basis': 'NFL Rule 6-2-4'}
    if kick.result == 'touchback':
        dead = kick.receiving_restart_spot
        flags['touchback'] = True
        expected_restart = 80 if kick.kind in ('punt', 'safety_kick') else 65
        if _v3_spot(dead, 'receiving_team', 'touchback_restart') != expected_restart:
            raise UnsupportedEventTransition('kick_v3_touchback_restart_spot_invalid')
        if _v3_spot(kick.dead_ball_spot, 'kicking_team', 'touchback_dead_ball') != 0:
            raise UnsupportedEventTransition('kick_v3_touchback_dead_ball_spot_invalid')
    if kick.result == 'muff':
        flags['fumble'] = True
        flags['fumble_recovery_team'] = _v3_team(kick.possession_after, state)
        flags['fumble_lost_team'] = (state['defense']
                                     if kick.possession_after == 'kicking_team' else None)
    if dead is None:
        raise UnsupportedEventTransition('kick_v3_dead_ball_or_restart_spot_required')
    final_role = kick.possession_after
    if final_role is None:
        raise UnsupportedEventTransition('kick_v3_possession_after_required')
    next_offense = _v3_team(final_role, state)
    final_yard = _v3_spot(dead, final_role, 'kick_v3_next_offense')

    scoring = play.scoring
    if scoring is not None:
        scorer = _v3_team(scoring.team, state)
        flags.update({'scoring_team': scorer, 'touchdown': scoring.kind == 'touchdown',
                      'safety': scoring.kind == 'safety',
                      'return_touchdown': scoring.kind == 'touchdown'})
        return AppliedEvent(None, scoring.kind, flags, scorer)
    if kick.result == 'missed':
        actual_kick_spot = game_state.kick_spot_yardline_100(kick_spot)
        expected_restart = game_state.missed_field_goal_spot(actual_kick_spot)
        if _v3_spot(kick.receiving_restart_spot, 'receiving_team', 'missed_field_goal_restart') != expected_restart:
            raise UnsupportedEventTransition('missed_field_goal_restart_spot_invalid')
        if _v3_spot(kick.dead_ball_spot, 'kicking_team', 'missed_field_goal_dead_ball') != 0:
            raise UnsupportedEventTransition('missed_field_goal_dead_ball_spot_invalid')
        flags['field_goal_restart_yardline_100'] = expected_restart
        return AppliedEvent(None, 'field_goal_attempt', flags)
    if final_yard in (0, 100):
        raise UnsupportedEventTransition('kick_v3_goal_line_dead_ball_needs_explicit_score')
    if is_field_goal:
        if kick.result == 'blocked':
            raise UnsupportedEventTransition('blocked_field_goal_transition_not_classified')
        return AppliedEvent(None, 'field_goal_attempt', flags)
    flags['possession_change'] = next_offense != state['offense']
    if is_punt:
        return AppliedEvent(_v3_next_state(state, next_offense, final_yard, 'kick_v3'), 'punt', flags)
    return AppliedEvent(_v3_next_state(state, next_offense, final_yard, 'kick_v3'),
                        'turnover' if next_offense != state['offense'] else 'kickoff', flags)
