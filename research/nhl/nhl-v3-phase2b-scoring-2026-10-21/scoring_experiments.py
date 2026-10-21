"""Controlled scoring and shot-quality variants for NHL V3 Phase 2B.

The Phase 2A simulator stays the source of truth. These adapters alter only
the conditional conversion probability or the training-only location pool.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, fields
import math
from typing import Dict, Iterator, Mapping, Sequence, Tuple

import stochastic_model as phase2a_model
from stochastic_model import FittedParameters, OUTCOME_CLASSES, sigmoid


Location = Tuple[float, float, str, str]
LocationKey = Tuple[str, str, str, str, str]
PeriodLocationKey = Tuple[str, str, str]


def _logit(probability: float) -> float:
    p = min(1.0 - 1e-12, max(1e-12, probability))
    return math.log(p / (1.0 - p))


@dataclass(frozen=True)
class ExperimentParameters(FittedParameters):
    """Phase 2A parameters with auditable pregame conversion offsets."""

    global_goal_logit_shift: float = 0.0
    state_location_pools: Mapping[LocationKey, Tuple[Location, ...]] = field(
        default_factory=dict, compare=False, repr=False)
    period_location_pools: Mapping[PeriodLocationKey, Tuple[Location, ...]] = field(
        default_factory=dict, compare=False, repr=False)
    state_location_counts: Mapping[LocationKey, int] = field(
        default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_base(cls, base: FittedParameters, *, global_goal_logit_shift: float = 0.0,
                  state_location_pools: Mapping[LocationKey, Tuple[Location, ...]] | None = None,
                  period_location_pools: Mapping[PeriodLocationKey, Tuple[Location, ...]] | None = None,
                  state_location_counts: Mapping[LocationKey, int] | None = None
                  ) -> "ExperimentParameters":
        values = {item.name: getattr(base, item.name) for item in fields(FittedParameters)}
        return cls(
            **values,
            global_goal_logit_shift=float(global_goal_logit_shift),
            state_location_pools=dict(state_location_pools or {}),
            period_location_pools=dict(period_location_pools or {}),
            state_location_counts=dict(state_location_counts or {}),
        )

    @staticmethod
    def _feature_shift(snapshot, side: str) -> float:
        key = f"goal_conversion_logit_shift_{side}"
        matches = [feature for feature in snapshot.features if feature.key == key]
        if not matches:
            return 0.0
        if len(matches) != 1:
            raise ValueError(f"SCORING_FEATURE_NOT_UNIQUE {snapshot.game_id}/{key}")
        return float(matches[0].value)

    def outcome_probabilities(self, snapshot, *, side: str, period: str,
                              strength: str, score_difference: int, remaining: int,
                              location_x: float | None, location_y: float | None,
                              shot_type: str, conditional: bool = True
                              ) -> Tuple[float, float, float, float]:
        probabilities = super().outcome_probabilities(
            snapshot, side=side, period=period, strength=strength,
            score_difference=score_difference, remaining=remaining,
            location_x=location_x, location_y=location_y,
            shot_type=shot_type, conditional=conditional)
        if not conditional:
            return probabilities
        p_sog = probabilities[2] + probabilities[3]
        if p_sog <= 0.0:
            return probabilities
        p_goal_given_sog = probabilities[3] / p_sog
        shift = self.global_goal_logit_shift + self._feature_shift(snapshot, side)
        adjusted_goal_probability = sigmoid(_logit(p_goal_given_sog) + shift)
        return (
            probabilities[0],
            probabilities[1],
            p_sog * (1.0 - adjusted_goal_probability),
            p_sog * adjusted_goal_probability,
        )

    def sample_location_context(self, rng, strength: str, *, period: str,
                                score_difference: int, remaining: int,
                                snapshot, side: str) -> Location:
        score = "TIED" if score_difference == 0 else "LEADING" if score_difference > 0 else "TRAILING"
        time_bucket = "LATE" if remaining <= 300 else "MIDDLE" if remaining <= 900 else "EARLY"
        state = phase2a_model.state_key(
            snapshot, self, side=side, period=period, strength=strength,
            score_difference=score_difference, remaining=remaining)
        attack_group = state[6]
        exact_key = (strength, period, score, time_bucket, attack_group)
        pool = self.state_location_pools.get(exact_key)
        if not pool:
            pool = self.period_location_pools.get((strength, period, attack_group))
        if not pool:
            pool = next((rows for level, rows in self.location_pools
                         if level == strength and rows), self.location_pool)
        if not pool:
            raise phase2a_model.SimulationInvariantError("ACCEPTED_LOCATION_POOL_EMPTY")
        x, y, shot_type, _ = pool[rng.randrange(len(pool))]
        return x, y, shot_type


class ContextLocationGameBuilder(phase2a_model._GameBuilder):
    """Phase 2A game builder with a state-aware, training-only location sampler."""

    def _shot(self, *, period_type: str, period_number: int, clock: int,
              duration: int, penalty_side: str | None, overtime: bool) -> None:
        rates = {}
        remaining = duration - clock
        period = "OT" if overtime else f"P{period_number}"
        for side in ("home", "away"):
            strength = self._strength(side, penalty_side, overtime=overtime)
            rates[side] = self.parameters.shot_rate(
                self.request.pregame, side=side, period=period, strength=strength,
                score_difference=self._score_difference(side), remaining=remaining,
                conditional=self.conditional)
        shooting_side = "home" if self.rng.random() * sum(rates.values()) < rates["home"] else "away"
        strength = self._strength(shooting_side, penalty_side, overtime=overtime)
        score_difference = self._score_difference(shooting_side)
        sampler = getattr(self.parameters, "sample_location_context", None)
        if sampler is None:
            x, y, shot_type = self.parameters.sample_location(self.rng, strength)
        else:
            x, y, shot_type = sampler(
                self.rng, strength, period=period,
                score_difference=score_difference, remaining=remaining,
                snapshot=self.request.pregame, side=shooting_side)
        probabilities = self.parameters.outcome_probabilities(
            self.request.pregame, side=shooting_side, period=period,
            strength=strength, score_difference=score_difference,
            remaining=remaining, location_x=x, location_y=y,
            shot_type=shot_type, conditional=self.conditional)
        draw = self.rng.random()
        outcome = OUTCOME_CLASSES[-1]
        cumulative = 0.0
        for category, probability in zip(OUTCOME_CLASSES, probabilities):
            cumulative += probability
            if draw < cumulative:
                outcome = category
                break
        self.attempt_number += 1
        attempt_id = self.attempt_number
        self.emit("SHOT_ATTEMPT", period_type, period_number, clock, shooting_side,
                  attempt_id=attempt_id, strength=strength, shot_type=shot_type,
                  shot_x=x, shot_y=y,
                  score_state="TIED" if score_difference == 0 else
                  "LEADING" if score_difference > 0 else "TRAILING")
        outcome_kind = {"BLOCKED": "SHOT_BLOCKED", "MISSED": "SHOT_MISSED",
                        "SAVED": "SHOT_SAVED", "GOAL": "GOAL"}[outcome]
        self.emit(outcome_kind, period_type, period_number, clock, shooting_side,
                  attempt_id=attempt_id, outcome=outcome,
                  on_target=int(outcome in {"SAVED", "GOAL"}),
                  counts_as_sog=int(outcome in {"SAVED", "GOAL"}),
                  shot_type=shot_type, shot_x=x, shot_y=y)
        self.outcomes[outcome] += 1
        if outcome in {"SAVED", "GOAL"}:
            self.sog[shooting_side] += 1
            self.period_sog[(period_type, period_number, shooting_side)] += 1
        if outcome == "GOAL":
            self.score[shooting_side] += 1
            self.reg_ot_score[shooting_side] += 1
            self.period_goals[(period_type, period_number, shooting_side)] += 1
            self.emit("SCORE_UPDATE", period_type, period_number, clock, shooting_side,
                      home_score=self.score["home"], away_score=self.score["away"])


@contextmanager
def use_context_location_builder() -> Iterator[None]:
    """Temporarily select the state-aware builder in a single-process research run."""
    original = phase2a_model._GameBuilder
    phase2a_model._GameBuilder = ContextLocationGameBuilder
    try:
        yield
    finally:
        phase2a_model._GameBuilder = original
