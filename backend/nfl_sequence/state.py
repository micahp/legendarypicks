"""Game state for the forward-only NFL play generator (nfl-seq v0.1).

Teams are sides, 'home' and 'away', inside the engine. The simulator attaches team codes only
in the public projection, so a side and a team are never confused. ``yardline_100`` is
offense-relative: yards from the offense's spot to the opponent's goal line, 1..99 at ordinary
spots. The state holds no randomness and no history; the simulator owns both.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

HOME = "home"
AWAY = "away"
SIDES = (HOME, AWAY)
PHASES = ("kickoff", "scrimmage", "try", "final")
RESULTS = (HOME, AWAY, "tie")
REGULATION_SECONDS = 900
OVERTIME_SECONDS = 600


class InvalidState(ValueError):
    """A state that breaks an invariant. Raised, never repaired."""


def other(side: str) -> str:
    if side == HOME:
        return AWAY
    if side == AWAY:
        return HOME
    raise InvalidState("not a side: %r" % (side,))


@dataclass(frozen=True)
class GameState:
    """Everything the reducer needs. ``phase`` decides which fields are populated.

    kickoff:   ``kicking`` is the team kicking off; offense, down, ydstogo, yardline are None.
    scrimmage: ``offense`` has the ball; down, ydstogo, yardline_100 are set.
    try:       ``offense`` is the team attempting the point after; no down or spot.
    final:     ``result`` is set; nothing else is legal.
    """

    period: int
    clock: int
    phase: str
    offense: Optional[str]
    kicking: Optional[str]
    home_score: int
    away_score: int
    down: Optional[int]
    ydstogo: Optional[int]
    yardline_100: Optional[int]
    opening_kicker: str
    ot_kicker: str
    ot_possessions: int
    drive_index: int
    events: int
    result: Optional[str]

    def score(self, side: str) -> int:
        return self.home_score if side == HOME else self.away_score

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameState":
        return cls(**data)


def validate_state(state: GameState) -> None:
    """Raise InvalidState unless ``state`` is internally consistent."""
    if state.phase not in PHASES:
        raise InvalidState("unknown phase %r" % (state.phase,))
    if state.period not in (1, 2, 3, 4, 5):
        raise InvalidState("period must be 1..5, got %r" % (state.period,))
    limit = REGULATION_SECONDS if state.period <= 4 else OVERTIME_SECONDS
    if not 0 <= state.clock <= limit:
        raise InvalidState("clock %r outside 0..%d" % (state.clock, limit))
    if state.home_score < 0 or state.away_score < 0 or state.events < 0:
        raise InvalidState("scores and event count must be non-negative")
    if state.opening_kicker not in SIDES or state.ot_kicker not in SIDES:
        raise InvalidState("kicker fields must be sides")
    if not 0 <= state.ot_possessions <= 2:
        raise InvalidState("ot_possessions must be 0..2")

    if state.phase == "scrimmage":
        if state.offense not in SIDES or state.kicking is not None:
            raise InvalidState("scrimmage needs an offense and no kicker")
        if state.down not in (1, 2, 3, 4):
            raise InvalidState("scrimmage down must be 1..4, got %r" % (state.down,))
        if state.yardline_100 is None or not 1 <= state.yardline_100 <= 99:
            raise InvalidState("scrimmage yardline_100 must be 1..99")
        if state.ydstogo is None or not 1 <= state.ydstogo <= state.yardline_100:
            raise InvalidState("ydstogo must be 1..yardline_100 (goal to go caps it)")
    elif state.phase == "kickoff":
        if state.kicking not in SIDES or state.offense is not None:
            raise InvalidState("kickoff needs a kicking side and no offense")
        if state.down is not None or state.yardline_100 is not None:
            raise InvalidState("kickoff carries no down or spot")
    elif state.phase == "try":
        if state.offense not in SIDES or state.kicking is not None:
            raise InvalidState("try needs the scoring side as offense")
        if state.down is not None or state.yardline_100 is not None:
            raise InvalidState("try carries no down or spot")
    else:
        if state.result not in RESULTS:
            raise InvalidState("final needs a result")
        if state.result == HOME and state.home_score <= state.away_score:
            raise InvalidState("result home contradicts the score")
        if state.result == AWAY and state.away_score <= state.home_score:
            raise InvalidState("result away contradicts the score")
        if state.result == "tie" and state.home_score != state.away_score:
            raise InvalidState("result tie contradicts the score")
