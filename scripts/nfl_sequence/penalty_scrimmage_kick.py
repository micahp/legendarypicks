"""Bounded 2026 NFL Rule 14-4-8 scrimmage-kick penalty transitions.

This resolves a *single* supported foul on a punt or field-goal attempt.
It does not infer acceptance, election, possession, a kick return, or the
foul's timing. Kick-specific foul labels absent from the V1.7 model still
require their own occurrence model and rule registry.

Coordinates: before is from the kicking offense's perspective; after_play
is from the team possessing the ball after the kick's perspective.
"""
from __future__ import annotations

from penalty_enforcement import DownState, Enforcement, _half_distance

# Only V1.7 catalog labels with a meaningful scrimmage-kick application.
# The "illegal_block" category is too broad without a verified subtype.
KICK_FOUL_YARDS = {
    ("offense", "offensive_holding"): 10,
    ("offense", "illegal_formation"): 5,
    ("offense", "illegal_shift"): 5,
    ("offense", "illegal_motion"): 5,
    ("offense", "illegal_block"): 10,
    ("defense", "offside"): 5,
    ("defense", "defensive_holding"): 5,
}


def enforce_scrimmage_kick(*, before: DownState, after_play: DownState,
                           kick_type: str, offender: str, foul: str,
                           accepted: bool, enforcement_option: str | None = None,
                           receiver_retained: bool | None = None,
                           defense_team: str | None = None,
                           foul_during_kick: bool | None = None,
                           block_subtype: str | None = None,
                           defensive_holding_block_attempt: bool | None = None,
                           end_of_kick_yardline_100: float | None = None,
                           foul_spot_receiving_yardline_100: float | None = None,
                           kick_crossed_scrimmage_line: bool | None = None) -> Enforcement:
    """Enforce only the supported previous-spot or kicking-team add-on choice.

    Rule 14-4-8: an accepted foul from snap until the legal scrimmage kick
    ends normally enforces from the previous spot. For a kicking-team foul
    with receiving-team possession throughout the down, the receiving team
    can instead choose add-on at the dead-ball spot. More complex
    post-scrimmage-kick, end-zone, return-foul, score and double-foul cases
    remain explicit non-coverage, not fabricated transitions.
    """
    if kick_type not in ("punt", "field_goal"):
        raise ValueError("scrimmage kick requires punt or field_goal")
    if not isinstance(before, DownState) or not isinstance(after_play, DownState):
        raise ValueError("scrimmage kick requires explicit legal before/after states")
    if not isinstance(accepted, bool):
        raise ValueError("scrimmage kick foul requires explicit accept/decline decision")
    if not defense_team or defense_team == before.possession:
        raise ValueError("scrimmage kick requires explicit receiving team")
    if foul_during_kick is not True:
        raise ValueError("foul timing during legal scrimmage kick is not verified")
    key = (offender, foul)
    yards = KICK_FOUL_YARDS.get(key)
    if yards is None:
        raise ValueError(f"scrimmage-kick foul not supported by V1.7: {key}")
    if foul == "illegal_block" and block_subtype not in ("in_back", "above_waist"):
        raise ValueError("scrimmage-kick illegal block requires verified 10-yard subtype")
    if (foul == "defensive_holding" and
            defensive_holding_block_attempt is not True and
            enforcement_option != "post_scrimmage_kick"):
        raise ValueError("receiving-team holding needs verified block-attempt or PSK context")
    if not accepted:
        if enforcement_option not in (None, "decline"):
            raise ValueError("declined foul cannot have enforcement election")
        return Enforcement(after_play, False, 0, "declined scrimmage-kick foul",
                           play_counts=True, replay_down=False,
                           clock_action="retain_play_clock", enforcement_spot="dead_ball")

    if enforcement_option not in ("previous_spot", "receiving_dead_ball", "post_scrimmage_kick"):
        raise ValueError("accepted scrimmage kick foul requires explicit enforcement election")
    if enforcement_option == "post_scrimmage_kick":
        # Rule 14-4-8(4): Team B fouls during a scrimmage kick beyond
        # the line (excluding an attempt to block the kick) are enforced
        # from the less advantageous of end of kick and spot of foul.
        if offender != "defense" or receiver_retained is not True:
            raise ValueError("PSK requires a receiving-team foul with continuous receiving possession")
        if defensive_holding_block_attempt is True or kick_crossed_scrimmage_line is not True:
            raise ValueError("PSK excludes attempted kick blocks and requires kick beyond the line")
        if after_play.possession != defense_team:
            raise ValueError("PSK enforcement requires receiver to keep the ball")
        if (end_of_kick_yardline_100 is None or foul_spot_receiving_yardline_100 is None
                or not 0 < end_of_kick_yardline_100 < 100
                or not 0 < foul_spot_receiving_yardline_100 < 100):
            raise ValueError("PSK requires verified end-of-kick and foul spots in receiving coordinates")
        base = max(end_of_kick_yardline_100, foul_spot_receiving_yardline_100)
        new_yl, actual = _half_distance(base, "offense", yards)
        new_state = DownState(1, min(10., new_yl), new_yl, defense_team)
        return Enforcement(new_state, True, actual, "NFL 2026 Rule 14-4-8(4)",
                           play_counts=True, replay_down=False,
                           clock_action="retain_play_clock",
                           enforcement_spot="post_scrimmage_kick")

    if enforcement_option == "receiving_dead_ball":
        if offender != "offense":
            raise ValueError("receiving-team foul cannot use kicking-team add-on election")
        if receiver_retained is not True or after_play.possession != defense_team:
            raise ValueError("add-on requires verified receiving-team possession throughout down")
        # after_play is relative to the receiving offense, so advancement
        # toward the opposing goal decreases yardline_100.
        new_yl, actual = _half_distance(after_play.yardline_100, "defense", yards)
        new_state = DownState(1, min(10.0, new_yl), new_yl, defense_team)
        return Enforcement(new_state, True, actual, "NFL 2026 Rule 14-4-8(2)",
                           play_counts=True, replay_down=False,
                           clock_action="retain_play_clock",
                           enforcement_spot="receiving_dead_ball")
    # Previous-spot choice nullifies the kick. It may preserve the kicking
    # team's possession and even award an automatic first down.
    if offender == "offense":
        new_yl, actual = _half_distance(before.yardline_100, "offense", yards)
        new_down = before.down
        new_togo = before.to_go + actual
    else:
        new_yl, actual = _half_distance(before.yardline_100, "defense", yards)
        awarded_first = foul == "defensive_holding" or (
            actual >= before.to_go)
        new_down = 1 if awarded_first else before.down
        new_togo = min(10.0, new_yl) if awarded_first else before.to_go - actual
    new_state = DownState(new_down, new_togo, new_yl, before.possession)
    return Enforcement(new_state, True, actual, "NFL 2026 Rule 14-4-8",
                       play_counts=False, replay_down=(new_down == before.down),
                       automatic_first_down=new_down == 1 and before.down != 1,
                       clock_action="replay_down", enforcement_spot="previous")
