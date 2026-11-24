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
