"""Late-clock context (v0.2 clock variant): the call table must key on the window; v0.1 must not."""
import os
from collections import Counter

import pytest

from nfl_sequence.model import StatModel, clock_window
from nfl_sequence.nflverse import iter_observations
from nfl_sequence.simulate import Simulator
from nfl_sequence.state import AWAY, GameState, HOME

HERE = os.path.dirname(os.path.abspath(__file__))
CLOCK_MODEL = os.path.join(HERE, "models-v0.2", "nfl-seq-v0.1-clock.json")
MAIN_MODEL = os.path.join(HERE, "models", "nfl-seq-v0.1-main.json")


@pytest.fixture(scope="module")
def clock():
    return StatModel.load(CLOCK_MODEL)


@pytest.fixture(scope="module")
def main():
    return StatModel.load(MAIN_MODEL)


def test_the_window_is_the_last_two_minutes_of_the_half_quarter_four_or_overtime():
    assert clock_window(2, 120) == "late" and clock_window(4, 0) == "late" and clock_window(5, 60) == "late"
    assert clock_window(2, 121) == "early" and clock_window(1, 60) == "early" and clock_window(3, 30) == "early"


def test_a_call_table_without_time_context_fails_the_structure_check(clock):
    levels = clock["call"].levels
    assert all("late" in level for level in levels[:3])  # the window sits on the three finest levels
    assert levels[3:] == [("down", "dist", "field"), ("down", "dist"), ("down",), ()]  # then the v0.1 structure


def test_coarse_late_backoff_never_drops_the_field(clock):
    # Amendment A1: a thin late cell must not pool calls across field positions.
    assert all("field" in level for level in clock["call"].levels[:4])


def test_the_frozen_v01_call_table_does_not_key_on_the_window(main):
    assert not any("late" in level for level in main["call"].levels)
    ctx = {"down": "4", "dist": "1-2", "field": "20-34", "score": "W", "qtr": "4+"}
    assert main["call"].probabilities(dict(ctx, late="late")) == main["call"].probabilities(dict(ctx, late="early"))


def test_the_clock_table_gives_different_call_mixes_in_the_late_window(clock):
    ctx = {"down": "4", "dist": "1-2", "field": "20-34", "score": "W", "qtr": "4+"}
    late = clock["call"].probabilities(dict(ctx, late="late"))
    early = clock["call"].probabilities(dict(ctx, late="early"))
    assert late != early
    assert early.get("kneel", 0.0) < 0.01  # kneels are an end-of-half and end-of-game call


def test_the_simulator_passes_the_window_to_the_call_table(clock):
    seen = []
    original = clock["call"].probabilities

    def recording(ctx):
        seen.append(dict(ctx))
        return original(ctx)

    clock["call"].probabilities = recording
    try:
        sim = Simulator(clock, game_id="g", home_team=HOME, away_team=AWAY, season=2030, snapshot_hash="t")
        run = sim.start(5)
        state = GameState(period=4, clock=100, phase="scrimmage", offense=HOME, kicking=None, home_score=20, away_score=17,
                          down=2, ydstogo=6, yardline_100=40, opening_kicker=AWAY, ot_kicker=HOME, ot_possessions=0,
                          drive_index=3, events=5, result=None)
        run.state = state
        run._draw_scrimmage(state, clock, run.rng)
    finally:
        clock["call"].probabilities = original
    assert seen and seen[-1]["late"] == "late"


def test_training_tags_call_observations_with_the_window():
    rows = [
        {"game_id": "g", "play_id": 1.0, "season": 2023, "season_type": "REG", "posteam": "BUF", "defteam": "KC",
         "home_team": "BUF", "away_team": "KC", "qtr": 4, "down": 1, "ydstogo": 10, "yardline_100": 60,
         "game_seconds_remaining": 100, "posteam_score": 20, "defteam_score": 17, "play_type": "run",
         "yards_gained": 2, "penalty": 0, "play_deleted": 0, "aborted_play": 0, "two_point_attempt": 0,
         "qb_scramble": 0, "sack": 0, "interception": 0, "complete_pass": 0, "incomplete_pass": 0,
         "fumble_lost": 0, "kick_distance": None, "field_goal_result": None, "extra_point_result": None,
         "touchback": 0, "return_yards": None, "drive": 1},
    ]
    windows = [ctx["late"] for name, ctx, _ in iter_observations(rows, Counter()) if name == "call"]
    assert windows == ["late"]
