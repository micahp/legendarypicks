"""test_nfl_epa_efficiency.py -- fixtures for the SPEC A 9 EPA layer.

Every number in these fixtures is hand-worked, and each test states what it can catch.
The fixtures are synthetic: the live gate against version 1 is the 2024/2025 backtest
(nfl_tune_epa.py), not this file.
"""
from __future__ import annotations

import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_backtest as nb
import nfl_epa_efficiency as ee


def make_db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE nfl_schedule (
            season INTEGER, week INTEGER, game_id TEXT, home_team TEXT, away_team TEXT,
            location TEXT, home_score REAL, away_score REAL,
            spread_line REAL, total_line REAL, game_type TEXT,
            home_moneyline REAL, away_moneyline REAL);
        CREATE TABLE nfl_pbp (
            season INTEGER, week INTEGER, game_id TEXT, home_team TEXT, away_team TEXT,
            posteam TEXT, epa REAL, pass_attempt INTEGER, rush_attempt INTEGER);
        """
    )
    # Weeks 1-3, four teams, two games a week. Scores are arbitrary; EPA below is
    # hand-worked so the aggregation and the fits are checkable by inspection.
    sched = [
        (2024, 1, "2024_01_A_B", "A", "B", None, 24, 17, -3.0, 41.0, "REG"),
        (2024, 1, "2024_01_C_D", "C", "D", None, 10, 20, 3.0, 30.0, "REG"),
        (2024, 2, "2024_02_B_C", "B", "C", None, 14, 13, 1.0, 27.0, "REG"),
        (2024, 2, "2024_02_D_A", "D", "A", None, 20, 21, -2.0, 41.0, "REG"),
        (2024, 3, "2024_03_A_C", "A", "C", None, 17, 17, None, 34.0, "REG"),
        (2024, 3, "2024_03_B_D", "B", "D", None, 21, 10, 4.0, 31.0, "REG"),
    ]
    for r in sched:
        con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)", r)
    plays = [
        # week 1, game 1 (A home): A's offense +0.5*4=2.0 over 4 plays (3 pass 1 rush);
        # B's offense -0.25*2=-0.5 over 2 plays (2 rush)
        (2024, 1, "2024_01_A_B", "A", "B", "A", 0.5, 1, 0),
        (2024, 1, "2024_01_A_B", "A", "B", "A", 0.5, 1, 0),
        (2024, 1, "2024_01_A_B", "A", "B", "A", 0.5, 1, 0),
        (2024, 1, "2024_01_A_B", "A", "B", "A", 0.5, 0, 1),
        (2024, 1, "2024_01_A_B", "A", "B", "B", -0.25, 0, 1),
        (2024, 1, "2024_01_A_B", "A", "B", "B", -0.25, 0, 1),
        # a kick play: published EPA null, must be excluded from sums, never crash
        (2024, 1, "2024_01_A_B", "A", "B", "A", None, 0, 0),
        # week 1, game 2: C -1.0 over 1 play, D +1.0 over 1 play
        (2024, 1, "2024_01_C_D", "C", "D", "C", -1.0, 1, 0),
        (2024, 1, "2024_01_C_D", "C", "D", "D", 1.0, 0, 1),
        # week 2 only (so a week-3 fit must not see these)
        (2024, 2, "2024_02_B_C", "B", "C", "B", 2.0, 1, 0),
        (2024, 2, "2024_02_B_C", "B", "C", "C", -2.0, 1, 0),
        (2024, 2, "2024_02_D_A", "D", "A", "D", 0.25, 1, 0),
        (2024, 2, "2024_02_D_A", "D", "A", "A", 0.75, 0, 1),
        # week 3 (must never enter a week-3 fit)
        (2024, 3, "2024_03_A_C", "A", "C", "A", 99.0, 1, 0),
        (2024, 3, "2024_03_A_C", "A", "C", "C", -99.0, 1, 0),
        (2024, 3, "2024_03_B_D", "B", "D", "B", 99.0, 1, 0),
        (2024, 3, "2024_03_B_D", "B", "D", "D", -99.0, 1, 0),
    ]
    for r in plays:
        con.execute("INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?)", r)
    con.commit()
    return con


def test_aggregation_is_exact():
    """Hand-worked sums: A week 1 = +2.0 over 4 plays (3 pass, 1 rush), B = -0.5 over 2."""
    con = make_db()
    rows = {r[1]: r for r in ee.team_game_epa_rows(con, 2024)}
    assert rows["2024_01_A_B"] == (1, "2024_01_A_B", "A", "B", 2.0, -0.5, 4, 2), rows["2024_01_A_B"]
    assert rows["2024_01_C_D"] == (1, "2024_01_C_D", "C", "D", -1.0, 1.0, 1, 1)
    assert rows["2024_02_B_C"] == (2, "2024_02_B_C", "B", "C", 2.0, -2.0, 1, 1)
    # the null-EPA kick play is excluded, not zeroed into a phantom play count
    assert rows["2024_01_A_B"][6] == 4


def test_before_week_excludes_the_week():
    """The EPA read for week w never sees week w: the +99/-99 week-3 plants are absent."""
    con = make_db()
    rows = ee.team_game_epa_rows(con, 2024, before_week=3)
    assert all(r[0] < 3 for r in rows)
    assert {r[1] for r in rows} == {"2024_01_A_B", "2024_01_C_D", "2024_02_B_C", "2024_02_D_A"}


def test_no_leakage_into_the_projection():
    """Adding the week-3 EPA plants must not change any week-3 projection, and the fit
    sizes must not grow: 4 EPA games before week 3, whatever week 3 holds."""
    con = make_db()
    base = ee.backtest_season_blend(con, 2024, {"w_blend": 0.5})
    wk3_base = [r for r in base if r["week"] == 3]
    assert all(r["epa_games"] == 4 for r in wk3_base)
    # corrupt week 3 with absurd EPA and confirm nothing moves
    con.execute("UPDATE nfl_pbp SET epa = 12345.0 WHERE season = 2024 AND week = 3")
    con.commit()
    corrupt = [r for r in ee.backtest_season_blend(con, 2024, {"w_blend": 0.5}) if r["week"] == 3]
    assert corrupt == wk3_base


def test_w_zero_reproduces_version_one():
    """w_blend = 0 must reproduce nfl_backtest.backtest_season margin-for-margin under the
    same frozen points parameters: the blend adds a term, it does not fork the v1 fit."""
    con = make_db()
    blend = ee.backtest_season_blend(con, 2024, {"w_blend": 0.0})
    v1 = nb.backtest_season(con, 2024, {"cap": 14.0})
    key = lambda r: r["game_id"]
    b = {key(r): r for r in blend}
    v = {key(r): r for r in v1}
    assert set(b) == set(v)
    for gid in b:
        assert b[gid]["proj_margin"] == v[gid]["proj_margin"], gid
        assert b[gid]["outcome"] == v[gid]["outcome"], gid
        assert b[gid]["proj_total"] == v[gid]["proj_total"], gid


def test_w_one_is_the_epa_fit_alone():
    """w_blend = 1: the projection is exactly the EPA fit's margin, with no points term."""
    con = make_db()
    rows = ee.backtest_season_blend(con, 2024, {"w_blend": 1.0})
    wk3 = [r for r in rows if r["week"] == 3 and r["game_id"] == "2024_03_A_C"]
    assert wk3[0]["proj_margin"] == wk3[0]["epa_margin"]
    assert wk3[0]["v1_margin"] != 0.0  # v1 was computed too, just not blended


