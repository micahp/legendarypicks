"""Checks for the contention feature (contention_columns, division_map_check). No real DB: every
input is a small fixture or an in-memory sqlite table."""
import sqlite3

import pytest

import nfl_feature_backtest as fb

TMAP = {"A": ("AFC", "AFC East"), "B": ("AFC", "AFC East"), "C": ("AFC", "AFC North")}


def _game(gid, season, week, h, a):
    return {"game_id": gid, "season": season, "week": week, "home": h, "away": a}


def _agg(p):
    """A minimal nfl_sim.aggregate-shaped dict with the given p_playoffs per team."""
    return {"n": 1000, "coin_flips": 0,
            "teams": {code: {"p_playoffs": v} for code, v in p.items()}}


def test_week_below_10_gives_zero_and_is_never_simulated():
    def sim(s, w):
        raise AssertionError("sim must not run for week %d" % w)
    rows = [_game("g1", 2018, 9, "A", "B"), _game("g2", 2018, 1, "B", "A")]
    cols, flags = fb.contention_columns(rows, sim)
    assert cols == {"g1": [0.0], "g2": [0.0]}
    assert flags == {}


def test_threshold_is_strict_p_equal_to_one_percent_is_not_out():
    def sim(s, w):
        return _agg({"A": 0.01, "B": 0.0099})
    rows = [_game("g1", 2018, 10, "A", "B")]
    cols, flags = fb.contention_columns(rows, sim)
    # A at exactly 0.01 is not out; B at 0.0099 is out. Column = out_home - out_away = 0 - 1.
    assert flags["g1"] == (0, 1)
    assert cols["g1"] == [-1.0]


def test_both_teams_at_threshold_boundary_give_zero_column():
    def sim(s, w):
        return _agg({"A": 0.01, "B": 0.01})
    cols, flags = fb.contention_columns([_game("g1", 2018, 12, "A", "B")], sim)
    assert flags["g1"] == (0, 0)
    assert cols["g1"] == [0.0]


def test_missing_team_in_simulation_raises():
    def sim(s, w):
        return _agg({"A": 0.5})
    with pytest.raises(ValueError):
        fb.contention_columns([_game("g1", 2018, 10, "A", "B")], sim)


def _schedule_db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE nfl_schedule (season INTEGER, game_type TEXT, week INTEGER, "
                "home_team TEXT, away_team TEXT, div_game INTEGER)")
    con.executemany("INSERT INTO nfl_schedule VALUES (?, 'REG', ?, ?, ?, ?)", rows)
    return con


GOOD_ROWS = [(2018, 1, "A", "B", 1),   # same division
             (2018, 2, "A", "C", 0)]   # different division


def test_division_map_agrees_returns_count():
    con = _schedule_db(GOOD_ROWS)
    assert fb.division_map_check(con, TMAP, seasons=[2018]) == 2


def test_division_map_doctored_raises():
    con = _schedule_db(GOOD_ROWS)
    doctored = dict(TMAP)
    doctored["B"] = ("AFC", "AFC North")  # A-B now looks like a cross-division game
    with pytest.raises(AssertionError):
        fb.division_map_check(con, doctored, seasons=[2018])


def test_division_map_unknown_code_raises():
    con = _schedule_db(GOOD_ROWS)
    without_c = {k: v for k, v in TMAP.items() if k != "C"}
    with pytest.raises(AssertionError):
        fb.division_map_check(con, without_c, seasons=[2018])


def test_division_map_null_flag_raises():
    con = _schedule_db([(2018, 1, "A", "B", None)])
    with pytest.raises(AssertionError):
        fb.division_map_check(con, TMAP, seasons=[2018])
