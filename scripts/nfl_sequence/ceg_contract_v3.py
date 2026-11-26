"""Additive ceg-play-3 special-teams facts.

ceg-play-2 remains byte-for-byte compatible and is not relaxed.  Play 3 adds
explicitly framed kick spots and role-separated recovery/return facts needed
for kick returns, muff recoveries, safety restarts, and blocked field goals.
This module validates special-teams records and ordered scrimmage turnover
chains. Other scrimmage plays continue to use ceg-play-2 until their producers
migrate.

Spot coordinates use the named team's offensive frame: 0 is that team's
opponent goal line and 100 is that team's own goal line. Return yards are
signed net yards in the returning team's offensive direction and are checked
against the start/recovery and dead-ball spots after coordinate conversion.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Optional

import ceg_contract as v2


CONTRACT_V3_VERSION = 'ceg-play-3'
SpotFrameV3 = Literal['kicking_team', 'receiving_team', 'offense', 'defense']
TeamSideV3 = Literal['kicking_team', 'receiving_team']


@dataclass(frozen=True)
class FieldSpotV3:
    yardline_100: int
    frame: SpotFrameV3


@dataclass(frozen=True)
class KickReturnV3:
    """A return after a catch/recovery; role fields are intentionally distinct."""

    returning_team: TeamSideV3
    returner: v2.PlayerRoleV2
    return_start_spot: Optional[FieldSpotV3]
    dead_ball_spot: FieldSpotV3
    return_yards: int
    muffing_returner: v2.PlayerRoleV2
    recoverer: v2.PlayerRoleV2
    post_recovery_returner: v2.PlayerRoleV2
    recovery_spot: Optional[FieldSpotV3] = None
    fumble_spot: Optional[FieldSpotV3] = None
    scoring_kind: Optional[Literal['touchdown', 'safety']] = None
    scoring_team: Optional[TeamSideV3] = None


@dataclass(frozen=True)
class KickSafetyV3:
    """Safety and its required free-kick/restart facts, all tied to team frames."""

    scoring_team: TeamSideV3
    possessing_team: TeamSideV3
    safety_dead_ball_spot: FieldSpotV3
    free_kick_team: TeamSideV3
    free_kick_spot: FieldSpotV3
    free_kick_spot_basis: Literal['own_20', 'penalty_adjusted']
    receiving_team: TeamSideV3
    restart_status: Literal['pending', 'resolved']
    receiving_restart_spot: Optional[FieldSpotV3] = None


@dataclass(frozen=True)
class KickoffOutOfBoundsV3:
    """Receiving team's selected Rule 6-2-4 disposition for an illegal free kick."""

    cause: Literal['kicking_team_out_of_bounds', 'short_of_landing_zone',
                   'receiving_team_last_touched']
    choice: Literal['at_inbounds_spot', 'at_distance_from_kick',
                     'at_out_of_bounds_spot', 'at_short_landing_spot']
    out_of_bounds_spot: Optional[FieldSpotV3]
    restart_spot: FieldSpotV3
    landing_spot: Optional[FieldSpotV3] = None
    distance_yards: Optional[int] = None


@dataclass(frozen=True)
class BlockedFieldGoalReturnV3:
    recovery_team: TeamSideV3
    recovery_spot: FieldSpotV3
    recoverer: v2.PlayerRoleV2
    post_block_returner: v2.PlayerRoleV2
    return_yards: int
    dead_ball_spot: FieldSpotV3
    possession_after: TeamSideV3
    scoring_kind: Optional[Literal['touchdown', 'safety']] = None
    scoring_team: Optional[TeamSideV3] = None


@dataclass(frozen=True)
class ScrimmageTurnoverChainV3:
    """Ordered turnover, return, fumble, recovery, and final return facts."""

    initial_turnover: Literal['interception']
    initial_possession_team: Literal['defense']
    turnover_spot: FieldSpotV3
    initial_returner: v2.PlayerRoleV2
    initial_return_yards: int
    fumbler: v2.PlayerRoleV2
    fumble_spot: FieldSpotV3
    recoverer: v2.PlayerRoleV2
    recovery_team: Literal['offense', 'defense']
    recovery_spot: FieldSpotV3
    post_recovery_returner: v2.PlayerRoleV2
    post_recovery_return_yards: int
    dead_ball_spot: FieldSpotV3
    final_possession_team: Literal['offense', 'defense']
    interceptor: v2.PlayerRoleV2
    scoring_kind: Optional[Literal['touchdown', 'safety']] = None
    scoring_team: Optional[Literal['offense', 'defense']] = None


