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


def test_rolling_baseline_forgets_matches_older_than_the_window():
    state = tpm.OnlineStats(baseline_years=1)
    state.add((20200101, "Hard", "A", "B", 100, 50, 0, 100, 40, 0))   # serve pts 200, won 90
    assert state.baseline("Hard") == pytest.approx(90 / 200)
    state.add((20230101, "Hard", "C", "D", 100, 30, 30, 100, 30, 30))  # serve pts 200, won 120
    state.expire(20230101)  # 2020 match is now older than one year
    assert state.baseline("Hard") == pytest.approx(120 / 200)


def test_same_day_matches_do_not_inform_each_other():
    rows = [
        (20240101, "Hard", "A", "B", 100, 60, 0, 100, 60, 0),
        (20240101, "Hard", "A", "C", 100, 60, 0, 100, 60, 0),
    ]
    acc = tpm.walk_forward(rows, validate_start=20240101, test_start=20250101, test_end=20251231, baseline_years=0)
    # Both matches are validation rows, predicted with no history: every serve is predicted at the cold-start baseline.
    assert acc[("validation", "Hard", "baseline", None)][1] == 400
    assert acc[("validation", "Hard", "baseline", None)][3] == pytest.approx(400 * tpm.COLD_START_BASELINE)


def test_wta_filter_keeps_main_tour_levels_and_only_historical_w():
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE tennis_wta_matches (tourney_date INTEGER, tourney_level TEXT, surface TEXT, "
        "winner_id INTEGER, loser_id INTEGER, w_svpt INTEGER, w_1stWon INTEGER, w_2ndWon INTEGER, "
        "l_svpt INTEGER, l_1stWon INTEGER, l_2ndWon INTEGER)"
    )
    cases = [
        ("G", 20000101), ("F", 20000101), ("P", 20150101), ("PM", 20150101), ("I", 20150101),
        ("T3", 19990101), ("W", 19990101),          # kept: main tour, historical W
        ("W", 20150101),                             # dropped: W from 2010 is held for review
        ("C", 19990101), ("CC", 19990101), ("25", 20000101), ("D", 20000101),
        ("O", 20000101), ("E", 20000101), ("J", 20000101), ("35+H", 20250101),   # dropped
    ]
    for level, date in cases:
        con.execute(
            "INSERT INTO tennis_wta_matches VALUES (?, ?, 'Hard', 1, 2, 100, 60, 15, 100, 55, 15)", (date, level)
        )
    rows = tpm.load_matches(con, "wta", 0, 99999999)
    assert len(rows) == 7
    assert sum(1 for r in rows if r[0] == 20150101) == 3  # P, PM and I, not the 2015 W


def test_by_level_keys_the_surface_field_by_tournament_level():
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE tennis_atp_matches (tourney_date INTEGER, tourney_level TEXT, surface TEXT, "
        "winner_id INTEGER, loser_id INTEGER, w_svpt INTEGER, w_1stWon INTEGER, w_2ndWon INTEGER, "
        "l_svpt INTEGER, l_1stWon INTEGER, l_2ndWon INTEGER)"
    )
    con.execute("INSERT INTO tennis_atp_matches VALUES (20240101, 'G', 'Clay', 1, 2, 100, 60, 15, 100, 55, 15)")
    con.execute("INSERT INTO tennis_atp_matches VALUES (20240101, 'A', 'Clay', 1, 2, 100, 60, 15, 100, 55, 15)")
    plain = tpm.load_matches(con, "atp", 0, 99999999)
    keyed = tpm.load_matches(con, "atp", 0, 99999999, by_level=True)
    assert {r[1] for r in plain} == {"Clay"}
    assert {r[1] for r in keyed} == {"Clay|G", "Clay|A"}
