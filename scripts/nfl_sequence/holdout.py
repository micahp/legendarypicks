"""The sealed holdout. Every path that can read a season checks it here before touching data.

2026 is the holdout for every model. No 2026 game outcome, player stat, tracking row, simulation output or mixed-season
artifact may be used for fitting, tuning, selection or evaluation. Any change to that rule needs an explicit written
protocol first; this module does not provide one.
"""

HOLDOUT_SEASON = 2026


def refuse_if_holdout(season, what):
    if int(season) >= HOLDOUT_SEASON:
        raise ValueError(f'{what}: season {season} is the sealed {HOLDOUT_SEASON} holdout')
