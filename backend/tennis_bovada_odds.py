"""Bovada prices for one tennis match, read from props by the ESPN event id.

A match shows its Bovada moneyline and total only when those prices were captured recently.
Stale prices are dropped rather than shown as current.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

MAX_AGE = dt.timedelta(hours=12)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def bovada_odds(con, espn_event_id: str, tour: str, home_player_id, away_player_id,
                now: dt.datetime) -> Optional[dict]:
    rows = con.execute(
        """SELECT p.market, p.player_id, p.line, p.side, p.odds, p.odds_captured_at
             FROM props p JOIN prop_games g ON g.id = p.game_id
            WHERE g.espn_event_id = ? AND g.league = ? AND p.source = 'bovada'
              AND p.market IN ('match_winner', 'total_games')
              AND (p.market != 'total_games' OR p.player_id IS NULL)
              AND p.odds_captured_at >= ?
            ORDER BY p.odds_captured_at DESC, p.id DESC""",
        (str(espn_event_id), tour, _iso(now - MAX_AGE)),
    ).fetchall()
    if not rows:
        return None

    home_ml = away_ml = None
    total = None
    captured = None
    for market, player_id, line, side, odds, captured_at in rows:
        captured = captured or captured_at
        if market == "match_winner" and odds is not None:
            if home_ml is None and home_player_id is not None and player_id == home_player_id:
                home_ml = odds
            elif away_ml is None and away_player_id is not None and player_id == away_player_id:
                away_ml = odds
        elif market == "total_games" and line is not None and side in ("over", "under"):
            if total is None:
                total = {"line": line}
            if total["line"] == line and side not in total:
                total[side] = odds
    if total is not None and not ("over" in total and "under" in total):
        total = None
    if home_ml is None and away_ml is None and total is None:
        return None
    return {
        "matchWinner": {"home": home_ml, "away": away_ml},
        "totalGames": total,
        "capturedAt": captured,
    }
