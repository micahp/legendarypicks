"""Bounded support guard for an already-selected fourth-down scrimmage call.

A fourth-down go-for-it decision is already made. This never converts
between a kick and a scrimmage call: it only substitutes an unsupported
run/pass intent with the other, supported scrimmage intent.
"""


def resolve_fourth_down_intent(intent, down, supported_intents, *, enabled=False):
    """Return (resolved intent, fallback reason or None).

    No scrimmage support remains an error in the caller; no missing outcome
    is manufactured from the historical data.
    """
    if not enabled or int(down) != 4 or intent not in ('run', 'dropback'):
        return intent, None
    supported = set(supported_intents)
    if intent in supported:
        return intent, None
    alternative = 'dropback' if intent == 'run' else 'run'
    if alternative in supported:
        return alternative, f'unsupported_fourth_down_{intent}_intent_resolved_to_{alternative}'
    return intent, None