@dataclass(frozen=True)
class KickV3:
    kind: Literal['punt', 'field_goal', 'kickoff', 'safety_kick']
    kicking_team: str
    receiving_team: str
    kick_spot: FieldSpotV3
    distance_yards: Optional[int]
    result: Literal['made', 'missed', 'blocked', 'touchback', 'return', 'muff',
                    'kicking_team_recovery', 'onside_recovery', 'period_expired',
                    'downed', 'fair_catch', 'out_of_bounds', 'short_of_landing_zone']
    possession_after: Optional[TeamSideV3] = None
    dead_ball_spot: Optional[FieldSpotV3] = None
    receiving_restart_spot: Optional[FieldSpotV3] = None
    recovery_team: Optional[TeamSideV3] = None
    recovery_spot: Optional[FieldSpotV3] = None
    recoverer: Optional[v2.PlayerRoleV2] = None
    return_facts: Optional[KickReturnV3] = None
    fair_catcher: Optional[v2.PlayerRoleV2] = None
    out_of_bounds_spot: Optional[FieldSpotV3] = None
    kickoff_oob: Optional[KickoffOutOfBoundsV3] = None
    safety: Optional[KickSafetyV3] = None
    blocked_field_goal_return: Optional[BlockedFieldGoalReturnV3] = None


@dataclass(frozen=True)
class GeneratedPlayV3(v2.GeneratedPlayV2):
    contract: str
    kick: Optional[KickV3] = None
    turnover_chain: Optional[ScrimmageTurnoverChainV3] = None


class ContractViolationV3(v2.ContractViolationV2):
    """A malformed ceg-play-3 special-teams fact record."""


def _fail(reason):
    raise ContractViolationV3(reason)


def _spot(spot, label):
    if not isinstance(spot, FieldSpotV3):
        _fail(label + '_spot_and_frame_required')
    if type(spot.yardline_100) is not int or not 0 <= spot.yardline_100 <= 100:
        _fail(label + '_spot_invalid')
    if spot.frame not in ('kicking_team', 'receiving_team', 'offense', 'defense'):
        _fail(label + '_spot_frame_invalid')


def _in_frame(spot, frame):
    _spot(spot, 'coordinate')
    return spot.yardline_100 if spot.frame == frame else 100 - spot.yardline_100


def _same_spot(left, right):
    _spot(left, 'left')
    _spot(right, 'right')
    return _in_frame(left, 'kicking_team') == _in_frame(right, 'kicking_team')


def _role(role, label, *, required=False):
    if role is None and required:
        _fail(label + '_role_required_or_unmodelled_slot')
    if not isinstance(role, v2.PlayerRoleV2):
        _fail(label + '_role_invalid')
    try:
        v2._v2_role(role, label)
    except v2.ContractViolationV2 as exc:
        _fail(str(exc))
    if required and role.status == 'none':
        _fail(label + '_role_required_or_unmodelled_slot')


