"""Opt-in feature identity for the frozen Week 11 V2 event-expansion branch.

The registry changes configuration identity only.  A switch has no effect
until a mechanism has a verified classifier, rule transition, and statistics
adapter.  Keeping every switch false preserves the frozen V2 execution path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


MODEL_BASE = 'slc-v2-week11-frozen'
SWITCH_NAMES = (
    'interception_returns',
    'fumble_returns',
    'pre_snap_penalties',
    'live_ball_penalties',
    'sack_fumble_transitions',
    'own_end_zone_recovery',
    'punt_return_events',
    'overtime_fourth_down_policy',
    'turnover_terminal_events',
    'kneel_events',
    'spike_events',
    'timeout_decisions',
)


@dataclass(frozen=True)
class EventExpansionSwitches:
    interception_returns: bool = True
    fumble_returns: bool = True
    pre_snap_penalties: bool = True
    live_ball_penalties: bool = True
    sack_fumble_transitions: bool = True
    own_end_zone_recovery: bool = True
    punt_return_events: bool = True
    overtime_fourth_down_policy: bool = True
    turnover_terminal_events: bool = True
    kneel_events: bool = True
    spike_events: bool = True
    timeout_decisions: bool = True

    def __post_init__(self):
        for name, enabled in asdict(self).items():
            if type(enabled) is not bool:
                raise ValueError(f'event switch {name} must be boolean')

    @classmethod
    def from_enabled(cls, names=()):
        names = tuple(names)
        unknown = sorted(set(names) - set(SWITCH_NAMES))
        if unknown:
            raise ValueError('unknown event expansion switch: ' + ', '.join(unknown))
        if len(names) != len(set(names)):
            raise ValueError('event expansion switches must be unique')
        return cls(**{name: name in names for name in SWITCH_NAMES})

    def enabled(self):
        return tuple(name for name in SWITCH_NAMES if getattr(self, name))

    def model_identity(self):
        """Content-addressed identity for a one-switch or multi-switch ablation."""
        config = {'base_model': MODEL_BASE, 'switches': asdict(self)}
        digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        suffix = '+'.join(self.enabled()) if self.enabled() else 'frozen-control'
        return {'model_id': MODEL_BASE + '+' + suffix, 'config_sha256': digest, 'config': config}


FROZEN_CONTROL = EventExpansionSwitches.from_enabled(())
