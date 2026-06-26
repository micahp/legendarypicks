"""Closing-line-value compute (design §2).

CLV = p_close_implied - p_open_implied, using the bet-side IMPLIED prob
(not de-vigged) so it isolates pure line movement. Requires an opening
snapshot (earliest captured_at) and a closing snapshot (is_close = 1).
"""
from typing import Optional

from .ev import implied_prob


def clv(odds_open: Optional[int], odds_close: Optional[int]) -> Optional[float]:
    """Positive => closing line implies a higher win prob than at capture
    (we got a better number). None if either side is missing."""
    if odds_open is None or odds_close is None:
        return None
    return implied_prob(odds_close) - implied_prob(odds_open)
