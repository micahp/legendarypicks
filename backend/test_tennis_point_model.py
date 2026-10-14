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


def test_wta_filter_keeps_main_tour_levels_and_only_the_named_w_events_from_2010():
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE tennis_wta_matches (tourney_date INTEGER, tourney_level TEXT, tourney_id TEXT, surface TEXT, "
        "winner_id INTEGER, loser_id INTEGER, w_svpt INTEGER, w_1stWon INTEGER, w_2ndWon INTEGER, "
        "l_svpt INTEGER, l_1stWon INTEGER, l_2ndWon INTEGER)"
    )
    cases = [
        ("G", 20000101, "x"), ("F", 20000101, "x"), ("P", 20150101, "x"), ("PM", 20150101, "x"), ("I", 20150101, "x"),
        ("T3", 19990101, "x"), ("W", 19990101, "x"),              # kept: main tour, and W before 2010
        ("W", 20150101, "2015-W-WT-SIN-01A-2015"),                 # kept: WTA Finals, named
        ("W", 20210412, "2021-2033"),                              # kept: Charleston 2, named
        ("W", 20210412, "2021-2041"),                              # dropped: Parma, a 125
        ("W", 20240101, "2024-2052"),                              # dropped: Buenos Aires 125
        ("W", 20150101, "unnamed-w"),                              # dropped: an unnamed W from 2010
        ("C", 19990101, "x"), ("CC", 19990101, "x"), ("25", 20000101, "x"), ("D", 20000101, "x"),
        ("O", 20000101, "x"), ("E", 20000101, "x"), ("J", 20000101, "x"), ("35+H", 20250101, "x"),   # dropped
    ]
    for level, date, tid in cases:
        con.execute(
            "INSERT INTO tennis_wta_matches VALUES (?, ?, ?, 'Hard', 1, 2, 100, 60, 15, 100, 55, 15)",
            (date, level, tid),
        )
    rows = tpm.load_matches(con, "wta", 0, 99999999)
    assert len(rows) == 9
    assert sum(1 for r in rows if r[0] == 20150101) == 4  # P, PM, I and the WTA Finals, not the unnamed 2015 W
    assert sum(1 for r in rows if r[0] == 20210412) == 1  # Charleston 2 only, not Parma on the same date


def test_player_counts_decay_with_the_player_half_life():
    state = tpm.OnlineStats(baseline_years=0, player_half_life=1.0)
    state.add((20220101, "Hard", "A", "B", 100, 40, 20, 100, 30, 10))  # A serves 60 of 100
    state.expire(20230101)  # 365 days later: one half-life
    won, pts, _, _ = state._counts("A", "Hard")
    assert won == pytest.approx(60 * 0.5, rel=1e-3)
    assert pts == pytest.approx(100 * 0.5, rel=1e-3)


def test_no_player_half_life_leaves_player_counts_undecayed():
    state = tpm.OnlineStats(baseline_years=0)
    state.add((20220101, "Hard", "A", "B", 100, 40, 20, 100, 30, 10))
    state.expire(20300101)
    assert state._counts("A", "Hard")[:2] == (60, 100)


def test_recent_matches_weigh_more_when_player_counts_are_weighted():
    rows = [
        (20200101, "Hard", "A", "B", 100, 60, 30, 100, 30, 10),  # A serves 90 of 100
        (20221231, "Hard", "A", "C", 100, 20, 10, 100, 30, 10),  # A serves 30 of 100
    ]
    cumulative = tpm.OnlineStats(baseline_years=0)
    weighted = tpm.OnlineStats(baseline_years=0, player_half_life=1.0)
    for row in rows:
        cumulative.add(row)
        weighted.add(row)
    cumulative.expire(20230101)
    weighted.expire(20230101)
    assert cumulative.serve("A", "Hard", k=0) == pytest.approx(120 / 200)
    f_old = 0.5 ** ((tpm._ordinal(20230101) - tpm._ordinal(20200101)) / 365.25)
    f_new = 0.5 ** ((tpm._ordinal(20230101) - tpm._ordinal(20221231)) / 365.25)
    expected = (90 * f_old + 30 * f_new) / (100 * f_old + 100 * f_new)
    assert weighted.serve("A", "Hard", k=0) == pytest.approx(expected)
    assert weighted.serve("A", "Hard", k=0) < 0.5


def test_rest_bucket_boundaries():
    last = 100
    assert tpm.rest_bucket(103, last) == 0   # 3 days
    assert tpm.rest_bucket(104, last) == 1   # 4 days
    assert tpm.rest_bucket(107, last) == 1   # 7 days
    assert tpm.rest_bucket(108, last) == tpm.REST_REFERENCE  # 8 days
    assert tpm.rest_bucket(114, last) == tpm.REST_REFERENCE  # 14 days
    assert tpm.rest_bucket(115, last) == 3  # 15 days
    assert tpm.rest_bucket(115, None) == tpm.REST_NO_MATCH


def test_rest_features_sign_convention():
    assert len(tpm.rest_features(2, 2)) == tpm.N_REST
    assert tpm.rest_features(2, 2) == [1.0] + [0.0] * 8  # reference on both sides: intercept only
    assert tpm.rest_features(0, 2)[1] == 1.0  # server rested 0 to 3 days raises the server's logit
    assert tpm.rest_features(2, 0)[5] == -1.0  # returner rested 0 to 3 days lowers the server's logit


def test_fit_rest_recovers_known_bucket_effects():
    # Saturated design: each cell's observed rate is exactly the fitted rate, so Newton's method recovers
    # the logits. Server rested 0 to 3 days wins 0.6 against the reference 0.5. A fresh returner wins 0.4 against a
    # reference server, so the server's logit falls by 0.405 and the returner's coefficient is +0.405.
    records = [
        ("validation", 0.5, 1000, 500, 2, 2),
        ("validation", 0.5, 1000, 600, 0, 2),
        ("validation", 0.5, 1000, 400, 2, 0),
    ]
    theta = tpm.fit_rest(records)
    expected = math.log(0.6 / 0.4)
    assert theta[1] == pytest.approx(expected, abs=1e-4)
    assert theta[5] == pytest.approx(expected, abs=1e-4)
    assert abs(theta[0]) < 1e-4


def test_walk_detail_reads_rest_before_the_match_is_added():
    rows = [
        (20240101, "Hard", "A", "B", 100, 60, 0, 100, 60, 0),
        (20240105, "Hard", "A", "C", 100, 60, 0, 100, 60, 0),  # A last played 4 days earlier; C never has
    ]
    records = tpm.walk_detail(rows, validate_start=20240101, test_start=20250101, test_end=20251231,
                              baseline_years=0, half_life_years=None, player_half_life=None, k=500)
    assert len(records) == 4
    assert records[0][4:6] == (tpm.REST_NO_MATCH, tpm.REST_NO_MATCH)
    assert records[2][4:6] == (1, tpm.REST_NO_MATCH)  # A: 4 days, rest bucket 1; C: no earlier match
    assert records[3][4:6] == (tpm.REST_NO_MATCH, 1)


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