def test_missing_epa_for_a_scored_game_refuses():
    """A scored game with no published EPA must raise, not silently fall back to v1:
    the gate would otherwise grade a mixture it cannot see."""
    con = make_db()
    con.execute("DELETE FROM nfl_pbp WHERE game_id = '2024_03_B_D'")
    con.commit()
    try:
        ee.backtest_season_blend(con, 2024, {"w_blend": 0.5})
    except ValueError as e:
        assert "2024_03_B_D" in str(e)
    else:
        raise AssertionError("missing EPA rows did not raise")


def test_zero_play_side_refuses():
    """A game where one side recorded no pass/rush plays cannot be rated from nothing."""
    con = make_db()
    con.execute("DELETE FROM nfl_pbp WHERE game_id = '2024_01_C_D' AND posteam = 'D'")
    con.commit()
    try:
        ee.team_game_epa_rows(con, 2024)
    except ValueError as e:
        assert "2024_01_C_D" in str(e)
    else:
        raise AssertionError("zero-play side did not raise")


def test_unknown_parameter_refuses():
    """A typo'd parameter must fail loudly instead of silently running with a default."""
    con = make_db()
    try:
        ee.backtest_season_blend(con, 2024, {"epa_wobble": 1.0})
    except ValueError as e:
        assert "epa_wobble" in str(e)
    else:
        raise AssertionError("unknown parameter did not raise")


def test_sigma_refit_changes_p_model_not_margin():
    """with_sigma() rescales win probability to the blend's own residual sigma; margins,
    actuals and outcomes are untouched (the A3 rule that sigma never moves projections)."""
    con = make_db()
    rows = ee.backtest_season_blend(con, 2024, {"w_blend": 0.3})
    rescaled = ee.with_sigma(rows)
    for a, b in zip(rows, rescaled):
        assert a["proj_margin"] == b["proj_margin"]
        assert a["actual_margin"] == b["actual_margin"]
        assert a["outcome"] == b["outcome"]
        assert b["sigma"] == rescaled[0]["sigma"]
    import nfl_ratings as nr
    for b in rescaled:
        assert b["p_model"] == nr.win_probability(b["proj_margin"], b["sigma"])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
