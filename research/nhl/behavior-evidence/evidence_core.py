"""Small, deterministic helpers for the NHL behavior-evidence audit."""

from __future__ import annotations

import math
import re
from typing import Iterable


CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
SIDES = ("home", "away")


def parse_clock(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError(f"clock must be a string, got {value!r}")
    match = CLOCK.fullmatch(value)
    if not match or int(match.group(2)) >= 60:
        raise ValueError(f"unsupported NHL period clock {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def decode_situation_code(value: object) -> dict[str, int] | None:
    """Decode a four-digit GameCenter situation code without guessing on bad rows.

    The observed convention to validate against shifts is away goalie, away
    skaters, home skaters, home goalie. This helper only decodes the digits;
    the audit reports empirical agreement before relying on the convention.
    """
    text = str(value or "")
    if len(text) != 4 or not text.isdigit():
        return None
    away_goalie, away_skaters, home_skaters, home_goalie = map(int, text)
    if away_goalie not in (0, 1) or home_goalie not in (0, 1):
        return None
    if not 0 <= away_skaters <= 6 or not 0 <= home_skaters <= 6:
        return None
    return {
        "away_goalie": away_goalie,
        "away_skaters": away_skaters,
        "home_skaters": home_skaters,
        "home_goalie": home_goalie,
    }


def reconcile_event_state(source_state: dict[str, int] | None,
                          shift_pre_state: dict[str, int] | None,
                          shift_post_state: dict[str, int] | None,
                          *, at_shift_boundary: bool) -> dict[str, object]:
    """Reconcile a PBP event snapshot with second-resolution shift intervals.

    Shift snapshots are the left and right limits around the event clock, not
    claims about subsecond ordering. A source situation code is eligible for
    conditional event-rate work only when it agrees with an available shift
    snapshot. Without a code, a shift fallback is allowed only when the state
    is stable across the clock; a boundary with no resolving evidence remains
    explicitly ambiguous.
    """
    keys = ("away_goalie", "away_skaters", "home_skaters", "home_goalie")

    def complete(state: dict[str, int] | None) -> bool:
        return state is not None and all(key in state for key in keys)

    def same(left: dict[str, int] | None, right: dict[str, int] | None) -> bool:
        return complete(left) and complete(right) and all(left[key] == right[key] for key in keys)

    pre_match = same(source_state, shift_pre_state)
    post_match = same(source_state, shift_post_state)
    shift_stable = same(shift_pre_state, shift_post_state)

    if complete(source_state):
        if at_shift_boundary:
            if pre_match and post_match:
                status, alignment, eligible = "source_matches_both_boundary_states", "both", True
            elif pre_match:
                status, alignment, eligible = "source_matches_left_limit", "left_limit", True
            elif post_match:
                status, alignment, eligible = "source_matches_right_limit", "right_limit", True
            else:
                status, alignment, eligible = "source_shift_conflict", "conflict", False
        elif same(source_state, shift_pre_state):
            status, alignment, eligible = "source_matches_stable_shift_state", "stable", True
        elif shift_pre_state is None and shift_post_state is None:
            status, alignment, eligible = "source_only_no_shift_comparison", "uncompared", True
        else:
            status, alignment, eligible = "source_shift_conflict", "conflict", False
        state = source_state if eligible else None
        state_source = "situation_code" if eligible else "unresolved"
    elif not at_shift_boundary and shift_stable and complete(shift_pre_state):
        status, alignment, eligible = "stable_shift_fallback", "stable", True
        state = shift_pre_state
        state_source = "shift_interval_fallback"
    elif at_shift_boundary:
        status, alignment, eligible = "missing_source_at_shift_boundary", "ambiguous", False
        state = None
        state_source = "unresolved"
    else:
        status, alignment, eligible = "missing_or_incomplete_state", "unresolved", False
        state = None
        state_source = "unresolved"

    return {
        "status": status,
        "temporal_alignment": alignment,
        "eligible_for_conditional_fit": eligible,
        "state_source": state_source,
        "state": state,
        "source_matches_shift_left_limit": pre_match,
        "source_matches_shift_right_limit": post_match,
    }


def goalie_identity_status(goalie_id_present: bool, state_resolved: bool,
                           defending_goalie_present: bool | None) -> str:
    """Classify a missing shot-event goalie ID without treating it as a skill value."""
    if goalie_id_present:
        return "goalie_id_present"
    if not state_resolved or defending_goalie_present is None:
        return "missing_id_state_unresolved"
    if not defending_goalie_present:
        return "expected_empty_net"
    return "missing_id_with_goalie_present"


def strength_for_side(home_skaters: int, away_skaters: int, side: str) -> str:
    if side == "home":
        return f"{home_skaters}v{away_skaters}"
    if side == "away":
        return f"{away_skaters}v{home_skaters}"
    raise ValueError(f"unknown team side {side!r}")


def score_state(own_goals: int, opponent_goals: int) -> str:
    if own_goals > opponent_goals:
        return "leading"
    if own_goals < opponent_goals:
        return "trailing"
    return "tied"


def time_remaining_bucket(period_type: str, period_length: int, elapsed: int) -> str:
    remaining = max(0, period_length - elapsed)
    if period_type == "SO":
        return "shootout"
    if remaining > 600:
        return ">10m"
    if remaining > 300:
        return "5-10m"
    if remaining > 60:
        return "1-5m"
    return "<=1m"


def shrink_binary_rate(successes: int, trials: int, parent_rate: float,
                       prior_strength: float = 20.0) -> float:
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("binary counts must satisfy 0 <= successes <= trials")
    if not 0.0 <= parent_rate <= 1.0 or prior_strength <= 0:
        raise ValueError("invalid parent rate or prior strength")
    return (successes + prior_strength * parent_rate) / (trials + prior_strength)


def binary_scores(labels: Iterable[int], probabilities: Iterable[float]) -> dict[str, float | int]:
    pairs = list(zip(labels, probabilities, strict=True))
    if not pairs:
        return {"n": 0, "brier": math.nan, "log_loss": math.nan}
    clipped = [(int(y), min(1.0 - 1e-12, max(1e-12, float(p)))) for y, p in pairs]
    if any(y not in (0, 1) for y, _ in clipped):
        raise ValueError("binary labels must be 0 or 1")
    return {
        "n": len(clipped),
        "brier": sum((p - y) ** 2 for y, p in clipped) / len(clipped),
        "log_loss": -sum(y * math.log(p) + (1 - y) * math.log(1 - p)
                         for y, p in clipped) / len(clipped),
    }
