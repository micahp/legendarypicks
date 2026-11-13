"""Pure precision guard for historical source rows after half-yard penalties.

Observed nflverse play positions/distances are integer yards.  A fractional
simulated state is valid football state but must not masquerade as the exact
floor() integer's historical play-context observation.
"""


def has_exact_historical_integer(value) -> bool:
    return type(value) in (int, float) and float(value).is_integer()
