"""Playbook seam: how a team configuration tilts the neutral baseline. Nothing else.

The engine owns the state machine and the baseline distributions. A playbook may only multiply
the baseline probability of each call in CALLS for the offense in the current state, and it may
name participants. It may not change outcomes, clocks, scores or legality. The neutral playbook
returns no tilt, so the engine's output with it is the league-average baseline.

Contract: docs/NFL-SEQUENCE-INTEGRATION-v0.1.md, section "Playbook interface".
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Protocol

CALLS = ("run", "pass", "punt", "field_goal", "kneel", "spike")


class PlaybookError(ValueError):
    """A playbook returned weights the engine cannot use. Raised, never clipped."""


class Playbook(Protocol):
    name: str
    version: str

    def call_weights(self, state: Mapping[str, object], team: str) -> Mapping[str, float]:
        """Non-negative multipliers over CALLS for ``team`` in the public state. Missing = 1.0."""

    def participants(self, state: Mapping[str, object], team: str, call: str) -> Mapping[str, Optional[str]]:
        """Roster ids for the call, or {} when the playbook has no roster. Never guess a name."""


class NeutralPlaybook:
    """Equal weights for every team. The default and the reference for playbook comparisons."""

    name = "neutral-mock"
    version = "v0"

    def call_weights(self, state: Mapping[str, object], team: str) -> Mapping[str, float]:
        return {}

    def participants(self, state: Mapping[str, object], team: str, call: str) -> Mapping[str, Optional[str]]:
        return {}


def checked_weights(raw: Mapping[str, float]) -> Dict[str, float]:
    """Validate a playbook's weights and fill missing calls with 1.0."""
    unknown = sorted(set(raw) - set(CALLS))
    if unknown:
        raise PlaybookError("unknown calls in playbook weights: %s" % ", ".join(unknown))
    weights = {}
    for call in CALLS:
        value = float(raw.get(call, 1.0))
        if not math.isfinite(value) or value < 0:
            raise PlaybookError("weight for %s must be finite and >= 0, got %r" % (call, value))
        weights[call] = value
    if sum(weights.values()) <= 0:
        raise PlaybookError("playbook weights are all zero")
    return weights
