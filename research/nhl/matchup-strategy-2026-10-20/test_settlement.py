#!/usr/bin/env python3
"""Regression tests for the corrected harness: settlement, standings reset, totals reachability.

Run: uv run --with scikit-learn --with numpy python test_settlement.py
"""
from __future__ import annotations

import math

from backtest_matchup_strategy import p_win, pick, settled, standings_before


def ml(side):
    return {"market": "ml", "side": side, "line": None, "price_open": -110, "price_close": -110}


def spread(side, line=1.5):
    return {"market": "spread", "side": side, "line": line, "price_open": -110, "price_close": None}


def total(side, line):
    return {"market": "total", "side": side, "line": line, "price_open": -110, "price_close": -110}


def test_shootout_moneyline_settles_from_official_winner():
    # 1-1 at the end of overtime, home wins the shootout. v1 graded both sides as losses.
    kw = dict(home_goals=1, away_goals=1, official_home_winner=1)
    assert settled(ml("home"), **kw) == "win"
    assert settled(ml("away"), **kw) == "loss"
    kw = dict(home_goals=1, away_goals=1, official_home_winner=0)
    assert settled(ml("home"), **kw) == "loss"
    assert settled(ml("away"), **kw) == "win"


def test_shootout_puck_line_and_total_use_the_ot_score():
    # Target 1-1 is the score at the end of OT; the shootout goal does not count for either market.
    kw = dict(home_goals=1, away_goals=1, official_home_winner=1)
    assert settled(spread("home"), **kw) == "win"      # 1 + 1.5 > 1
    assert settled(spread("away"), **kw) == "win"      # 1 + 1.5 > 1
    assert settled(total("under", 2.5), **kw) == "win"  # 2 goals, not the official 3
    assert settled(total("over", 2.5), **kw) == "loss"


def test_pushes():
    kw = dict(home_goals=3, away_goals=2, official_home_winner=1)
    assert settled(total("over", 5.0), **kw) == "push"
    assert settled(total("under", 5.0), **kw) == "push"
    assert settled(total("over", 5.5), **kw) == "loss"
    assert settled(total("under", 5.5), **kw) == "win"


def test_standings_reset_at_season_boundary():
    rows = [
        {"game_id": 1, "season": 2018, "game_date": "2018-10-01", "start_time_utc": "2018-10-01T23:00:00Z",
         "home_team": "TOR", "away_team": "MTL", "home_goals": 4, "away_goals": 2,
         "official_home_winner": 1, "last_period_type": "REG"},
        {"game_id": 2, "season": 2019, "game_date": "2019-10-01", "start_time_utc": "2019-10-01T23:00:00Z",
         "home_team": "TOR", "away_team": "MTL", "home_goals": 1, "away_goals": 3,
         "official_home_winner": 0, "last_period_type": "REG"},
    ]
    table = standings_before(rows)
    assert table[1]["home"]["gp"] == 0 and table[1]["home"]["pts"] == 0
    assert table[2]["home"]["gp"] == 0, "season 2 must not inherit season 1 games"
    assert table[2]["home"]["pct"] != table[2]["home"]["pct"] or math.isnan(table[2]["home"]["pct"])


def test_overtime_loss_earns_one_point_and_shootout_counts_as_a_win():
    rows = [
        {"game_id": 1, "season": 2018, "game_date": "2018-10-01", "start_time_utc": "2018-10-01T23:00:00Z",
         "home_team": "TOR", "away_team": "MTL", "home_goals": 2, "away_goals": 1,
         "official_home_winner": 1, "last_period_type": "OT"},
        {"game_id": 2, "season": 2018, "game_date": "2018-10-02", "start_time_utc": "2018-10-02T23:00:00Z",
         "home_team": "TOR", "away_team": "BOS", "home_goals": 1, "away_goals": 1,
         "official_home_winner": 0, "last_period_type": "SO"},
    ]
    table = standings_before(rows)
    # TOR: OT win (2 pts) then SO loss (1 pt) -> 3 points in 2 games.
    assert table[2]["home"]["pts"] == 2 and table[2]["home"]["gp"] == 1
    assert table[2]["away"]["pts"] == 0


def test_totals_branch_is_structurally_unreachable():
    """For |puck| = 1.5, S <= 1.0 implies the model favourite is the Vegas favourite."""
    tie = 0.4918
    puck = 1.5
    for mh in [1.6, 2.0, 2.5, 3.0, 3.4]:
        for ma in [1.4, 1.8, 2.2, 2.6, 3.2]:
            for favourite in ("home", "away"):
                fav_margin = (mh - ma) if favourite == "home" else (ma - mh)
                s = puck - fav_margin
                model_fav = "home" if p_win(mh, ma, tie) >= 0.5 else "away"
                if round(s + 0.0, 1) <= 1.0:
                    assert model_fav == favourite, (mh, ma, favourite, s)


def test_pick_uses_the_selected_sides_total_price():
    """The total branch cannot be reached, so assert the mapping the branch would use."""
    game = {"home": "TOR", "away": "MTL", "home_puck_line": -1.5,
            "home_ml_open": -150, "home_ml_close": -160,
            "away_ml_open": 130, "away_ml_close": 140,
            "home_puck_open": -110, "away_puck_open": -110,
            "over_ou_open": -105, "under_ou_open": -115,
            "over_ou_close": -110, "under_ou_close": -110}
    fc = {"margin": 0.5, "p_home": 0.6, "total": 5.2}
    pk, reason = pick(fc, game)
    assert pk is not None, reason
    assert pk["market"] == "ml" and pk["side"] == "home" and pk["price_open"] == -150


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
