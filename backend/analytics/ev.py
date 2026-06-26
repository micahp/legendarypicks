"""Expected-value compute (design §1, Appendix A).

All inputs are American odds (ints) + a de_vig_status string from
prop_odds_snapshots. EV is computed on read, never pre-stored.
"""
from typing import Optional, Tuple


def american_to_decimal(a: int) -> float:
    """+110 -> 2.10 ; -110 -> 1.9090..."""
    if a > 0:
        return 1 + a / 100.0
    return 1 + 100.0 / abs(a)


def implied_prob(american: int) -> float:
    return 1.0 / american_to_decimal(american)


def de_vig(odds: int, odds_opp: Optional[int], status: str) -> Tuple[Optional[float], Optional[str]]:
    """Return (p_fair, confidence).

    'paired'  -> proportional de-vig of the two sides (high confidence)
    'single'  -> raw implied, no de-vig possible (low confidence)
    'stale'   -> (None, None), cannot de-vig
    """
    if status == "paired" and odds_opp is not None:
        p_side = implied_prob(odds)
        p_opp = implied_prob(odds_opp)
        total = p_side + p_opp
        if total <= 0:
            return None, None
        return p_side / total, "high"
    if status == "single" or odds_opp is None:
        return implied_prob(odds), "low"
    # 'stale'
    return None, None


def ev(odds: int, p_fair: float) -> float:
    """EV per 1 unit staked: p_fair*(d-1) - (1-p_fair)."""
    d = american_to_decimal(odds)
    return p_fair * (d - 1) - (1 - p_fair)


def compute_ev(odds: Optional[int], odds_opp: Optional[int], de_vig_status: str) -> Optional[dict]:
    """Full EV row from one opening snapshot. Returns None if not computable."""
    if odds is None:
        return None
    p_fair, confidence = de_vig(odds, odds_opp, de_vig_status)
    if p_fair is None:
        return None
    d = american_to_decimal(odds)
    return {
        "odds_american": odds,
        "d_decimal": round(d, 4),
        "p_implied": round(implied_prob(odds), 4),
        "p_fair": round(p_fair, 4),
        "ev": round(ev(odds, p_fair), 4),
        "de_vig_confidence": confidence,
    }
