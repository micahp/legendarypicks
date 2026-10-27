"""Dynamic, cutoff-safe, matchup-conditioned historical sampling pools.

Spec sections 5 and 6, Phase 2. Interface only: the behavior is not implemented yet.
"""
from __future__ import annotations


def eligible_games(season_games, cutoff):
    """Phase 2: games eligible for a pool at `cutoff`. New games enter; games after the cutoff never do."""
    raise NotImplementedError('Phase 2: cutoff-safe eligibility')


def build_context_pool(games, context):
    """Phase 2: an indexed, seed-reproducible sampling structure for one frozen context."""
    raise NotImplementedError('Phase 2: context-specific indexed sampling')