def _return_facts(facts, kick):
    if facts is None:
        _fail('kick_return_facts_required')
    if not isinstance(facts, KickReturnV3):
        _fail('kick_return_facts_invalid')
    if facts.returning_team not in ('kicking_team', 'receiving_team'):
        _fail('kick_returning_team_invalid')
    _role(facts.returner, 'kick_returner', required=(kick.result == 'return'))
    _role(facts.muffing_returner, 'muffing_returner', required=(kick.result == 'muff'))
    _role(facts.recoverer, 'muff_recoverer', required=(kick.result == 'muff'))
    _role(facts.post_recovery_returner, 'post_recovery_returner', required=(kick.result == 'muff'))
    if type(facts.return_yards) is not int:
        _fail('kick_return_yards_must_be_integer')
    _spot(facts.dead_ball_spot, 'kick_return_dead_ball')
    if kick.result == 'return':
        if facts.muffing_returner.status != 'none' or facts.recoverer.status != 'none' \
                or facts.post_recovery_returner.status != 'none' or facts.recovery_spot is not None \
                or facts.fumble_spot is not None:
            _fail('ordinary_return_has_muff_recovery_roles')
        if facts.return_start_spot is None:
            _fail('kick_return_start_spot_required')
        start = facts.return_start_spot
    elif kick.result == 'muff':
        if facts.returner.status != 'none' or facts.return_start_spot is not None:
            _fail('muff_returner_roles_must_not_be_overloaded')
        if facts.recovery_spot is None:
            _fail('muff_recovery_spot_required')
        if facts.fumble_spot is None:
            _fail('muff_fumble_spot_required')
        _spot(facts.recovery_spot, 'muff_recovery')
        _spot(facts.fumble_spot, 'muff_fumble')
        _role(kick.recoverer, 'kick_recoverer', required=True)
        if kick.recoverer != facts.recoverer:
            _fail('muff_recoverer_role_mismatch')
        start = facts.recovery_spot
        if kick.recovery_team != facts.returning_team or not _same_spot(kick.recovery_spot, facts.recovery_spot):
            _fail('muff_recovery_team_or_spot_mismatch')
    else:
        _fail('kick_return_facts_on_nonreturn_result')
    _spot(start, 'kick_return_start')
    if kick.possession_after != facts.returning_team:
        _fail('kick_return_possession_mismatch')
    start_y = _in_frame(start, facts.returning_team)
    dead_y = _in_frame(facts.dead_ball_spot, facts.returning_team)
    if start_y - dead_y != facts.return_yards:
        _fail('kick_return_yards_disagree_with_framed_spots')
    if kick.dead_ball_spot is not None and not _same_spot(kick.dead_ball_spot, facts.dead_ball_spot):
        _fail('kick_return_dead_ball_spot_mismatch')
    if facts.scoring_kind is None:
        if facts.scoring_team is not None:
            _fail('kick_return_scorer_without_scoring_kind')
        if dead_y in (0, 100):
            _fail('kick_return_goal_line_needs_touchdown_or_safety_fact')
    elif facts.scoring_kind == 'touchdown':
        if facts.scoring_team != facts.returning_team or dead_y != 0:
            _fail('kick_return_touchdown_team_or_spot_mismatch')
    elif facts.scoring_kind == 'safety':
        if facts.scoring_team != ('receiving_team' if facts.returning_team == 'kicking_team'
                                  else 'kicking_team') or dead_y != 100:
            _fail('kick_return_safety_team_or_spot_mismatch')


def _safety_facts(facts, kick):
    if facts is None:
        _fail('kick_safety_facts_required')
    if not isinstance(facts, KickSafetyV3):
        _fail('kick_safety_facts_invalid')
    if facts.scoring_team not in ('kicking_team', 'receiving_team'):
        _fail('kick_safety_scoring_team_invalid')
    if facts.possessing_team not in ('kicking_team', 'receiving_team'):
        _fail('kick_safety_possessing_team_invalid')
    if facts.possessing_team == facts.scoring_team:
        _fail('kick_safety_possession_team_must_differ_from_scorer')
    if facts.free_kick_team != ('receiving_team' if facts.scoring_team == 'kicking_team'
                                else 'kicking_team'):
        _fail('kick_safety_free_kick_team_mismatch')
    if facts.receiving_team != facts.scoring_team:
        _fail('kick_safety_receiving_team_mismatch')
    _spot(facts.safety_dead_ball_spot, 'safety_dead_ball')
    if facts.safety_dead_ball_spot.frame != facts.possessing_team:
        _fail('kick_safety_dead_ball_frame_must_name_possessing_team')
    if facts.safety_dead_ball_spot.yardline_100 != 100:
        _fail('kick_safety_dead_ball_must_be_scoring_teams_opponent_goal_line')
    if kick.possession_after != facts.possessing_team:
        _fail('kick_safety_possession_mismatch')
    if not _same_spot(kick.dead_ball_spot, facts.safety_dead_ball_spot):
        _fail('kick_safety_dead_ball_spot_mismatch')
    _spot(facts.free_kick_spot, 'safety_free_kick')
    if facts.free_kick_spot.frame != facts.free_kick_team:
        _fail('safety_free_kick_spot_frame_must_name_kicking_team')
    if facts.free_kick_spot_basis == 'own_20' and facts.free_kick_spot.yardline_100 != 80:
        _fail('safety_free_kick_own_20_spot_mismatch')
    if facts.free_kick_spot_basis not in ('own_20', 'penalty_adjusted'):
        _fail('safety_free_kick_spot_basis_invalid')
    if facts.restart_status == 'pending':
        if facts.receiving_restart_spot is not None or kick.receiving_restart_spot is not None:
            _fail('pending_safety_restart_has_spot')
    elif facts.restart_status == 'resolved':
        _spot(facts.receiving_restart_spot, 'safety_receiving_restart')
        if facts.receiving_restart_spot.frame != facts.receiving_team:
            _fail('safety_receiving_restart_frame_must_name_receiving_team')
        if kick.receiving_restart_spot != facts.receiving_restart_spot:
            _fail('safety_receiving_restart_spot_mismatch')
    else:
        _fail('safety_restart_status_invalid')
    if kick.safety is not facts:
        _fail('kick_safety_fact_not_attached_to_kick')


