"""Current-season adaptation rule for SLC V1.5 (research, flag off by default).

Blends a historical (V1) probability with a current-season estimate:

    P_V15 = (N0 * P_hist + n * P_season) / (N0 + n)

n is the effective current-season sample for that distribution, not the number of
games. When n is 0 the historical value is returned unchanged, so with no current-season
evidence V1 is reproduced exactly. N0 is prespecified; the default is 4, from the
protocol in docs/research/SLC-V15-WALKFORWARD-PROTOCOL-2026-11-03.md.
"""
from __future__ import annotations

DEFAULT_N0 = 4.0


def blend_probability(p_hist: float, p_season: float, n_season: float, n0: float = DEFAULT_N0) -> float:
    """Blend one probability. Returns ``p_hist`` unchanged when there is no current-season evidence."""
    if n_season < 0 or n0 < 0:
        raise ValueError("sample sizes must be non-negative")
    if n_season == 0:
        return p_hist
    return (n0 * p_hist + n_season * p_season) / (n0 + n_season)


def blend_distribution(hist: dict, season: dict, n_season: float, n0: float = DEFAULT_N0) -> dict:
    """Blend two categorical distributions outcome by outcome.

    Both inputs must already be normalized. The result sums to 1 when both do. With no
    current-season evidence the historical distribution is returned as a new dict with the
    same values.
    """
    if n_season == 0:
        return dict(hist)
    outcomes = set(hist) | set(season)
    return {o: blend_probability(hist.get(o, 0.0), season.get(o, 0.0), n_season, n0) for o in outcomes}


def effective_weight_on_history(n_season: float, n0: float = DEFAULT_N0) -> float:
    """Share of the blended estimate that comes from the historical model."""
    if n_season < 0 or n0 < 0:
        raise ValueError("sample sizes must be non-negative")
    if n0 + n_season == 0:
        raise ValueError("no evidence and no prior")
    return n0 / (n0 + n_season)
