"""SLC-CEG event contract (research): the typed record a conditional generator returns for one snap.

A generator never returns a historical row. It returns a GeneratedPlay whose facts are coherent by construction and whose
provenance names the model components and the draws that produced it. The football rules (reducer, penalty core) still
decide the legal next state; `validate()` checks the facts against the pre-snap state before the reducer sees them.

Separation the Phase 1 review asked for:
  PlayCall          the pre-snap intent, drawn at the snap decision.
  TimeoutDecision   drawn at a timeout opportunity (before a snap), never a flag copied from a play.
  GeneratedPlay     the realized event and its quantities.
  Clock             live-play seconds and the dead-ball runoff, separately; the clock-stop class says which applies.
  Penalty           occurrence, type, team, yards and whether it is accepted; enforcement is the rules core's job.
  Possession        who has the ball when the play is dead, where, and how it got there (recovery, return).

No field here is a cap. Yardage is whatever the model drew; validate() refuses a value the field cannot hold and reports
the boundary (opponent goal line: touchdown; own goal line: safety or touchback by the rules core).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

INTENTS = ('designed_run', 'dropback', 'punt', 'field_goal', 'kneel', 'spike')
EVENTS = ('run', 'scramble', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'kneel', 'spike', 'punt',
          'field_goal_attempt')
CLOCK_STOP = ('running', 'stopped')
CONTRACT_VERSION = 'ceg-play-1'


@dataclass(frozen=True)
class Provenance:
    generator: str                 # model id of the scrimmage generator, e.g. 'ceg-arm-b'
    version: str
    manifest_sha256: str           # the component manifest the pack was built from
    components: tuple[str, ...]    # component model ids used for this play, in draw order
    draw_ids: tuple[str, ...]      # rng stream keys of the draws, for exact replay


@dataclass(frozen=True)
class PlayCall:
    intent: Literal['designed_run', 'dropback', 'punt', 'field_goal', 'kneel', 'spike']
    probabilities: dict            # intent -> probability the call was drawn from
    provenance: Provenance


@dataclass(frozen=True)
class TimeoutDecision:
    team: Optional[str]            # 'A', 'B' or None: no timeout at this opportunity
    probabilities: dict
    provenance: Provenance


@dataclass(frozen=True)
class Clock:
    live_seconds: float            # ball in play
    dead_ball_seconds: float       # clock running between the whistle and the next snap; 0 when the clock is stopped
    stop_class: Literal['running', 'stopped']

    @property
    def runoff_seconds(self):
        return self.live_seconds + self.dead_ball_seconds


@dataclass(frozen=True)
class Penalty:
    penalty_type: str
    team: Literal['offense', 'defense']
    yards: int
    accepted: bool
    automatic_first_down: bool
    pre_snap: bool                 # a no-play foul: the play facts below are void


@dataclass(frozen=True)
class Possession:
    team: Literal['offense', 'defense']   # the team with the ball when the play is dead
    how: Literal['kept', 'interception', 'fumble_recovery', 'punt', 'downs', 'score']
    dead_ball_yardline_100: Optional[int]  # from the offense's direction at the snap; None for a score
    return_yards: Optional[int] = None     # yards the recovering team gained after the change, attributed to it
    recovered_by_player: Optional[str] = None


@dataclass(frozen=True)
class GeneratedPlay:
    contract: str
    call: PlayCall
    event: str
    yards_gained: Optional[int]           # offense's net yards from the line of scrimmage; None for kicks
    air_yards: Optional[int] = None       # pass attempts: depth of the target
    yards_after_catch: Optional[int] = None
    fumble: bool = False
    possession: Optional[Possession] = None
    penalty: Optional[Penalty] = None
    out_of_bounds: bool = False
    clock: Optional[Clock] = None
    passer: Optional[str] = None
    rusher: Optional[str] = None
    receiver: Optional[str] = None
    touchdown_team: Optional[Literal['offense', 'defense']] = None
    provenance: Optional[Provenance] = None
    probabilities: dict = field(default_factory=dict)


class ContractViolation(ValueError):
    """A generated play that the pre-snap state cannot hold. Never caught and turned into a default."""


def validate(state, play, require_clock=True):
    """Check a GeneratedPlay against the pre-snap state {'down', 'togo', 'yl'}. Returns the boundary reached, or None.

    require_clock=False is for a generator that does not yet own the clock (CEG Phase 2): the play must then carry no
    clock at all, so a missing clock can never pass as a generated one."""
    if play.contract != CONTRACT_VERSION:
        raise ContractViolation(f'contract {play.contract!r} is not {CONTRACT_VERSION}')
    if play.provenance is None:
        raise ContractViolation('a generated play needs provenance')
    if play.event not in EVENTS:
        raise ContractViolation(f'unknown event {play.event!r}')
    if play.penalty is not None and play.penalty.pre_snap:
        if play.yards_gained not in (None, 0) or play.fumble or play.receiver:
            raise ContractViolation('a pre-snap foul voids the play: no yards, fumble or target')
        return None
    if not require_clock:
        if play.clock is not None:
            raise ContractViolation('require_clock=False is only for plays with no clock')
    elif play.clock is None or play.clock.live_seconds < 0 or play.clock.dead_ball_seconds < 0:
        raise ContractViolation('clock seconds must be present and non-negative')
    elif play.clock.stop_class == 'stopped' and play.clock.dead_ball_seconds != 0:
        raise ContractViolation('a stopped clock has no dead-ball runoff')
    intent = play.call.intent
    allowed = {'designed_run': {'run'}, 'dropback': {'pass_complete', 'pass_incomplete', 'interception', 'sack', 'scramble'},
               'punt': {'punt'}, 'field_goal': {'field_goal_attempt'}, 'kneel': {'kneel'}, 'spike': {'spike'}}[intent]
    if play.event not in allowed:
        raise ContractViolation(f'event {play.event} cannot follow intent {intent}')
    yl, y = state['yl'], play.yards_gained
    if play.event in ('pass_incomplete', 'spike') and y != 0:
        raise ContractViolation(f'{play.event} gains no yards')
    if play.event == 'sack':
        if y is None or y > 0:
            raise ContractViolation('a sack loses yards or gains none')
        if play.receiver:
            raise ContractViolation('a sack has no target')
    if play.event == 'pass_complete':
        if play.air_yards is None or play.yards_after_catch is None or play.air_yards + play.yards_after_catch != y:
            raise ContractViolation('a completion needs air yards and YAC that sum to the yards gained')
        if not play.receiver:
            raise ContractViolation('a completion needs a receiver')
    if play.event == 'scramble' and (play.receiver or not play.rusher):
        raise ContractViolation('a scramble credits the QB as rusher and has no target')
    if play.event in ('interception',) and (play.possession is None or play.possession.how != 'interception'):
        raise ContractViolation('an interception changes possession by interception')
    if play.fumble and play.possession is None:
        raise ContractViolation('a fumble needs its recovery: who has the ball and where it is dead')
    boundary = None
    if y is not None and play.event not in ('punt', 'field_goal_attempt'):
        end = yl - y
        if end < 0 or end > 100:
            raise ContractViolation(f'yards {y} from the {yl} carries the ball past an end line')
        if end == 0:
            boundary = 'opponent_goal_line'
            if play.touchdown_team != 'offense' and not play.fumble:
                raise ContractViolation('a gain to the opponent goal line is an offensive touchdown')
        elif end == 100:
            boundary = 'own_goal_line'
    return boundary


# `ceg-play-1` remains the default above because the CEG generator, harness and
# Phase 9 reports still import those exact classes.  Event expansion consumers
# opt into this additive version explicitly until every branch has migrated.
CONTRACT_V2_VERSION = 'ceg-play-2'
INTENTS_V2 = ('designed_run', 'dropback', 'punt', 'field_goal', 'kickoff', 'kneel', 'spike')
EVENTS_V2 = ('run', 'scramble', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'kneel', 'spike',
             'punt', 'field_goal_attempt', 'kickoff', 'no_play')


@dataclass(frozen=True)
class ProvenanceV2:
    generator: str
    version: str
    manifest_sha256: str
    components: tuple = ()
    draw_ids: tuple = ()
    source_row_id: Optional[str] = None
    source_sha256: Optional[str] = None


@dataclass(frozen=True)
class PlayerRoleV2:
    """A statistical role is absent, present as an unmodelled slot, or named."""

    status: Literal['none', 'unmodelled', 'named']
    player_id: Optional[str] = None
    slot: Optional[str] = None

    @classmethod
    def none(cls):
        return cls('none')

    @classmethod
    def unmodelled(cls, slot):
        return cls('unmodelled', slot=slot)

    @classmethod
    def named(cls, player_id):
        return cls('named', player_id=player_id)

    @property
    def stat_player_id(self):
        return self.player_id if self.status == 'named' else None


def _none_role_v2():
    return PlayerRoleV2.none()


def _unmodelled_penalty_offender_v2():
    return PlayerRoleV2.unmodelled('penalty_offender')


@dataclass(frozen=True)
class PlayerRolesV2:
    passer: PlayerRoleV2 = field(default_factory=_none_role_v2)
    rusher: PlayerRoleV2 = field(default_factory=_none_role_v2)
    receiver: PlayerRoleV2 = field(default_factory=_none_role_v2)
    interceptor: PlayerRoleV2 = field(default_factory=_none_role_v2)
    sacker: PlayerRoleV2 = field(default_factory=_none_role_v2)
    fumbler: PlayerRoleV2 = field(default_factory=_none_role_v2)
    recoverer: PlayerRoleV2 = field(default_factory=_none_role_v2)
    returner: PlayerRoleV2 = field(default_factory=_none_role_v2)
    kicker: PlayerRoleV2 = field(default_factory=_none_role_v2)
    punter: PlayerRoleV2 = field(default_factory=_none_role_v2)
    tackler: PlayerRoleV2 = field(default_factory=_none_role_v2)

    def statistical_ids(self):
        return {name: role.player_id for name, role in self.__dict__.items()
                if role.status == 'named' and role.player_id is not None}


@dataclass(frozen=True)
class PlayCallV2:
    intent: str
    probabilities: dict = field(default_factory=dict)
    provenance: Optional[ProvenanceV2] = None


@dataclass(frozen=True)
class TimeoutDecisionV2:
    """A between-snap decision, separate from any play or no-play foul."""

    team: Optional[str]
    probabilities: dict = field(default_factory=dict)
    provenance: Optional[ProvenanceV2] = None


@dataclass(frozen=True)
class ClockV2:
    runoff_seconds: float
    live_seconds: Optional[float] = None
    dead_ball_seconds: Optional[float] = None
    stop_class: Optional[Literal['running', 'stopped']] = None


@dataclass(frozen=True)
class PenaltyFoulV2:
    penalty_type: str
    team: Literal['offense', 'defense', 'kicking_team', 'receiving_team']
    yards_assessed: int  # nominal rule yards before half-distance; stats use enforced yards
    foul_spot: Optional[float] = None
    player: PlayerRoleV2 = field(default_factory=_unmodelled_penalty_offender_v2)
    block_subtype: Optional[Literal['in_back', 'above_waist']] = None


@dataclass(frozen=True)
class PenaltyV2:
    phase: Literal['pre_snap', 'live_ball']
    fouls: tuple
    disposition: Literal['accepted', 'declined', 'offsetting', 'unknown']
    automatic_first_down: Optional[bool] = None
    play_void: bool = False
    provenance: Optional[ProvenanceV2] = None

    @property
    def enforcement_basis(self):
        return 'foul_spot' if any(foul.foul_spot is not None for foul in self.fouls) else 'previous_spot'


@dataclass(frozen=True)
class PossessionV2:
    """Dead-ball possession facts in the offense-at-snap yardline frame."""

    team: Literal['offense', 'defense']
    how: Literal['kept', 'interception', 'fumble_recovery']
    turnover_spot_yardline_100: Optional[float] = None
    recovery_spot_yardline_100: Optional[float] = None
    dead_ball_yardline_100: Optional[float] = None
    return_yards: Optional[int] = None
    returner: PlayerRoleV2 = field(default_factory=_none_role_v2)
    recovered_by: PlayerRoleV2 = field(default_factory=_none_role_v2)
    fumble_spot_yardline_100: Optional[float] = None
    touchback: bool = False
    next_possession_yardline_100: Optional[float] = None  # in the team-with-possession frame


@dataclass(frozen=True)
class ScoringV2:
    kind: Literal['touchdown', 'field_goal', 'safety']
    team: Literal['offense', 'defense', 'kicking_team', 'receiving_team']


@dataclass(frozen=True)
class KickV2:
    """Kick spots use the kicking team's yardline frame: its own goal line is 100."""

    kind: Literal['punt', 'field_goal', 'kickoff']
    kicking_team: str
    receiving_team: str
    kick_spot_yardline_100: float
    distance_yards: Optional[int]
    result: Literal['made', 'missed', 'blocked', 'touchback', 'return', 'muff',
                    'kicking_team_recovery', 'onside_recovery', 'period_expired']
    possession_after: Optional[Literal['kicking_team', 'receiving_team']] = None
    recovery_team: Optional[Literal['kicking_team', 'receiving_team']] = None
    recovery_yardline_100: Optional[float] = None
    return_start_yardline_100: Optional[float] = None
    dead_ball_yardline_100: Optional[float] = None
    return_yards: Optional[int] = None
    receiving_team_touched_beyond_line: Optional[bool] = None
    returner: PlayerRoleV2 = field(default_factory=_none_role_v2)
    recoverer: PlayerRoleV2 = field(default_factory=_none_role_v2)
    out_of_bounds: bool = False
    fumble_spot_yardline_100: Optional[float] = None