def _kickoff_oob(facts, kick):
    if not isinstance(facts, KickoffOutOfBoundsV3):
        _fail('kickoff_oob_choice_and_enforcement_required')
    _spot(facts.restart_spot, 'kickoff_oob_restart')
    receiver_frame = 'receiving_team'
    if facts.restart_spot.frame != receiver_frame:
        _fail('kickoff_oob_restart_frame_must_be_receiving_team')
    restart_y = facts.restart_spot.yardline_100
    if facts.cause == 'receiving_team_last_touched':
        _spot(facts.out_of_bounds_spot, 'kickoff_out_of_bounds')
        oob_y = _in_frame(facts.out_of_bounds_spot, receiver_frame)
        if facts.choice != 'at_inbounds_spot' or restart_y != oob_y:
            _fail('receiver_touched_oob_requires_inbounds_spot')
        if facts.distance_yards is not None or facts.landing_spot is not None:
            _fail('receiver_touched_oob_has_inapplicable_enforcement_facts')
        if not _same_spot(kick.out_of_bounds_spot, facts.out_of_bounds_spot):
            _fail('kickoff_oob_spot_disagrees_with_kick')
        return
    if facts.cause not in ('kicking_team_out_of_bounds', 'short_of_landing_zone'):
        _fail('kickoff_oob_cause_invalid')
    distance = 30 if kick.kind == 'safety_kick' else 25
    kick_y = _in_frame(kick.kick_spot, receiver_frame)
    if facts.choice == 'at_distance_from_kick':
        if facts.distance_yards != distance or restart_y != min(100, kick_y + distance):
            _fail('kickoff_oob_distance_option_mismatch')
        if facts.cause == 'kicking_team_out_of_bounds' and facts.landing_spot is not None:
            _fail('kickoff_oob_distance_option_has_landing_spot')
        if facts.cause == 'kicking_team_out_of_bounds':
            _spot(facts.out_of_bounds_spot, 'kickoff_out_of_bounds')
        else:
            if facts.out_of_bounds_spot is not None or facts.landing_spot is None:
                _fail('short_landing_needs_only_landing_spot')
            _spot(facts.landing_spot, 'kickoff_landing')
            if _in_frame(facts.landing_spot, receiver_frame) - kick_y >= distance:
                _fail('short_landing_not_shorter_than_distance_option')
    elif facts.choice == 'at_out_of_bounds_spot':
        _spot(facts.out_of_bounds_spot, 'kickoff_out_of_bounds')
        oob_y = _in_frame(facts.out_of_bounds_spot, receiver_frame)
        if (facts.cause != 'kicking_team_out_of_bounds' or facts.distance_yards is not None
                or facts.landing_spot is not None or restart_y != oob_y):
            _fail('kickoff_oob_spot_option_mismatch')
    elif facts.choice == 'at_short_landing_spot':
        if (facts.cause != 'short_of_landing_zone' or facts.landing_spot is None
                or facts.out_of_bounds_spot is not None):
            _fail('kickoff_short_landing_option_needs_landing_fact')
        _spot(facts.landing_spot, 'kickoff_landing')
        landing_y = _in_frame(facts.landing_spot, receiver_frame)
        if (landing_y - kick_y >= distance or restart_y != landing_y):
            _fail('kickoff_short_landing_option_mismatch')
        if facts.distance_yards is not None:
            _fail('kickoff_short_landing_has_distance_option_fact')
    else:
        _fail('kickoff_oob_choice_invalid')
    if facts.out_of_bounds_spot is not None and not _same_spot(kick.out_of_bounds_spot, facts.out_of_bounds_spot):
        _fail('kickoff_oob_spot_disagrees_with_kick')


