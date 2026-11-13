"""Link V1.7 single-foul proposals to the shared 16-label enforcement rules.

This is an explicit-ruling adapter, not an acceptance-choice model or a
full-game clock/statistics driver. The normal game engine remains opt-in.
"""
from dataclasses import asdict, dataclass

from penalty_enforcement import DownState, enforce
from penalty_scrimmage_kick import enforce_scrimmage_kick
from penalty_fit import Context
from penalty_sampler import PenaltyProposal, PenaltySampler


@dataclass(frozen=True)
class PenaltyTransition:
    state: DownState
    proposal: PenaltyProposal
    enforcement: dict | None


def transition(*, sampler: PenaltySampler, context: Context, game_seed: int,
               opportunity_key: str, before: DownState, after_play: DownState,
               accepted: bool | None = None, foul_yardline_100: float | None = None,
               pass_outcome: str | None = None,
               block_subtype: str | None = None,
               kick_type: str | None = None,
               kick_enforcement_option: str | None = None,
               receiver_retained: bool | None = None,
               foul_during_kick: bool | None = None,
               defensive_holding_block_attempt: bool | None = None) -> PenaltyTransition:
    """Sample and enforce if an explicit acceptance decision is available.

    Source-dependent inputs are mandatory for grounding, DPI, run holding,
    certain illegal blocks and completion-dependent roughing.
    """
    if (context.offense_team, context.down, context.to_go, context.yardline_100) != (
            before.possession, before.down, before.to_go, before.yardline_100):
        raise ValueError("penalty context does not match before-play state")
    proposal = sampler.propose(context, game_seed=game_seed, opportunity_key=opportunity_key)
    if not proposal.has_foul:
        if accepted is not None or foul_yardline_100 is not None or block_subtype is not None:
            raise ValueError("no-foul opportunity cannot have an adjudication")
        return PenaltyTransition(after_play, proposal, None)
    if not isinstance(accepted, bool):
        raise ValueError("a foul requires an explicit accept/decline decision")
    if context.phase == "pre_snap" and after_play != before:
        raise ValueError("a pre-snap foul cannot have a completed play")
    if context.phase == "live_ball" and context.play_class == "kick":
        result = enforce_scrimmage_kick(
            before=before, after_play=after_play, kick_type=kick_type,
            offender=proposal.committing_side, foul=proposal.foul_type,
            accepted=accepted, enforcement_option=kick_enforcement_option,
            receiver_retained=receiver_retained, defense_team=context.defense_team,
            foul_during_kick=foul_during_kick, block_subtype=block_subtype,
            defensive_holding_block_attempt=defensive_holding_block_attempt)
        return PenaltyTransition(result.state, proposal, asdict(result))
    result = enforce(
        before=before, after_play=after_play,
        phase=context.phase, play_class=context.play_class,
        offender=proposal.committing_side, foul=proposal.foul_type,
        accepted=accepted, foul_yardline_100=foul_yardline_100,
        pass_outcome=pass_outcome, block_subtype=block_subtype,
        defense_team=context.defense_team)
    return PenaltyTransition(result.state, proposal, asdict(result))
