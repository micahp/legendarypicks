"""Post-recovery endpoint sampler for a fumble at or past the offense goal line (V1.7 research path).

A recovery outcome of 'continuation' means the ball stays live after the recovery. This module draws where the play
ends. It draws post-recovery movement, not the historical play's total yards: the pool measures movement from the
recovery spot to the dead-ball spot (data/recovery_endpoint_pool_1999_2025.csv, built by
docs/research/own-end-zone-recovery-2026-11-16/endpoint_audit.md).

Two rules are checked explicitly, not sampled:
- Fourth down (before a change of possession): a teammate of the fumbler who recovers makes the ball dead at the
  recovery spot.
- After the two-minute warning (Q2 and Q4, at 2:00 or less): the same restriction applies.
The fumbler recovers in about 57 percent of parsed offensive recoveries. A teammate recovery under a restriction is
drawn with that share, and then resolved by the rule above.

Nothing here invents a spot. A draw is refused when the pool has too few rows near the recovery spot.
"""
import csv
from pathlib import Path

POOL_PATH = Path(__file__).resolve().parent / 'data' / 'recovery_endpoint_pool_1999_2025.csv'
MIN_ROWS = 30          # a window with fewer observed recoveries is refused, not padded
WINDOW = 10            # yards either side of the recovery spot
FUMBLER_SHARE = None   # computed from the pool when loaded


class EndpointUnavailable(Exception):
    """The pool has too few observed recoveries near this spot for this side."""


def _as_int(text):
    return int(float(text)) if text not in ('', None) else None


class EndpointPool:
    def __init__(self, path=POOL_PATH):
        with open(path, newline='') as handle:
            self.rows = [{
                'side': r['side'], 'rec_yl': _as_int(r['rec_yl']), 'terminal': r['terminal'],
                'end_yl': _as_int(r['end_yl']), 'G': _as_int(r['G']),
                'fumbler': {'True': True, 'False': False}.get(r['fumbler'])}
                for r in csv.DictReader(handle)]
        offense = [r for r in self.rows if r['side'] == 'offense' and r['fumbler'] is not None]
        self.fumbler_share = sum(1 for r in offense if r['fumbler']) / len(offense)

    def candidates(self, side, base):
        """Observed recoveries that match the base. A base at or past the goal line uses only recoveries that were
        themselves at the goal line (100 to 110). Own-deep recoveries are tackled on the spot far more often, so mixing
        them in would understate continuation."""
        if base >= 100:
            goal = [r for r in self.rows if r['side'] == side and r['rec_yl'] is not None
                    and 100 <= r['rec_yl'] <= 110]
            if len(goal) >= MIN_ROWS:
                return goal
            raise EndpointUnavailable(f'{side} recoveries at the goal line: {len(goal)} observed, floor {MIN_ROWS}')
        near = [r for r in self.rows if r['side'] == side and r['rec_yl'] is not None
                and abs(r['rec_yl'] - base) <= WINDOW]
        if len(near) >= MIN_ROWS:
            return near
        raise EndpointUnavailable(f'{side} recoveries near spot {base}: {len(near)} observed, floor {MIN_ROWS}')

    def draw(self, rng, side, base, restricted_teammate=False, fumble_spot=None):
        """Return a dict: terminal, end_yl (offense frame, or None), source. `base` is the recovery spot.

        A teammate recovery under a restriction makes the ball dead, and the next snap is at the fumble spot, or at the
        recovery spot if that is further back (Rule 8-7-5c and 8-7-6c). Further back is a larger yardline value.
        """
        if restricted_teammate:
            spot = base if fumble_spot is None else max(base, fumble_spot)
            return {'terminal': 'restricted_dead', 'end_yl': spot, 'source': 'rule_fourth_down_or_two_minute'}
        pool = self.candidates(side, base)
        row = pool[rng.randrange(len(pool))]
        if row['terminal'] == 'touchdown':
            return {'terminal': 'touchdown', 'end_yl': None, 'source': f'pool_n={len(pool)}'}
        if row['terminal'] == 'safety':
            return {'terminal': 'safety', 'end_yl': None, 'source': f'pool_n={len(pool)}'}
        if row['terminal'] == 'incomplete':
            return {'terminal': 'incomplete', 'end_yl': base, 'source': f'pool_n={len(pool)}'}
        moved = row['G'] or 0
        end = base - moved if side == 'offense' else base + moved
        return {'terminal': row['terminal'], 'end_yl': end, 'source': f'pool_n={len(pool)}'}


def is_restricted(down, quarter, clock):
    """Fourth down, or the last two minutes of the first or second half (clock in seconds, Q2 and Q4 only)."""
    return down == 4 or (quarter in (2, 4) and clock <= 120)


_POOL = None


def pool():
    global _POOL
    if _POOL is None:
        _POOL = EndpointPool()
    return _POOL
