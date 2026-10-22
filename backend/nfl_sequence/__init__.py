"""Forward-only NFL play-by-play engine for Gridiron Physics (nfl-seq v0.1).

Prediction and historical reconstruction are separate: a simulated run is always labelled
HYPOTHETICAL MODEL SIMULATION. See docs/NFL-SEQUENCE-INTEGRATION-v0.1.md for the contract that the
playbook and interface agents build against.
"""
from .simulate import MODEL_VERSION, RULES_VERSION, Simulator, script, validate_script

__all__ = ["MODEL_VERSION", "RULES_VERSION", "Simulator", "script", "validate_script"]
