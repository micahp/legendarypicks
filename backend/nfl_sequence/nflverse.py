"""Turns nflverse play-by-play rows into the observations the count tables learn from.

Offline only: this module reads parquet with pyarrow, which lives in the data-prep environment,
not in the request path. The engine never imports it. Every row that cannot become an observation
is counted under a named skip reason, so a silent drop shows up in the manifest.

Pre-play fields only: ``posteam_score``/``defteam_score`` (before the play), ``down``, ``ydstogo``,
``yardline_100``, ``qtr``. Outcome fields (``epa``, ``wpa``, ``xpass``, ``pass_oe``, ``cpoe``,
``success``) are never read, because they can encode the play's own result.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .model import fg_bin, situation

COLUMNS = [
    "game_id", "play_id", "season", "season_type", "week",
    "posteam", "defteam", "qtr", "down", "ydstogo", "yardline_100",
    "game_seconds_remaining", "posteam_score", "defteam_score",
    "play_type", "yards_gained", "penalty", "play_deleted", "aborted_play", "two_point_attempt",
    "qb_kneel", "qb_spike", "qb_scramble", "sack", "interception", "complete_pass",
    "incomplete_pass", "out_of_bounds", "fumble_lost", "kick_distance", "field_goal_result",
    "extra_point_result", "extra_point_attempt", "two_point_conv_result", "touchback", "return_yards", "kickoff_attempt", "punt_attempt",
    "home_team", "away_team", "total_home_score", "total_away_score", "drive",
]
CALL_BY_PLAY_TYPE = {"run": "run", "pass": "pass", "punt": "punt", "field_goal": "field_goal", "qb_kneel": "kneel", "qb_spike": "spike"}
KICKOFF_RECEIVE_SPOT = 75  # yardline_100 at the receiving team's own 25
MAX_RUNOFF_SECONDS = 200

Observation = Tuple[str, Dict[str, str], str]


def read_season(path: str) -> List[Dict[str, Any]]:
    """All regular-season rows of one season file, ordered by game then play."""
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=COLUMNS)
    rows = [row for row in table.to_pylist() if row["season_type"] == "REG"]
    rows.sort(key=lambda row: (row["game_id"], row["play_id"]))
    return rows


def _int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _skip_reason(row: Dict[str, Any]) -> Optional[str]:
    if row["play_type"] is None:
        return "not_a_play"
    if row["penalty"] == 1 or row["play_type"] == "no_play":
        return "penalty_or_no_play"
    if row["play_deleted"] == 1 or row["aborted_play"] == 1:
        return "deleted_or_aborted"
    if row["two_point_attempt"] == 1:
        return "two_point_attempt"
    if row["posteam"] is None:
        return "no_offense"
    return None


def iter_observations(rows: List[Dict[str, Any]], skips: Counter) -> Iterator[Observation]:
    """Yield (table, context, value) for every usable row. ``skips`` counts what was dropped and why."""
    for index, row in enumerate(rows):
        reason = _skip_reason(row)
        nxt = rows[index + 1] if index + 1 < len(rows) else None
        if row["game_id"] != (nxt["game_id"] if nxt else None):
            nxt = None
        play_type = row["play_type"]

        if play_type == "kickoff":
            yield from _kickoff(row, nxt, skips)
            elapsed = _runoff(row, nxt, skips)
            if elapsed is not None:
                yield ("elapsed", {"call": "kickoff", "sub": "normal"}, str(elapsed))
            continue
        if play_type == "extra_point":
            if row["extra_point_result"] in ("good", "failed", "blocked"):
                yield ("xp", {}, "make" if row["extra_point_result"] == "good" else "miss")
            else:
                skips["xp_result_missing"] += 1
            elapsed = _runoff(row, nxt, skips)
            if elapsed is not None:
                yield ("elapsed", {"call": "extra_point", "sub": "normal"}, str(elapsed))
            continue
        if reason is not None:
            skips[reason] += 1
            continue
        call = CALL_BY_PLAY_TYPE.get(play_type)
        if call is None:
            skips["other_play_type"] += 1
            continue
        if play_type == "run" and row["qb_scramble"] == 1:
            call = "pass"  # nflverse codes a QB scramble as a run; it is a dropback outcome here.
        if row["down"] is None or row["ydstogo"] is None or row["yardline_100"] is None or row["posteam_score"] is None:
            skips["missing_situation"] += 1
            continue

        ctx = situation(
            int(row["down"]),
            int(row["ydstogo"]),
            int(row["yardline_100"]),
            int(row["qtr"]),
            int(row["posteam_score"]) - int(row["defteam_score"] or 0),
        )
        yield ("call", ctx, call)
        sub = "incomplete" if (call == "pass" and row["incomplete_pass"] == 1) else "normal"
        elapsed = _runoff(row, nxt, skips)
        if elapsed is not None:
            yield ("elapsed", {"call": call, "sub": sub}, str(elapsed))

        if call == "field_goal":
            distance = _int(row["kick_distance"])
            if distance is None:
                skips["fg_distance_missing"] += 1
            else:
                made = "make" if row["field_goal_result"] == "made" else "miss"
                yield ("fg", {"fg": fg_bin(distance)}, made)
        elif call == "punt":
            gross = _int(row["kick_distance"])
            if gross is None or not 0 <= gross <= 100:
                skips["punt_distance_invalid"] += 1
            else:
                yield ("punt_gross", {"field": ctx["field"]}, str(gross))
                yield ("punt_return", {}, str(_int(row["return_yards"]) or 0))
        elif call in ("run", "pass"):
            yield from _offense_outcome(row, call, ctx, skips)


def _offense_outcome(row: Dict[str, Any], call: str, ctx: Dict[str, str], skips: Counter) -> Iterator[Observation]:
    fumble = "yes" if row["fumble_lost"] == 1 else "no"
    yield ("fumble", {"call": call}, fumble)
    if call == "run":
        if row["yards_gained"] is None:
            skips["run_yards_missing"] += 1
            return
        yield ("run_yards", ctx, str(int(row["yards_gained"])))
        return
    if row["sack"] == 1:
        pass_class, table, scope = "sack", "sack_yards", {"field": ctx["field"]}
    elif row["qb_scramble"] == 1:
        pass_class, table, scope = "scramble", "scramble_yards", {"field": ctx["field"]}
    elif row["interception"] == 1:
        pass_class, table, scope = "interception", None, None
    elif row["complete_pass"] == 1:
        pass_class, table, scope = "complete", "pass_yards", {"dist": ctx["dist"], "field": ctx["field"]}
    else:
        pass_class, table, scope = "incomplete", None, None
    yield ("pass_class", ctx, pass_class)
    if table is not None:
        if row["yards_gained"] is None:
            skips["pass_yards_missing"] += 1
            return
        yield (table, scope, str(int(row["yards_gained"])))


def _kickoff(row: Dict[str, Any], nxt: Optional[Dict[str, Any]], skips: Counter) -> Iterator[Observation]:
    """Touchback share, and the receiving spot as an implied return from the receiving team's 25.

    nflverse's ``return_yards`` on kickoffs does not measure from the 25 consistently (it matches
    the next play's spot in about 13% of returns), so the engine samples the observed spot itself.
    """
    if row["touchback"] == 1:
        yield ("kickoff_touchback", {}, "touchback")
        return
    yield ("kickoff_touchback", {}, "return")
    if nxt is None or nxt["posteam"] != row["posteam"] or nxt["down"] is None or nxt["yardline_100"] is None:
        skips["kickoff_spot_missing"] += 1
        return
    if int(nxt["qtr"]) != int(row["qtr"]):
        skips["kickoff_spot_period_change"] += 1
        return
    yield ("kickoff_implied_return", {}, str(KICKOFF_RECEIVE_SPOT - int(nxt["yardline_100"])))


def _runoff(row: Dict[str, Any], nxt: Optional[Dict[str, Any]], skips: Counter) -> Optional[int]:
    """Clock seconds from this play's start to the next play's start, within one period."""
    if nxt is None or nxt["qtr"] != row["qtr"] or nxt["play_type"] in (None, "no_play") or nxt["penalty"] == 1:
        return None
    if row["game_seconds_remaining"] is None or nxt["game_seconds_remaining"] is None:
        skips["runoff_missing_clock"] += 1
        return None
    elapsed = int(row["game_seconds_remaining"]) - int(nxt["game_seconds_remaining"])
    if not 0 <= elapsed <= MAX_RUNOFF_SECONDS:
        skips["runoff_out_of_range"] += 1
        return None
    return elapsed


def game_finals(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Final score per game: the maximum cumulative total seen for each side.

    Totals never decrease, so the maximum is the final even when a stray row sits out of sequence
    (nflverse 2023 MIA@KC has one at play 4092 that reports away 0; the published schedule has 14).
    """
    finals: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row["total_home_score"] is None or row["total_away_score"] is None:
            continue
        current = finals.get(row["game_id"])
        home, away = int(row["total_home_score"]), int(row["total_away_score"])
        if current is None:
            finals[row["game_id"]] = {
                "season": int(row["season"]),
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home": home,
                "away": away,
            }
        else:
            current["home"] = max(current["home"], home)
            current["away"] = max(current["away"], away)
    return finals
