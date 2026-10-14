import math

import pytest

import tennis_point_model as tpm


@pytest.mark.parametrize("b", [0.60, 0.64, 0.66])
def test_average_players_give_the_baseline(b):
    assert tpm.point_prob(b, 1.0 - b, b) == pytest.approx(b)


def test_better_serve_raises_the_point_probability_and_better_return_lowers_it():
    base = tpm.point_prob(0.64, 0.36, 0.64)
    assert tpm.point_prob(0.70, 0.36, 0.64) > base
    assert tpm.point_prob(0.64, 0.42, 0.64) < base  # a stronger returner (higher return rate) lowers it
    assert tpm.point_prob(0.64, 0.30, 0.64) > base  # a weaker returner raises it


def test_unknown_players_shrink_to_the_surface_baseline():
    stats = tpm.Stats([])
    stats.surface_won["Hard"] = 640
    stats.surface_pts["Hard"] = 1000
    assert stats.baseline("Hard") == pytest.approx(0.64)
    assert stats.serve("nobody", "Hard", k=500) == pytest.approx(0.64)
    assert stats.returns("nobody", "Hard", k=500) == pytest.approx(0.36)


def test_counts_are_split_into_serve_and_return_for_both_players():
    # date, surface, winner, loser, w_svpt, w_1stWon, w_2ndWon, l_svpt, l_1stWon, l_2ndWon
    rows = [(20240101, "Hard", "A", "B", 100, 40, 20, 100, 30, 10)]
    stats = tpm.Stats(rows)
    assert stats.player[("A", "Hard")] == [60, 100, 100 - 40, 100]  # A: won 60 on serve, returned 60 of 100
    assert stats.player[("B", "Hard")] == [40, 100, 100 - 60, 100]  # B: won 40 on serve, returned 40 of 100
    assert stats.surface_won["Hard"] == 100
    assert stats.surface_pts["Hard"] == 200


def test_score_is_a_log_loss_per_point_and_the_baseline_equals_the_surface_rate():
    rows = [(20240101, "Hard", "A", "B", 100, 40, 20, 100, 30, 10)]
    stats = tpm.Stats([])
    stats.surface_won["Hard"] = 640
    stats.surface_pts["Hard"] = 1000
    result = tpm.score(rows, stats, 500, "baseline")
    expected = -(60 * math.log(0.64) + 40 * math.log(0.36) + 40 * math.log(0.64) + 60 * math.log(0.36)) / 200
    assert result["log_loss_per_point"] == pytest.approx(expected)
    assert result["points"] == 200
