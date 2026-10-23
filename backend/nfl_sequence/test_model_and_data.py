"""Count tables, data mapping and one-step reconstruction, on hand-built rows (no parquet needed)."""
import random
from collections import Counter

from nfl_sequence.model import CountBuilder, Sampler, StatModel, Table, situation
from nfl_sequence.nflverse import game_finals, iter_observations
from nfl_sequence.reconstruct import replay

HOME_TEAM, AWAY_TEAM = "BUF", "KC"
DEFAULTS = dict(
    game_id="2023_01_KC_BUF", play_id=1.0, season=2023, season_type="REG", posteam=None, defteam=None,
    home_team=HOME_TEAM, away_team=AWAY_TEAM, qtr=1, down=None, ydstogo=None, yardline_100=None,
    game_seconds_remaining=3600, posteam_score=0, defteam_score=0, play_type=None, yards_gained=None,
    penalty=0, play_deleted=0, aborted_play=0, two_point_attempt=0, qb_kneel=0, qb_spike=0,
    qb_scramble=0, sack=0, interception=0, complete_pass=0, incomplete_pass=0, out_of_bounds=0,
    fumble_lost=0, kick_distance=None, field_goal_result=None, extra_point_result=None, touchback=0,
    return_yards=None, kickoff_attempt=0, punt_attempt=0, total_home_score=0, total_away_score=0,
    drive=1, week=1,
)


def row(**fields):
    data = dict(DEFAULTS)
    data.update(fields)
    return data


def test_situation_bins_match_the_engine_context():
    ctx = situation(down=3, ydstogo=4, yardline_100=18, period=5, diff=-9)
    assert ctx == {"down": "3", "dist": "3-4", "field": "11-19", "score": "L9", "qtr": "4+"}


def test_penalties_and_two_point_tries_are_skipped_and_counted():
    rows = [
        row(play_id=1.0, play_type="run", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=1, ydstogo=10, yardline_100=70, penalty=1, yards_gained=3),
        row(play_id=2.0, play_type="pass", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=1, ydstogo=10, yardline_100=70, two_point_attempt=1, complete_pass=1, yards_gained=2),
    ]
    skips = Counter()
    observations = list(iter_observations(rows, skips))
    assert [name for name, _, _ in observations if name == "call"] == []
    assert skips["penalty_or_no_play"] == 1 and skips["two_point_attempt"] == 1


def test_qb_scramble_coded_as_a_run_becomes_a_pass_scramble():
    rows = [row(play_id=1.0, play_type="run", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=2, ydstogo=7, yardline_100=60, qb_scramble=1, yards_gained=4, fumble_lost=0)]
    observations = list(iter_observations(rows, Counter()))
    assert ("call", dict(situation(2, 7, 60, 1, 0), late="early"), "pass") in observations
    assert any(name == "pass_class" and value == "scramble" for name, _, value in observations)
    assert any(name == "scramble_yards" and value == "4" for name, _, value in observations)


def test_runoff_is_the_clock_difference_to_the_next_play_in_the_same_period():
    rows = [
        row(play_id=1.0, play_type="run", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=1, ydstogo=10, yardline_100=70, game_seconds_remaining=1000, yards_gained=2),
        row(play_id=2.0, play_type="pass", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=2, ydstogo=8, yardline_100=68, game_seconds_remaining=985, complete_pass=1, yards_gained=3),
    ]
    observations = list(iter_observations(rows, Counter()))
    assert ("elapsed", {"call": "run", "sub": "normal"}, "15") in observations


def test_a_non_touchback_kickoff_records_the_receiving_spot_as_an_implied_return():
    rows = [
        row(play_id=1.0, play_type="kickoff", posteam=HOME_TEAM, defteam=AWAY_TEAM, yardline_100=35, touchback=0, return_yards=20, game_seconds_remaining=3600),
        row(play_id=2.0, play_type="run", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=1, ydstogo=10, yardline_100=60, game_seconds_remaining=3595, yards_gained=1),
    ]
    observations = list(iter_observations(rows, Counter()))
    assert ("kickoff_implied_return", {}, "15") in observations


