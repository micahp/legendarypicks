"""Connect a penalty proposal to the bounded enforcement engine.

This adapter is research infrastructure, not yet a full-game integration.
The caller must supply an adjudicated acceptance decision and, for DPI, the
verified foul spot; neither can be inferred from the occurrence model.
"""
from dataclasses import asdict, dataclass

from penalty_enforcement import DownState, enforce
from penalty_fit import Context
from penalty_sampler import PenaltyProposal, PenaltySampler


@dataclass(frozen=True)
class PenaltyTransition:
    state: DownState
    proposal: PenaltyProposal
    enforcement: dict | None


def transition(*, sampler: PenaltySampler, context: Context, game_seed: int,
               opportunity_key: str, before: DownState, after_play: DownState,
               accepted: bool | None = None, foul_yardline_100: int | None = None) -> PenaltyTransition:
    """Propose one foul and enforce it only with an explicit decision.

    An unsupported foul, phase, boundary, or missing adjudication raises
    instead of silently changing the play or treating a foul as no foul.
    """
    if (context.offense_team, context.down, context.to_go, context.yardline_100) != (
            before.possession, before.down, before.to_go, before.yardline_100):
        raise ValueError('penalty context does not match the before-play state')
    proposal = sampler.propose(context, game_seed=game_seed, opportunity_key=opportunity_key)
    if not proposal.has_foul:
        if accepted is not None or foul_yardline_100 is not None:
            raise ValueError('no-foul opportunity cannot have a penalty ruling')
        return PenaltyTransition(after_play, proposal, None)
    if not isinstance(accepted, bool):
        raise ValueError('a foul requires an explicit accept/decline decision')
    if context.phase == 'pre_snap':
        if after_play != before:
            raise ValueError('a pre-snap foul cannot have a completed play')
        phase = 'pre_snap'
    elif context.phase == 'live_ball' and context.play_class == 'dropback':
        phase = 'live_pass'
    else:
        raise ValueError('live-ball enforcement supports dropbacks only')
    result = enforce(before=before, after_play=after_play, phase=phase,
                     offender=proposal.committing_side, foul=proposal.foul_type,
                     accepted=accepted, foul_yardline_100=foul_yardline_100)
    return PenaltyTransition(result.state, proposal, asdict(result))