def _blocked_fg(facts, kick, play):
    if not isinstance(facts, BlockedFieldGoalReturnV3):
        _fail('blocked_field_goal_recovery_and_return_facts_required')
    if facts.recovery_team not in ('kicking_team', 'receiving_team'):
        _fail('blocked_field_goal_recovery_team_invalid')
    if facts.possession_after != facts.recovery_team:
        _fail('blocked_field_goal_possession_mismatch')
    _spot(facts.recovery_spot, 'blocked_field_goal_recovery')
    _spot(facts.dead_ball_spot, 'blocked_field_goal_dead_ball')
    _role(facts.recoverer, 'blocked_field_goal_recoverer', required=True)
    _role(facts.post_block_returner, 'blocked_field_goal_post_block_returner', required=True)
    if kick.possession_after != facts.possession_after:
        _fail('blocked_field_goal_possession_mismatch')
    if kick.recovery_team != facts.recovery_team or not _same_spot(kick.recovery_spot, facts.recovery_spot):
        _fail('blocked_field_goal_recovery_fact_mismatch')
    if type(facts.return_yards) is not int:
        _fail('blocked_field_goal_return_yards_must_be_integer')
    start_y = _in_frame(facts.recovery_spot, facts.recovery_team)
    dead_y = _in_frame(facts.dead_ball_spot, facts.recovery_team)
    if start_y - dead_y != facts.return_yards:
        _fail('blocked_field_goal_return_yards_disagree_with_spots')
    if facts.scoring_kind is None:
        if facts.scoring_team is not None:
            _fail('blocked_field_goal_scorer_without_scoring_kind')
        if dead_y in (0, 100):
            _fail('blocked_field_goal_goal_line_needs_score_fact')
    elif facts.scoring_kind == 'touchdown':
        if facts.scoring_team != facts.recovery_team or dead_y != 0:
            _fail('blocked_field_goal_touchdown_team_or_spot_mismatch')
    elif facts.scoring_kind == 'safety':
        if facts.scoring_team == facts.recovery_team or dead_y != 100:
            _fail('blocked_field_goal_safety_team_or_spot_mismatch')
    if facts.scoring_kind is not None and play.scoring is None:
        _fail('blocked_field_goal_scoring_fact_missing')
    if play.scoring is not None:
        expected = {'kicking_team': 'kicking_team', 'receiving_team': 'receiving_team'}.get(facts.scoring_team)
        if (play.scoring.kind != facts.scoring_kind or play.scoring.team != expected):
            _fail('blocked_field_goal_scoring_fact_mismatch')


def _named_role_conflicts(existing, supplied, label):
    if (existing.status == 'named' and supplied.status == 'named'
            and existing.player_id != supplied.player_id):
        _fail(label + '_player_id_mismatch')