def test_game_finals_takes_the_maximum_so_a_stray_row_cannot_lower_the_final():
    rows = [
        row(play_id=1.0, total_home_score=7, total_away_score=3),
        row(play_id=5.0, total_home_score=21, total_away_score=14),
        row(play_id=9.0, total_home_score=21, total_away_score=0),  # out-of-sequence row
    ]
    assert game_finals(rows)["2023_01_KC_BUF"]["away"] == 14


def test_backoff_uses_the_coarse_cell_when_the_fine_cell_is_thin():
    levels = [("down", "dist"), ()]
    thin = Table(levels, [{"1|10": {"run": 1}}, {"": {"pass": 10}}], min_n=3)
    assert thin.probabilities({"down": "1", "dist": "10"}) == {"pass": 1.0}
    dense = Table(levels, [{"1|10": {"run": 3, "pass": 1}}, {"": {"pass": 10}}], min_n=3)
    assert dense.probabilities({"down": "1", "dist": "10"}) == {"pass": 0.25, "run": 0.75}


def test_sampler_is_reproducible_for_a_fixed_random_stream():
    sampler = Sampler({"a": 1, "b": 3})
    first = [sampler.draw(random.Random(seed)) for seed in range(50)]
    second = [sampler.draw(random.Random(seed)) for seed in range(50)]
    assert first == second
    assert set(first) == {"a", "b"}
    assert abs(sum(sampler.probabilities().values()) - 1.0) < 1e-12


def test_a_model_round_trips_through_json_with_the_same_probabilities():
    import json

    fresh = CountBuilder("frequency", min_n=1)
    for name, ctx, value in [
        ("call", {"down": "1", "dist": "10", "field": "G10", "score": "T", "qtr": "1"}, "run"),
        ("call", {"down": "1", "dist": "10", "field": "G10", "score": "T", "qtr": "1"}, "pass"),
        ("pass_class", {"down": "1", "dist": "10", "field": "G10", "score": "T", "qtr": "1"}, "complete"),
        ("run_yards", {"down": "1", "dist": "10", "field": "G10"}, "3"),
        ("pass_yards", {"dist": "10", "field": "G10"}, "7"),
        ("sack_yards", {"field": "G10"}, "-5"),
        ("scramble_yards", {"field": "G10"}, "2"),
        ("fumble", {"call": "run"}, "no"),
        ("fumble", {"call": "pass"}, "no"),
        ("punt_gross", {"field": "G10"}, "40"),
        ("punt_return", {}, "5"),
        ("fg", {"fg": "<=29"}, "make"),
        ("xp", {}, "make"),
        ("kickoff_touchback", {}, "touchback"),
        ("kickoff_implied_return", {}, "10"),
        ("elapsed", {"call": "run", "sub": "normal"}, "25"),
        ("elapsed", {"call": "pass", "sub": "incomplete"}, "5"),
    ]:
        fresh.add(name, ctx, value)
    model = fresh.build({"source": "unit"})
    restored = StatModel.from_dict(json.loads(json.dumps(model.to_dict())))
    ctx = {"down": "1", "dist": "10", "field": "G10", "score": "T", "qtr": "1"}
    assert restored["call"].probabilities(ctx) == model["call"].probabilities(ctx)


def test_a_build_with_no_observations_for_a_table_is_refused():
    builder = CountBuilder("main", min_n=1)
    try:
        builder.build({})
    except ValueError as error:
        assert "has no observations" in str(error)
    else:
        raise AssertionError("an empty table must not build")


def test_one_step_replay_matches_a_recorded_kickoff_run_pass_sequence():
    rows = [
        row(play_id=1.0, play_type="kickoff", posteam=HOME_TEAM, defteam=AWAY_TEAM, yardline_100=35, touchback=1, return_yards=0, game_seconds_remaining=3600),
        row(play_id=2.0, play_type="run", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=1, ydstogo=10, yardline_100=75, game_seconds_remaining=3595, yards_gained=4),
        row(play_id=3.0, play_type="pass", posteam=HOME_TEAM, defteam=AWAY_TEAM, down=2, ydstogo=6, yardline_100=71, game_seconds_remaining=3580, complete_pass=1, yards_gained=5),
    ]
    counts, _ = replay(rows)
    assert counts["match"] == 2  # kickoff -> run and run -> pass; the truncated last play has no next state
    assert any(key.startswith("mismatch:phase") for key in counts)
