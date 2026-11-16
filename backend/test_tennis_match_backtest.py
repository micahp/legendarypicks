import tennis_match_backtest as bt


def test_only_complete_scores_are_scored():
    assert bt.is_complete("6-4 3-6 7-6(5)")
    assert bt.is_complete("6-4 3-6 [10-8]")
    assert not bt.is_complete("6-4 RET")
    assert not bt.is_complete("W/O")
    assert not bt.is_complete("6-4 DEF")
    assert not bt.is_complete("ABD")
    assert not bt.is_complete(None)


def test_a_match_without_serve_counts_is_not_history():
    with_stats = (20240101, "Hard", 1, 2, 3, "6-4 6-3", 100, 60, 15, 100, 55, 15)
    without = (20240101, "Hard", 1, 2, 3, "6-4 6-3", None, None, None, None, None, None)
    zero = (20240101, "Hard", 1, 2, 3, "6-4 6-3", 0, 0, 0, 0, 0, 0)
    assert bt.has_serve_stats(with_stats)
    assert not bt.has_serve_stats(without)
    assert not bt.has_serve_stats(zero)


def test_depth_buckets_follow_the_protocol_thresholds():
    assert bt.depth_bucket(0) == "thin"
    assert bt.depth_bucket(299.9) == "thin"
    assert bt.depth_bucket(300) == "middling"
    assert bt.depth_bucket(1499.9) == "middling"
    assert bt.depth_bucket(1500) == "deep"


def _rec(p_sim, p_elo, y, year=2023):
    return {"p_sim": p_sim, "p_elo": p_elo, "y": y, "year": year}


def test_paired_interval_is_negative_when_the_simulator_is_the_better_forecast():
    recs = [_rec(0.8, 0.5, 1)] * 50 + [_rec(0.2, 0.5, 0)] * 50
    interval = bt.paired_interval(recs)
    assert interval["mean_difference"] < 0
    assert interval["ci_high"] < 0


def test_predictive_decision_needs_a_lower_log_loss_with_the_interval_below_zero():
    recs = [_rec(0.8, 0.5, 1, y) for y in (2023, 2024, 2025)] * 30 + [_rec(0.2, 0.5, 0, y) for y in (2023, 2024, 2025)] * 30
    overall = bt.summarise(recs)
    decision = bt.decide(recs, overall, bt.paired_interval(recs))
    assert decision["P1_predictive_value"] is True
    assert decision["P3_years"] == 3
    assert decision["P3_stability_years_won"] == 3
