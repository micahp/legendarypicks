"""NFL picks policy: prediction, lean and qualifying wager are three different claims.

The Model page used to derive a single "model pick" from the projection and print it beside a
straight-up record. That conflates three things a reader must be able to tell apart:

- **Prediction** -- the projected score, margin, total and win probability. Always present for a
  locked projection, whether or not anything is bettable.
- **Lean** -- which side the model prefers on each market. A lean is an opinion about the game,
  never an instruction to bet it.
- **Qualifying wager** -- a named side at a real, pregame price that a versioned policy selected.
  A lean is never promoted to a wager automatically.

Two states that used to collapse into one must stay distinct:

- ``no_qualifying_wager`` -- a price existed and the policy declined to bet.
- ``insufficient_price_data`` -- there was never a price to evaluate, so the policy says nothing
  about the game. Reporting this as "failed our criteria" would claim a wager we could not price.

Policy v1 is **observe-only**. The 16 gradeable pregame games in the 2026 window (and the absence
of any captured price before week 5) cannot establish a selection rule, so v1 issues no wagers by
construction. A rule that qualifies anything must arrive as a new version in this module with its
own pre-registration -- do not add thresholds here to make the page look active.

Pure functions only: no database, no clock, no network. The router passes the locked row and the
kickoff time in, which keeps every rule in this file testable.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

POLICY_ID = "nfl-wager-policy-v1"
POLICY_STATUS = "observe_only"
POLICY_NOTE = ("Policy v1 is observe-only: no selection rule has been validated on captured "
               "pregame prices, so no wager is issued.")
EPS = 1e-9

# The markets the policy is able to speak about, and why one can be unevaluable.
MARKETS = ("ml", "spread", "total")


def american_to_prob(american: Optional[float]) -> Optional[float]:
    """Implied probability of an American price. None when the price is absent or impossible."""
    if american is None:
        return None
    price = float(american)
    if price == 0:
        return None
    return 100.0 / (price + 100.0) if price > 0 else abs(price) / (abs(price) + 100.0)


def devig(home_ml: Optional[float], away_ml: Optional[float]):
    """Multiplicative de-vig of a two-sided moneyline. None when either side is missing."""
    ph, pa = american_to_prob(home_ml), american_to_prob(away_ml)
    if ph is None or pa is None or (ph + pa) <= 0:
        return None
    total = ph + pa
    return ph / total, pa / total


def prediction(lock: Dict[str, Any]) -> Dict[str, Any]:
    """What the model says about the game, independent of any price."""
    return {
        "proj_home": lock.get("proj_home"),
        "proj_away": lock.get("proj_away"),
        "margin": lock.get("margin"),          # positive = home favored
        "total": lock.get("total"),
        "p_home_win": lock.get("p_home_win"),
    }


def _ml_lean(p_home_win: Optional[float]) -> Dict[str, Any]:
    if p_home_win is None:
        return {"side": "none", "reason": "no_probability", "edge_pts": None, "edge_pp": None}
    if abs(float(p_home_win) - 0.5) < EPS:
        return {"side": "none", "reason": "level_at_50", "edge_pts": None, "edge_pp": None}
    return {"side": "home" if p_home_win > 0.5 else "away", "reason": "probability",
            "edge_pts": None, "edge_pp": None}


def _spread_lean(proj_margin: Optional[float], spread: Optional[float]) -> Dict[str, Any]:
    if proj_margin is None or spread is None:
        return {"side": "none", "reason": "no_line", "edge_pts": None}
    diff = float(proj_margin) - float(spread)
    if abs(diff) < EPS:
        # The model agrees with the posted number exactly: there is no side to prefer. This is
        # the case the old page resolved to "away" and the grader called no_pick.
        return {"side": "none", "reason": "level_with_line", "edge_pts": 0.0}
    return {"side": "home" if diff > 0 else "away", "reason": "margin_vs_line",
            "edge_pts": diff}


def _total_lean(proj_total: Optional[float], total_line: Optional[float]) -> Dict[str, Any]:
    if proj_total is None or total_line is None:
        return {"side": "none", "reason": "no_line", "edge_pts": None}
    diff = float(proj_total) - float(total_line)
    if abs(diff) < EPS:
        return {"side": "none", "reason": "level_with_line", "edge_pts": 0.0}
    return {"side": "over" if diff > 0 else "under", "reason": "total_vs_line", "edge_pts": diff}


def lean(lock: Dict[str, Any]) -> Dict[str, Any]:
    """The model's preferred side per market. Sides are 'home'/'away', 'over'/'under', or 'none'."""
    line = lock.get("line") or {}
    spread = line.get("spread")
    out = {
        "ml": _ml_lean(lock.get("p_home_win")),
        "spread": _spread_lean(lock.get("margin"), spread),
        "total": _total_lean(lock.get("total"), line.get("total")),
    }
    priced = devig(line.get("home_moneyline"), line.get("away_moneyline"))
    p = lock.get("p_home_win")
    if priced is not None and p is not None and out["ml"]["side"] != "none":
        # Model probability minus the market's de-vigged probability, in percentage points. This is
        # a measurement of disagreement with the price, not a claim of edge.
        market_p = priced[0] if out["ml"]["side"] == "home" else priced[1]
        out["ml"]["edge_pp"] = (float(p) - market_p) * 100.0
    return out


