"""Forward-only reducer for nfl-seq v0.1: ``apply(state, event) -> (next_state, derived_events)``.

Pure and deterministic: the reducer never samples. Every outcome it needs arrives in the event,
so the same state and event always give the same next state, and a real event can be replayed
through it to test the transitions.

Approximations, all stated in docs/NFL-SEQUENCE-INTEGRATION-v0.1.md:
- Regular-season overtime: 10 minutes; each team gets one possession; a first-possession touchdown
  ends the game; otherwise a tie is final.
- A punt or kickoff return of 0 yards after a touchback is not modelled separately.
- An interception or fumble return yards come only from the event; the engine samples zero.
- Timeouts are never called; the clock is set entirely by the event's ``elapsed``.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Tuple

from .events import DERIVED_KINDS, Event, INPUT_KINDS, PLAY_KINDS, UNSUPPORTED_KINDS
from .state import AWAY, GameState, HOME, OVERTIME_SECONDS, REGULATION_SECONDS, other, validate_state

FIRST_DOWN_TO_GO = 10
KICKOFF_RECEIVE_SPOT = 75  # yardline_100 at the receiving team's own 25
TOUCHBACK_SPOT = 80  # yardline_100 at the receiving team's own 20
TOUCHDOWN_POINTS = 6
FIELD_GOAL_POINTS = 3
SAFETY_POINTS = 2
EXTRA_POINT = 1

_EXPECTED_PHASE = {"kickoff": "kickoff", "extra_point": "try", "punt": "scrimmage", "field_goal": "scrimmage"}
_EXPECTED_PHASE.update({kind: "scrimmage" for kind in PLAY_KINDS})


class RulesError(ValueError):
    """An event the current state cannot take. The game is not advanced."""


class UnsupportedMechanic(RulesError):
    """A contract event family that v0.1 does not model."""


def initial_state(opening_kicker: str, ot_kicker: str) -> GameState:
    """Pregame state: the opening kickoff is pending. ``ot_kicker`` kicks off any overtime."""
    state = GameState(
        period=1,
        clock=REGULATION_SECONDS,
        phase="kickoff",
        offense=None,
        kicking=opening_kicker,
        home_score=0,
        away_score=0,
        down=None,
        ydstogo=None,
        yardline_100=None,
        opening_kicker=opening_kicker,
        ot_kicker=ot_kicker,
        ot_possessions=0,
        drive_index=0,
        events=0,
        result=None,
    )
    validate_state(state)
    return state


def apply(state: GameState, event: Event) -> Tuple[GameState, List[Event]]:
    """Advance ``state`` by one event and return the new state with reducer-derived events."""
    _check_input(state, event)
    derived: List[Event] = []
    elapsed = min(event.elapsed, state.clock)

    nxt = _play(state, event, derived)
    nxt = replace(nxt, clock=state.clock - elapsed, events=state.events + 1)
    if nxt.phase != "final":
        nxt = _settle(nxt, derived)
    if nxt.phase == "final" and state.phase != "final":
        derived.append(Event(kind="game_end"))
    validate_state(nxt)
    return nxt, derived


def _check_input(state: GameState, event: Event) -> None:
    if state.phase == "final":
        raise RulesError("the game is final; %s is not legal" % event.kind)
    if event.kind in UNSUPPORTED_KINDS:
        raise UnsupportedMechanic("%s is not modelled in nfl-seq v0.1" % event.kind)
    if event.kind in DERIVED_KINDS or event.kind not in INPUT_KINDS:
        raise RulesError("%s is derived or unknown and cannot be an input" % event.kind)
    if state.phase != _EXPECTED_PHASE[event.kind]:
        raise RulesError("%s is not legal in phase %s" % (event.kind, state.phase))
    if event.kind == "kickoff":
        if event.offense != state.kicking:
            raise RulesError("kickoff must come from the kicking side %s" % state.kicking)
    elif event.kind == "extra_point":
        if event.offense != state.offense:
            raise RulesError("extra point must come from the scoring side %s" % state.offense)
    elif event.offense != state.offense:
        raise RulesError("%s must come from the offense %s" % (event.kind, state.offense))
    if event.kind == "kickoff" and event.touchback and event.return_yards:
        raise RulesError("a touchback carries no return yards")


def _play(state: GameState, event: Event, derived: List[Event]) -> GameState:
    kind = event.kind
    if kind == "kickoff":
        return _kickoff(state, event)
    if kind == "extra_point":
        state = _add_points(state, state.offense, EXTRA_POINT if event.made else 0)
        return _new_possession_kickoff(state, kicker=state.offense)
    if kind == "field_goal":
        if event.made:
            state = _add_points(state, state.offense, FIELD_GOAL_POINTS)
            return _new_possession_kickoff(state, kicker=state.offense)
        return _turnover(state, spot=state.yardline_100, returned=0)
    if kind == "punt":
        return _punt(state, event)
    return _scrimmage_play(state, event, derived)


def _scrimmage_play(state: GameState, event: Event, derived: List[Event]) -> GameState:
    if event.kind == "interception":
        return _turnover(state, spot=state.yardline_100, returned=event.return_yards)
    yards = 0 if event.kind in ("pass_incomplete", "spike") else event.yards
    spot = state.yardline_100 - yards
    if spot <= 0:
        return _touchdown(state, scorer=state.offense)
    if spot >= 100:
        derived.append(Event(kind="safety", offense=state.offense))
        state = _add_points(state, other(state.offense), SAFETY_POINTS)
        return _new_possession_kickoff(state, kicker=state.offense)
    if event.fumble_lost:
        return _turnover(state, spot=spot, returned=0)
    if yards >= state.ydstogo:
        return replace(state, down=1, ydstogo=min(FIRST_DOWN_TO_GO, spot), yardline_100=spot)
    if state.down == 4:
        return _turnover(state, spot=spot, returned=0)
    return replace(
        state,
        down=state.down + 1,
        ydstogo=min(state.ydstogo - yards, spot),
        yardline_100=spot,
    )


def _kickoff(state: GameState, event: Event) -> GameState:
    receiver = other(state.kicking)
    spot = KICKOFF_RECEIVE_SPOT - event.return_yards
    if event.touchback:
        spot = KICKOFF_RECEIVE_SPOT
    if spot <= 0:
        return _touchdown(state, scorer=receiver)
    return replace(
        state,
        phase="scrimmage",
        offense=receiver,
        kicking=None,
        down=1,
        ydstogo=min(FIRST_DOWN_TO_GO, _clamp(spot)),
        yardline_100=_clamp(spot),
    )


def _punt(state: GameState, event: Event) -> GameState:
    receiver = other(state.offense)
    landing = state.yardline_100 - event.yards
    if landing <= 0:
        return _new_possession_scrimmage(state, receiver, TOUCHBACK_SPOT)
    spot = (100 - landing) - event.return_yards
    if spot <= 0:
        return _touchdown(state, scorer=receiver)
    return _new_possession_scrimmage(state, receiver, _clamp(spot))


def _touchdown(state: GameState, scorer: str) -> GameState:
    state = _add_points(state, scorer, TOUCHDOWN_POINTS)
    if state.period >= 5 and state.ot_possessions == 1:
        return _final(state)
    return replace(
        state,
        phase="try",
        offense=scorer,
        kicking=None,
        down=None,
        ydstogo=None,
        yardline_100=None,
    )


def _turnover(state: GameState, spot: int, returned: int) -> GameState:
    """Possession goes to the other side at ``spot`` (offense-relative), returned toward its goal."""
    receiver = other(state.offense)
    spot_for_receiver = (100 - spot) - returned
    if spot_for_receiver <= 0:
        return _touchdown(state, scorer=receiver)
    return _new_possession_scrimmage(state, receiver, _clamp(spot_for_receiver))


def _clamp(spot: int) -> int:
    """A return that would carry the ball past the goal line is spotted on the goal line."""
    return min(spot, 99)


def _new_possession_kickoff(state: GameState, kicker: str) -> GameState:
    if state.period >= 5:
        if state.ot_possessions >= 2:
            return _final(state)
        state = replace(state, ot_possessions=state.ot_possessions + 1)
    return replace(
        state,
        phase="kickoff",
        offense=None,
        kicking=kicker,
        down=None,
        ydstogo=None,
        yardline_100=None,
        drive_index=state.drive_index + 1,
    )


def _new_possession_scrimmage(state: GameState, team: str, spot: int) -> GameState:
    if state.period >= 5:
        if state.ot_possessions >= 2:
            return _final(state)
        state = replace(state, ot_possessions=state.ot_possessions + 1)
    return replace(
        state,
        phase="scrimmage",
        offense=team,
        kicking=None,
        down=1,
        ydstogo=min(FIRST_DOWN_TO_GO, spot),
        yardline_100=spot,
        drive_index=state.drive_index + 1,
    )


def _settle(state: GameState, derived: List[Event]) -> GameState:
    """Apply period boundaries once the clock is at zero, except while a try is pending."""
    while state.phase not in ("final", "try") and state.clock == 0:
        derived.append(Event(kind="period_end"))
        if state.period == 4 and state.home_score == state.away_score:
            state = replace(state, period=5, clock=OVERTIME_SECONDS)
            state = _new_possession_kickoff(state, kicker=state.ot_kicker)
            continue
        if state.period >= 4:
            return _final(state)
        state = replace(state, period=state.period + 1, clock=REGULATION_SECONDS)
        if state.period == 3 and state.phase in ("scrimmage", "kickoff"):
            # The team that received the opening kickoff kicks off to start the second half.
            state = _new_possession_kickoff(state, kicker=other(state.opening_kicker))
    return state


def _final(state: GameState) -> GameState:
    if state.home_score > state.away_score:
        result = HOME
    elif state.away_score > state.home_score:
        result = AWAY
    else:
        result = "tie"
    return replace(
        state,
        phase="final",
        offense=None,
        kicking=None,
        down=None,
        ydstogo=None,
        yardline_100=None,
        result=result,
    )


def _add_points(state: GameState, side: str, points: int) -> GameState:
    if side == HOME:
        return replace(state, home_score=state.home_score + points)
    return replace(state, away_score=state.away_score + points)
