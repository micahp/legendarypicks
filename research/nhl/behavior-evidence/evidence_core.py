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
