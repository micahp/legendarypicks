"""Event vocabulary for nfl-seq v0.1, taken from docs/GRIDIRON-CONTRACT-v1.md.

Input kinds are what the reducer accepts. Unsupported kinds are named in the contract but not
modelled yet; the reducer refuses them with UnsupportedMechanic so they never run as a benign
play. Derived kinds are emitted by the reducer and cannot be fed back in.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from .state import SIDES

PLAY_KINDS = (
    "run",
    "pass_complete",
    "pass_incomplete",
    "interception",
    "sack",
    "qb_scramble",
    "kneel",
    "spike",
)
INPUT_KINDS = PLAY_KINDS + ("punt", "field_goal", "extra_point", "kickoff")
UNSUPPORTED_KINDS = ("penalty", "two_point_try", "fumble")
DERIVED_KINDS = ("period_end", "game_end", "safety")
ALL_KINDS = INPUT_KINDS + UNSUPPORTED_KINDS + DERIVED_KINDS
PROVENANCES = ("simulated", "observed")


@dataclass(frozen=True)
class Event:
    """One football event. Fields not used by a kind keep their defaults.

    ``yards`` is signed gain for plays, gross distance for punts, and the signed outcome for
    kneels. ``elapsed`` is clock seconds consumed before the next event. ``made`` applies to
    field goals and extra points. ``return_yards`` is the signed return after a punt, kickoff or
    interception (a negative return moves the ball back toward the returning team's own goal).
    ``fumble_lost`` marks a lost fumble on a play that is otherwise resolved.
    """

    kind: str
    offense: Optional[str] = None
    yards: int = 0
    elapsed: int = 0
    made: Optional[bool] = None
    touchback: bool = False
    return_yards: int = 0
    fumble_lost: bool = False
    provenance: str = "simulated"

    def __post_init__(self) -> None:
        if self.kind not in ALL_KINDS:
            raise ValueError("unknown event kind %r" % (self.kind,))
        if self.provenance not in PROVENANCES:
            raise ValueError("unknown provenance %r" % (self.provenance,))
        if self.offense is not None and self.offense not in SIDES:
            raise ValueError("offense must be a side, got %r" % (self.offense,))
        if self.elapsed < 0:
            raise ValueError("elapsed must be non-negative")
        if self.kind in ("field_goal", "extra_point") and self.made is None:
            raise ValueError("%s needs made=True or False" % self.kind)
        if self.kind in INPUT_KINDS and self.offense is None:
            raise ValueError("%s needs the acting side" % self.kind)
        if self.kind == "punt" and self.yards < 0:
            raise ValueError("punt yards is gross distance and must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(**data)
