"""Pregame context snapshot: as-of-safe matchup context and its source manifest.

Spec section 4, Phase 1. Interface only: the behavior is not implemented yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONTEXT_SCHEMA = 'lp-nfl-pregame-context-1'


@dataclass(frozen=True)
class SourceRecord:
    name: str
    as_of: str
    sha256: str


@dataclass(frozen=True)
class PregameContext:
    game_id: str
    as_of: str
    sources: tuple = field(default_factory=tuple)


def build_pregame_context(game_id, as_of, sources):
    """Phase 1: build the versioned context, using only sources stamped at or before `as_of`."""
    raise NotImplementedError('Phase 1: build the as-of-safe pregame context')
