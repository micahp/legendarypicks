"""Tests for the preseason prior's rating formula (nfl_feature_backtest.shrunk_ratings)."""
import pytest

import nfl_feature_backtest as fb


def test_large_sample_keeps_most_of_the_gap():
    off = {"A": (0.20, 100000), "B": (0.00, 100000)}
    dfn = {"A": (0.00, 100000), "B": (0.00, 100000)}
    r = fb.shrunk_ratings(off, dfn, k=400.0)
    w = 100000 / 100400
    # league offense mean 0.10, defense mean 0; each team keeps weight w of its gap to the mean
    assert r["A"] == pytest.approx(0.10 + 0.10 * w, abs=1e-9)
    assert r["B"] == pytest.approx(0.10 - 0.10 * w, abs=1e-9)


def test_zero_sample_is_pulled_fully_to_league_mean():
    off = {"A": (0.30, 0), "B": (0.10, 400)}
    dfn = {"A": (0.00, 0), "B": (0.00, 400)}
    r = fb.shrunk_ratings(off, dfn, k=400.0)
    # league offense mean is 0.20; A has no plays, so its offense sits at the mean (defense 0)
    assert r["A"] == pytest.approx(0.20)


def test_defense_sign_is_inverted():
    off = {"A": (0.0, 1000), "B": (0.0, 1000)}
    dfn = {"A": (-0.10, 1000), "B": (0.10, 1000)}  # A allows less EPA
    r = fb.shrunk_ratings(off, dfn, k=400.0)
    assert r["A"] > r["B"]


def test_only_teams_in_both_dicts_are_rated():
    off = {"A": (0.1, 500), "B": (0.0, 500)}
    dfn = {"A": (0.0, 500)}
    assert set(fb.shrunk_ratings(off, dfn)) == {"A"}
