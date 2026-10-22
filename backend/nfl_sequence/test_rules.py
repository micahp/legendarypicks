"""Reducer tests: hand-built states that pin each transition, and the rules that must refuse."""
from dataclasses import replace

import pytest

from nfl_sequence.events import Event
from nfl_sequence.rules import RulesError, UnsupportedMechanic, apply, initial_state
from nfl_sequence.state import AWAY, GameState, HOME, validate_state


def scrimmage(offense=HOME, down=1, ydstogo=None, yardline=70, period=1, clock=600, home=0, away=0, **extra):
    if ydstogo is None:
        ydstogo = min(10, yardline)
    state = GameState(
        period=period,
        clock=clock,
        phase="scrimmage",
        offense=offense,
        kicking=None,
        home_score=home,
        away_score=away,
        down=down,
        ydstogo=ydstogo,
        yardline_100=yardline,
        opening_kicker=AWAY,
        ot_kicker=HOME,
        ot_possessions=0,
        drive_index=1,
        events=0,
        result=None,
    )
    state = replace(state, **extra)
    validate_state(state)
    return state


def play(kind, offense=HOME, **kwargs):
    return Event(kind=kind, offense=offense, **kwargs)


def test_initial_state_has_the_opening_kickoff_pending():
    state = initial_state(opening_kicker=AWAY, ot_kicker=HOME)
    assert (state.phase, state.kicking, state.period, state.clock) == ("kickoff", AWAY, 1, 900)


def test_touchback_gives_the_receiver_its_own_25():
    state, derived = apply(initial_state(AWAY, HOME), Event("kickoff", offense=AWAY, touchback=True, elapsed=5))
    assert (state.phase, state.offense, state.yardline_100, state.down, state.ydstogo) == ("scrimmage", HOME, 75, 1, 10)
    assert state.clock == 895 and derived == []


def test_kickoff_return_to_goal_line_is_a_touchdown_then_a_try():
    state, _ = apply(initial_state(AWAY, HOME), Event("kickoff", offense=AWAY, return_yards=80, elapsed=5))
    assert (state.phase, state.offense, state.home_score) == ("try", HOME, 6)


def test_first_down_between_the_20s_resets_to_first_and_ten():
    state, _ = apply(scrimmage(yardline=30, ydstogo=3), play("run", yards=4, elapsed=20))
    assert (state.down, state.ydstogo, state.yardline_100) == (1, 10, 26)


def test_first_down_short_of_goal_line_caps_ydstogo_at_the_goal():
    state, _ = apply(scrimmage(yardline=15, ydstogo=3), play("run", yards=4, elapsed=20))
    assert (state.down, state.ydstogo, state.yardline_100) == (1, 10, 11)


def test_failed_fourth_down_hands_the_ball_over_at_the_spot():
    state, _ = apply(scrimmage(down=4, ydstogo=5, yardline=60), play("run", yards=2, elapsed=20))
    assert (state.offense, state.down, state.yardline_100) == (AWAY, 1, 100 - 58)


def test_touchdown_then_extra_point_then_kickoff_by_the_scoring_team():
    state, _ = apply(scrimmage(yardline=4), play("run", yards=6, elapsed=10))
    assert (state.phase, state.home_score) == ("try", 6)
    state, _ = apply(state, play("extra_point", made=True, elapsed=0))
    assert (state.phase, state.home_score, state.kicking) == ("kickoff", 7, HOME)


def test_made_field_goal_scores_three_and_kicks_off():
    state, _ = apply(scrimmage(yardline=20), play("field_goal", made=True, elapsed=8))
    assert (state.phase, state.home_score, state.kicking) == ("kickoff", 3, HOME)


def test_missed_field_goal_turns_the_ball_over_at_the_spot():
    state, _ = apply(scrimmage(yardline=30), play("field_goal", made=False, elapsed=8))
    assert (state.offense, state.yardline_100) == (AWAY, 70)


def test_punt_that_lands_past_the_goal_is_a_touchback_to_the_20():
    state, _ = apply(scrimmage(yardline=40), play("punt", yards=50, return_yards=0, elapsed=6))
    assert (state.offense, state.yardline_100) == (AWAY, 80)


