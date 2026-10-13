"""Tests for nfl_score_dist (task 4.2): the nearest neighbours, reproducibility, integer scores,
ties, the probability denominators, and the leakage guard.

Run: cd backend && LP_DB_PATH=<dev db> venv/bin/python -m pytest -q test_nfl_score_dist.py
"""
from __future__ import annotations

import numpy as np
import pytest

import nfl_score_dist as sd


def row(season, week, eh, ea, hs, as_):
    return {"season": season, "week": week, "game_id": "%d_%02d_%d" % (season, week, len(str(hs))),
            "eh": float(eh), "ea": float(ea), "hs": int(hs), "as_": int(as_),
            "spread": None, "total": None}


def planted_pool(n=40, ties=0):
    """n games whose expected margin and expected total both increase with the index.

    Game i has expected margin m_i = -14 + i * 28 / (n - 1) and expected total
    t_i = 40 + i * 12 / (n - 1), with actual scores (eh, ea) rounded to integers. The ordering of
    the pool is therefore known, and the nearest training game to a row's own expectations is that
    row. The first `ties` games are turned into ties by making both scores equal.
    """
    rows = []
    for i in range(n):
        m = -14.0 + i * 28.0 / (n - 1)
        t = 40.0 + i * 12.0 / (n - 1)
        eh, ea = (t + m) / 2.0, (t - m) / 2.0
        hs = int(round(eh))
        as_ = int(round(ea))
        if i < ties:
            hs = as_ = 20 + i
        elif ties == 0:
            as_ = hs - 3          # a pool with no tied pairs, for the tie-negative test
        rows.append(row(2015, 1 + i, eh, ea, hs, as_))
    return rows


def mid_target():
    """The expectations of the middle planted game, a neutral target for draws."""
    rows = planted_pool()
    return rows[20]["eh"], rows[20]["ea"]


def test_the_nearest_training_game_to_a_target_is_the_one_with_its_expectations():
    rows = planted_pool()
    dist = sd.ScoreDist(rows, k=25)
    target = rows[7]
    order = dist.order(target["eh"], target["ea"])
    assert int(order[0]) == 7
    assert dist.hs[order[0]] == target["hs"] and dist.as_[order[0]] == target["as_"]


def test_k_controls_how_many_games_can_be_drawn():
    rows = planted_pool()
    rng = np.random.default_rng(1)
    dist = sd.ScoreDist(rows, k=25)
    drawn = set(dist.sample(rows[20]["eh"], rows[20]["ea"], rng, 4000))
    allowed = {(int(dist.hs[i]), int(dist.as_[i]))
               for i in dist.order(rows[20]["eh"], rows[20]["ea"])[:25]}
    assert drawn <= allowed
    assert len(drawn) > 1


def test_k_outside_the_pre_registered_grid_is_refused():
    with pytest.raises(ValueError):
        sd.ScoreDist(planted_pool(), k=30)


def test_the_same_seed_gives_the_same_draws_and_a_different_seed_does_not():
    dist = sd.ScoreDist(planted_pool(), k=25)
    eh, ea = mid_target()
    a = dist.sample(eh, ea, np.random.default_rng(99), 200)
    b = dist.sample(eh, ea, np.random.default_rng(99), 200)
    c = dist.sample(eh, ea, np.random.default_rng(100), 200)
    assert a == b
    assert a != c


def test_every_draw_is_an_integer_pair_of_plausible_scores():
    dist = sd.ScoreDist(planted_pool(), k=50)
    for hs, as_ in dist.sample(*mid_target(), np.random.default_rng(3), 500):
        assert isinstance(hs, int) and isinstance(as_, int)
        assert 0 <= hs <= 80 and 0 <= as_ <= 80


def test_ties_are_drawn_when_the_neighbourhood_has_ties_and_never_when_it_does_not():
    with_ties = sd.ScoreDist(planted_pool(n=40, ties=12), k=50)
    draws = with_ties.sample(11.0, 27.0, np.random.default_rng(5), 2000)
    assert sum(1 for h, a in draws if h == a) > 0
    without = sd.ScoreDist(planted_pool(n=40, ties=0), k=25)
    draws = without.sample(*mid_target(), np.random.default_rng(5), 2000)
    assert all(h != a for h, a in draws)


def test_win_and_tie_rates_partition_the_draws():
    dist = sd.ScoreDist(planted_pool(n=40, ties=8), k=25)
    out = dist.probabilities(11.0, 27.0, n=4000, rng=np.random.default_rng(11))
    assert out["ties"] + out["decisive"] == out["n"]
    assert 0.0 <= out["p_tie"] <= 1.0
    wins = out["p_home_win"] * out["decisive"]
    assert abs(wins - round(wins)) < 1e-9


def test_cover_and_push_denominators():
    dist = sd.ScoreDist(planted_pool(), k=25)
    out = dist.probabilities(*mid_target(), spread=2.0, total=44.0, n=4000,
                             rng=np.random.default_rng(12))
    assert out["pushes"] >= 0
    decided = out["n"] - out["pushes"]
    assert abs(out["p_cover"] * decided - round(out["p_cover"] * decided)) < 1e-9
    assert 0.0 <= out["p_over"] <= 1.0


def test_a_target_season_is_never_in_its_own_pool():
    rows = [row(2015, w, 20.0 + w, 22.0, 24 + w, 20 - w) for w in range(1, 29)]
    rows += [row(2016, w, 20.0 + w, 22.0, 26 + w, 18 - w) for w in range(1, 10)]
    dist = sd.for_season(rows, 2016, k=25)
    assert {r["season"] for r in dist.rows} == {2015}
    with pytest.raises(ValueError):
        sd.for_season(rows, 2015, k=25)


def test_the_pair_probability_distribution_sums_to_one():
    dist = sd.ScoreDist(planted_pool(), k=25)
    probs, denom = dist.pair_probability(*mid_target())
    assert abs(sum(probs.values()) - 1.0) < 1e-12
    assert denom == dist.k + len(probs)


def test_the_normal_comparator_matches_a_known_value():
    out = sd.normal_probabilities(3.0, 0.0)
    assert abs(out["p_home_win"] - 0.58926) < 0.0005    # Phi(3 / 13.295)
    out = sd.normal_probabilities(0.0, 0.0)
    assert abs(out["p_home_win"] - 0.5) < 1e-12
