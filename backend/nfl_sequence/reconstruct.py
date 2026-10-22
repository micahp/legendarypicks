"""Historical reconstruction: one-step replay of recorded plays through the reducer.

This is not prediction. Each recorded play is turned into an event, applied to the recorded
pre-play state, and the result is compared with the recorded pre-play state of the next play.
Every step starts from the recorded state, so one mismatch never cascades into later steps.

The point is to test the reducer's transitions (possession, down, distance, spot, score, clock)
against what actually happened. Mismatches are the list of approximations still in the reducer,
and they are reported by category rather than hidden.

Historical rows are used here on purpose. Their outcomes are the observed record, so every result
from this module must be labelled as historical reconstruction.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .events import Event
from .rules import RulesError, UnsupportedMechanic, apply
from .state import AWAY, GameState, HOME, InvalidState, REGULATION_SECONDS, validate_state

SCRIMMAGE_TYPES = ("run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike")
EXAMPLE_LIMIT = 12


def quarter_clock(qtr: int, game_seconds_remaining: int) -> int:
    if qtr <= 4:
        return game_seconds_remaining - REGULATION_SECONDS * (4 - qtr)
    return game_seconds_remaining


def _side(row: Dict[str, Any], team: str) -> str:
    return HOME if team == row["home_team"] else AWAY


def _kicking_side(row: Dict[str, Any]) -> str:
    """nflverse marks a kickoff's posteam as the RECEIVING team; the kicker is the defteam."""
    return _side(row, row["defteam"])


def _seconds(row: Dict[str, Any]) -> Optional[int]:
    if row["game_seconds_remaining"] is None:
        return None
    return int(row["game_seconds_remaining"])


def pre_state(row: Dict[str, Any], opening_kicker: str, ot_kicker: str) -> GameState:
    """The recorded state before ``row``, expressed as a reducer state."""
    qtr = int(row["qtr"])
    clock = quarter_clock(qtr, _seconds(row))
    offense_side = _side(row, row["posteam"])
    defense_side = _side(row, row["defteam"])
    scores = {offense_side: int(row["posteam_score"]), defense_side: int(row["defteam_score"])}
    play_type = row["play_type"]
    kwargs: Dict[str, Any] = dict(
        period=qtr,
        clock=clock,
        home_score=scores[HOME],
        away_score=scores[AWAY],
        opening_kicker=opening_kicker,
        ot_kicker=ot_kicker,
        ot_possessions=0,
        drive_index=0,
        events=0,
        result=None,
    )
    if play_type == "kickoff":
        return GameState(phase="kickoff", offense=None, kicking=_kicking_side(row), down=None, ydstogo=None, yardline_100=None, **kwargs)
    if play_type == "extra_point":
        return GameState(phase="try", offense=offense_side, kicking=None, down=None, ydstogo=None, yardline_100=None, **kwargs)
    return GameState(
        phase="scrimmage",
        offense=offense_side,
        kicking=None,
        down=int(row["down"]),
        ydstogo=int(row["ydstogo"]),
        yardline_100=int(row["yardline_100"]),
        **kwargs,
    )


def event_for(row: Dict[str, Any], elapsed: int) -> Event:
    """The reducer event that a recorded play corresponds to. Raises UnsupportedMechanic for the rest."""
    play_type = row["play_type"]
    offense = _side(row, row["posteam"])
    fumble = row["fumble_lost"] == 1
    if row["penalty"] == 1 or play_type in (None, "no_play") or row["two_point_attempt"] == 1:
        raise UnsupportedMechanic("penalty, no-play or two-point row")
    if play_type == "kickoff":
        kicker = _kicking_side(row)
        return Event("kickoff", offense=kicker, elapsed=elapsed, touchback=row["touchback"] == 1, return_yards=int(row["return_yards"] or 0))
    if play_type == "extra_point":
        return Event("extra_point", offense=offense, made=row["extra_point_result"] == "good", elapsed=elapsed)
    if play_type == "punt":
        return Event("punt", offense=offense, yards=int(row["kick_distance"]), return_yards=int(row["return_yards"] or 0), elapsed=elapsed)
    if play_type == "field_goal":
        return Event("field_goal", offense=offense, made=row["field_goal_result"] == "made", elapsed=elapsed)
    if play_type == "qb_kneel":
        return Event("kneel", offense=offense, yards=int(row["yards_gained"]), elapsed=elapsed)
    if play_type == "qb_spike":
        return Event("spike", offense=offense, yards=0, elapsed=elapsed)
    yards = int(row["yards_gained"] or 0)
    if play_type == "run":
        if row["qb_scramble"] == 1:
            return Event("qb_scramble", offense=offense, yards=yards, fumble_lost=fumble, elapsed=elapsed)
        return Event("run", offense=offense, yards=yards, fumble_lost=fumble, elapsed=elapsed)
    if row["sack"] == 1:
        return Event("sack", offense=offense, yards=yards, fumble_lost=fumble, elapsed=elapsed)
    if row["interception"] == 1:
        return Event("interception", offense=offense, elapsed=elapsed)
    if row["complete_pass"] == 1:
        return Event("pass_complete", offense=offense, yards=yards, fumble_lost=fumble, elapsed=elapsed)
    return Event("pass_incomplete", offense=offense, elapsed=elapsed)


def _expected_phase(nxt: Optional[Dict[str, Any]]) -> str:
    if nxt is None or nxt["play_type"] is None:
        return "final"
    if nxt["play_type"] == "kickoff":
        return "kickoff"
    if nxt["play_type"] == "extra_point":
        return "try"
    return "scrimmage"


