"""Pregame-only boundary for a future stochastic simulator.

This module deliberately has no adapter from historical replay events or final
boxscores. Phase 1 defines the boundary; Phase 2 supplies fitted components.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol
import random


class LookaheadFeatureError(ValueError):
    """A proposed pregame feature was not available by scheduled start."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LookaheadFeatureError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value


@dataclass(frozen=True)
class PregameFeature:
    key: str
    value: float | int | str
    available_at_utc: datetime
    source_kind: str
    source_key: str
    source_sha256: str
    quality_disposition: str


@dataclass(frozen=True)
class PregameSnapshot:
    game_id: str
    scheduled_start_utc: datetime
    home_team_id: int
    away_team_id: int
    features: tuple[PregameFeature, ...]

    def __post_init__(self) -> None:
        start = _utc(self.scheduled_start_utc)
        if self.home_team_id <= 0 or self.away_team_id <= 0 or self.home_team_id == self.away_team_id:
            raise ValueError("PREGAME_TEAM_IDENTITIES_INVALID")
        seen: set[str] = set()
        for feature in self.features:
            available = _utc(feature.available_at_utc)
            if available > start:
                raise LookaheadFeatureError(
                    f"FEATURE_AVAILABLE_AFTER_START {feature.key}: {available.isoformat()} > {start.isoformat()}")
            if feature.quality_disposition != "ACCEPT":
                raise ValueError(f"PREGAME_FEATURE_NOT_ACCEPTED {feature.key}")
            if feature.key in seen:
                raise ValueError(f"DUPLICATE_PREGAME_FEATURE {feature.key}")
            seen.add(feature.key)


@dataclass(frozen=True)
class GeneratedEvent:
    """An event sampled prospectively by a future simulator component."""
    sequence_index: int
    event_kind: str
    period_type: str
    period_number: int
    period_clock_seconds: int
    event_owner_team_id: int | None
    generated_attributes: tuple[tuple[str, str | int | float | None], ...]


@dataclass(frozen=True)
class SimulationRequest:
    """The complete public input to a future simulation call."""
    pregame: PregameSnapshot
    random_seed: int


class StochasticComponent(Protocol):
    name: str

    def generate(self, pregame: PregameSnapshot,
                 rng: random.Random) -> Iterable[GeneratedEvent]:
        """Generate future events from pregame information and fitted parameters."""


def assert_no_replay_input(request: SimulationRequest) -> None:
    """Runtime boundary guard used by adapters and tests."""
    if not isinstance(request.pregame, PregameSnapshot):
        raise TypeError("SIMULATION_REQUIRES_PREGAME_SNAPSHOT")
    for feature in request.pregame.features:
        if feature.available_at_utc > request.pregame.scheduled_start_utc:
            raise LookaheadFeatureError(f"FEATURE_LOOKAHEAD {feature.key}")