def total_lean_result(proj_total: Optional[float], total_line: Optional[float],
                      actual_total: Optional[float]) -> Optional[str]:
    """Grade the model's over/under lean against the actual total.

    'win'/'loss', 'push' (the game landed exactly on the number), 'no_pick' (the model sat on the
    number), 'no_line', or None when the game is not final.
    """
    if proj_total is None or total_line is None:
        return "no_line"
    if actual_total is None:
        return None
    if abs(float(proj_total) - float(total_line)) < EPS:
        return "no_pick"
    if abs(float(actual_total) - float(total_line)) < EPS:
        return "push"
    over = float(proj_total) > float(total_line)
    return "win" if over == (float(actual_total) > float(total_line)) else "loss"


def price_status(lock: Dict[str, Any], kickoff_utc: Optional[str]) -> str:
    """Whether the lock carries a usable *pregame* moneyline: 'pregame', 'post_kickoff',
    'unknown_time' or 'no_price'."""
    line = lock.get("line") or {}
    if line.get("home_moneyline") is None or line.get("away_moneyline") is None:
        return "no_price"
    captured = line.get("captured_at")
    if not captured or not kickoff_utc:
        return "unknown_time"
    try:
        from datetime import datetime, timezone
        cap = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
        kick = datetime.fromisoformat(str(kickoff_utc).replace("Z", "+00:00"))
        if cap.tzinfo is None:
            cap = cap.replace(tzinfo=timezone.utc)
        if kick.tzinfo is None:
            kick = kick.replace(tzinfo=timezone.utc)
    except ValueError:
        return "unknown_time"
    return "pregame" if cap < kick else "post_kickoff"


def wager(lock: Dict[str, Any], kickoff_utc: Optional[str]) -> Dict[str, Any]:
    """Per-market wager state, then one overall state.

    Order of precedence per market: first, is there a price at all? Only a pregame price lets the
    policy speak. Then the policy itself. v1 declines everything, so a priced market resolves to
    ``no_qualifying_wager`` and a priceless one to ``insufficient_price_data``.
    """
    line = lock.get("line") or {}
    ps = price_status(lock, kickoff_utc)
    markets: Dict[str, Dict[str, Any]] = {}

    if ps != "pregame":
        markets["ml"] = {"status": "insufficient_price_data", "reason": ps}
    else:
        markets["ml"] = {"status": "no_qualifying_wager", "reason": POLICY_STATUS}

    for name, value_key in (("spread", "spread"), ("total", "total")):
        if line.get(value_key) is None:
            markets[name] = {"status": "insufficient_price_data", "reason": "no_line"}
        else:
            # A line without juice cannot be converted into a return, so it is not a price.
            markets[name] = {"status": "insufficient_price_data", "reason": "no_price"}

    if any(m["status"] == "qualifying_wager" for m in markets.values()):
        status, reason = "qualifying_wager", None
    elif all(m["status"] == "insufficient_price_data" for m in markets.values()):
        status, reason = "insufficient_price_data", "no_market_priced"
    else:
        status, reason = "no_qualifying_wager", POLICY_STATUS

    return {"policy": POLICY_ID, "status": status, "reason": reason,
            "policy_note": POLICY_NOTE, "markets": markets}


def describe(lock: Dict[str, Any], kickoff_utc: Optional[str]) -> Dict[str, Any]:
    """Everything the Model page needs to separate the three claims for one lock."""
    return {"prediction": prediction(lock), "lean": lean(lock),
            "wager": wager(lock, kickoff_utc)}
