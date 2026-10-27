"""In-game context: score differential, time remaining, workload, and fatigue.

Spec sections 8 and 9, Phases 4 and 5. Interface only: the behavior is not implemented yet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameContext:
    score_differential: int = 0
    seconds_remaining: int = 3600
    offensive_workload: int = 0
    defensive_workload: int = 0


def advance_game_context(context, play):
    """Phases 4 and 5: update the in-game variables after a simulated play, leaving the reducer authoritative."""
    raise NotImplementedError('Phases 4 and 5: in-game context updates')
