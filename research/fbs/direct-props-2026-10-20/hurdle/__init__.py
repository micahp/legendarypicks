"""Preregistered FBS passing-hurdle implementation (prereg rev4).

Modules
-------
cohort          strictly chronological, per-season pregame membership + provenance
priors          the two separate priors (participation vs conditional volume)
model           smoothed hurdle, zero-truncated NB, shared attempts, comparators
leakage         the §7 assertions, as callable guards that raise
prereg_gate     the §10 signature gate — fitting refuses to start unsigned
run_hurdle_passing   --check-only readiness report; --fit is gated
"""
from __future__ import annotations

from . import cohort, leakage, model, prereg_gate, priors   # noqa: F401

__all__ = ["cohort", "priors", "model", "leakage", "prereg_gate"]