def _validate_scrimmage_turnover_chain(state, play, require_clock):
    chain = play.turnover_chain
    if not isinstance(chain, ScrimmageTurnoverChainV3):
        _fail('scrimmage_turnover_chain_invalid')
    if play.event not in ('interception', 'run', 'scramble', 'sack', 'pass_complete'):
        _fail('turnover_chain_event_unsupported')
    if not play.fumble:
        _fail('turnover_chain_requires_fumble_fact')
    if chain.initial_turnover != 'interception':
        _fail('turnover_chain_initial_turnover_invalid')
    if play.event != 'interception' or chain.initial_possession_team != 'defense':
        _fail('interception_return_chain_initial_possession_mismatch')
    _role(chain.interceptor, 'interceptor', required=True)
    if chain.recovery_team != chain.final_possession_team:
        _fail('turnover_chain_final_possession_mismatch')
    for role, label in ((chain.initial_returner, 'initial_returner'),
                        (chain.fumbler, 'return_fumbler'),
                        (chain.recoverer, 'turnover_chain_recoverer'),
                        (chain.post_recovery_returner, 'post_recovery_returner')):
        _role(role, label, required=True)
    for label, spot in (('turnover', chain.turnover_spot), ('fumble', chain.fumble_spot),
                        ('recovery', chain.recovery_spot), ('dead_ball', chain.dead_ball_spot)):
        _spot(spot, label)
    if type(chain.initial_return_yards) is not int or type(chain.post_recovery_return_yards) is not int:
        _fail('turnover_chain_yards_must_be_integer')
    initial_start = _in_frame(chain.turnover_spot, chain.initial_possession_team)
    initial_end = _in_frame(chain.fumble_spot, chain.initial_possession_team)
    if initial_start - initial_end != chain.initial_return_yards:
        _fail('turnover_chain_initial_return_yards_disagree_with_spots')
    recovery = _in_frame(chain.recovery_spot, chain.final_possession_team)
    dead = _in_frame(chain.dead_ball_spot, chain.final_possession_team)
    if recovery - dead != chain.post_recovery_return_yards:
        _fail('turnover_chain_post_recovery_yards_disagree_with_spots')
    if chain.scoring_kind is None:
        if chain.scoring_team is not None or play.scoring is not None:
            _fail('turnover_chain_scoring_fact_mismatch')
    elif chain.scoring_kind == 'touchdown':
        if chain.scoring_team != chain.final_possession_team or dead != 0:
            _fail('turnover_chain_touchdown_team_or_spot_mismatch')
        if play.scoring is None or play.scoring.kind != 'touchdown' \
                or play.scoring.team != chain.scoring_team:
            _fail('turnover_chain_scoring_fact_mismatch')
    elif chain.scoring_kind == 'safety':
        if chain.scoring_team == chain.final_possession_team or dead != 100:
            _fail('turnover_chain_safety_team_or_spot_mismatch')
        if play.scoring is None or play.scoring.kind != 'safety' \
                or play.scoring.team != chain.scoring_team:
            _fail('turnover_chain_scoring_fact_mismatch')
    if chain.scoring_kind is None and dead in (0, 100):
        _fail('turnover_chain_goal_line_needs_score_fact')

    offense_frame_spots = {
        'turnover': _in_frame(chain.turnover_spot, 'offense'),
        'fumble': _in_frame(chain.fumble_spot, 'offense'),
        'recovery': _in_frame(chain.recovery_spot, 'offense'),
        'dead_ball': _in_frame(chain.dead_ball_spot, 'offense'),
    }
    source_possession = play.possession
    if source_possession is not None:
        if not isinstance(source_possession, v2.PossessionV2):
            _fail('possession_record_invalid')
        if source_possession.team != chain.final_possession_team \
                or source_possession.how != 'fumble_recovery':
            _fail('turnover_chain_possession_fact_mismatch')
        for value, expected, label in (
                (source_possession.turnover_spot_yardline_100, offense_frame_spots['fumble'], 'turnover'),
                (source_possession.fumble_spot_yardline_100, offense_frame_spots['fumble'], 'fumble'),
                (source_possession.recovery_spot_yardline_100, offense_frame_spots['recovery'], 'recovery'),
                (source_possession.dead_ball_yardline_100, offense_frame_spots['dead_ball'], 'dead_ball')):
            if value != expected:
                _fail('turnover_chain_' + label + '_spot_mismatch')
        if source_possession.return_yards != chain.post_recovery_return_yards:
            _fail('turnover_chain_final_return_yards_mismatch')
        if source_possession.recovered_by != chain.recoverer \
                or source_possession.returner != chain.post_recovery_returner:
            _fail('turnover_chain_possession_player_attribution_mismatch')

    _named_role_conflicts(play.players.interceptor, chain.interceptor, 'interceptor')
    _named_role_conflicts(play.players.fumbler, chain.fumbler, 'return_fumbler')
    _named_role_conflicts(play.players.recoverer, chain.recoverer, 'turnover_chain_recoverer')
    _named_role_conflicts(play.players.returner, chain.post_recovery_returner,
                          'post_recovery_returner')

    # Validate the ordinary play shell and football legality with a V2-shaped
    # projection. The projection uses the fumble/recovery leg for legacy fields;
    # the V3 chain above remains authoritative for the earlier interception and
    # return leg that V2 cannot encode.
    projected_possession = v2.PossessionV2(
        team=chain.final_possession_team, how='fumble_recovery',
        turnover_spot_yardline_100=offense_frame_spots['fumble'],
        recovery_spot_yardline_100=offense_frame_spots['recovery'],
        dead_ball_yardline_100=offense_frame_spots['dead_ball'],
        return_yards=chain.post_recovery_return_yards,
        returner=chain.post_recovery_returner, recovered_by=chain.recoverer,
        fumble_spot_yardline_100=offense_frame_spots['fumble'])
    projected_players = replace(
        play.players, interceptor=chain.interceptor, fumbler=chain.fumbler, recoverer=chain.recoverer,
        returner=chain.post_recovery_returner)
    projected = replace(play, contract=v2.CONTRACT_V2_VERSION, kick=None,
                        possession=projected_possession, scoring=None,
                        players=projected_players, turnover_chain=None)
    try:
        v2.validate_v2(state, projected, require_clock=require_clock)
    except v2.ContractViolationV2 as exc:
        _fail('turnover_chain_base_play_invalid:' + str(exc))


