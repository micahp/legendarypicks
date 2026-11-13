"""Deterministic, exploratory adjudication for V1.7 penalty-enabled full games.

This is a mechanics harness, NOT an estimated NFL acceptance/spot model.
Every synthetic ruling is marked as an assumption, and the game record must
remain research-only.  The source sample supplies the available play result
and runoff; a separate seeded stream supplies assumptions about foul spots.
Use PinnedPenaltyRulingBook for audited historical rulings.
"""
from __future__ import annotations

import hashlib
import random


RESEARCH_RULING_VERSION = "slc-v17-rule-assumptions-v0"


class ResearchPenaltyRulingPolicy:
    """Resolve the fitted 16-label foul vocabulary into a *hypothetical* ruling.

    Acceptance is a deterministic election policy, not an observed NFL
    conditional choice model.  No input from the target game's final score,
    future gamebook, or postgame stats may enter this function.
    """

    def __init__(self, game_seed: int):
        if type(game_seed) is not int:
            raise ValueError("research ruling seed must be an int")
        self.seed = game_seed

    def __call__(self, proposal, *, phase, state, event, after):
        if not proposal.has_foul:
            raise ValueError("ruling policy was called for a no-foul draw")
        offender, foul = proposal.outcome.split(":", 1)
        material = (f"{RESEARCH_RULING_VERSION}|{self.seed}|"
                    f"{proposal.phase}|{proposal.opportunity_key}|{proposal.outcome}")
        rng = random.Random(int.from_bytes(hashlib.sha256(
            material.encode("utf-8")).digest(), "big"))
        clock = state["clock"]
        runoff = 0 if phase == "pre_snap" else int(state.get("sampled_runoff_seconds", 0))
        runoff = max(0, min(clock, runoff))
        terminal = state.get("sampled_event_terminal")
        src_class = state.get("selected_play_class")
        is_kick = src_class == "kick"
        is_punt = event in ("punt", "blocked_punt")
        receiving_team_has_ball = (
            isinstance(after, dict) and after.get("offense") == state["defense"]
            and terminal in ("punt", "turnover"))
        # Decline a defensive foul on an offensive touchdown, rather than
        # canceling the offense's score. Decline an offensive foul on an
        # already-lost ball or safety so the defense retains the benefit.
        accepted = True
        if offender == "defense" and terminal == "touchdown":
            accepted = False
        if offender == "offense" and terminal in (
                "turnover", "turnover_on_downs", "safety"):
            accepted = False
        if is_punt and offender == "defense" and foul == "offside":
            accepted = state["togo"] <= 5
        # The player-selection source is independent of this model.
        ruling = {
            "accepted": accepted,
            "clock_runoff_seconds": runoff,
            "ruling_origin": "synthetic_research_policy",
            "ruling_version": RESEARCH_RULING_VERSION,
            "verified": False,
            "assumptions": [],
        }
        if not accepted:
            if is_kick:
                ruling.update(kick_enforcement_option=None,
                              foul_during_kick=True)
            return ruling

        if phase == "pre_snap":
            return ruling

        if is_kick:
            ruling["foul_during_kick"] = True
            ruling["assumptions"].append(
                "foul assumed during legal scrimmage kick")
            if offender == "offense" and is_punt and receiving_team_has_ball:
                ruling["kick_enforcement_option"] = "receiving_dead_ball"
                ruling["receiver_retained"] = True
                ruling["assumptions"].append(
                    "receiver assumed to retain uninterrupted possession")
            elif offender == "defense" and foul == "defensive_holding" and is_punt and receiving_team_has_ball:
                ruling["kick_enforcement_option"] = "post_scrimmage_kick"
                ruling["receiver_retained"] = True
                ruling["kick_crossed_scrimmage_line"] = True
                # Only a next-snap spot is known from the historical kick
                # transition. Use it as an *assumed* end-of-kick point for
                # this mechanics experiment, not as verified return tracking.
                spot = float(after["yl"])
                ruling["end_of_kick_yardline_100"] = spot
                ruling["foul_spot_receiving_yardline_100"] = min(
                    99., spot + rng.uniform(0., min(8., 99. - spot)))
                ruling["assumptions"].append(
                    "end-of-kick/foul spots inferred from next-snap spot; not historical evidence")
            else:
                ruling["kick_enforcement_option"] = "previous_spot"
                if offender == "defense" and foul == "defensive_holding":
                    ruling["defensive_holding_block_attempt"] = True
                    ruling["assumptions"].append(
                        "defensive holding assumed during kick-block attempt")
            if foul == "illegal_block":
                ruling["block_subtype"] = "above_waist"
                ruling["assumptions"].append(
                    "coarse illegal-block class assumed to be 10-yard above-waist")
            return ruling

        base = float(state["yl"])
        if foul == "roughing_passer":
            ruling["pass_outcome"] = (
                "complete" if event == "pass_complete" else "incomplete")
            if event == "pass_complete" and terminal == "touchdown":
                # A pass TD survives the offensive decision, but we do not
                # model the multiple enforcement elections on a try/kickoff.
                ruling["accepted"] = False
                ruling["assumptions"].append(
                    "roughing on touchdown declined; try/kickoff election not modeled")
        if foul == "defensive_pass_interference":
            gain = max(1., float(state.get("sampled_event_yards") or 0))
            depth = rng.uniform(1., min(35., max(5., gain + 12.)))
            ruling["foul_yardline_100"] = max(0., base - depth)
            ruling["assumptions"].append("hypothetical pass-interference foul location")
        elif foul == "intentional_grounding":
            # Half-distance enforcement can leave a snap inside the last
            # yard of the offense's own territory. Never move the alleged
            # passer release point *ahead* of that snap with a hard 99 cap.
            room_to_goal = 100. - base
            release_depth = rng.uniform(0., min(7., 0.9 * room_to_goal))
            ruling["foul_yardline_100"] = base + release_depth
            ruling["assumptions"].append(
                "hypothetical passer release spot; own-end-zone safety not generated")
        elif foul in ("offensive_holding", "illegal_block"):
            if foul == "illegal_block":
                ruling["block_subtype"] = "above_waist"
                ruling["assumptions"].append(
                    "coarse illegal-block class assumed to be 10-yard above-waist")
            if foul == "illegal_block" or src_class == "run":
                signed = rng.uniform(-3., 5.)
                ruling["foul_yardline_100"] = min(99., max(1., base - signed))
                ruling["assumptions"].append("hypothetical foul spot relative to LOS")
        return ruling
