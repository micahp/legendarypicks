"""Chronological evaluation of the contextual simulator against v1.

Spec section 13, Phases 3 and 7. Interface only: the behavior is not implemented yet.
"""
from __future__ import annotations


def chronological_split(games, cutoff):
    """Phase 3: train on games before `cutoff`, evaluate on games at or after it. No future leakage."""
    raise NotImplementedError('Phase 3: chronological split')


def compare_to_v1(challenger_results, v1_results):
    """Phases 3 and 7: paired comparison of scores and probabilities against NFL v1 and market baselines."""
    raise NotImplementedError('Phase 7: adoption comparison against v1')