def validate_v3(state, play, require_clock=True):
    """Validate a V3 kick record or ordered scrimmage turnover chain."""
    if not isinstance(play, GeneratedPlayV3) or play.contract != CONTRACT_V3_VERSION:
        _fail('generated_play_contract_mismatch')
    if play.event not in ('punt', 'field_goal_attempt', 'kickoff'):
        if play.kick is not None:
            _fail('kick_record_on_non_kick_event')
        if play.turnover_chain is None:
            _fail('ceg_play_3_scrimmage_scope_requires_turnover_chain')
        _validate_scrimmage_turnover_chain(state, play, require_clock)
        return None
    if play.turnover_chain is not None:
        _fail('scrimmage_turnover_chain_on_kick_event')
    if not isinstance(play.provenance, v2.ProvenanceV2):
        _fail('play_provenance_invalid')
    v2._v2_provenance(play.provenance, 'play')
    if not isinstance(play.call, v2.PlayCallV2):
        _fail('play_call_required_or_invalid')
    expected_intent = {'punt': 'punt', 'field_goal_attempt': 'field_goal', 'kickoff': 'kickoff'}[play.event]
    if play.call.intent != expected_intent:
        _fail('play_intent_event_mismatch')
    if play.call.provenance is not None:
        v2._v2_provenance(play.call.provenance, 'play_call')
    if require_clock:
        v2._v2_clock(play.clock)
    elif play.clock is not None:
        v2._v2_clock(play.clock)
    v2._v2_penalty(play.penalty, play, play.event)
    if not isinstance(play.players, v2.PlayerRolesV2):
        _fail('player_roles_record_invalid')
    for name, role in play.players.__dict__.items():
        _role(role, name)
    if play.event == 'punt':
        _role(play.players.punter, 'punt_punter', required=True)
    elif play.event == 'field_goal_attempt':
        _role(play.players.kicker, 'field_goal_kicker', required=True)
    else:
        _role(play.players.kicker, 'kickoff_kicker', required=True)
    if play.scoring is not None:
        if not isinstance(play.scoring, v2.ScoringV2):
            _fail('scoring_fact_invalid')
        if play.scoring.kind not in ('touchdown', 'field_goal', 'safety'):
            _fail('scoring_fact_invalid')
    kick = play.kick
    if not isinstance(kick, KickV3):
        _fail('kick_v3_record_required')
    expected_kinds = {'punt': ('punt',), 'field_goal_attempt': ('field_goal',),
                      'kickoff': ('kickoff', 'safety_kick')}
    if kick.kind not in expected_kinds[play.event]:
        _fail('kick_record_event_mismatch')
    if not kick.kicking_team or not kick.receiving_team or kick.kicking_team == kick.receiving_team:
        _fail('kick_teams_invalid')
    _spot(kick.kick_spot, 'kick')
    if kick.kick_spot.frame != 'kicking_team':
        _fail('kick_spot_frame_must_be_kicking_team')
    if kick.distance_yards is not None and (type(kick.distance_yards) is not int or kick.distance_yards < 0):
        _fail('kick_distance_invalid')
    if kick.result not in ('made', 'missed', 'blocked', 'touchback', 'return', 'muff',
                           'kicking_team_recovery', 'onside_recovery', 'period_expired',
                           'downed', 'fair_catch', 'out_of_bounds', 'short_of_landing_zone'):
        _fail('kick_result_invalid')
    if kick.possession_after not in (None, 'kicking_team', 'receiving_team'):
        _fail('kick_possession_role_invalid')
    for label, spot in (('dead_ball', kick.dead_ball_spot), ('recovery', kick.recovery_spot),
                        ('out_of_bounds', kick.out_of_bounds_spot)):
        if spot is not None:
            _spot(spot, label)
    if kick.recoverer is not None:
        _role(kick.recoverer, 'kick_recoverer')

    if kick.result in ('return', 'muff'):
        _return_facts(kick.return_facts, kick)
        if kick.result == 'muff' and not play.fumble:
            _fail('muff_requires_fumble_fact')
    elif kick.return_facts is not None:
        _fail('kick_return_facts_on_nonreturn_result')
    if kick.result == 'fair_catch':
        _role(kick.fair_catcher, 'fair_catcher', required=True)
        _spot(kick.dead_ball_spot, 'fair_catch_dead_ball')
        if kick.possession_after != 'receiving_team':
            _fail('fair_catch_possession_must_be_receiving_team')
    elif kick.fair_catcher is not None:
        _fail('fair_catcher_on_non_fair_catch')
    if kick.result == 'downed':
        _spot(kick.dead_ball_spot, 'downed_kick_dead_ball')
        if kick.possession_after != 'receiving_team':
            _fail('downed_kick_possession_must_be_receiving_team')
    if kick.result in ('out_of_bounds', 'short_of_landing_zone'):
        _spot(kick.dead_ball_spot, 'kick_oob_dead_ball')
        if kick.kind in ('kickoff', 'safety_kick'):
            _kickoff_oob(kick.kickoff_oob, kick)
            source_spot = (kick.kickoff_oob.out_of_bounds_spot
                           if kick.result == 'out_of_bounds' else kick.kickoff_oob.landing_spot)
            if source_spot is None or not _same_spot(kick.dead_ball_spot, source_spot):
                _fail('free_kick_oob_or_short_dead_ball_spot_mismatch')
        else:
            if kick.kickoff_oob is not None:
                _fail('punt_oob_has_free_kick_choice')
            _spot(kick.out_of_bounds_spot, 'punt_out_of_bounds')
            if not _same_spot(kick.out_of_bounds_spot, kick.dead_ball_spot):
                _fail('kick_oob_dead_ball_spot_mismatch')
        if kick.result == 'out_of_bounds' and kick.kickoff_oob is not None \
                and kick.kickoff_oob.cause == 'short_of_landing_zone':
            _fail('out_of_bounds_result_cause_mismatch')
        if kick.result == 'short_of_landing_zone' and (kick.kind not in ('kickoff', 'safety_kick')
                or kick.kickoff_oob is None or kick.kickoff_oob.cause != 'short_of_landing_zone'):
            _fail('short_landing_result_cause_mismatch')
        if kick.possession_after != 'receiving_team':
            _fail('kick_oob_possession_must_be_receiving_team')
    elif kick.kickoff_oob is not None:
        _fail('kickoff_oob_choice_without_oob_result')

    if kick.kind == 'field_goal' and kick.result == 'blocked':
        _blocked_fg(kick.blocked_field_goal_return, kick, play)
    elif kick.blocked_field_goal_return is not None:
        _fail('blocked_field_goal_return_on_nonblocked_fg')
    if kick.result == 'made':
        if kick.kind != 'field_goal' or play.scoring is None or play.scoring.kind != 'field_goal':
            _fail('made_field_goal_requires_matching_scoring_fact')
        if play.scoring.team != 'kicking_team':
            _fail('field_goal_score_team_mismatch')
    if kick.result == 'touchback' and (kick.possession_after != 'receiving_team'
                                       or kick.dead_ball_spot is None
                                       or kick.receiving_restart_spot is None):
        _fail('touchback_needs_receiving_possession_dead_ball_and_restart_spots')
    if kick.result == 'missed' and (kick.kind != 'field_goal'
            or kick.possession_after != 'receiving_team' or kick.dead_ball_spot is None
            or kick.receiving_restart_spot is None):
        _fail('missed_field_goal_needs_explicit_receiving_restart')
    if kick.receiving_restart_spot is not None:
        _spot(kick.receiving_restart_spot, 'kick_receiving_restart')
        if kick.receiving_restart_spot.frame != 'receiving_team':
            _fail('kick_receiving_restart_frame_must_be_receiving_team')
    if kick.receiving_restart_spot is not None and kick.result not in ('touchback', 'missed') \
            and not (play.scoring is not None and play.scoring.kind == 'safety'):
        _fail('receiving_restart_spot_without_restart_context')

    if play.scoring is not None and play.scoring.kind == 'safety':
        _safety_facts(kick.safety, kick)
        if kick.safety.scoring_team != play.scoring.team:
            _fail('kick_safety_scoring_team_mismatch')
    elif kick.safety is not None:
        _fail('kick_safety_facts_without_safety_score')
    if kick.return_facts is not None:
        facts = kick.return_facts
        if facts.scoring_kind is None:
            if play.scoring is not None:
                _fail('kick_return_scoring_facts_missing')
        elif play.scoring is None or play.scoring.kind != facts.scoring_kind \
                or play.scoring.team != facts.scoring_team:
            _fail('kick_return_scoring_fact_mismatch')
    if kick.result == 'blocked' and kick.kind != 'field_goal':
        _fail('blocked_non_field_goal_requires_separately_classified_recovery')
    return None