@dataclass(frozen=True)
class GeneratedPlayV2:
    contract: str
    call: Optional[PlayCallV2]
    event: str
    yards_gained: Optional[int]
    provenance: Optional[ProvenanceV2]
    clock: Optional[ClockV2]
    air_yards: Optional[int] = None
    yards_after_catch: Optional[int] = None
    fumble: bool = False
    possession: Optional[PossessionV2] = None
    scoring: Optional[ScoringV2] = None
    kick: Optional[KickV2] = None
    penalty: Optional[PenaltyV2] = None
    play_void: bool = False
    out_of_bounds: bool = False
    players: PlayerRolesV2 = field(default_factory=PlayerRolesV2)
    probabilities: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TryRecordV2:
    contract: str
    kind: Literal['extra_point', 'two_point']
    offense_team: str
    result: Literal['made', 'missed', 'defensive_return']
    scoring_team: Optional[str]
    provenance: Optional[ProvenanceV2]


class ContractViolationV2(ContractViolation):
    """A malformed ceg-play-2 record; callers must not silently repair it."""


def _v2_fail(reason):
    raise ContractViolationV2(reason)


def _v2_number(value):
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _v2_provenance(value, label):
    import re
    if not isinstance(value, ProvenanceV2):
        _v2_fail(label + '_provenance_required')
    if not value.generator or not value.version:
        _v2_fail(label + '_provenance_identity_missing')
    if not isinstance(value.manifest_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', value.manifest_sha256):
        _v2_fail(label + '_manifest_sha256_invalid')
    if (value.source_row_id is None) != (value.source_sha256 is None):
        _v2_fail(label + '_source_row_and_hash_must_be_paired')
    if value.source_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', value.source_sha256):
        _v2_fail(label + '_source_sha256_invalid')
    if not isinstance(value.components, tuple) or not isinstance(value.draw_ids, tuple):
        _v2_fail(label + '_provenance_sequences_must_be_tuples')


def _v2_role(role, label):
    if not isinstance(role, PlayerRoleV2) or role.status not in ('none', 'unmodelled', 'named'):
        _v2_fail(label + '_player_role_invalid')
    if role.status == 'none' and (role.player_id is not None or role.slot is not None):
        _v2_fail(label + '_none_role_has_identity')
    if role.status == 'unmodelled' and (not role.slot or role.player_id is not None):
        _v2_fail(label + '_unmodelled_role_needs_slot_only')
    if role.status == 'named' and (not role.player_id or role.slot is not None):
        _v2_fail(label + '_named_role_needs_player_id_only')


def _v2_clock(clock):
    if not isinstance(clock, ClockV2) or not _v2_number(clock.runoff_seconds) or clock.runoff_seconds < 0:
        _v2_fail('clock_total_runoff_required')
    has_live, has_dead = clock.live_seconds is not None, clock.dead_ball_seconds is not None
    if has_live != has_dead:
        _v2_fail('clock_split_must_be_present_together')
    if has_live:
        if (not _v2_number(clock.live_seconds) or not _v2_number(clock.dead_ball_seconds)
                or clock.live_seconds < 0 or clock.dead_ball_seconds < 0):
            _v2_fail('clock_split_seconds_invalid')
        if abs(clock.live_seconds + clock.dead_ball_seconds - clock.runoff_seconds) > 1e-6:
            _v2_fail('clock_split_does_not_match_total')
        if clock.stop_class not in (None, 'running', 'stopped'):
            _v2_fail('clock_stop_class_invalid')
        if clock.stop_class == 'stopped' and clock.dead_ball_seconds != 0:
            _v2_fail('stopped_clock_has_dead_ball_runoff')
    elif clock.stop_class not in (None, 'running', 'stopped'):
        _v2_fail('clock_stop_class_invalid')


def _v2_penalty(penalty, play, event):
    if penalty is None:
        if play.play_void:
            _v2_fail('play_void_requires_pre_snap_penalty')
        return
    if not isinstance(penalty, PenaltyV2):
        _v2_fail('penalty_record_invalid')
    if penalty.phase not in ('pre_snap', 'live_ball'):
        _v2_fail('penalty_phase_invalid')
    if penalty.disposition == 'unknown':
        _v2_fail('unknown_penalty_disposition')
    if penalty.disposition not in ('accepted', 'declined', 'offsetting'):
        _v2_fail('penalty_disposition_invalid')
    if not isinstance(penalty.fouls, tuple) or not penalty.fouls:
        _v2_fail('penalty_foul_required')
    if penalty.disposition == 'offsetting' and len(penalty.fouls) < 2:
        _v2_fail('offsetting_penalty_needs_multiple_fouls')
    if penalty.disposition != 'offsetting' and len(penalty.fouls) != 1:
        _v2_fail('multiple_fouls_need_offsetting_or_named_rules_support')
    for foul in penalty.fouls:
        if (not isinstance(foul, PenaltyFoulV2) or not foul.penalty_type
                or foul.team not in ('offense', 'defense', 'kicking_team', 'receiving_team')
                or type(foul.yards_assessed) is not int or foul.yards_assessed < 0):
            _v2_fail('penalty_foul_fields_invalid')
        if foul.foul_spot is not None and (not _v2_number(foul.foul_spot) or not 0 <= foul.foul_spot <= 100):
            _v2_fail('penalty_foul_spot_invalid')
        _v2_role(foul.player, 'penalty_player')
        if foul.player.status == 'none':
            _v2_fail('penalty_requires_player_or_unmodelled_offender_slot')
        if foul.block_subtype not in (None, 'in_back', 'above_waist'):
            _v2_fail('penalty_block_subtype_invalid')
    if penalty.automatic_first_down is not None and type(penalty.automatic_first_down) is not bool:
        _v2_fail('automatic_first_down_flag_invalid')
    if penalty.provenance is not None:
        _v2_provenance(penalty.provenance, 'penalty')
    if penalty.automatic_first_down is not None and penalty.provenance is None:
        _v2_fail('automatic_first_down_flag_needs_provenance')
    if penalty.phase == 'pre_snap':
        if not play.play_void or not penalty.play_void or event != 'no_play':
            _v2_fail('pre_snap_penalty_must_void_play')
    elif play.play_void or penalty.play_void or event == 'no_play':
        _v2_fail('live_ball_penalty_must_preserve_play_facts')


def _v2_possession(possession, play):
    if possession is None:
        if play.fumble and not (play.kick is not None and play.kick.result == 'muff'
                                and play.kick.fumble_spot_yardline_100 is not None):
            _v2_fail('fumble_requires_recovery_facts')
        if play.event == 'interception':
            _v2_fail('interception_requires_possession_facts')
        if play.scoring is not None and play.scoring.team == 'defense' and play.scoring.kind == 'touchdown':
            _v2_fail('defensive_return_touchdown_requires_possession_facts')
        return
    if not isinstance(possession, PossessionV2):
        _v2_fail('possession_record_invalid')
    if possession.team not in ('offense', 'defense'):
        _v2_fail('possession_team_role_invalid')
    if possession.how not in ('kept', 'interception', 'fumble_recovery'):
        _v2_fail('possession_how_must_be_fact')
    for label, spot in (('turnover', possession.turnover_spot_yardline_100),
                        ('recovery', possession.recovery_spot_yardline_100),
                        ('dead_ball', possession.dead_ball_yardline_100),
                        ('fumble', possession.fumble_spot_yardline_100),
                        ('next_possession', possession.next_possession_yardline_100)):
        if spot is not None and (not _v2_number(spot) or not 0 <= spot <= 100):
            _v2_fail('possession_' + label + '_spot_invalid')
    if possession.next_possession_yardline_100 is not None \
            and (type(possession.next_possession_yardline_100) is not int
                 or not 1 <= possession.next_possession_yardline_100 <= 99):
        _v2_fail('possession_next_spot_invalid')
    if possession.return_yards is not None and type(possession.return_yards) is not int:
        _v2_fail('possession_return_yards_invalid')
    _v2_role(possession.returner, 'possession_returner')
    _v2_role(possession.recovered_by, 'possession_recovered_by')
    if possession.return_yards is None and possession.returner.status != 'none':
        _v2_fail('returner_requires_return_yards')
    if possession.return_yards not in (None, 0) and possession.returner.status == 'none':
        _v2_fail('nonzero_return_requires_returner_or_unmodelled_slot')
    if type(possession.touchback) is not bool:
        _v2_fail('possession_touchback_flag_invalid')
    if play.fumble:
        if possession.fumble_spot_yardline_100 is None:
            _v2_fail('fumble_spot_required')
    elif possession.fumble_spot_yardline_100 is not None:
        _v2_fail('fumble_spot_without_fumble')
    if possession.how == 'kept':
        if possession.team != 'offense' or any(value is not None for value in (
                possession.turnover_spot_yardline_100, possession.return_yards)):
            _v2_fail('kept_possession_has_turnover_facts')
        if play.fumble and (possession.recovery_spot_yardline_100 is None
                            or possession.dead_ball_yardline_100 is None
                            or possession.recovered_by.status == 'none'):
            _v2_fail('retained_fumble_needs_fumble_recovery_and_dead_ball_facts')
    elif possession.how == 'interception':
        if play.event != 'interception' or possession.team != 'defense':
            _v2_fail('interception_possession_mismatch')
        if possession.turnover_spot_yardline_100 is None or possession.dead_ball_yardline_100 is None:
            _v2_fail('interception_needs_turnover_and_dead_ball_spots')
        if possession.return_yards is None or possession.returner.status == 'none':
            _v2_fail('interception_return_requires_yards_and_returner_or_unmodelled_slot')
        if play.fumble:
            _v2_fail('interception_return_fumble_needs_ordered_recovery_facts')
    elif possession.how == 'fumble_recovery':
        if not play.fumble or possession.turnover_spot_yardline_100 is None \
                or possession.recovery_spot_yardline_100 is None or possession.dead_ball_yardline_100 is None:
            _v2_fail('fumble_recovery_needs_fumble_turnover_recovery_and_dead_ball_spots')
        if possession.recovered_by.status == 'none':
            _v2_fail('fumble_recovery_requires_recoverer_or_unmodelled_slot')
        if possession.turnover_spot_yardline_100 != possession.fumble_spot_yardline_100:
            _v2_fail('fumble_turnover_spot_disagrees_with_fumble_spot')
    if possession.touchback:
        if (possession.team != 'defense' or possession.how not in ('interception', 'fumble_recovery')
                or possession.dead_ball_yardline_100 != 0 or possession.return_yards != 0
                or possession.next_possession_yardline_100 is None or play.scoring is not None):
            _v2_fail('defensive_touchback_needs_end_zone_dead_ball_and_restart_facts')
    elif possession.next_possession_yardline_100 is not None:
        if possession.dead_ball_yardline_100 is None \
                or possession.next_possession_yardline_100 != 100 - possession.dead_ball_yardline_100:
            _v2_fail('next_possession_spot_disagrees_with_dead_ball_spot')
    if play.scoring is not None and play.scoring.kind == 'touchdown' \
            and play.scoring.team == 'defense' and possession.team != 'defense':
        _v2_fail('defensive_touchdown_possession_mismatch')
    if (play.scoring is not None and play.scoring.kind == 'touchdown'
            and play.scoring.team == 'defense' and possession.returner.status == 'none'):
        _v2_fail('defensive_return_touchdown_requires_returner_or_unmodelled_slot')


def _v2_kick(kick, play):
    expected = {'punt': 'punt', 'field_goal_attempt': 'field_goal', 'kickoff': 'kickoff'}.get(play.event)
    if kick is None:
        if expected is not None:
            _v2_fail('kick_event_requires_kick_record')
        return
    if not isinstance(kick, KickV2) or expected != kick.kind:
        _v2_fail('kick_record_event_mismatch')
    if play.scoring is not None and play.scoring.kind == 'safety':
        if (kick.kind != 'punt' or kick.result != 'return'
                or kick.possession_after != 'receiving_team'
                or kick.dead_ball_yardline_100 != 0
                or play.scoring.team != 'kicking_team'):
            _v2_fail('punt_return_safety_facts_invalid')
    if (play.scoring is not None and play.scoring.kind == 'touchdown'
            and kick.result in ('blocked', 'muff')):
        _v2_fail(kick.result + '_return_touchdown_attribution_unsupported')
    if not kick.kicking_team or not kick.receiving_team or kick.kicking_team == kick.receiving_team:
        _v2_fail('kick_teams_invalid')
    if not _v2_number(kick.kick_spot_yardline_100) or not 0 <= kick.kick_spot_yardline_100 <= 100:
        _v2_fail('kick_spot_invalid')
    if kick.distance_yards is not None and (type(kick.distance_yards) is not int or kick.distance_yards < 0):
        _v2_fail('kick_distance_invalid')
    allowed = ('made', 'missed', 'blocked', 'touchback', 'return', 'muff',
               'kicking_team_recovery', 'onside_recovery', 'period_expired')
    if kick.result not in allowed:
        _v2_fail('kick_result_invalid')
    if kick.result == 'blocked' and kick.kind == 'kickoff':
        _v2_fail('kickoff_cannot_be_blocked')
    if kick.result in ('return', 'touchback') and kick.kind == 'field_goal':
        _v2_fail('field_goal_result_not_supported_for_return_or_touchback')
    if kick.kind == 'field_goal' and kick.result not in ('made', 'missed', 'blocked', 'period_expired'):
        _v2_fail('field_goal_result_invalid')
    if kick.result == 'made' and (kick.kind != 'field_goal' or kick.possession_after is not None):
        _v2_fail('made_kick_possession_invalid')
    if kick.result == 'period_expired' and kick.possession_after is not None:
        _v2_fail('period_expired_kick_has_next_possession')
    has_score = play.scoring is not None
    if kick.result not in ('made', 'period_expired') and not has_score and kick.possession_after is None:
        _v2_fail('kick_possession_after_required')
    if kick.possession_after not in (None, 'kicking_team', 'receiving_team'):
        _v2_fail('kick_possession_role_invalid')
    for label, spot in (('recovery', kick.recovery_yardline_100),
                        ('return_start', kick.return_start_yardline_100),
                        ('dead_ball', kick.dead_ball_yardline_100),
                        ('fumble', kick.fumble_spot_yardline_100)):
        if spot is not None and (not _v2_number(spot) or not 0 <= spot <= 100):
            _v2_fail('kick_' + label + '_spot_invalid')
    if kick.return_yards is not None and type(kick.return_yards) is not int:
        _v2_fail('kick_return_yards_invalid')
    _v2_role(kick.returner, 'kick_returner')
    _v2_role(kick.recoverer, 'kick_recoverer')
    if kick.return_yards not in (None, 0) and kick.returner.status == 'none':
        _v2_fail('nonzero_kick_return_requires_returner_or_unmodelled_slot')
    if kick.result in ('return', 'muff', 'touchback') and kick.dead_ball_yardline_100 is None:
        _v2_fail('kick_return_dead_ball_spot_required')
    if kick.result == 'return' and kick.return_start_yardline_100 is None:
        _v2_fail('kick_return_start_spot_required')
    if kick.result == 'return' and kick.return_yards is None:
        _v2_fail('kick_return_yards_required')
    if kick.result == 'muff':
        if kick.recovery_team is None or kick.recovery_yardline_100 is None or kick.possession_after != kick.recovery_team:
            _v2_fail('muff_needs_recovery_team_spot_and_possession')
        if not play.fumble:
            _v2_fail('muff_requires_fumble_fact')
        if kick.fumble_spot_yardline_100 is None:
            _v2_fail('muff_fumble_spot_required')
        if kick.returner.status == 'none':
            _v2_fail('muff_requires_fumbler_or_unmodelled_returner')
        if kick.recoverer.status == 'none':
            _v2_fail('muff_requires_recoverer_or_unmodelled_slot')
        if kick.return_yards not in (None, 0):
            _v2_fail('muff_return_yardage_attribution_unsupported')
    elif play.fumble and play.event in ('punt', 'field_goal_attempt', 'kickoff'):
        _v2_fail('kick_fumble_requires_muff_or_named_recovery_event')
    if kick.result in ('blocked', 'kicking_team_recovery', 'onside_recovery'):
        if kick.recovery_team is None or kick.recovery_yardline_100 is None:
            _v2_fail('kick_recovery_needs_team_and_spot')
    elif kick.result != 'muff' and (kick.recovery_team is not None or kick.recovery_yardline_100 is not None):
        _v2_fail('kick_recovery_facts_without_muff')
    if kick.result in ('kicking_team_recovery', 'onside_recovery') and kick.kind != 'kickoff':
        _v2_fail('kicking_team_recovery_only_supported_for_kickoffs')
    if kick.result in ('blocked', 'kicking_team_recovery', 'onside_recovery'):
        expected_possession = kick.recovery_team
        if expected_possession is None or kick.possession_after != expected_possession:
            _v2_fail('kick_recovery_possession_mismatch')
        if kick.recoverer.status == 'none':
            _v2_fail('kick_recovery_requires_recoverer_or_unmodelled_slot')
    if kick.fumble_spot_yardline_100 is not None and kick.result != 'muff':
        _v2_fail('kick_fumble_spot_without_muff')
    if kick.receiving_team_touched_beyond_line is not None \
            and type(kick.receiving_team_touched_beyond_line) is not bool:
        _v2_fail('receiving_touch_fact_invalid')
    if (kick.result == 'muff' and kick.recovery_team == 'kicking_team'
            and kick.recovery_yardline_100 is not None \
            and kick.recovery_yardline_100 < kick.kick_spot_yardline_100 \
            and kick.receiving_team_touched_beyond_line is None):
        _v2_fail('kicking_team_beyond_line_recovery_needs_receiving_touch_fact')
    if kick.result in ('kicking_team_recovery', 'onside_recovery') and kick.possession_after != 'kicking_team':
        _v2_fail('kicking_team_recovery_possession_mismatch')
    if kick.result == 'touchback' and kick.possession_after != 'receiving_team':
        _v2_fail('touchback_possession_mismatch')
    if kick.result == 'blocked' and (kick.recovery_team is None or kick.recovery_yardline_100 is None):
        _v2_fail('blocked_kick_needs_recovery_or_score')
    if play.scoring is not None and play.scoring.team not in ('kicking_team', 'receiving_team'):
        _v2_fail('kick_scoring_team_role_invalid')


def validate_v2(state, play, require_clock=True):
    """Validate a ceg-play-2 record before rules/reducer execution; never repairs facts."""
    if not isinstance(play, GeneratedPlayV2) or play.contract != CONTRACT_V2_VERSION:
        _v2_fail('generated_play_contract_mismatch')
    _v2_provenance(play.provenance, 'play')
    if play.event not in EVENTS_V2:
        _v2_fail('unknown_event:' + str(play.event))
    if not isinstance(play.players, PlayerRolesV2):
        _v2_fail('player_roles_record_invalid')
    if play.scoring is not None:
        if not isinstance(play.scoring, ScoringV2) or play.scoring.kind not in ('touchdown', 'field_goal', 'safety'):
            _v2_fail('scoring_fact_invalid')
        if play.scoring.team not in ('offense', 'defense', 'kicking_team', 'receiving_team'):
            _v2_fail('scoring_team_role_invalid')
    for role_name, role in play.players.__dict__.items():
        _v2_role(role, role_name)
    if require_clock:
        _v2_clock(play.clock)
    elif play.clock is not None:
        _v2_clock(play.clock)
    _v2_penalty(play.penalty, play, play.event)

    if play.event == 'no_play':
        if not play.play_void or play.call is not None or play.penalty is None or play.penalty.phase != 'pre_snap':
            _v2_fail('no_play_requires_void_pre_snap_penalty')
        if any((play.yards_gained is not None, play.air_yards is not None, play.yards_after_catch is not None,
                play.fumble, play.possession is not None, play.scoring is not None, play.kick is not None,
                play.out_of_bounds, any(role.status != 'none' for role in play.players.__dict__.values()))):
            _v2_fail('pre_snap_penalty_carries_play_facts')
        if play.clock is not None and play.clock.runoff_seconds != 0:
            _v2_fail('pre_snap_penalty_clock_runoff_must_be_zero')
        return None
    if play.play_void:
        _v2_fail('play_void_only_valid_for_pre_snap_foul')
    if not isinstance(play.call, PlayCallV2) or play.call.intent not in INTENTS_V2:
        _v2_fail('play_call_required_or_invalid')
    if play.call.provenance is not None:
        _v2_provenance(play.call.provenance, 'play_call')
    expected_intents = {
        'run': ('designed_run', 'kneel'), 'kneel': ('kneel',), 'spike': ('spike',),
        'punt': ('punt',), 'field_goal_attempt': ('field_goal',), 'kickoff': ('kickoff',),
        'scramble': ('dropback',), 'pass_complete': ('dropback',), 'pass_incomplete': ('dropback',),
        'interception': ('dropback',), 'sack': ('dropback',),
    }
    if play.call.intent not in expected_intents.get(play.event, ()):
        _v2_fail('play_intent_event_mismatch')
    _v2_kick(play.kick, play)
    if play.event not in ('punt', 'field_goal_attempt', 'kickoff') and play.kick is not None:
        _v2_fail('kick_record_on_non_kick_event')

    if play.event in ('run', 'scramble', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'kneel', 'spike'):
        if type(play.yards_gained) is not int:
            _v2_fail('scrimmage_yards_gained_required')
    elif play.event not in ('punt', 'field_goal_attempt', 'kickoff') and play.yards_gained is not None:
        _v2_fail('non_scrimmage_event_has_yards')
    if play.event in ('pass_incomplete', 'spike') and play.yards_gained != 0:
        _v2_fail('incomplete_or_spike_must_gain_zero')
    if play.event == 'sack' and play.yards_gained > 0:
        _v2_fail('sack_cannot_gain_yards')
    if play.event == 'pass_complete':
        if (type(play.air_yards) is not int or type(play.yards_after_catch) is not int
                or play.air_yards + play.yards_after_catch != play.yards_gained):
            _v2_fail('completion_air_yards_plus_yac_mismatch')
        if play.players.receiver.status == 'none':
            _v2_fail('completion_receiver_role_required')
    if play.event in ('pass_complete', 'pass_incomplete', 'interception', 'sack', 'spike') \
            and play.players.passer.status == 'none':
        _v2_fail('pass_event_passer_role_required')
    if play.event == 'scramble' and play.players.rusher.status == 'none':
        _v2_fail('scramble_rusher_role_required')
    if play.event == 'run' and play.call.intent == 'designed_run' and play.players.rusher.status == 'none':
        _v2_fail('designed_run_rusher_role_required')
    if play.event == 'kneel' and play.players.rusher.status == 'none':
        _v2_fail('kneel_rusher_role_required')
    if play.event == 'interception' and play.players.interceptor.status == 'none':
        _v2_fail('interceptor_role_required')
    if play.event == 'sack' and play.players.sacker.status == 'none':
        _v2_fail('sacker_role_required')
    if play.event == 'punt' and play.players.punter.status == 'none':
        _v2_fail('punt_punter_role_required')
    if play.event == 'field_goal_attempt' and play.players.kicker.status == 'none':
        _v2_fail('field_goal_kicker_role_required')
    if play.fumble and play.event not in ('punt', 'field_goal_attempt', 'kickoff') \
            and play.players.fumbler.status == 'none':
        _v2_fail('fumble_requires_fumbler_or_unmodelled_slot')
    _v2_possession(play.possession, play)

    boundary = None
    if state is not None and not isinstance(state, dict):
        _v2_fail('pre_snap_state_must_be_mapping')
    if state is not None and 'yl' in state and play.event not in ('punt', 'field_goal_attempt', 'kickoff'):
        yl = state['yl']
        if type(yl) is not int or not 1 <= yl <= 99:
            _v2_fail('pre_snap_yardline_invalid')
        end = yl - play.yards_gained
        if end < 0 or end > 100:
            _v2_fail('play_yardage_crosses_end_line')
        if end == 0:
            boundary = 'opponent_goal_line'
            if (play.event in ('run', 'scramble', 'pass_complete')
                    and (play.scoring is None or play.scoring.kind != 'touchdown'
                         or play.scoring.team != 'offense')):
                _v2_fail('goal_line_gain_needs_offensive_touchdown_fact')
        elif end == 100:
            boundary = 'own_goal_line'
    if play.scoring is not None:
        if play.event in ('punt', 'field_goal_attempt', 'kickoff'):
            if play.scoring.kind == 'field_goal' and (play.event != 'field_goal_attempt'
                    or play.kick is None or play.kick.result != 'made'
                    or play.scoring.team != 'kicking_team'):
                _v2_fail('field_goal_score_needs_made_kick_by_kicking_team')
            if play.scoring.kind == 'touchdown' and play.kick is not None:
                role = play.scoring.team
                if (role not in ('kicking_team', 'receiving_team')
                        or play.kick.possession_after != role
                        or play.kick.result != 'return'):
                    _v2_fail('kick_return_touchdown_team_or_result_mismatch')
                if play.kick.returner.status == 'none':
                    _v2_fail('kick_return_touchdown_requires_returner_or_unmodelled_slot')
                scoring_spot = play.kick.dead_ball_yardline_100
                expected_spot = 0 if role == 'kicking_team' else 100
                if scoring_spot != expected_spot:
                    _v2_fail('kick_return_touchdown_spot_mismatch')
            if play.scoring.kind == 'safety' and play.kick is not None:
                if (play.event != 'punt' or play.kick.result != 'return'
                        or play.scoring.team != 'kicking_team'
                        or play.kick.possession_after != 'receiving_team'
                        or play.kick.dead_ball_yardline_100 != 0):
                    _v2_fail('punt_return_safety_facts_invalid')
        elif play.scoring.kind == 'touchdown':
            if play.scoring.team == 'offense' and boundary != 'opponent_goal_line':
                _v2_fail('offensive_touchdown_must_reach_opponent_goal_line')
            if play.scoring.team == 'defense':
                if play.possession is None or play.possession.team != 'defense' \
                        or play.possession.dead_ball_yardline_100 != 100:
                    _v2_fail('defensive_return_touchdown_needs_defensive_possession_at_own_goal_line')
        elif play.scoring.kind == 'safety':
            ordinary_safety = (play.scoring.team == 'defense' and play.possession is not None
                               and play.possession.team == 'offense'
                               and play.possession.dead_ball_yardline_100 == 100)
            return_safety = (play.scoring.team == 'offense' and play.possession is not None
                             and play.possession.team == 'defense'
                             and play.possession.dead_ball_yardline_100 == 0)
            if not (ordinary_safety or return_safety):
                _v2_fail('safety_needs_possession_and_correct_end_zone_scorer')
        elif play.scoring.kind == 'field_goal' and play.event != 'field_goal_attempt':
            _v2_fail('field_goal_score_requires_field_goal_attempt')
    if play.event == 'field_goal_attempt' and play.kick is not None:
        if (play.kick.result == 'made') != (play.scoring is not None and play.scoring.kind == 'field_goal'):
            _v2_fail('made_field_goal_requires_matching_scoring_fact')
    return boundary


def validate_try_v2(record):
    if not isinstance(record, TryRecordV2) or record.contract != CONTRACT_V2_VERSION:
        _v2_fail('try_contract_mismatch')
    _v2_provenance(record.provenance, 'try')
    if record.kind not in ('extra_point', 'two_point') or not record.offense_team:
        _v2_fail('try_kind_or_offense_invalid')
    if record.result not in ('made', 'missed', 'defensive_return'):
        _v2_fail('try_result_invalid')
    if record.result == 'defensive_return' and not record.scoring_team:
        _v2_fail('defensive_try_return_needs_scoring_team')
    if record.result != 'defensive_return' and record.scoring_team not in (None, record.offense_team):
        _v2_fail('offensive_try_scoring_team_mismatch')


def validate_timeout_v2(record):
    if not isinstance(record, TimeoutDecisionV2):
        _v2_fail('timeout_record_invalid')
    if record.team is not None and not isinstance(record.team, str):
        _v2_fail('timeout_team_invalid')
    _v2_provenance(record.provenance, 'timeout')


def validate_record_v2(state, record, require_clock=True):
    if isinstance(record, GeneratedPlayV2):
        return validate_v2(state, record, require_clock=require_clock)
    if isinstance(record, TryRecordV2):
        return validate_try_v2(record)
    if isinstance(record, TimeoutDecisionV2):
        return validate_timeout_v2(record)
    _v2_fail('record_kind_unsupported')
