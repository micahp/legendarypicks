"""Player projections from per-game logs (design: docs/PROJECTIONS-METHODOLOGY.md).

Marcel-lite baseline: recency-weighted expected value + an empirical distribution
(floor/median/ceiling) + P(over a line). Deliberately the honest floor — regression
to league mean, opportunity share, and aging curves are later layers. Outlier-robust
where it counts: the point projection is a recency-weighted MEAN (expected value, what
props/fantasy want), but we also surface the MEDIAN since means are skewed by ceiling
games (the Ja'Marr Chase lesson).
"""
from typing import List, Optional


def _avg(x: List[float]) -> float:
    return sum(x) / len(x) if x else 0.0


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def project_stat(values: List[float], min_games: int = 3) -> Optional[dict]:
    """values ordered MOST-RECENT-FIRST. Returns a projection dict or None."""
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n < min_games:
        return None
    l5, l10 = vals[:5], vals[:10]
    # recency-weighted expected value
    proj = 0.5 * _avg(l5) + 0.3 * _avg(l10) + 0.2 * _avg(vals)
    srt = sorted(vals)
    season_avg = _avg(vals)
    l5_avg = _avg(l5)
    trend = "up" if l5_avg > season_avg * 1.1 else "down" if l5_avg < season_avg * 0.9 else "flat"
    return {
        "n": n,
        "projection": round(proj, 2),
        "median": round(_percentile(srt, 0.5), 2),
        "floor": round(_percentile(srt, 0.25), 2),
        "ceiling": round(_percentile(srt, 0.75), 2),
        "l5_avg": round(l5_avg, 2),
        "season_avg": round(season_avg, 2),
        "trend": trend,
        "last5": [round(v, 2) for v in l5],
    }


def prob_over(values: List[float], line: float) -> Optional[dict]:
    """Empirical hit rate vs a line, from the player's own game distribution."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    over = sum(1 for v in vals if v > line)
    push = sum(1 for v in vals if v == line)
    return {
        "line": line,
        "n": len(vals),
        "over": over,
        "p_over": round(over / len(vals), 3),
        "push": push,
    }