def _mismatches(after: GameState, nxt: Optional[Dict[str, Any]]) -> List[str]:
    if nxt is None or nxt["play_type"] is None:
        return [] if after.phase == "final" else ["phase"]
    fields = []
    expected = _expected_phase(nxt)
    if after.phase != expected:
        return ["phase"]
    offense = _side(nxt, nxt["posteam"])
    if expected == "kickoff" and after.kicking != _kicking_side(nxt):
        fields.append("kicking")
    if expected == "try" and after.offense != offense:
        fields.append("offense")
    if expected == "scrimmage":
        if after.offense != offense:
            fields.append("offense")
        if after.down != int(nxt["down"]):
            fields.append("down")
        if after.ydstogo != int(nxt["ydstogo"]):
            fields.append("ydstogo")
        if after.yardline_100 != int(nxt["yardline_100"]):
            fields.append("yardline_100")
    scores = {_side(nxt, nxt["posteam"]): int(nxt["posteam_score"]), _side(nxt, nxt["defteam"]): int(nxt["defteam_score"])}
    if after.home_score != scores[HOME] or after.away_score != scores[AWAY]:
        fields.append("score")
    if after.period != int(nxt["qtr"]):
        fields.append("period")
    if after.clock != quarter_clock(int(nxt["qtr"]), _seconds(nxt)):
        fields.append("clock")
    return fields


def replay(rows: Sequence[Dict[str, Any]]) -> Tuple[Counter, List[Dict[str, Any]]]:
    """Check every consecutive pair of recorded plays, one step each. Rows must be one season, sorted."""
    counts: Counter = Counter()
    examples: List[Dict[str, Any]] = []
    by_game: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_game.setdefault(row["game_id"], []).append(row)

    for game_rows in by_game.values():
        openers = [row for row in game_rows if row["play_type"] == "kickoff"]
        if not openers:
            counts["game_without_kickoff"] += 1
            continue
        opening_kicker = _kicking_side(openers[0])
        ot = [row for row in openers if int(row["qtr"]) == 5]
        ot_kicker = _kicking_side(ot[0]) if ot else opening_kicker
        for index, row in enumerate(game_rows):
            if row["play_type"] is None:
                continue
            if row["penalty"] == 1 or row["play_type"] in ("no_play",) or row["two_point_attempt"] == 1:
                counts["unsupported_play_row"] += 1
                continue
            # Period-boundary marker rows (play_type None) are skipped. If no play follows, the game ended.
            nxt = next((later for later in game_rows[index + 1:] if later["play_type"] is not None), None)
            if int(row["qtr"]) == 5 or (nxt is not None and int(nxt["qtr"]) == 5):
                counts["overtime_not_checked"] += 1
                continue
            try:
                pre = pre_state(row, opening_kicker, ot_kicker)
                validate_state(pre)
            except (TypeError, ValueError, InvalidState) as error:
                counts["pre_state_invalid:%s" % type(error).__name__] += 1
                continue
            if nxt is not None and (nxt["penalty"] == 1 or nxt["play_type"] in ("no_play", "two_point")):
                counts["next_row_is_penalty_or_no_play"] += 1
                continue
            if nxt is not None and _expected_phase(nxt) == "scrimmage" and None in (nxt["posteam"], nxt["down"], nxt["ydstogo"], nxt["yardline_100"]):
                counts["next_state_incomplete"] += 1
                continue
            elapsed = _elapsed(row, nxt, pre.clock)
            if elapsed is None:
                counts["runoff_anomaly"] += 1
                continue
            try:
                event = event_for(row, elapsed)
            except UnsupportedMechanic:
                counts["unsupported_play_row"] += 1
                continue
            except (TypeError, ValueError) as error:
                counts["event_invalid:%s" % type(error).__name__] += 1
                continue
            try:
                after, _ = apply(pre, event)
            except (RulesError, ValueError, KeyError) as error:
                counts["rules_error:%s" % type(error).__name__] += 1
                _keep(examples, row, nxt, "rules_error", str(error))
                continue
            fields = _mismatches(after, nxt)
            if not fields:
                counts["match"] += 1
            else:
                label = "mismatch:%s@%s" % ("+".join(fields), _attribution(row))
                counts[label] += 1
                _keep(examples, row, nxt, label, "")
    return counts, examples


def _attribution(row: Dict[str, Any]) -> str:
    """Which recorded play the mismatch came from, so each approximation can be counted on its own."""
    if row["interception"] == 1:
        return "interception"
    if row["fumble_lost"] == 1:
        return "fumble_lost"
    if row["sack"] == 1:
        return "sack"
    if row["play_type"] == "kickoff":
        return "kickoff_touchback" if row["touchback"] == 1 else "kickoff_return"
    return str(row["play_type"])


def _elapsed(row: Dict[str, Any], nxt: Optional[Dict[str, Any]], clock: int) -> Optional[int]:
    if nxt is None or int(nxt["qtr"]) != int(row["qtr"]) or _seconds(row) is None or _seconds(nxt) is None:
        return clock
    delta = _seconds(row) - _seconds(nxt)
    if delta < 0:
        return None
    return delta


def _keep(examples: List[Dict[str, Any]], row: Dict[str, Any], nxt: Optional[Dict[str, Any]], label: str, detail: str) -> None:
    if len(examples) >= EXAMPLE_LIMIT:
        return
    examples.append(
        {
            "game_id": row["game_id"],
            "play_id": row["play_id"],
            "play_type": row["play_type"],
            "next_play_type": nxt["play_type"] if nxt else None,
            "label": label,
            "detail": detail,
        }
    )