def test_punt_with_return_moves_the_receiver_from_the_landing_spot():
    state, _ = apply(scrimmage(yardline=60), play("punt", yards=40, return_yards=5, elapsed=6))
    assert (state.offense, state.yardline_100) == (AWAY, 100 - 20 - 5)


def test_interception_returned_past_the_goal_line_is_a_pick_six():
    # Offense at its opponent's 10: the defense starts 90 yards from the far goal, so 95 yards back is six.
    state, _ = apply(scrimmage(yardline=10), play("interception", return_yards=95, elapsed=5))
    assert (state.phase, state.offense, state.away_score) == ("try", AWAY, 6)


def test_safety_scores_two_for_the_defense_and_a_free_kick_by_the_conceding_side():
    state, derived = apply(scrimmage(yardline=99), play("sack", yards=-3, elapsed=7))
    assert (state.away_score, state.phase, state.kicking) == (2, "kickoff", HOME)
    assert [event.kind for event in derived] == ["safety"]


def test_clock_is_capped_at_the_time_remaining_and_quarter_end_keeps_possession():
    state, derived = apply(scrimmage(clock=3, yardline=50), play("run", yards=2, elapsed=40))
    assert (state.period, state.clock, state.offense, state.phase) == (2, 900, HOME, "scrimmage")
    assert [event.kind for event in derived] == ["period_end"]


def test_halftime_kickoff_is_taken_by_the_team_that_received_the_opening_kickoff():
    state = scrimmage(period=2, clock=2, yardline=50, offense=HOME)
    state, derived = apply(state, play("run", yards=0, elapsed=5))
    assert (state.period, state.phase, state.kicking) == (3, "kickoff", HOME)
    assert "period_end" in [event.kind for event in derived]


def test_regulation_tie_starts_overtime_with_the_coin_loser_kicking():
    state = scrimmage(period=4, clock=1, yardline=50, home=20, away=20, offense=HOME)
    state, _ = apply(state, play("run", yards=0, elapsed=1))
    assert (state.period, state.clock, state.phase, state.kicking) == (5, 600, "kickoff", HOME)


def test_first_possession_touchdown_in_overtime_ends_the_game():
    state = scrimmage(period=5, clock=400, yardline=3, ydstogo=3, offense=AWAY, home=20, away=20, ot_possessions=1)
    state, derived = apply(state, play("run", offense=AWAY, yards=5, elapsed=20))
    assert (state.phase, state.result, state.away_score) == ("final", AWAY, 26)
    assert [event.kind for event in derived] == ["game_end"]


def test_regulation_ends_at_zero_with_a_lead_and_no_kickoff():
    state = scrimmage(period=4, clock=5, yardline=40, home=10, away=7)
    state, derived = apply(state, play("kneel", yards=-1, elapsed=40))
    assert (state.phase, state.result) == ("final", HOME)
    assert "game_end" in [event.kind for event in derived]


def test_penalties_and_two_point_tries_are_refused_not_run_as_plays():
    with pytest.raises(UnsupportedMechanic):
        apply(scrimmage(), Event("penalty", offense=HOME, elapsed=5))
    with pytest.raises(UnsupportedMechanic):
        apply(scrimmage(), Event("two_point_try", offense=HOME, elapsed=5))


def test_derived_kinds_cannot_be_fed_back_in():
    with pytest.raises(RulesError):
        apply(scrimmage(), Event("period_end"))


def test_events_from_the_wrong_side_or_phase_are_refused():
    with pytest.raises(RulesError):
        apply(scrimmage(offense=HOME), play("run", offense=AWAY, yards=1, elapsed=5))
    with pytest.raises(RulesError):
        apply(scrimmage(), Event("kickoff", offense=HOME, elapsed=5))


def test_a_final_game_accepts_nothing():
    final = replace(scrimmage(), phase="final", offense=None, down=None, ydstogo=None, yardline_100=None, result=HOME, home_score=7, away_score=3, period=4, clock=0)
    with pytest.raises(RulesError):
        apply(final, play("run", yards=1, elapsed=1))


def test_an_observed_illegal_event_leaves_the_state_unchanged():
    state = scrimmage(offense=HOME)
    with pytest.raises(RulesError):
        apply(state, play("extra_point", offense=HOME, made=True, elapsed=0))
    assert state == scrimmage(offense=HOME)
