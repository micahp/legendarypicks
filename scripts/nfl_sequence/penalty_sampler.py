"""Isolated V1.7 penalty event proposal sampler.

This produces a *proposal*, never an enforced or credited penalty. No existing
V1.6 game-state path is touched. A future caller must feed proposals to a
rule-accurate enforcement engine, and refuse unsupported transitions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

from penalty_fit import Context, NO_FOUL, PenaltyModel


@dataclass(frozen=True)
class PenaltyProposal:
    opportunity_key: str
    phase: str
    outcome: str
    model_sha256: str | None
    source_sha256: str | None
    rng_namespace: str | None

    @property
    def has_foul(self) -> bool:
        return self.outcome != NO_FOUL

    @property
    def committing_side(self) -> str | None:
        return None if not self.has_foul else self.outcome.split(":", 1)[0]

    @property
    def foul_type(self) -> str | None:
        return None if not self.has_foul else self.outcome.split(":", 1)[1]


class PenaltySampler:
    """One independent deterministic draw per unique phase/opportunity.

    The stream is derived by SHA-256 from the seed, unique opportunity key,
    and pre-snap/live-ball phase. It cannot advance the existing SLC RNG.
    """

    def __init__(self, model: PenaltyModel | None, *, enabled: bool = False):
        self.enabled = bool(enabled)
        if self.enabled and (model is None or not model.fitted):
            raise ValueError("enabled V1.7 penalties require a fitted model")
        self.model = model
        self._model_hash = model.sha256() if self.enabled else None

    def propose(self, context: Context, *, game_seed: int, opportunity_key: str) -> PenaltyProposal:
        if not isinstance(opportunity_key, str) or not opportunity_key.strip():
            raise ValueError("unique opportunity key is required")
        if not isinstance(game_seed, int) or isinstance(game_seed, bool):
            raise ValueError("game_seed must be an integer")
        if not self.enabled:
            return PenaltyProposal(opportunity_key, context.phase, NO_FOUL, None, None, None)

        namespace = f"slc-v1.7/penalty/{context.phase}"
        material = f"{namespace}|{game_seed}|{opportunity_key}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        result = self.model.sample(context, rng)
        return PenaltyProposal(
            opportunity_key=opportunity_key, phase=context.phase, outcome=result,
            model_sha256=self._model_hash,
            source_sha256=self.model.source_sha256, rng_namespace=namespace)
