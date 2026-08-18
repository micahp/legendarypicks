"""Shared helpers for the NFL mock-draft package."""
import json
from typing import Optional, Tuple

from fastapi.responses import JSONResponse
from ppr_scoring import STAT_IDS, normalize_stats


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status)


def _device_id(x_device_id: Optional[str]) -> Optional[str]:
    """Copy of ``ufc_picks.py:84`` — trim, empty means None."""
    if not x_device_id:
        return None
    device_id = x_device_id.strip()
    return device_id or None


def _compute_round_and_pick(pick_count: int, teams: int) -> Tuple[int, int]:
    """Given total picks made and number of teams, return (current_round, current_pick).

    Round is 1-indexed, pick is 1-indexed within the round (snake draft).
    If 0 picks have been made, returns (1, 1).
    If all picks are made, returns (rounds, teams) — the draft is complete.
    """
    if pick_count == 0:
        return 1, 1
    # Round number: which round does the NEXT pick belong to?
    current_round = (pick_count // teams) + 1
    # Pick within round: remainder gives position
    remainder = pick_count % teams
    if remainder == 0:
        # Just finished a round — next pick is first of next round
        current_pick = teams
    else:
        current_pick = remainder
    return current_round, current_pick


def _named_stat_line(raw_json, *, include_actual_first_downs=False):
    """Normalize a stored ESPN stat map into the overlay's stable vocabulary."""
    if not raw_json:
        return None
    try:
        stats = normalize_stats(json.loads(raw_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not stats:
        return None
    get = lambda key: stats.get(STAT_IDS[key])
    completion_pct = get("completion_pct")
    if completion_pct is not None and abs(completion_pct) <= 1:
        completion_pct *= 100
    return {
        "games": get("games"),
        "pass_att": get("pass_att"),
        "pass_cmp": get("pass_cmp"),
        "pass_yds": get("pass_yds"),
        "pass_td": get("pass_td"),
        "interceptions": get("interceptions"),
        "completion_pct": completion_pct,
        "sacks": get("sacks"),
        "rush_att": get("rush_att"),
        "rush_yds": get("rush_yds"),
        "rush_td": get("rush_td"),
        "receptions": get("receptions"),
        "targets": get("targets"),
        "rec_yds": get("rec_yds"),
        "rec_td": get("rec_td"),
        "fumbles": get("fumbles"),
        "fumbles_lost": get("fumbles_lost"),
        # ESPN's prior-season total map uses these measured IDs. Its fantasy
        # projection map shifts the extension IDs for some positions, so the
        # projection contract stays honestly null until that schema is
        # independently named and validated.
        "passing_first_downs": (
            get("passing_first_downs") if include_actual_first_downs else None
        ),
        "rushing_first_downs": (
            get("rushing_first_downs") if include_actual_first_downs else None
        ),
        "receiving_first_downs": (
            get("receiving_first_downs") if include_actual_first_downs else None
        ),
        "qbr": None,
        "passer_rating": None,
        "adj_qbr": None,
        "fg_att": get("fg_att"),
        "fg_made": get("fg_made"),
        "xp_att": get("xp_att"),
        "xp_made": get("xp_made"),
        "def_td": get("def_td"),
        "def_int": get("def_int"),
        "def_sack": get("def_sack"),
        "def_fumble_rec": get("def_fumble_rec"),
        "def_points_allowed": get("def_points_allowed"),
        "def_yds_allowed": get("def_yds_allowed"),
    }


def _missing_picks(pick_numbers):
    """Which pick numbers are absent from a draft that claims to have got this far.

    Picks arrive in batches over the network and the client's append is
    best-effort, so a dropped batch leaves a hole: [1,2,3,7,8,9] with nothing
    anywhere saying 6 picks never made it.  `INSERT OR IGNORE` on
    (draft_id, pick_no) means the hole is permanent -- later batches still
    insert, so no error surfaces on either side.

    Reported against the highest pick actually saved, not against the full
    180: a draft abandoned at pick 40 is incomplete, not holed, and calling
    those two the same thing would make the field useless.
    """
    if not pick_numbers:
        return []
    saved = set(pick_numbers)
    return [n for n in range(1, max(saved) + 1) if n not in saved]