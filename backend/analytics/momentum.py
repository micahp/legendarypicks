"""Momentum engine core (design: docs/SPEC-momentum-engine.md).

Dual Wilder moving averages (Wilder smoothing = EMA with alpha = 1/n) of one stat
over a fast and a slow window, MACD-style. The crossover is an EVENT (timestamped,
alertable); the spread between the averages is a continuous momentum score.
Projections measure LEVEL ("how good lately"); this measures TURN (regime change).

Pure math only — no DB, no league knowledge. Adapters feed it series; the compute
job (compute_momentum.py) persists state and cross events.
"""
from typing import List, Optional


def wilder(values: List[float], n: int) -> List[Optional[float]]:
    """Wilder-smoothed series. values ordered OLDEST-FIRST (chronological).

    Standard Wilder init: the first emitted value is the simple mean of the first
    n observations; positions before warmup are None. alpha = 1/n thereafter.
    """
    if n <= 0 or len(values) < n:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * (n - 1)
    seed = sum(values[:n]) / n
    out.append(seed)
    prev = seed
    for v in values[n:]:
        prev = prev + (v - prev) / n
        out.append(prev)
    return out


def cross_state(values: List[float], fast_n: int = 5, slow_n: int = 26) -> Optional[dict]:
    """Full dual-MA read of one stat series. values ordered OLDEST-FIRST.

    Returns None when the series can't support the slow window (small-sample
    guard — a 3-game WC group stage gets no verdict, not a noisy one).

    state: 'hot' (fast above slow) | 'cold' (fast below slow) | 'neutral' (equal).
    crosses: every sign change after warmup, oldest first, as
             {idx, direction: 'golden'|'death', fast, slow} — idx indexes `values`.
    games_since_cross: games elapsed since the most recent cross (0 = crossed on
    the latest game); None if no cross has occurred since warmup.
    """
    vals = [float(v) for v in values if v is not None]
    if len(vals) < slow_n or fast_n >= slow_n:
        return None
    f = wilder(vals, fast_n)
    s = wilder(vals, slow_n)
    crosses = []
    prev_sign = 0
    for i in range(slow_n - 1, len(vals)):
        d = f[i] - s[i]
        sign = 1 if d > 0 else -1 if d < 0 else 0
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            crosses.append({
                "idx": i,
                "direction": "golden" if sign > 0 else "death",
                "fast": round(f[i], 3), "slow": round(s[i], 3),
            })
        if sign != 0:
            prev_sign = sign
    fast, slow = f[-1], s[-1]
    spread = fast - slow
    state = "hot" if spread > 0 else "cold" if spread < 0 else "neutral"
    last_idx = len(vals) - 1
    return {
        "n": len(vals),
        "fast": round(fast, 3),
        "slow": round(slow, 3),
        "spread": round(spread, 3),
        # slow-normalized so a +0.4 TB spread and a +4 K spread are comparable
        "spread_pct": round(spread / slow, 4) if slow > 0 else None,
        "state": state,
        "crosses": crosses,
        "games_since_cross": (last_idx - crosses[-1]["idx"]) if crosses else None,
        "last_cross_direction": crosses[-1]["direction"] if crosses else None,
    }
