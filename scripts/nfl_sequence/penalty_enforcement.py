"""Fail-closed NFL penalty transitions for a deliberately narrow V1.7 subset.

This module is deterministic. It does not choose whether a foul occurs or is
accepted, and it refuses unsupported timing, possession changes, and special
field-position cases instead of approximating them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DownState:
    down: int
    to_go: int
    yardline_100: int  # offense's distance from its opponent's goal line
    possession: str

    def __post_init__(self):
        if not 1 <= self.down <= 4 or self.to_go < 1:
            raise ValueError("invalid down and distance")
        if not 0 <= self.yardline_100 <= 100 or not self.possession:
            raise ValueError("invalid field position or possession")


@dataclass(frozen=True)
class Enforcement:
    state: DownState
    accepted: bool
    yards: int
    rule_basis: str


_PRESNAP = {
    ("offense", "false_start"): 5,
    ("offense", "delay_of_game"): 5,
    ("defense", "encroachment"): 5,
    ("defense", "neutral_zone_infraction"): 5,
}
_PASS_PLAY = {
    ("offense", "offensive_holding"): (10, False, "previous"),
    ("defense", "defensive_holding"): (5, True, "previous"),
    ("defense", "illegal_contact"): (5, True, "previous"),
    ("defense", "defensive_pass_interference"): (None, True, "foul"),
}


def _distance(state: DownState, side: str, yards: int) -> tuple[int, int]:
    """Return enforced distance from opponent goal and actual penalty yards."""
    if side == "offense":
        available = 100 - state.yardline_100  # distance to offense's own goal
        if yards > available / 2:
            raise ValueError("half-distance enforcement is outside this integer-yard subset")
        return state.yardline_100 + yards, yards
    available = state.yardline_100  # distance to opponent's goal
    if yards > available / 2:
        raise ValueError("half-distance enforcement is outside this integer-yard subset")
    return state.yardline_100 - yards, yards


def enforce(*, before: DownState, after_play: DownState, phase: str,
            offender: str, foul: str, accepted: bool,
            foul_yardline_100: int | None = None) -> Enforcement:
    """Apply one supported foul with an explicit accept/decline decision.

    `after_play` is the ordinary result if declined. Accepted supported fouls
    use the previous spot except defensive pass interference, which requires
    an in-field foul spot. Both states must retain the same possession; turnover,
    score, goal-line, offsetting, multiple-foul, and kick situations are out of
    scope and rejected.
    """
    if offender not in ("offense", "defense"):
        raise ValueError("offender must be offense or defense")
    if phase not in ("pre_snap", "live_pass"):
        raise ValueError(f"unsupported penalty phase: {phase}")
    if phase == "pre_snap" and (offender, foul) not in _PRESNAP:
        raise ValueError(f"unsupported pre-snap foul: {(offender, foul)}")
    if phase == "live_pass" and (offender, foul) not in _PASS_PLAY:
        raise ValueError(f"unsupported live-pass foul: {(offender, foul)}")
    if not accepted:
        return Enforcement(after_play, False, 0, "declined: play result stands")
    if before.possession != after_play.possession:
        raise ValueError("accepted supported foul with possession change is unsupported")
    if before.yardline_100 in (0, 100) or after_play.yardline_100 in (0, 100):
        raise ValueError("goal-line or scoring transitions are unsupported")

    if phase == "pre_snap":
        key = (offender, foul)
        yards = _PRESNAP[key]
        new_yardline, actual = _distance(before, offender, yards)
        if new_yardline in (0, 100):
            raise ValueError("enforcement resulting in a goal-line/safety case is unsupported")
        new_to_go = before.to_go + actual if offender == "offense" else max(1, before.to_go - actual)
        if offender == "defense" and (actual >= before.to_go or new_yardline <= before.yardline_100 - before.to_go):
            down, new_to_go = 1, 10
        else:
            down = before.down
        return Enforcement(DownState(down, new_to_go, new_yardline, before.possession),
                           True, actual, "NFL Rule 14-4-1: pre-snap foul; succeeding spot, down retained unless first down")

    yards, automatic_first, spot = _PASS_PLAY[(offender, foul)]
    if spot == "foul":
        if foul_yardline_100 is None or not 0 < foul_yardline_100 < 100:
            raise ValueError("defensive pass interference requires an in-field foul spot")
        if foul_yardline_100 >= before.yardline_100:
            raise ValueError("defensive pass interference must occur beyond the line of scrimmage")
        # The special one-yard/half-distance goal-line DPI rules need a richer
        # hash-mark/spot model, so reject the defense's two-yard line region.
        if foul_yardline_100 <= 2:
            raise ValueError("defensive pass interference near goal line is unsupported")
        new_yardline, actual = foul_yardline_100, abs(before.yardline_100 - foul_yardline_100)
    else:
        assert yards is not None
        new_yardline, actual = _distance(before, offender, yards)
    if new_yardline in (0, 100):
        raise ValueError("enforcement resulting in a goal-line/safety case is unsupported")
    if automatic_first or (offender == "defense" and new_yardline <= before.yardline_100 - before.to_go):
        down, to_go = 1, 10
    elif offender == "offense":
        down, to_go = before.down, before.to_go + actual
    else:
        # Defensive pass interference always grants a first down; other
        # supported defensive fouls above already use automatic_first.
        raise AssertionError("unsupported defensive first-down rule")
    return Enforcement(DownState(down, to_go, new_yardline, before.possession), True,
                       actual, "NFL Rule 14-4-5: passing-play previous spot; defensive pass interference at foul spot")
