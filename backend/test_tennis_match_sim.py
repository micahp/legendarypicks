import math
import random

import pytest

import tennis_match_sim as sim


def race(q, n):
    """Closed form: P(a player who wins each point with probability q wins a first-to-n race by two)."""
    total = sum(math.comb(n - 1 + k, k) * q**n * (1 - q) ** k for k in range(n - 1))
    deuce = math.comb(2 * n - 2, n - 1) * (q * (1 - q)) ** (n - 1)
    return total + deuce * q * q / (q * q + (1 - q) ** 2)


@pytest.mark.parametrize("p", [0.05, 0.3, 0.5, 0.62, 0.7, 0.95])
def test_game_win_probability_matches_the_race_to_four_by_two(p):
    assert sim.game_win_prob(p) == pytest.approx(race(p, 4), abs=1e-12)


def test_game_probability_is_one_half_at_fifty_fifty_and_rises_with_the_point_probability():
    assert sim.game_win_prob(0.5) == pytest.approx(0.5)
    assert sim.game_win_prob(0.6) > sim.game_win_prob(0.55) > 0.5


@pytest.mark.parametrize("q", [0.4, 0.5, 0.58, 0.65])
@pytest.mark.parametrize("points", [7, 10])
@pytest.mark.parametrize("first_is_a", [True, False])
def test_tiebreak_with_one_point_probability_matches_the_race(q, points, first_is_a):
    # A wins each point with probability q whoever serves: serve_a = q and serve_b = 1 - q.
    assert sim.tiebreak_win_prob_a(q, 1 - q, first_is_a, points) == pytest.approx(race(q, points), abs=1e-10)


def test_tiebreak_serves_one_point_then_two_each_starting_with_the_first_server():
    assert [sim.point_server_is_a(n, True) for n in range(8)] == [True, False, False, True, True, False, False, True]
    assert [sim.point_server_is_a(n, False) for n in range(3)] == [False, True, True]


def test_rules_are_validated():
    with pytest.raises(ValueError):
        sim.normalise_rules({"bestOf": 4})
    with pytest.raises(ValueError):
        sim.normalise_rules({"finalSet": "shootout"})
    with pytest.raises(ValueError):
        sim.normalise_rules({"finalSet": "tiebreak", "finalSetTiebreakAt": None})


@pytest.mark.parametrize("fmt", list(sim.VERIFY_FORMATS))
def test_swapping_the_players_and_the_first_server_gives_the_complement(fmt):
    rules = sim.VERIFY_FORMATS[fmt]
    x = sim.match_distribution(0.66, 0.58, rules, "A")
    y = sim.match_distribution(0.58, 0.66, rules, "B")
    assert x["p_a"] == pytest.approx(y["p_b"], abs=1e-12)


@pytest.mark.parametrize("fmt", list(sim.VERIFY_FORMATS))
def test_outcomes_sum_to_one(fmt):
    x = sim.match_distribution(0.64, 0.60, sim.VERIFY_FORMATS[fmt], "B")
    assert x["p_a"] + x["p_b"] + x["unresolved"] == pytest.approx(1.0, abs=1e-9)
    assert sum(x["sets_played"].values()) == pytest.approx(x["p_a"] + x["p_b"], abs=1e-9)
    assert sum(x["total_games"].values()) == pytest.approx(x["p_a"] + x["p_b"], abs=1e-9)


def test_every_match_plays_set_one_so_its_results_sum_to_one():
    x = sim.match_distribution(0.64, 0.60, sim.VERIFY_FORMATS["bo3_final_tiebreak"], "A")
    set_one = sum(v for (no, _, _, _), v in x["set_scores"].items() if no == 1)
    assert set_one == pytest.approx(1.0, abs=1e-9)


def test_match_tiebreak_happens_exactly_when_the_sets_are_level_at_one_all():
    x = sim.match_distribution(0.64, 0.60, sim.VERIFY_FORMATS["bo3_match_tiebreak_10"], "A")
    assert x["p_match_tiebreak"] == pytest.approx(x["sets_played"][3], abs=1e-12)


def test_equal_serving_gives_an_even_match_when_the_first_server_is_averaged_out():
    a = sim.match_distribution(0.63, 0.63, sim.VERIFY_FORMATS["bo5_final_tiebreak"], "A")
    b = sim.match_distribution(0.63, 0.63, sim.VERIFY_FORMATS["bo5_final_tiebreak"], "B")
    assert (a["p_a"] + b["p_a"]) / 2 == pytest.approx(0.5, abs=1e-9)


def test_a_better_server_wins_more_matches():
    lo = sim.match_distribution(0.62, 0.60, sim.VERIFY_FORMATS["bo3_final_tiebreak"], "A")["p_a"]
    hi = sim.match_distribution(0.66, 0.60, sim.VERIFY_FORMATS["bo3_final_tiebreak"], "A")["p_a"]
    assert hi > lo > 0.5


@pytest.mark.parametrize("fmt", ["bo3_final_tiebreak", "bo5_match_tiebreak_10"])
def test_monte_carlo_agrees_with_the_exact_distribution(fmt):
    rules = sim.VERIFY_FORMATS[fmt]
    exact = sim.match_distribution(0.66, 0.60, rules, "A")
    mc = sim.monte_carlo(0.66, 0.60, rules, "A", n=6000, seed=3)
    assert mc["p_a"] == pytest.approx(exact["p_a"], abs=0.03)
    assert mc["expected_games"] == pytest.approx(exact["expected_games"], abs=0.25)
    assert mc["p_tiebreak_any"] == pytest.approx(exact["p_tiebreak_any"], abs=0.03)


def test_one_simulated_match_is_internally_consistent():
    rng = random.Random(11)
    for _ in range(200):
        m = sim.simulate_match(rng, 0.64, 0.61, sim.VERIFY_FORMATS["bo3_final_tiebreak"], "B")
        assert m["winner"] == ("A" if m["sets_a"] > m["sets_b"] else "B")
        assert max(m["sets_a"], m["sets_b"]) == 2
        assert m["games"] == sum(max(w, l) + min(w, l) for _, _, w, l in m["set_log"])
