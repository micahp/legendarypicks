"""Game-clustered bootstrap and denominator helpers in the evaluator."""
from nfl_sequence.evaluate import game_bootstrap


def _game(p, home, away):
    return {"p_home_decisive": p, "home": home, "away": away}


def test_bootstrap_excludes_ties_and_brackets_the_estimate():
    records = [_game(0.6, 24, 17), _game(0.4, 10, 20), _game(0.5, 21, 21), _game(0.7, 31, 3), _game(0.3, 14, 28)]
    result = game_bootstrap(records, base_rate=0.5, reps=1000, seed=7)
    assert result["decisive_games"] == 4 and result["ties"] == 1
    for key in ("brier", "log_loss", "accuracy"):
        estimate = result["metrics"][key]["estimate"]
        low, high = result["metrics"][key]["ci95"]
        assert low <= estimate <= high, key


def test_a_forecast_equal_to_the_base_rate_has_zero_difference_from_baseline():
    records = [_game(0.5, 24, 17), _game(0.5, 10, 20), _game(0.5, 31, 3), _game(0.5, 14, 28)]
    metrics = game_bootstrap(records, base_rate=0.5, reps=1000, seed=7)["metrics"]
    assert metrics["brier_minus_base"]["estimate"] == 0.0
    assert metrics["log_loss_minus_base"]["estimate"] == 0.0
    assert metrics["accuracy"]["estimate"] == 0.5  # p = 0.5 picks the away side, so it is right on 2 of 4


def test_bootstrap_is_reproducible_for_a_fixed_seed():
    records = [_game(0.2 + 0.01 * i, 20 + i % 5, 17 + i % 3) for i in range(40)]
    assert game_bootstrap(records, 0.55, reps=500, seed=3) == game_bootstrap(records, 0.55, reps=500, seed=3)
