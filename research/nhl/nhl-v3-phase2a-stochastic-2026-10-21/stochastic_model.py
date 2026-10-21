"""Fitted, team-level stochastic NHL event generator for V3 Phase 2A.

This module depends only on the Phase 1 pregame request and generated-event
interfaces. Historical events are used by the offline fitter, never by
``simulate_game``. Every ordinary shot is emitted as an attempt followed by
exactly one explicit outcome event.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from typing import Iterable, Mapping, Sequence

import numpy as np

from prospective import GeneratedEvent, PregameSnapshot, SimulationRequest, assert_no_replay_input


LEVELS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("period", ("P1", "P2", "P3", "OT"), "P1"),
    ("strength", ("EVEN", "ADVANTAGE", "DISADVANTAGE", "EMPTY_NET", "UNKNOWN"), "EVEN"),
    ("score", ("TIED", "LEADING", "TRAILING"), "TIED"),
    ("time", ("EARLY", "MIDDLE", "LATE"), "EARLY"),
    ("game_time", ("EARLY", "MIDDLE", "LATE", "OVERTIME"), "EARLY"),
    ("venue", ("AWAY", "HOME"), "AWAY"),
    ("attack", ("LOW", "AVERAGE", "HIGH"), "AVERAGE"),
    ("defense", ("STRONG", "AVERAGE", "WEAK"), "AVERAGE"),
)
BASE_KEYS = tuple(item[0] for item in LEVELS)
OUTCOME_CLASSES = ("BLOCKED", "MISSED", "SAVED", "GOAL")
MAX_RATE_PER_MINUTE = 2.0


class SimulationInvariantError(ValueError):
    """A generated game violated event, clock, penalty, or score accounting."""


def level_for(name: str, value: str) -> tuple[str, ...]:
    return tuple(sorted((name, value)))


def _design_row(key: Sequence[str], dimensions: Sequence[tuple[str, tuple[str, ...], str]]) -> list[float]:
    if len(key) != len(dimensions):
        raise ValueError(f"MODEL_KEY_WIDTH {len(key)} != {len(dimensions)}")
    values = [1.0]
    for value, (_, levels, reference) in zip(key, dimensions):
        if value not in levels:
            value = reference
        values.extend(1.0 if value == level else 0.0
                      for level in levels if level != reference)
    return values


def _fit_poisson(exposure_counts: Mapping[tuple[str, ...], tuple[float, int]],
                 dimensions: Sequence[tuple[str, tuple[str, ...], str]],
                 ridge: float = 4.0) -> tuple[float, ...]:
    rows = [(key, exposure, count) for key, (exposure, count) in exposure_counts.items()
            if exposure > 0]
    if not rows:
        raise ValueError("POISSON_TRAINING_EXPOSURE_EMPTY")
    x = np.asarray([_design_row(key, dimensions) for key, _, _ in rows], dtype=float)
    exposure = np.asarray([row[1] for row in rows], dtype=float)
    counts = np.asarray([row[2] for row in rows], dtype=float)
    beta = np.zeros(x.shape[1], dtype=float)
    beta[0] = math.log(max(float(counts.sum() / exposure.sum()), 1e-8))
    penalty = np.eye(x.shape[1], dtype=float) * ridge
    penalty[0, 0] = 0.0
    for _ in range(80):
        eta = np.clip(x @ beta, -8.0, 3.0)
        mu = exposure * np.exp(eta)
        grad = x.T @ (counts - mu) - penalty @ beta
        hessian = x.T @ (x * mu[:, None]) + penalty
        step = np.linalg.solve(hessian, grad)
        beta += step
        if float(np.max(np.abs(step))) < 1e-9:
            break
    return tuple(float(value) for value in beta)


def _fit_logit(success_total: Mapping[tuple[str, ...], tuple[int, int]],
                dimensions: Sequence[tuple[str, tuple[str, ...], str]],
                ridge: float = 6.0) -> tuple[float, ...]:
    rows = [(key, success, total) for key, (success, total) in success_total.items()
            if total > 0]
    if not rows:
        raise ValueError("LOGIT_TRAINING_ROWS_EMPTY")
    x = np.asarray([_design_row(key, dimensions) for key, _, _ in rows], dtype=float)
    success = np.asarray([row[1] for row in rows], dtype=float)
    total = np.asarray([row[2] for row in rows], dtype=float)
    rate = min(1.0 - 1e-6, max(1e-6, float(success.sum() / total.sum())))
    beta = np.zeros(x.shape[1], dtype=float)
    beta[0] = math.log(rate / (1.0 - rate))
    penalty = np.eye(x.shape[1], dtype=float) * ridge
    penalty[0, 0] = 0.0
    for _ in range(100):
        eta = np.clip(x @ beta, -10.0, 10.0)
        p = 1.0 / (1.0 + np.exp(-eta))
        weights = np.maximum(total * p * (1.0 - p), 1e-8)
        grad = x.T @ (success - total * p) - penalty @ beta
        hessian = x.T @ (x * weights[:, None]) + penalty
        step = np.linalg.solve(hessian, grad)
        beta += step
        if float(np.max(np.abs(step))) < 1e-9:
            break
    return tuple(float(value) for value in beta)


def _predict_linear(beta: Sequence[float], key: Sequence[str],
                    dimensions: Sequence[tuple[str, tuple[str, ...], str]]) -> float:
    return float(np.dot(np.asarray(beta), np.asarray(_design_row(key, dimensions))))


def sigmoid(value: float) -> float:
    value = min(10.0, max(-10.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def score_level(score_difference: int) -> str:
    return "LEADING" if score_difference > 0 else "TRAILING" if score_difference < 0 else "TIED"


def time_level(seconds_remaining: int) -> str:
    return "LATE" if seconds_remaining <= 300 else "MIDDLE" if seconds_remaining <= 900 else "EARLY"


def game_time_level(period: str, seconds_remaining_in_period: int) -> str:
    if period == "OT":
        return "OVERTIME"
    if period not in {"P1", "P2", "P3"}:
        raise ValueError(f"UNSUPPORTED_GAME_TIME_PERIOD {period}")
    period_number = int(period[1])
    game_remaining = (3 - period_number) * 1200 + seconds_remaining_in_period
    return time_level(game_remaining)


def period_level(period_type: str, period_number: int) -> str:
    if period_type == "OT":
        return "OT"
    if period_type != "REG" or period_number not in (1, 2, 3):
        raise ValueError(f"UNSUPPORTED_REGULATION_PERIOD {period_type}/{period_number}")
    return f"P{period_number}"


def strength_level(manpower: object | None, shooting_side: str) -> str:
    if manpower is None:
        return "UNKNOWN"
    if shooting_side == "home":
        own, opponent, defending_goalie = manpower.home_skaters, manpower.away_skaters, manpower.away_goalie_present
    else:
        own, opponent, defending_goalie = manpower.away_skaters, manpower.home_skaters, manpower.home_goalie_present
    if not defending_goalie:
        return "EMPTY_NET"
    return "ADVANTAGE" if own > opponent else "DISADVANTAGE" if own < opponent else "EVEN"


def quality_level(value: float, sample_n: int, reference: float, *, defense: bool = False) -> str:
    if sample_n <= 0:
        return "AVERAGE"
    ratio = value / max(reference, 1e-6)
    if defense:
        return "WEAK" if ratio >= 1.10 else "STRONG" if ratio <= 0.90 else "AVERAGE"
    return "HIGH" if ratio >= 1.10 else "LOW" if ratio <= 0.90 else "AVERAGE"


def coordinate_features(x: float | None, y: float | None) -> tuple[str, str]:
    if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
        return "UNKNOWN", "UNKNOWN"
    # GameCenter rink coordinates are accepted only after the Phase 1 spatial gate.
    distance = math.sqrt((89.0 - abs(x)) ** 2 + y ** 2)
    angle = math.degrees(math.atan2(abs(y), max(89.0 - abs(x), 1.0)))
    distance_band = "NEAR" if distance < 12.0 else "MID" if distance < 25.0 else "FAR"
    angle_band = "CENTER" if angle < 15.0 else "ANGLE" if angle < 40.0 else "SHARP"
    return distance_band, angle_band


def _pregame_values(snapshot: PregameSnapshot) -> dict[str, float]:
    values = {feature.key: float(feature.value) for feature in snapshot.features
              if isinstance(feature.value, (float, int))}
    required = {
        "home_attack_sog_per_game", "home_attack_sog_n", "home_allowed_sog_per_game", "home_allowed_sog_n",
        "away_attack_sog_per_game", "away_attack_sog_n", "away_allowed_sog_per_game", "away_allowed_sog_n",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"PREGAME_TEAM_FEATURES_MISSING {missing}")
    return values


def state_key(snapshot: PregameSnapshot, parameters: "FittedParameters", *, side: str,
              period: str, strength: str, score_difference: int,
              remaining: int) -> tuple[str, ...]:
    values = _pregame_values(snapshot)
    opponent = "away" if side == "home" else "home"
    return (
        period,
        strength,
        score_level(score_difference),
        time_level(remaining),
        game_time_level(period, remaining),
        "HOME" if side == "home" else "AWAY",
        quality_level(values[f"{side}_attack_sog_per_game"],
                      int(values[f"{side}_attack_sog_n"]), parameters.sog_reference),
        quality_level(values[f"{opponent}_allowed_sog_per_game"],
                      int(values[f"{opponent}_allowed_sog_n"]), parameters.sog_reference,
                      defense=True),
    )


@dataclass(frozen=True)
class FittedParameters:
    fit_seasons: tuple[int, ...]
    poisson_coefficients: tuple[float, ...]
    sog_logit_coefficients: tuple[float, ...]
    block_logit_coefficients: tuple[float, ...]
    goal_logit_coefficients: tuple[float, ...]
    baseline_attempt_rate_per_minute: float
    baseline_outcome_probabilities: tuple[float, float, float, float]
    penalty_rate_per_minute: float
    shootout_goal_probability: float
    sog_reference: float
    rate_dimensions: tuple[tuple[str, tuple[str, ...], str], ...] = LEVELS
    goal_dimensions: tuple[tuple[str, tuple[str, ...], str], ...] = ()
    location_pool: tuple[tuple[float, float, str, str], ...] = ()
    location_pools: tuple[tuple[str, tuple[tuple[float, float, str, str], ...]], ...] = ()
    training_counts: tuple[tuple[str, int], ...] = ()

    def shot_rate(self, snapshot: PregameSnapshot, *, side: str, period: str,
                  strength: str, score_difference: int, remaining: int,
                  conditional: bool = True) -> float:
        if not conditional:
            return max(0.01, self.baseline_attempt_rate_per_minute)
        key = state_key(snapshot, self, side=side, period=period, strength=strength,
                        score_difference=score_difference, remaining=remaining)
        value = math.exp(min(3.0, max(-8.0, _predict_linear(
            self.poisson_coefficients, key, self.rate_dimensions))))
        return min(MAX_RATE_PER_MINUTE, max(0.01, value))

    def outcome_probabilities(self, snapshot: PregameSnapshot, *, side: str, period: str,
                              strength: str, score_difference: int, remaining: int,
                              location_x: float | None, location_y: float | None,
                              shot_type: str, conditional: bool = True) -> tuple[float, float, float, float]:
        if not conditional:
            return self.baseline_outcome_probabilities
        base_key = state_key(snapshot, self, side=side, period=period, strength=strength,
                             score_difference=score_difference, remaining=remaining)
        p_sog = sigmoid(_predict_linear(self.sog_logit_coefficients, base_key, self.rate_dimensions))
        p_block = sigmoid(_predict_linear(self.block_logit_coefficients, base_key, self.rate_dimensions))
        distance, angle = coordinate_features(location_x, location_y)
        goal_key = base_key + (distance, angle, shot_type)
        p_goal = sigmoid(_predict_linear(self.goal_logit_coefficients, goal_key, self.goal_dimensions))
        return ((1.0 - p_sog) * p_block,
                (1.0 - p_sog) * (1.0 - p_block),
                p_sog * (1.0 - p_goal),
                p_sog * p_goal)

    def sample_location(self, rng: random.Random, strength: str) -> tuple[float, float, str]:
        pool = self.location_pool
        for level, locations in self.location_pools:
            if level == strength and locations:
                pool = locations
                break
        if not pool:
            raise SimulationInvariantError("ACCEPTED_LOCATION_POOL_EMPTY")
        x, y, shot_type, _ = pool[rng.randrange(len(pool))]
        return x, y, shot_type

    def to_json(self) -> dict[str, object]:
        return {
            "model_name": "nhl_v3_phase2a_team_shot_scoring",
            "model_version": "1.0.0",
            "fit_seasons": list(self.fit_seasons),
            "poisson_coefficients": list(self.poisson_coefficients),
            "sog_logit_coefficients": list(self.sog_logit_coefficients),
            "block_logit_coefficients": list(self.block_logit_coefficients),
            "goal_logit_coefficients": list(self.goal_logit_coefficients),
            "rate_dimensions": [[n, list(c), r] for n, c, r in self.rate_dimensions],
            "goal_dimensions": [[n, list(c), r] for n, c, r in self.goal_dimensions],
            "baseline_attempt_rate_per_minute": self.baseline_attempt_rate_per_minute,
            "baseline_outcome_probabilities": list(self.baseline_outcome_probabilities),
            "penalty_rate_per_minute": self.penalty_rate_per_minute,
            "shootout_goal_probability": self.shootout_goal_probability,
            "sog_reference": self.sog_reference,
            "location_pool": [list(item) for item in self.location_pool],
            "location_pools": [[level, [list(item) for item in pool]]
                               for level, pool in self.location_pools],
            "training_counts": {key: value for key, value in self.training_counts},
        }

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> "FittedParameters":
        return cls(
            fit_seasons=tuple(int(value) for value in data["fit_seasons"]),
            poisson_coefficients=tuple(float(value) for value in data["poisson_coefficients"]),
            sog_logit_coefficients=tuple(float(value) for value in data["sog_logit_coefficients"]),
            block_logit_coefficients=tuple(float(value) for value in data["block_logit_coefficients"]),
            goal_logit_coefficients=tuple(float(value) for value in data["goal_logit_coefficients"]),
            baseline_attempt_rate_per_minute=float(data["baseline_attempt_rate_per_minute"]),
            baseline_outcome_probabilities=tuple(float(value) for value in data["baseline_outcome_probabilities"]),
            penalty_rate_per_minute=float(data["penalty_rate_per_minute"]),
            shootout_goal_probability=float(data["shootout_goal_probability"]),
            sog_reference=float(data["sog_reference"]),
            rate_dimensions=tuple((row[0], tuple(row[1]), row[2]) for row in data["rate_dimensions"]),
            goal_dimensions=tuple((row[0], tuple(row[1]), row[2]) for row in data["goal_dimensions"]),
            location_pool=tuple((float(r[0]), float(r[1]), str(r[2]), str(r[3])) for r in data["location_pool"]),
            location_pools=tuple((str(row[0]), tuple((float(r[0]), float(r[1]), str(r[2]), str(r[3]))
                                                      for r in row[1]))
                                 for row in data.get("location_pools", [])),
            training_counts=tuple(sorted((str(key), int(value)) for key, value in data["training_counts"].items())),
        )


GOAL_DIMENSIONS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    *LEVELS,
    ("distance", ("NEAR", "MID", "FAR", "UNKNOWN"), "MID"),
    ("angle", ("CENTER", "ANGLE", "SHARP", "UNKNOWN"), "ANGLE"),
    ("shot_type", ("WRIST", "SNAP", "SLAP", "BACKHAND", "TIP", "DEFLECTED", "WRAP", "OTHER", "UNKNOWN"), "WRIST"),
)


def fit_parameters(*, fit_seasons: Sequence[int],
                    rate_exposure_counts: Mapping[tuple[str, ...], tuple[float, int]],
                    sog_counts: Mapping[tuple[str, ...], tuple[int, int]],
                    block_counts: Mapping[tuple[str, ...], tuple[int, int]],
                    goal_counts: Mapping[tuple[str, ...], tuple[int, int]],
                    outcome_counts: Sequence[int], baseline_attempts: int,
                    baseline_exposure_minutes: float, penalty_calls: int,
                    penalty_exposure_minutes: float, shootout_goals: int,
                    shootout_attempts: int, sog_reference: float,
                    location_pool: Sequence[tuple[float, float, str, str]],
                    location_pools: Mapping[str, Sequence[tuple[float, float, str, str]]],
                    training_counts: Mapping[str, int]) -> FittedParameters:
    if sum(outcome_counts) <= 0 or baseline_attempts <= 0 or baseline_exposure_minutes <= 0:
        raise ValueError(
            "TRAINING_POPULATION_EMPTY "
            f"outcomes={sum(outcome_counts)} attempts={baseline_attempts} "
            f"exposure_minutes={baseline_exposure_minutes:.6f}")
    total = float(sum(outcome_counts))
    probabilities = tuple(float(value / total) for value in outcome_counts)
    return FittedParameters(
        fit_seasons=tuple(int(season) for season in fit_seasons),
        poisson_coefficients=_fit_poisson(rate_exposure_counts, LEVELS),
        sog_logit_coefficients=_fit_logit(sog_counts, LEVELS),
        block_logit_coefficients=_fit_logit(block_counts, LEVELS),
        goal_logit_coefficients=_fit_logit(goal_counts, GOAL_DIMENSIONS),
        baseline_attempt_rate_per_minute=baseline_attempts / baseline_exposure_minutes,
        baseline_outcome_probabilities=probabilities,
        penalty_rate_per_minute=(penalty_calls / penalty_exposure_minutes
                                 if penalty_exposure_minutes > 0 else 0.0),
        shootout_goal_probability=(shootout_goals / shootout_attempts
                                  if shootout_attempts else 0.30),
        sog_reference=float(sog_reference),
        goal_dimensions=GOAL_DIMENSIONS,
        location_pool=tuple(location_pool),
        location_pools=tuple((str(level), tuple(rows)) for level, rows in sorted(location_pools.items())),
        training_counts=tuple(sorted((str(key), int(value)) for key, value in training_counts.items())),
    )


@dataclass(frozen=True)
class SimulationResult:
    events: tuple[GeneratedEvent, ...]
    home_sog: int
    away_sog: int
    home_reg_ot_goals: int
    away_reg_ot_goals: int
    home_final_goals: int
    away_final_goals: int
    home_wins: bool
    period_sog: tuple[tuple[str, int, str, int], ...]
    period_goals: tuple[tuple[str, int, str, int], ...]
    penalty_count: int
    shot_outcomes: tuple[tuple[str, int], ...]


class _GameBuilder:
    def __init__(self, request: SimulationRequest, parameters: FittedParameters,
                 *, conditional: bool):
        self.request = request
        self.parameters = parameters
        self.conditional = conditional
        self.rng = random.Random(request.random_seed)
        self.home_id = request.pregame.home_team_id
        self.away_id = request.pregame.away_team_id
        self.score = {"home": 0, "away": 0}
        self.sog = {"home": 0, "away": 0}
        self.reg_ot_score = {"home": 0, "away": 0}
        self.events: list[GeneratedEvent] = []
        self.period_sog: Counter[tuple[str, int, str]] = Counter()
        self.period_goals: Counter[tuple[str, int, str]] = Counter()
        self.outcomes: Counter[str] = Counter()
        self.penalty_count = 0
        self.attempt_number = 0
        self.penalty_number = 0
        self.shootout_winner: str | None = None

    def emit(self, kind: str, period_type: str, period_number: int, clock: int,
             owner: str | None, **attrs: str | int | float | None) -> None:
        owner_id = None if owner is None else self.home_id if owner == "home" else self.away_id
        self.events.append(GeneratedEvent(
            sequence_index=len(self.events), event_kind=kind, period_type=period_type,
            period_number=period_number, period_clock_seconds=clock,
            event_owner_team_id=owner_id,
            generated_attributes=tuple(sorted(attrs.items())),
        ))

    def _score_difference(self, side: str) -> int:
        return self.score[side] - self.score["away" if side == "home" else "home"]

    def _strength(self, side: str, penalty_side: str | None, *, overtime: bool) -> str:
        if overtime or penalty_side is None:
            return "EVEN"
        return "DISADVANTAGE" if side == penalty_side else "ADVANTAGE"

    def _shot(self, *, period_type: str, period_number: int, clock: int,
              duration: int, penalty_side: str | None, overtime: bool) -> None:
        rates = {}
        remaining = duration - clock
        for side in ("home", "away"):
            strength = self._strength(side, penalty_side, overtime=overtime)
            rates[side] = self.parameters.shot_rate(
                self.request.pregame, side=side, period="OT" if overtime else f"P{period_number}",
                strength=strength, score_difference=self._score_difference(side),
                remaining=remaining, conditional=self.conditional)
        shooting_side = "home" if self.rng.random() * sum(rates.values()) < rates["home"] else "away"
        strength = self._strength(shooting_side, penalty_side, overtime=overtime)
        x, y, shot_type = self.parameters.sample_location(self.rng, strength)
        probs = self.parameters.outcome_probabilities(
            self.request.pregame, side=shooting_side,
            period="OT" if overtime else f"P{period_number}", strength=strength,
            score_difference=self._score_difference(shooting_side), remaining=remaining,
            location_x=x, location_y=y, shot_type=shot_type, conditional=self.conditional)
        draw = self.rng.random()
        outcome = OUTCOME_CLASSES[-1]
        cumulative = 0.0
        for category, probability in zip(OUTCOME_CLASSES, probs):
            cumulative += probability
            if draw < cumulative:
                outcome = category
                break
        self.attempt_number += 1
        attempt_id = self.attempt_number
        self.emit("SHOT_ATTEMPT", period_type, period_number, clock, shooting_side,
                  attempt_id=attempt_id, strength=strength, shot_type=shot_type,
                  shot_x=x, shot_y=y, score_state=score_level(self._score_difference(shooting_side)))
        outcome_kind = {"BLOCKED": "SHOT_BLOCKED", "MISSED": "SHOT_MISSED",
                        "SAVED": "SHOT_SAVED", "GOAL": "GOAL"}[outcome]
        self.emit(outcome_kind, period_type, period_number, clock, shooting_side,
                  attempt_id=attempt_id, outcome=outcome, on_target=int(outcome in {"SAVED", "GOAL"}),
                  counts_as_sog=int(outcome in {"SAVED", "GOAL"}), shot_type=shot_type,
                  shot_x=x, shot_y=y)
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


def simulate_game(request: SimulationRequest, parameters: FittedParameters,
                  *, conditional: bool = True, validate: bool = True) -> SimulationResult:
    """Generate one full game from a validated pregame snapshot and seed."""
    assert_no_replay_input(request)
    builder = _GameBuilder(request, parameters, conditional=conditional)
    penalty_side: str | None = None
    penalty_end: int | None = None
    for period_number in (1, 2, 3):
        builder.emit("PERIOD_START", "REG", period_number, 0, None, duration_seconds=1200)
        clock = 0.0
        penalty_side = None
        penalty_end = None
        while clock < 1200:
            clock_i = int(clock)
            remaining = 1200 - clock_i
            rates = {}
            for side in ("home", "away"):
                strength = builder._strength(side, penalty_side, overtime=False)
                rates[side] = parameters.shot_rate(
                    request.pregame, side=side, period=f"P{period_number}", strength=strength,
                    score_difference=builder._score_difference(side), remaining=remaining,
                    conditional=conditional)
            total_rate_sec = (rates["home"] + rates["away"]) / 60.0
            shot_at = clock + builder.rng.expovariate(total_rate_sec)
            penalty_at = math.inf
            expiry_at = float(penalty_end) if penalty_end is not None else math.inf
            if penalty_side is None and parameters.penalty_rate_per_minute > 0 and remaining > 120:
                penalty_at = clock + builder.rng.expovariate(parameters.penalty_rate_per_minute / 60.0)
                if penalty_at > 1080.0:
                    penalty_at = math.inf
            next_at = min(shot_at, penalty_at, expiry_at, 1200.0)
            if next_at >= 1200.0:
                clock = 1200.0
                break
            clock = next_at
            clock_i = int(clock)
            if expiry_at <= shot_at and expiry_at <= penalty_at:
                assert penalty_side is not None
                builder.emit("PENALTY_EXPIRED", "REG", period_number, clock_i, penalty_side,
                             penalty_id=builder.penalty_number, reason="TWO_MINUTES_ELAPSED")
                builder.emit("MANPOWER_CHANGE", "REG", period_number, clock_i, None,
                             state="EVEN_STRENGTH", penalty_id=builder.penalty_number)
                penalty_side = None
                penalty_end = None
            elif penalty_at <= shot_at:
                # One minor at a time; calls during an active penalty are outside this
                # explicitly limited generator.
                penalty_side = "home" if builder.rng.random() < 0.5 else "away"
                penalty_end = clock_i + 120
                builder.penalty_number += 1
                builder.penalty_count += 1
                builder.emit("PENALTY_CALLED", "REG", period_number, clock_i, penalty_side,
                             penalty_id=builder.penalty_number, duration_seconds=120,
                             penalty_class="MINOR")
                builder.emit("MANPOWER_CHANGE", "REG", period_number, clock_i, None,
                             state="POWER_PLAY", advantaged_team_id=(builder.away_id if penalty_side == "home" else builder.home_id),
                             penalty_id=builder.penalty_number)
            else:
                builder._shot(period_type="REG", period_number=period_number,
                              clock=clock_i, duration=1200, penalty_side=penalty_side,
                              overtime=False)
                if penalty_side is not None and builder.score["away" if penalty_side == "home" else "home"] > 0:
                    # The power-play goal condition is checked against the last generated
                    # outcome's owner below; scores themselves are authoritative here.
                    last_outcome = builder.events[-2]
                    if last_outcome.event_kind == "GOAL" and last_outcome.event_owner_team_id != (
                            builder.home_id if penalty_side == "home" else builder.away_id):
                        builder.emit("PENALTY_EXPIRED", "REG", period_number, clock_i, penalty_side,
                                     penalty_id=builder.penalty_number, reason="POWER_PLAY_GOAL")
                        builder.emit("MANPOWER_CHANGE", "REG", period_number, clock_i, None,
                                     state="EVEN_STRENGTH", penalty_id=builder.penalty_number)
                        penalty_side = None
                        penalty_end = None
        if penalty_side is not None:
            # Penalties are sampled only with at least two minutes remaining. Any
            # remainder can therefore expire before a regulation period ends.
            if penalty_end is not None and penalty_end <= 1200:
                builder.emit("PENALTY_EXPIRED", "REG", period_number, penalty_end, penalty_side,
                             penalty_id=builder.penalty_number, reason="TWO_MINUTES_ELAPSED")
                builder.emit("MANPOWER_CHANGE", "REG", period_number, penalty_end, None,
                             state="EVEN_STRENGTH", penalty_id=builder.penalty_number)
            penalty_side = None
            penalty_end = None
        builder.emit("PERIOD_END", "REG", period_number, 1200, None,
                     home_score=builder.score["home"], away_score=builder.score["away"])

    if builder.score["home"] == builder.score["away"]:
        builder.emit("OVERTIME_START", "OT", 4, 0, None, duration_seconds=300,
                     manpower="3v3", sudden_death=1)
        clock = 0.0
        overtime_goal = False
        while clock < 300:
            clock_i = int(clock)
            remaining = 300 - clock_i
            rates = {}
            for side in ("home", "away"):
                rates[side] = parameters.shot_rate(
                    request.pregame, side=side, period="OT", strength="EVEN",
                    score_difference=builder._score_difference(side), remaining=remaining,
                    conditional=conditional)
            total_rate_sec = (rates["home"] + rates["away"]) / 60.0
            next_at = clock + builder.rng.expovariate(total_rate_sec)
            if next_at >= 300:
                clock = 300.0
                break
            clock = next_at
            before = builder.score["home"] + builder.score["away"]
            builder._shot(period_type="OT", period_number=4, clock=int(clock), duration=300,
                          penalty_side=None, overtime=True)
            if builder.score["home"] + builder.score["away"] > before:
                overtime_goal = True
                break
        builder.emit("OVERTIME_END", "OT", 4, int(clock), None,
                     sudden_death_goal=int(overtime_goal))
        if builder.score["home"] == builder.score["away"]:
            _simulate_shootout(builder, parameters)

    winner = builder.shootout_winner or ("home" if builder.score["home"] > builder.score["away"] else "away")
    final_score = dict(builder.score)
    has_shootout = any(event.period_type == "SO" for event in builder.events)
    if has_shootout:
        final_score[winner] += 1
    if has_shootout:
        end_period_type, end_period_number = "SO", 5
        end_clock = max(event.period_clock_seconds for event in builder.events if event.period_type == "SO")
    elif any(event.period_type == "OT" for event in builder.events):
        end_period_type, end_period_number = "OT", 4
        end_clock = int(clock)
    else:
        end_period_type, end_period_number, end_clock = "REG", 3, 1200
    builder.emit("GAME_END", end_period_type, end_period_number, end_clock, None,
                 home_final_score=final_score["home"], away_final_score=final_score["away"],
                 **({"clock_semantics": "attempt_order"} if has_shootout else {}))
    result = SimulationResult(
        events=tuple(builder.events), home_sog=builder.sog["home"], away_sog=builder.sog["away"],
        home_reg_ot_goals=builder.reg_ot_score["home"], away_reg_ot_goals=builder.reg_ot_score["away"],
        home_final_goals=final_score["home"], away_final_goals=final_score["away"],
        home_wins=winner == "home",
        period_sog=tuple(sorted((ptype, number, side, count)
                                for (ptype, number, side), count in builder.period_sog.items())),
        period_goals=tuple(sorted((ptype, number, side, count)
                                  for (ptype, number, side), count in builder.period_goals.items())),
        penalty_count=builder.penalty_count,
        shot_outcomes=tuple(sorted(builder.outcomes.items())),
    )
    if validate:
        validate_simulation(request, result)
    return result


def simulate_many(pregame: PregameSnapshot, parameters: FittedParameters, count: int, *,
                  first_seed: int, conditional: bool = True,
                  validate: bool = True) -> tuple[SimulationResult, ...]:
    """Run a reproducible batch of independent seeds for one matchup snapshot."""
    if count <= 0:
        raise ValueError("SIMULATION_BATCH_COUNT_MUST_BE_POSITIVE")
    return tuple(simulate_game(SimulationRequest(pregame, first_seed + index), parameters,
                               conditional=conditional, validate=validate)
                 for index in range(count))


def _simulate_shootout(builder: _GameBuilder, parameters: FittedParameters) -> None:
    first = "home" if builder.rng.random() < 0.5 else "away"
    second = "away" if first == "home" else "home"
    goals = {"home": 0, "away": 0}
    attempts = {"home": 0, "away": 0}
    attempt_id = 0
    for round_number in range(1, 4):
        for side in (first, second):
            attempt_id += 1
            attempts[side] += 1
            scored = builder.rng.random() < parameters.shootout_goal_probability
            builder.emit("SHOOTOUT_ATTEMPT", "SO", 5, attempt_id, side,
                         attempt_id=attempt_id, round=round_number, counts_as_regular_sog=0,
                         clock_semantics="attempt_order")
            if scored:
                goals[side] += 1
                builder.emit("SHOOTOUT_GOAL", "SO", 5, attempt_id, side,
                             attempt_id=attempt_id, round=round_number, counts_as_regular_sog=0,
                             clock_semantics="attempt_order")
            else:
                builder.emit("SHOOTOUT_MISS", "SO", 5, attempt_id, side,
                             attempt_id=attempt_id, round=round_number, counts_as_regular_sog=0,
                             clock_semantics="attempt_order")
        left = 3 - round_number
        if abs(goals["home"] - goals["away"]) > left:
            builder.shootout_winner = "home" if goals["home"] > goals["away"] else "away"
            return
    sudden_round = 4
    while goals["home"] == goals["away"]:
        results = {}
        for side in (first, second):
            attempt_id += 1
            attempts[side] += 1
            scored = builder.rng.random() < parameters.shootout_goal_probability
            builder.emit("SHOOTOUT_ATTEMPT", "SO", 5, attempt_id, side,
                         attempt_id=attempt_id, round=sudden_round, counts_as_regular_sog=0,
                         clock_semantics="attempt_order")
            if scored:
                goals[side] += 1
                builder.emit("SHOOTOUT_GOAL", "SO", 5, attempt_id, side,
                             attempt_id=attempt_id, round=sudden_round, counts_as_regular_sog=0,
                             clock_semantics="attempt_order")
            else:
                builder.emit("SHOOTOUT_MISS", "SO", 5, attempt_id, side,
                             attempt_id=attempt_id, round=sudden_round, counts_as_regular_sog=0,
                             clock_semantics="attempt_order")
            results[side] = scored
        if results[first] != results[second]:
            builder.shootout_winner = "home" if goals["home"] > goals["away"] else "away"
            return
        sudden_round += 1
        if sudden_round > 10000:
            raise SimulationInvariantError("SHOOTOUT_FAILED_TO_RESOLVE")


def _attrs(event: GeneratedEvent) -> dict[str, str | int | float | None]:
    return dict(event.generated_attributes)


def validate_simulation(request: SimulationRequest, result: SimulationResult) -> None:
    """Recompute totals from generated events and fail on an illegal state."""
    home_id, away_id = request.pregame.home_team_id, request.pregame.away_team_id
    scores = {home_id: 0, away_id: 0}
    sog = {home_id: 0, away_id: 0}
    reg_ot_goals = {home_id: 0, away_id: 0}
    attempts: dict[int, tuple[int, str, str, int]] = {}
    outcomes: Counter[str] = Counter()
    period_sog: Counter[tuple[str, int, int]] = Counter()
    period_goals: Counter[tuple[str, int, int]] = Counter()
    previous_period_rank = 0
    previous_clock = -1
    previous_period: tuple[str, int] | None = None
    pending_penalties: dict[int, tuple[int, int, str]] = {}
    pending_penalty_transition: tuple[str, int] | None = None
    pending_attempt: int | None = None
    shootout_goals = {home_id: 0, away_id: 0}
    shootout_attempts: Counter[int] = Counter()
    shootout_rows: dict[int, tuple[int, int, bool | None]] = {}
    seen_game_end = False
    allowed = {"REG": (1, 2, 3), "OT": (4,), "SO": (5,)}
    rank = {("REG", 1): 1, ("REG", 2): 2, ("REG", 3): 3,
            ("OT", 4): 4, ("SO", 5): 5}
    shootout_pending: set[int] = set()
    periods_started: set[int] = set()
    periods_ended: set[int] = set()
    overtime_started = False
    overtime_ended = False
    pending_score_update: tuple[int, int, int] | None = None
    last_goal: tuple[str, int, int, int] | None = None
    expected_shootout_side: int | None = None
    regulation_score: tuple[int, int] | None = None
    overtime_end_clock: int | None = None
    game_end_scores: tuple[int, int] | None = None
    for index, event in enumerate(result.events):
        if event.sequence_index != index:
            raise SimulationInvariantError("EVENT_SEQUENCE_INDEX_NOT_CONTIGUOUS")
        period_key = (event.period_type, event.period_number)
        if event.period_type not in allowed or event.period_number not in allowed[event.period_type]:
            raise SimulationInvariantError(f"ILLEGAL_PERIOD {period_key}")
        current_rank = rank[period_key]
        if current_rank < previous_period_rank:
            raise SimulationInvariantError("PERIOD_ORDER_REGRESSION")
        duration = 1200 if event.period_type == "REG" else 300 if event.period_type == "OT" else 30000
        if not 0 <= event.period_clock_seconds <= duration:
            raise SimulationInvariantError(f"CLOCK_OUT_OF_RANGE {period_key}/{event.period_clock_seconds}")
        if period_key == previous_period and event.period_clock_seconds < previous_clock:
            raise SimulationInvariantError("CLOCK_REGRESSION")
        data = _attrs(event)
        if event.event_kind == "GAME_END":
            if seen_game_end or index != len(result.events) - 1:
                raise SimulationInvariantError("GAME_END_NOT_TERMINAL")
            seen_game_end = True
            game_end_scores = (int(data["home_final_score"]), int(data["away_final_score"]))
            if shootout_attempts:
                if (event.period_type, event.period_number) != ("SO", 5):
                    raise SimulationInvariantError("GAME_END_PERIOD_MISMATCH")
                if data.get("clock_semantics") != "attempt_order":
                    raise SimulationInvariantError("SHOOTOUT_GAME_END_CLOCK_SEMANTICS_MISSING")
            elif overtime_started:
                if (event.period_type, event.period_number, event.period_clock_seconds) != (
                        "OT", 4, overtime_end_clock):
                    raise SimulationInvariantError("GAME_END_OVERTIME_CLOCK_MISMATCH")
            elif (event.period_type, event.period_number, event.period_clock_seconds) != ("REG", 3, 1200):
                raise SimulationInvariantError("GAME_END_REGULATION_CLOCK_MISMATCH")
        elif seen_game_end:
            raise SimulationInvariantError("EVENT_AFTER_GAME_END")
        if event.event_owner_team_id not in {None, home_id, away_id}:
            raise SimulationInvariantError("EVENT_OWNER_NOT_IN_MATCHUP")
        if pending_score_update is not None and event.event_kind != "SCORE_UPDATE":
            raise SimulationInvariantError("GOAL_MISSING_IMMEDIATE_SCORE_UPDATE")
        if pending_attempt is not None and event.event_kind not in {
                "SHOT_BLOCKED", "SHOT_MISSED", "SHOT_SAVED", "GOAL"}:
            raise SimulationInvariantError("SHOT_OUTCOME_NOT_IMMEDIATE")
        if pending_penalty_transition is not None and event.event_kind != "MANPOWER_CHANGE":
            raise SimulationInvariantError("MANPOWER_CHANGE_NOT_IMMEDIATE")
        if event.event_kind == "PERIOD_START":
            if event.period_type != "REG" or event.period_clock_seconds != 0 or event.period_number in periods_started:
                raise SimulationInvariantError("REGULATION_PERIOD_START_INVALID")
            if event.period_number != len(periods_started) + 1:
                raise SimulationInvariantError("REGULATION_PERIOD_START_ORDER_INVALID")
            periods_started.add(event.period_number)
        elif event.event_kind == "PERIOD_END":
            if event.period_type != "REG" or event.period_number not in periods_started or \
                    event.period_clock_seconds != 1200 or event.period_number in periods_ended:
                raise SimulationInvariantError("REGULATION_PERIOD_END_INVALID")
            if pending_penalties or pending_penalty_transition is not None:
                raise SimulationInvariantError("REGULATION_ENDED_WITH_ACTIVE_PENALTY")
            periods_ended.add(event.period_number)
            if int(data["home_score"]) != scores[home_id] or int(data["away_score"]) != scores[away_id]:
                raise SimulationInvariantError("PERIOD_SCORE_SNAPSHOT_MISMATCH")
            if event.period_number == 3:
                regulation_score = (scores[home_id], scores[away_id])
        elif event.event_kind == "OVERTIME_START":
            if overtime_started or periods_ended != {1, 2, 3} or scores[home_id] != scores[away_id] or \
                    event.period_type != "OT" or event.period_number != 4 or event.period_clock_seconds != 0:
                raise SimulationInvariantError("OVERTIME_START_STATE_INVALID")
            if regulation_score is None or regulation_score[0] != regulation_score[1]:
                raise SimulationInvariantError("OVERTIME_STARTED_WITH_NON_TIED_REGULATION")
            overtime_started = True
        elif event.event_kind == "OVERTIME_END":
            if not overtime_started or overtime_ended or event.period_type != "OT" or event.period_number != 4:
                raise SimulationInvariantError("OVERTIME_END_STATE_INVALID")
            if scores[home_id] == scores[away_id] and event.period_clock_seconds != 300:
                raise SimulationInvariantError("TIED_OVERTIME_ENDED_BEFORE_FULL_CLOCK")
            if scores[home_id] != scores[away_id] and (last_goal is None or
                    last_goal[0] != "OT" or last_goal[1] != 4 or last_goal[3] != event.period_clock_seconds):
                raise SimulationInvariantError("OVERTIME_ENDED_WITHOUT_SUDDEN_DEATH_GOAL")
            overtime_end_clock = event.period_clock_seconds
            overtime_ended = True
        elif event.event_kind == "SCORE_UPDATE":
            if pending_score_update is None or (int(data["home_score"]), int(data["away_score"])) != \
                    (scores[home_id], scores[away_id]):
                raise SimulationInvariantError("SCORE_UPDATE_DOES_NOT_MATCH_GOALS")
            pending_score_update = None
        if event.event_kind == "SHOT_ATTEMPT":
            attempt_id = int(data["attempt_id"])
            if attempt_id in attempts:
                raise SimulationInvariantError("DUPLICATE_SHOT_ATTEMPT_ID")
            if event.event_owner_team_id is None or event.period_type == "SO":
                raise SimulationInvariantError("ORDINARY_SHOT_ATTEMPT_OWNER_OR_PERIOD_INVALID")
            attempts[attempt_id] = (event.event_owner_team_id, event.period_type,
                                    str(data["strength"]), event.period_clock_seconds)
            pending_attempt = attempt_id
        elif event.event_kind in {"SHOT_BLOCKED", "SHOT_MISSED", "SHOT_SAVED", "GOAL"}:
            attempt_id = int(data["attempt_id"])
            if attempt_id not in attempts:
                raise SimulationInvariantError("SHOT_OUTCOME_WITHOUT_ATTEMPT")
            owner, ptype, _, clock = attempts.pop(attempt_id)
            if (owner != event.event_owner_team_id or ptype != event.period_type or
                    clock != event.period_clock_seconds or pending_attempt != attempt_id):
                raise SimulationInvariantError("SHOT_OUTCOME_DOES_NOT_MATCH_ATTEMPT")
            pending_attempt = None
            label = str(data["outcome"])
            if event.event_kind != {"BLOCKED": "SHOT_BLOCKED", "MISSED": "SHOT_MISSED",
                                    "SAVED": "SHOT_SAVED", "GOAL": "GOAL"}.get(label):
                raise SimulationInvariantError("SHOT_OUTCOME_LABEL_MISMATCH")
            outcomes[label] += 1
            if label in {"SAVED", "GOAL"}:
                sog[owner] += 1
                period_sog[(event.period_type, event.period_number, owner)] += 1
                if int(data.get("counts_as_sog", 0)) != 1 or int(data.get("on_target", 0)) != 1:
                    raise SimulationInvariantError("ON_TARGET_SHOT_NOT_MARKED_AS_SOG")
            elif int(data.get("counts_as_sog", 0)) != 0 or int(data.get("on_target", 0)) != 0:
                raise SimulationInvariantError("OFF_TARGET_SHOT_MARKED_AS_SOG")
            if label == "GOAL":
                scores[owner] += 1
                reg_ot_goals[owner] += 1
                period_goals[(event.period_type, event.period_number, owner)] += 1
                last_goal = (event.period_type, event.period_number, owner, event.period_clock_seconds)
                pending_score_update = (scores[home_id], scores[away_id], event.period_clock_seconds)
        elif event.event_kind == "PENALTY_CALLED":
            penalty_id = int(data["penalty_id"])
            if event.period_type != "REG" or data.get("duration_seconds") != 120 or event.event_owner_team_id is None:
                raise SimulationInvariantError("LIMITED_PENALTY_RULE_VIOLATION")
            if pending_penalties:
                raise SimulationInvariantError("OVERLAPPING_PENALTY_UNSUPPORTED")
            pending_penalties[penalty_id] = (event.period_number, event.period_clock_seconds,
                                             "home" if event.event_owner_team_id == home_id else "away")
            pending_penalty_transition = ("POWER_PLAY", penalty_id)
            if data.get("penalty_class") != "MINOR":
                raise SimulationInvariantError("UNSUPPORTED_PENALTY_CLASS")
        elif event.event_kind == "PENALTY_EXPIRED":
            penalty_id = int(data["penalty_id"])
            active = pending_penalties.pop(penalty_id, None)
            if active is None or active[0] != event.period_number:
                raise SimulationInvariantError("PENALTY_EXPIRY_WITHOUT_ACTIVE_CALL")
            if event.event_owner_team_id != (home_id if active[2] == "home" else away_id):
                raise SimulationInvariantError("PENALTY_EXPIRY_TEAM_MISMATCH")
            elapsed = event.period_clock_seconds - active[1]
            reason = str(data.get("reason"))
            if reason == "TWO_MINUTES_ELAPSED" and elapsed != 120:
                raise SimulationInvariantError("PENALTY_DURATION_MISMATCH")
            if reason == "POWER_PLAY_GOAL" and not 0 <= elapsed <= 120:
                raise SimulationInvariantError("POWER_PLAY_RELEASE_TIME_INVALID")
            if reason == "POWER_PLAY_GOAL" and (last_goal is None or
                    last_goal != ("REG", event.period_number,
                                  away_id if active[2] == "home" else home_id,
                                  event.period_clock_seconds)):
                raise SimulationInvariantError("POWER_PLAY_RELEASE_WITHOUT_MATCHING_GOAL")
            if reason not in {"POWER_PLAY_GOAL", "TWO_MINUTES_ELAPSED"}:
                raise SimulationInvariantError("UNSUPPORTED_PENALTY_EXPIRY_REASON")
            pending_penalty_transition = ("EVEN_STRENGTH", penalty_id)
        elif event.event_kind == "MANPOWER_CHANGE":
            if pending_penalty_transition is None:
                raise SimulationInvariantError("MANPOWER_CHANGE_WITHOUT_PENALTY_TRANSITION")
            state, penalty_id = pending_penalty_transition
            if int(data.get("penalty_id", -1)) != penalty_id or data.get("state") != state:
                raise SimulationInvariantError("MANPOWER_CHANGE_STATE_MISMATCH")
            if state == "POWER_PLAY":
                expected_advantage = away_id if pending_penalties[penalty_id][2] == "home" else home_id
                if int(data.get("advantaged_team_id", -1)) != expected_advantage:
                    raise SimulationInvariantError("POWER_PLAY_ADVANTAGE_TEAM_MISMATCH")
            pending_penalty_transition = None
        elif event.event_kind == "SHOOTOUT_ATTEMPT":
            if event.period_type != "SO" or event.event_owner_team_id is None:
                raise SimulationInvariantError("SHOOTOUT_ATTEMPT_STATE_INVALID")
            shootout_attempts[event.event_owner_team_id] += 1
            attempt_id = int(data["attempt_id"])
            round_number = int(data["round"])
            if (event.period_clock_seconds != attempt_id or attempt_id != len(shootout_rows) + 1 or
                    data.get("clock_semantics") != "attempt_order"):
                raise SimulationInvariantError("SHOOTOUT_ATTEMPT_ORDER_INVALID")
            if round_number < 1 or data.get("counts_as_regular_sog") != 0:
                raise SimulationInvariantError("SHOOTOUT_ATTEMPT_ATTRIBUTES_INVALID")
            if not overtime_ended or scores[home_id] != scores[away_id]:
                raise SimulationInvariantError("SHOOTOUT_STARTED_OUTSIDE_TIED_OVERTIME")
            if expected_shootout_side is not None and event.event_owner_team_id != expected_shootout_side:
                raise SimulationInvariantError("SHOOTOUT_TEAMS_NOT_ALTERNATING")
            expected_shootout_side = away_id if event.event_owner_team_id == home_id else home_id
            if attempt_id in shootout_pending:
                raise SimulationInvariantError("DUPLICATE_SHOOTOUT_ATTEMPT_ID")
            shootout_pending.add(attempt_id)
            shootout_rows[attempt_id] = (event.event_owner_team_id, round_number, None)
        elif event.event_kind == "SHOOTOUT_GOAL":
            if event.period_type != "SO" or event.event_owner_team_id is None or \
                    data.get("clock_semantics") != "attempt_order":
                raise SimulationInvariantError("SHOOTOUT_GOAL_STATE_INVALID")
            shootout_goals[event.event_owner_team_id] += 1
            attempt_id = int(data["attempt_id"])
            if attempt_id not in shootout_pending or shootout_rows[attempt_id][0] != event.event_owner_team_id:
                raise SimulationInvariantError("SHOOTOUT_GOAL_WITHOUT_ATTEMPT")
            shootout_pending.remove(attempt_id)
            shootout_rows[attempt_id] = (*shootout_rows[attempt_id][:2], True)
        elif event.event_kind == "SHOOTOUT_MISS":
            attempt_id = int(data["attempt_id"])
            if (attempt_id not in shootout_pending or
                    shootout_rows[attempt_id][0] != event.event_owner_team_id or
                    data.get("counts_as_regular_sog") != 0 or
                    data.get("clock_semantics") != "attempt_order"):
                raise SimulationInvariantError("SHOOTOUT_MISS_WITHOUT_ATTEMPT")
            shootout_pending.remove(attempt_id)
            shootout_rows[attempt_id] = (*shootout_rows[attempt_id][:2], False)
        if pending_attempt is not None and event.event_kind in {
                "SHOT_BLOCKED", "SHOT_MISSED", "SHOT_SAVED", "GOAL"}:
            pending_attempt = None
        previous_period_rank = current_rank
        previous_period = period_key
        previous_clock = event.period_clock_seconds
    if not seen_game_end or attempts or shootout_pending or pending_attempt is not None:
        raise SimulationInvariantError("GAME_INCOMPLETE_OR_UNRESOLVED_SHOTS")
    if periods_started != {1, 2, 3} or periods_ended != {1, 2, 3}:
        raise SimulationInvariantError("REGULATION_PERIODS_INCOMPLETE")
    if pending_score_update is not None:
        raise SimulationInvariantError("GOAL_SCORE_UPDATE_MISSING_AT_END")
    if pending_penalties or pending_penalty_transition is not None:
        raise SimulationInvariantError("PENALTY_LEFT_ACTIVE_AT_GAME_END")
    if regulation_score is None:
        raise SimulationInvariantError("REGULATION_SCORE_MISSING")
    regulation_tied = regulation_score[0] == regulation_score[1]
    if regulation_tied != overtime_started or overtime_started != overtime_ended:
        raise SimulationInvariantError("REGULATION_OVERTIME_SEQUENCE_INVALID")
    if overtime_ended and (scores[home_id] == scores[away_id]) != bool(sum(shootout_attempts.values())):
        raise SimulationInvariantError("SHOOTOUT_OVERTIME_SEQUENCE_INVALID")
    final_scores = dict(scores)
    if sum(shootout_attempts.values()):
        if shootout_goals[home_id] == shootout_goals[away_id]:
            raise SimulationInvariantError("SHOOTOUT_DID_NOT_RESOLVE")
        final_scores[home_id if shootout_goals[home_id] > shootout_goals[away_id] else away_id] += 1
        ordered = [shootout_rows[key] for key in sorted(shootout_rows)]
        if any(row[2] is None for row in ordered) or len(ordered) % 2:
            raise SimulationInvariantError("SHOOTOUT_PAIR_INCOMPLETE")
        if any(ordered[index][0] == ordered[index + 1][0] for index in range(0, len(ordered), 2)):
            raise SimulationInvariantError("SHOOTOUT_PAIR_TEAMS_INVALID")
        if any(ordered[index][0] != ordered[index + 2][0]
               for index in range(0, len(ordered) - 2, 2)):
            raise SimulationInvariantError("SHOOTOUT_TURN_ORDER_INVALID")
        round_numbers = [row[1] for row in ordered]
        if round_numbers[:6] != [1, 1, 2, 2, 3, 3][:len(round_numbers[:6])]:
            raise SimulationInvariantError("SHOOTOUT_REGULATION_ROUNDS_INVALID")
        if len(ordered) < 6:
            if len(ordered) != 4 or round_numbers[-1] != 2 or \
                    abs(shootout_goals[home_id] - shootout_goals[away_id]) <= 1:
                raise SimulationInvariantError("SHOOTOUT_STOPPED_BEFORE_CLINCH_RULE")
        if len(ordered) >= 6 and round_numbers[5] != 3:
            raise SimulationInvariantError("SHOOTOUT_THREE_ROUND_SEQUENCE_INVALID")
        if len(ordered) > 6:
            first_six = ordered[:6]
            if sum(bool(row[2]) for row in first_six if row[0] == home_id) != \
                    sum(bool(row[2]) for row in first_six if row[0] == away_id):
                raise SimulationInvariantError("SHOOTOUT_SUDDEN_DEATH_BEFORE_THREE_ROUNDS")
            if round_numbers[6:] != [round for round in range(4, 4 + (len(ordered) - 6) // 2)
                                     for _ in (0, 1)]:
                raise SimulationInvariantError("SHOOTOUT_SUDDEN_DEATH_ROUNDS_INVALID")
            if shootout_goals[home_id] == shootout_goals[away_id] or \
                    ordered[-1][2] == ordered[-2][2]:
                raise SimulationInvariantError("SHOOTOUT_SUDDEN_DEATH_NOT_RESOLVED")
        elif shootout_goals[home_id] == shootout_goals[away_id]:
            raise SimulationInvariantError("SHOOTOUT_DID_NOT_RESOLVE")
    if game_end_scores is None or game_end_scores != (final_scores[home_id], final_scores[away_id]):
        raise SimulationInvariantError("GAME_END_SCORE_NOT_TRACEABLE_TO_EVENTS")
    if sog[home_id] != result.home_sog or sog[away_id] != result.away_sog:
        raise SimulationInvariantError("SOG_TOTAL_NOT_TRACEABLE_TO_EVENTS")
    if reg_ot_goals[home_id] != result.home_reg_ot_goals or reg_ot_goals[away_id] != result.away_reg_ot_goals:
        raise SimulationInvariantError("REG_OT_GOALS_NOT_TRACEABLE_TO_EVENTS")
    if final_scores[home_id] != result.home_final_goals or final_scores[away_id] != result.away_final_goals:
        raise SimulationInvariantError("FINAL_SCORE_NOT_TRACEABLE_TO_EVENTS")
    if result.home_wins != (final_scores[home_id] > final_scores[away_id]):
        raise SimulationInvariantError("WINNER_NOT_TRACEABLE_TO_FINAL_SCORE")
    if sum(outcomes.values()) != len([event for event in result.events if event.event_kind == "SHOT_ATTEMPT"]):
        raise SimulationInvariantError("SHOT_OUTCOME_ACCOUNTING_FAILURE")
    if dict(outcomes) != dict(result.shot_outcomes):
        raise SimulationInvariantError("SHOT_OUTCOME_SUMMARY_MISMATCH")
    reported_sog = {(ptype, number, home_id if side == "home" else away_id): count
                    for ptype, number, side, count in result.period_sog}
    if reported_sog != dict(period_sog):
        raise SimulationInvariantError("PERIOD_SOG_SUMMARY_MISMATCH")
    reported_goals = {(ptype, number, home_id if side == "home" else away_id): count
                      for ptype, number, side, count in result.period_goals}
    if reported_goals != dict(period_goals):
        raise SimulationInvariantError("PERIOD_GOAL_SUMMARY_MISMATCH")
