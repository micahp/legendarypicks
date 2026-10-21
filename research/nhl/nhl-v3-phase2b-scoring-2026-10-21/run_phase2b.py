#!/usr/bin/env python3
"""Diagnose NHL V3 scoring and compare isolated Phase 2B candidates.

Selection is restricted to the forward 2021 development season (fit 2018-2020).
The exposed 2022 holdout is read only as historical Phase 2A evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
import pickle
from pathlib import Path
import random
import statistics
import sys
import time as walltime
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PHASE1 = REPO_ROOT / "research/nhl/nhl-v3-phase1-replay-2026-10-21"
PHASE2A = REPO_ROOT / "research/nhl/nhl-v3-phase2a-stochastic-2026-10-21"
for path in (PHASE1, PHASE2A):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_phase2a as phase2a  # noqa: E402
import stochastic_model as phase2a_model  # noqa: E402
from prospective import PregameFeature  # noqa: E402
from replay_model import SOG_EVENTS, SHOT_EVENTS, parse_situation_code  # noqa: E402
from scoring_experiments import (  # noqa: E402
    ExperimentParameters,
    Location,
    LocationKey,
    PeriodLocationKey,
    use_context_location_builder,
)
from stochastic_model import (  # noqa: E402
    FittedParameters,
    _predict_linear,
    coordinate_features,
    score_level,
    sigmoid,
)


FIT_SEASONS = (2018, 2019, 2020)
DEVELOPMENT_SEASONS = (2021,)
HISTORICAL_EXPOSED_SEASONS = (2022,)
SAMPLE_SEED = 20261021
ROLLING_WINDOW = 10
ROLLING_PRIOR_GAMES = 10.0
LOCATION_EXACT_CAPACITY = 400
LOCATION_PERIOD_CAPACITY = 800
LOCATION_EXACT_MINIMUM = 150
LOCATION_PERIOD_MINIMUM = 200


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(encoded)


def _capture_development_fold(bundle, snapshots, canonical):
    captured = {}
    original_fit = phase2a.fit_parameters

    def capture_fit(*args, **kwargs):
        captured["goal_counts"] = dict(kwargs["goal_counts"])
        fitted = original_fit(*args, **kwargs)
        captured["fitted_goal_parameters"] = fitted.goal_logit_coefficients
        captured["goal_dimensions"] = fitted.goal_dimensions
        return fitted

    phase2a.fit_parameters = capture_fit
    try:
        fold = phase2a._build_fold(bundle, snapshots, canonical,
                                   FIT_SEASONS, DEVELOPMENT_SEASONS)
    finally:
        phase2a.fit_parameters = original_fit
    if fold.parameters is None or "goal_counts" not in captured:
        raise RuntimeError("DEVELOPMENT_FIT_CAPTURE_FAILED")
    return fold, captured


def _population_conversion_shift(parameters: FittedParameters,
                                 goal_counts: Mapping[Tuple[str, ...], Tuple[int, int]],
                                 shrinkage: float) -> Dict[str, float]:
    n_on_target = sum(int(row[1]) for row in goal_counts.values())
    observed_goals = sum(int(row[0]) for row in goal_counts.values())
    if n_on_target <= 0:
        raise ValueError("TRAINING_ON_TARGET_POPULATION_EMPTY")
    scored = []
    predicted_goals = 0.0
    for key, (goals, attempts) in goal_counts.items():
        p_goal = sigmoid(_predict_linear(parameters.goal_logit_coefficients,
                                         key, parameters.goal_dimensions))
        scored.append((p_goal, int(attempts)))
        predicted_goals += p_goal * int(attempts)
    observed_rate = observed_goals / n_on_target
    predicted_rate = predicted_goals / n_on_target
    if not 0.0 < observed_rate < 1.0 or not 0.0 < predicted_rate < 1.0:
        raise ValueError("TRAINING_CONVERSION_RATE_OUT_OF_RANGE")
    target = observed_rate
    low, high = -4.0, 4.0
    for _ in range(80):
        middle = (low + high) / 2.0
        mean_probability = sum(sigmoid(math.log(p / (1.0 - p)) + middle) * n
                               for p, n in scored) / n_on_target
        if mean_probability < target:
            low = middle
        else:
            high = middle
    raw_shift = (low + high) / 2.0
    return {
        "training_on_target_events": n_on_target,
        "training_goals": observed_goals,
        "training_observed_goal_rate": observed_rate,
        "training_unadjusted_predicted_goal_rate": predicted_rate,
        "raw_logit_intercept_shift": raw_shift,
        "fixed_shrinkage": shrinkage,
        "applied_logit_intercept_shift": raw_shift * shrinkage,
    }


def _with_goal_offsets(games, offsets: Mapping[str, Tuple[float, float]], *,
                       source_kind: str, source_sha256: str,
                       source_label: str, available_at_start: bool = False):
    adjusted = []
    feature_meta = {}
    for game in games:
        pair = offsets.get(game.definition.game_id)
        if pair is None:
            raise ValueError(f"PREGAME_SCORING_OFFSET_MISSING {game.definition.game_id}/{source_label}")
        if available_at_start:
            available = game.snapshot.scheduled_start_utc
        else:
            previous_date = date.fromisoformat(game.definition.game_date) - timedelta(days=1)
            available = datetime.combine(previous_date, time(23, 59, 59), tzinfo=timezone.utc)
        features = list(game.snapshot.features)
        for side, value in zip(("home", "away"), pair):
            features.append(PregameFeature(
                key=f"goal_conversion_logit_shift_{side}", value=float(value),
                available_at_utc=available, source_kind=source_kind,
                source_key=f"{source_label}:{game.definition.game_id}:{side}",
                source_sha256=source_sha256, quality_disposition="ACCEPT"))
        snapshot = replace(game.snapshot, features=tuple(features))
        adjusted.append(replace(game, snapshot=snapshot))
        feature_meta[game.definition.game_id] = {
            "home_logit_shift": float(pair[0]),
            "away_logit_shift": float(pair[1]),
            "feature_available_at_utc": available.isoformat(),
            "scheduled_start_utc": game.snapshot.scheduled_start_utc.isoformat(),
        }
    for game in adjusted:
        if any(f.available_at_utc > game.snapshot.scheduled_start_utc for f in game.snapshot.features):
            raise ValueError(f"PREGAME_SCORING_FEATURE_LOOKAHEAD {game.definition.game_id}")
    return adjusted, feature_meta


def _rolling_goal_offsets(bundle, canonical, heldout_games):
    fit_definitions = [game for game in bundle.games.values()
                       if game.season in FIT_SEASONS and game.score_disposition == "ACCEPT"]
    fit_total = 0
    for game in fit_definitions:
        row = canonical.get(game.game_id)
        if row is None:
            raise ValueError(f"ROLLING_GOAL_CANONICAL_MISSING {game.game_id}")
        fit_total += row.home_goals_model_target + row.away_goals_model_target
    league_goal_mean = fit_total / (2.0 * len(fit_definitions))
    by_date = defaultdict(list)
    for game in bundle.games.values():
        if game.season <= 2021 and game.score_disposition == "ACCEPT":
            by_date[game.game_date].append(game)
    history = defaultdict(lambda: deque(maxlen=ROLLING_WINDOW))
    eval_ids = {game.definition.game_id for game in heldout_games}
    offsets = {}
    metadata = {}

    def smooth(team_id, component):
        rows = list(history[team_id])
        values = [row[component] for row in rows]
        rate = (sum(values) + ROLLING_PRIOR_GAMES * league_goal_mean) / (
            len(values) + ROLLING_PRIOR_GAMES)
        return rate, len(rows), rows[-1][2] if rows else None

    for game_date in sorted(by_date):
        same_day = sorted(by_date[game_date], key=lambda item: item.game_id)
        for definition in same_day:
            if definition.game_id not in eval_ids:
                continue
            row = canonical.get(definition.game_id)
            if row is None:
                raise ValueError(f"ROLLING_GOAL_EVAL_CANONICAL_MISSING {definition.game_id}")
            home_gf, home_n, home_last = smooth(definition.home_team_id, 0)
            away_ga, away_n, away_last = smooth(definition.away_team_id, 1)
            away_gf, away_gn, away_last_for = smooth(definition.away_team_id, 0)
            home_ga, home_gn, home_last_against = smooth(definition.home_team_id, 1)
            home_shift = math.log(home_gf / away_ga)
            away_shift = math.log(away_gf / home_ga)
            offsets[definition.game_id] = (home_shift, away_shift)
            metadata[definition.game_id] = {
                "home_attack_prior_games": home_n,
                "home_defense_prior_games": home_gn,
                "away_attack_prior_games": away_gn,
                "away_defense_prior_games": away_n,
                "home_attack_rate": home_gf,
                "away_defense_allowed_rate": away_ga,
                "away_attack_rate": away_gf,
                "home_defense_allowed_rate": home_ga,
                "home_last_source_game": home_last,
                "away_defense_last_source_game": away_last,
                "away_last_source_game": away_last_for,
                "home_defense_last_source_game": home_last_against,
                "league_prior_goal_mean": league_goal_mean,
            }
        # Same-date results become available only to later dates.
        for definition in same_day:
            row = canonical.get(definition.game_id)
            if row is None:
                raise ValueError(f"ROLLING_GOAL_HISTORY_CANONICAL_MISSING {definition.game_id}")
            history[definition.home_team_id].append(
                (row.home_goals_model_target, row.away_goals_model_target, definition.game_id))
            history[definition.away_team_id].append(
                (row.away_goals_model_target, row.home_goals_model_target, definition.game_id))
    if set(offsets) != eval_ids:
        raise ValueError(f"ROLLING_GOAL_OFFSET_COVERAGE {len(offsets)}/{len(eval_ids)}")
    return offsets, metadata, league_goal_mean


def _v2_offsets_from_canonical(fold, canonical, heldout_games):
    ratings = fold.v2_model.ratings()
    offsets = {}
    metadata = {}
    for game in heldout_games:
        row = canonical[game.definition.game_id]
        home_rating = ratings.get(row.home_team, {"attack": 0.0, "defence": 0.0})
        away_rating = ratings.get(row.away_team, {"attack": 0.0, "defence": 0.0})
        home_shift = float(home_rating["attack"] - away_rating["defence"])
        away_shift = float(away_rating["attack"] - home_rating["defence"])
        offsets[game.definition.game_id] = (home_shift, away_shift)
        metadata[game.definition.game_id] = {
            "home_attack_log_strength": float(home_rating["attack"]),
            "away_defense_log_strength": float(away_rating["defence"]),
            "away_attack_log_strength": float(away_rating["attack"]),
            "home_defense_log_strength": float(home_rating["defence"]),
            "home_logit_shift": home_shift,
            "away_logit_shift": away_shift,
        }
    return offsets, metadata


def _stable_key_seed(key: object, seed: int) -> int:
    digest = hashlib.sha256(repr(key).encode("utf-8")).digest()
    return seed + int.from_bytes(digest[:4], "big")


def _reservoir_add(pool_map, count_map, rng_map, key, row, capacity, *, seed):
    count_map[key] += 1
    pool = pool_map.setdefault(key, [])
    if len(pool) < capacity:
        pool.append(row)
        return
    rng = rng_map.setdefault(key, random.Random(_stable_key_seed(key, seed)))
    index = rng.randrange(count_map[key])
    if index < capacity:
        pool[index] = row


def _empty_event_metric():
    return {
        "attempts": 0, "observed_sog": 0, "expected_sog": 0.0,
        "sog_brier_sum": 0.0, "sog_log_loss_sum": 0.0,
        "on_target_events": 0, "observed_goals": 0, "expected_goals": 0.0,
        "goal_brier_sum": 0.0, "goal_log_loss_sum": 0.0,
        "multiclass_brier_sum": 0.0, "multiclass_log_loss_sum": 0.0,
    }


def _scan_training_and_development(bundle, fold, snapshots, variants):
    """Recount accepted PBP outcomes and build location pools from fit seasons only."""
    fit_ids = {game_id for game_id, game in bundle.games.items()
               if game.season in FIT_SEASONS}
    eval_games = {game.definition.game_id: game for game in fold.heldout_games}
    eval_ids = set(eval_games)
    selected_ids = fit_ids | eval_ids
    actual = {game_id: {
        "attempts": Counter(), "event_sog": Counter(), "goals": Counter(),
        "goals_by_period": Counter(), "attempts_by_strength": Counter(),
        "goals_by_strength": Counter(), "locations": Counter(),
        "location_distance": Counter(), "location_angle": Counter(),
        "location_type": Counter(), "outcomes": Counter(), "penalties": 0,
        "has_overtime": False, "has_shootout": False,
    } for game_id in eval_ids}
    event_metrics = {name: _empty_event_metric() for name in variants}
    exact_pools = {}
    exact_counts = Counter()
    exact_rngs = {}
    period_pools = {}
    period_counts = Counter()
    period_rngs = {}
    training_location_rows = 0
    scanned_eval_games = set()

    for game_id, events in phase2a.iter_game_event_groups(bundle, game_ids=selected_ids):
        definition = bundle.games[game_id]
        is_training = definition.season in FIT_SEASONS
        is_eval = game_id in eval_ids
        if not is_training and not is_eval:
            raise ValueError(f"SCANNER_UNEXPECTED_SEASON {game_id}/{definition.season}")
        if is_eval:
            scanned_eval_games.add(game_id)
        snapshot = snapshots[game_id]
        groups = phase2a._pregame_quality_groups(snapshot, fold.parameters.sog_reference)
        score = {"home": 0, "away": 0}
        manpower = parse_situation_code("1551")
        period_key = None
        previous_elapsed = 0
        previous_duration = 0
        for event in events:
            side = phase2a._event_side(definition, event)
            ordinary = event.period_type in {"REG", "OT"}
            valid_period = event.quality.period_number == "ACCEPT"
            if ordinary and event.quality.event == "ACCEPT" and valid_period:
                number = event.period_number
                current_key = (event.period_type, number)
                duration = phase2a._period_duration(event.period_type)
                if period_key is None or current_key != period_key:
                    period_key = current_key
                    previous_elapsed = 0
                    previous_duration = duration
                    manpower = parse_situation_code("1551")
                recorded_elapsed = phase2a._event_elapsed(event, duration)
                elapsed = max(previous_elapsed, recorded_elapsed)
                event_manpower = parse_situation_code(event.situation_code)
                if event_manpower is not None:
                    manpower = event_manpower
                if is_eval and event.period_type == "OT":
                    actual[game_id]["has_overtime"] = True
                if event.event_type == "penalty" and event.quality.event == "ACCEPT":
                    if is_eval:
                        actual[game_id]["penalties"] += 1
                if (event.event_type in SHOT_EVENTS and event.ordinary_shot_eligible is True and
                        side in {"home", "away"} and event.quality.event == "ACCEPT" and
                        event.quality.team_count == "ACCEPT"):
                    period = phase2a.period_level(event.period_type, number)
                    strength = "UNKNOWN"
                    if manpower is not None:
                        if ((side == "home" and not manpower.away_goalie_present) or
                                (side == "away" and not manpower.home_goalie_present)):
                            strength = "EMPTY_NET"
                        elif ((side == "home" and manpower.home_skaters > manpower.away_skaters) or
                              (side == "away" and manpower.away_skaters > manpower.home_skaters)):
                            strength = "ADVANTAGE"
                        elif ((side == "home" and manpower.home_skaters < manpower.away_skaters) or
                              (side == "away" and manpower.away_skaters < manpower.home_skaters)):
                            strength = "DISADVANTAGE"
                        else:
                            strength = "EVEN"
                    remaining = duration - elapsed
                    difference = score[side] - score["away" if side == "home" else "home"]
                    score_group = score_level(difference)
                    time_group = phase2a.time_level(remaining)
                    label = phase2a._attempt_label(event.event_type)
                    spatial_ok = (event.quality.spatial == "ACCEPT" and
                                  event.shot_x is not None and event.shot_y is not None)
                    x = float(event.shot_x) if spatial_ok else None
                    y = float(event.shot_y) if spatial_ok else None
                    shot_type = phase2a._shot_type(
                        event.shot_type if event.quality.shot_type == "ACCEPT" else None)
                    if is_training and spatial_ok:
                        row = (x, y, shot_type, strength)
                        attack_group = groups[side][0]
                        exact_key = (strength, period, score_group, time_group, attack_group)
                        period_pool_key = (strength, period, attack_group)
                        _reservoir_add(exact_pools, exact_counts, exact_rngs,
                                       exact_key, row, LOCATION_EXACT_CAPACITY,
                                       seed=20261021)
                        _reservoir_add(period_pools, period_counts, period_rngs,
                                       period_pool_key, row, LOCATION_PERIOD_CAPACITY,
                                       seed=20261023)
                        training_location_rows += 1
                    if is_eval:
                        current = actual[game_id]
                        current["attempts"][side] += 1
                        current["outcomes"][label] += 1
                        current["attempts_by_strength"][strength] += 1
                        if label in {"SAVED", "GOAL"}:
                            current["event_sog"][side] += 1
                        if label == "GOAL":
                            current["goals_by_strength"][strength] += 1
                        if event.period_type == "SO":
                            current["has_shootout"] = True
                        if spatial_ok:
                            distance, angle = coordinate_features(x, y)
                            current["locations"][f"{distance}|{angle}|{shot_type}"] += 1
                            current["location_distance"][distance] += 1
                            current["location_angle"][angle] += 1
                            current["location_type"][shot_type] += 1
                        for name, (parameters, variant_snapshots) in variants.items():
                            variant_snapshot = variant_snapshots.get(game_id, snapshot)
                            probabilities = parameters.outcome_probabilities(
                                variant_snapshot, side=side, period=period,
                                strength=strength, score_difference=difference,
                                remaining=remaining, location_x=x, location_y=y,
                                shot_type=shot_type, conditional=True)
                            metric = event_metrics[name]
                            observed_index = phase2a_model.OUTCOME_CLASSES.index(label)
                            p_sog = probabilities[2] + probabilities[3]
                            actual_sog = int(label in {"SAVED", "GOAL"})
                            metric["attempts"] += 1
                            metric["observed_sog"] += actual_sog
                            metric["expected_sog"] += p_sog
                            metric["sog_brier_sum"] += (p_sog - actual_sog) ** 2
                            metric["sog_log_loss_sum"] += -math.log(
                                max(1e-12, p_sog if actual_sog else 1.0 - p_sog))
                            metric["multiclass_brier_sum"] += sum(
                                (probability - int(index == observed_index)) ** 2
                                for index, probability in enumerate(probabilities))
                            metric["multiclass_log_loss_sum"] += -math.log(
                                max(1e-12, probabilities[observed_index]))
                            if actual_sog:
                                p_goal = probabilities[3] / p_sog if p_sog else 0.0
                                actual_goal = int(label == "GOAL")
                                metric["on_target_events"] += 1
                                metric["observed_goals"] += actual_goal
                                metric["expected_goals"] += p_goal
                                metric["goal_brier_sum"] += (p_goal - actual_goal) ** 2
                                metric["goal_log_loss_sum"] += -math.log(
                                    max(1e-12, p_goal if actual_goal else 1.0 - p_goal))
                previous_elapsed = elapsed
            if event.period_type == "SO" and is_eval:
                actual[game_id]["has_shootout"] = True
            if phase2a._accepted_team_goal(event, side):
                score[side] += 1
                if is_eval:
                    actual[game_id]["goals"][side] += 1
                    actual[game_id]["goals_by_period"][event.period_type] += 1
    if scanned_eval_games != eval_ids:
        raise ValueError(f"DEVELOPMENT_EVENT_SCAN_COVERAGE {len(scanned_eval_games)}/{len(eval_ids)}")
    exact_supported = {key: tuple(rows) for key, rows in exact_pools.items()
                       if exact_counts[key] >= LOCATION_EXACT_MINIMUM}
    period_supported = {key: tuple(rows) for key, rows in period_pools.items()
                        if period_counts[key] >= LOCATION_PERIOD_MINIMUM}
    if not exact_supported or not period_supported or training_location_rows <= 0:
        raise ValueError("TRAINING_LOCATION_POOL_SUPPORT_EMPTY")
    pool_metadata = {
        "training_spatial_shot_rows": training_location_rows,
            "exact_state_cells_seen": len(exact_counts),
        "exact_state_cells_used": len(exact_supported),
        "exact_state_minimum_rows": LOCATION_EXACT_MINIMUM,
        "exact_state_reservoir_capacity": LOCATION_EXACT_CAPACITY,
        "period_strength_cells_seen": len(period_counts),
        "period_strength_cells_used": len(period_supported),
        "period_strength_minimum_rows": LOCATION_PERIOD_MINIMUM,
        "period_strength_reservoir_capacity": LOCATION_PERIOD_CAPACITY,
        "state_cell_source_counts": {"|".join(key): int(count)
                                     for key, count in exact_counts.items()},
    }
    return actual, event_metrics, exact_supported, period_supported, dict(exact_counts), pool_metadata


def _trace_result(request, result):
    home_id = request.pregame.home_team_id
    attempts = Counter()
    outcomes = Counter()
    attempts_by_strength = Counter()
    goals_by_strength = Counter()
    goals_by_period = Counter()
    locations = Counter()
    distance_counts = Counter()
    angle_counts = Counter()
    type_counts = Counter()
    shot_context = {}
    penalty_count = 0
    has_ot = False
    has_so = False
    for event in result.events:
        if event.period_type == "OT":
            has_ot = True
        if event.period_type == "SO":
            has_so = True
        attrs = dict(event.generated_attributes)
        if event.event_kind == "PENALTY_CALLED":
            penalty_count += 1
        if event.event_kind == "SHOT_ATTEMPT":
            side = "home" if event.event_owner_team_id == home_id else "away"
            attempts[side] += 1
            strength = str(attrs["strength"])
            attempts_by_strength[strength] += 1
            shot_context[int(attrs["attempt_id"])] = (strength, event.period_type)
            shot_type = str(attrs["shot_type"])
            x, y = float(attrs["shot_x"]), float(attrs["shot_y"])
            distance, angle = coordinate_features(x, y)
            locations[f"{distance}|{angle}|{shot_type}"] += 1
            distance_counts[distance] += 1
            angle_counts[angle] += 1
            type_counts[shot_type] += 1
        elif event.event_kind in {"SHOT_BLOCKED", "SHOT_MISSED", "SHOT_SAVED", "GOAL"}:
            outcomes[str(attrs["outcome"])] += 1
            if event.event_kind == "GOAL":
                goals_by_period[event.period_type] += 1
                strength, _ = shot_context[int(attrs["attempt_id"])]
                goals_by_strength[strength] += 1
    return {
        "attempts": dict(attempts),
        "sog": {"home": int(result.home_sog), "away": int(result.away_sog)},
        "goals": {"home": int(result.home_reg_ot_goals), "away": int(result.away_reg_ot_goals)},
        "final": {"home": int(result.home_final_goals), "away": int(result.away_final_goals)},
        "margin": int(result.home_final_goals - result.away_final_goals),
        "outcomes": dict(outcomes),
        "attempts_by_strength": dict(attempts_by_strength),
        "goals_by_strength": dict(goals_by_strength),
        "goals_by_period": dict(goals_by_period),
        "locations": dict(locations),
        "location_distance": dict(distance_counts),
        "location_angle": dict(angle_counts),
        "location_type": dict(type_counts),
        "penalties": penalty_count,
        "has_overtime": has_ot,
        "has_shootout": has_so,
    }


def _run_simulation_variant(name, games, parameters, sims, seed, *, conditional=True,
                            context_locations=False):
    traces = defaultdict(list)
    original_simulator = phase2a.simulate_game
    validations = 0

    def traced_simulator(request, fitted, *, conditional=True, validate=True):
        nonlocal validations
        if not validate:
            raise ValueError("PHASE2B_SIMULATION_VALIDATION_CANNOT_BE_DISABLED")
        result = original_simulator(request, fitted, conditional=conditional, validate=True)
        traces[request.pregame.game_id].append(_trace_result(request, result))
        validations += 1
        return result

    phase2a.simulate_game = traced_simulator
    context = use_context_location_builder() if context_locations else nullcontext()
    started = walltime.perf_counter()
    try:
        with context:
            metrics = phase2a._evaluate_simulations(
                games, parameters, sims, seed=seed, conditional=conditional)
    finally:
        phase2a.simulate_game = original_simulator
    expected = len(games) * sims
    if validations != expected or metrics["validated_simulations"] != expected:
        raise ValueError(f"SIMULATION_VALIDATION_COUNT_MISMATCH {name}/{validations}/{expected}")
    if any(len(traces[game.definition.game_id]) != sims for game in games):
        raise ValueError(f"SIMULATION_TRACE_COVERAGE_MISMATCH {name}")
    metrics["runtime_seconds_wall"] = walltime.perf_counter() - started
    metrics["trace_games"] = len(traces)
    return metrics, dict(traces)


def _run_cached_simulation_variant(cache_dir, run_fingerprint, name, games, parameters,
                                   sims, seed, *, conditional=True,
                                   context_locations=False):
    safe_name = "".join(character.lower() if character.isalnum() else "-"
                        for character in name).strip("-")
    cache_path = cache_dir / f"{safe_name}-{run_fingerprint[:16]}.pickle"
    expected = len(games) * sims
    if cache_path.exists():
        with cache_path.open("rb") as stream:
            cached = pickle.load(stream)
        if cached.get("run_fingerprint") != run_fingerprint or cached.get("name") != name:
            raise ValueError(f"SIMULATION_CACHE_IDENTITY_MISMATCH {name}")
        metrics, traces = cached["metrics"], cached["traces"]
        if (metrics.get("validated_simulations") != expected or
                set(traces) != {game.definition.game_id for game in games} or
                any(len(traces[game.definition.game_id]) != sims for game in games)):
            raise ValueError(f"SIMULATION_CACHE_COVERAGE_MISMATCH {name}")
        print(f"LOAD cached simulations {name}", flush=True)
        return metrics, traces

    print(f"RUN {name}", flush=True)
    metrics, traces = _run_simulation_variant(
        name, games, parameters, sims, seed, conditional=conditional,
        context_locations=context_locations)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".pickle.tmp")
    with temporary_path.open("wb") as stream:
        pickle.dump({"run_fingerprint": run_fingerprint, "name": name,
                     "metrics": metrics, "traces": traces}, stream,
                    protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, cache_path)
    return metrics, traces


def _sample_variance(values):
    return statistics.pvariance(values) if len(values) > 1 else 0.0


def _count_diagnostics(games, actual, traces):
    definitions = {game.definition.game_id: game for game in games}
    result = {}
    for metric in ("attempts", "sog", "goals"):
        actual_values = []
        forecast_means = []
        predictive_variances = []
        covered = {"50": [], "80": [], "90": []}
        eligible_n = 0
        for game_id, game in definitions.items():
            if metric == "sog" and not game.sog_eligible:
                continue
            sides = ("home", "away")
            for side in sides:
                if metric == "attempts":
                    observed = int(actual[game_id]["attempts"].get(side, 0))
                    values = [int(row["attempts"].get(side, 0)) for row in traces[game_id]]
                elif metric == "sog":
                    observed = int(getattr(game.definition, f"official_{side}_sog"))
                    values = [int(row["sog"][side]) for row in traces[game_id]]
                else:
                    observed = int(getattr(game, f"actual_{side}_reg_ot_goals"))
                    values = [int(row["goals"][side]) for row in traces[game_id]]
                actual_values.append(observed)
                forecast_means.append(statistics.fmean(values))
                predictive_variances.append(_sample_variance(values))
                eligible_n += 1
                for coverage in (50, 80, 90):
                    covered[str(coverage)].append(
                        phase2a._count_distribution_coverage(values, observed)[str(coverage)])
        result[metric] = {
            "team_observations": eligible_n,
            "observed_mean": statistics.fmean(actual_values),
            "predicted_mean": statistics.fmean(forecast_means),
            "mean_error_predicted_minus_observed": statistics.fmean(forecast_means) -
                                                     statistics.fmean(actual_values),
            "observed_variance_across_team_games": _sample_variance(actual_values),
            "mean_within_game_predictive_variance": statistics.fmean(predictive_variances),
            "central_interval_coverage": {
                key: {"n": len(values), "observed": statistics.fmean(values)}
                for key, values in covered.items()},
        }
    actual_margins = []
    predicted_means = []
    predictive_variances = []
    actual_pbp_goals = 0
    actual_pbp_sog = 0
    predicted_generated_goals = 0
    predicted_generated_sog = 0
    for game in games:
        game_id = game.definition.game_id
        actual_margins.append(game.definition.official_home_score - game.definition.official_away_score)
        rows = traces[game_id]
        margins = [int(row["margin"]) for row in rows]
        predicted_means.append(statistics.fmean(margins))
        predictive_variances.append(_sample_variance(margins))
        for row in rows:
            predicted_generated_sog += row["sog"]["home"] + row["sog"]["away"]
            predicted_generated_goals += row["goals"]["home"] + row["goals"]["away"]
    for game_id in definitions:
        outcomes = actual[game_id]["outcomes"]
        pbp_sog = int(outcomes.get("SAVED", 0) + outcomes.get("GOAL", 0))
        actual_pbp_sog += pbp_sog
        actual_pbp_goals += int(outcomes.get("GOAL", 0))
    result["score_margin"] = {
        "games": len(games),
        "observed_mean": statistics.fmean(actual_margins),
        "predicted_mean": statistics.fmean(predicted_means),
        "observed_variance_across_games": _sample_variance(actual_margins),
        "mean_within_game_predictive_variance": statistics.fmean(predictive_variances),
    }
    result["shooting_percentage"] = {
        "observed_pbp_goal_per_pbp_sog": actual_pbp_goals / actual_pbp_sog,
        "predicted_generated_goal_per_generated_sog": predicted_generated_goals / predicted_generated_sog,
        "observed_pbp_sog_events": actual_pbp_sog,
        "predicted_generated_sog_events": predicted_generated_sog,
    }
    return result


def _distribution_tv(observed: Mapping[str, int], predicted: Mapping[str, int]):
    keys = set(observed) | set(predicted)
    observed_total = sum(observed.values())
    predicted_total = sum(predicted.values())
    if not observed_total or not predicted_total:
        raise ValueError("SHOT_QUALITY_DISTRIBUTION_EMPTY")
    return 0.5 * sum(abs(observed.get(key, 0) / observed_total -
                         predicted.get(key, 0) / predicted_total) for key in keys)


def _simulated_component_summary(games, actual, traces, sims):
    total_attempts = Counter()
    total_sog = Counter()
    total_goals = Counter()
    predicted_location = Counter()
    predicted_distance = Counter()
    predicted_angle = Counter()
    predicted_type = Counter()
    predicted_strength_attempts = Counter()
    predicted_strength_goals = Counter()
    predicted_period_goals = Counter()
    penalties = []
    ot_games = 0
    so_games = 0
    for game in games:
        game_traces = traces[game.definition.game_id]
        ot_games += sum(bool(row["has_overtime"]) for row in game_traces) / float(sims)
        so_games += sum(bool(row["has_shootout"]) for row in game_traces) / float(sims)
        penalties.extend(row["penalties"] for row in game_traces)
        for row in game_traces:
            total_attempts.update(row["attempts"])
            total_sog.update(row["sog"])
            total_goals.update(row["goals"])
            predicted_location.update(row["locations"])
            predicted_distance.update(row["location_distance"])
            predicted_angle.update(row["location_angle"])
            predicted_type.update(row["location_type"])
            predicted_strength_attempts.update(row["attempts_by_strength"])
            predicted_strength_goals.update(row["goals_by_strength"])
            predicted_period_goals.update(row["goals_by_period"])
    observed_attempts = Counter()
    observed_sog = Counter()
    observed_goals = Counter()
    observed_strength_attempts = Counter()
    observed_strength_goals = Counter()
    observed_period_goals = Counter()
    observed_locations = Counter()
    observed_distance = Counter()
    observed_angle = Counter()
    observed_type = Counter()
    observed_penalties = []
    observed_ot_games = 0
    observed_so_games = 0
    for game in games:
        row = actual[game.definition.game_id]
        observed_attempts.update(row["attempts"])
        observed_sog.update(row["event_sog"])
        observed_goals.update(row["goals"])
        observed_strength_attempts.update(row["attempts_by_strength"])
        observed_strength_goals.update(row["goals_by_strength"])
        observed_period_goals.update(row["goals_by_period"])
        observed_locations.update(row["locations"])
        observed_distance.update(row["location_distance"])
        observed_angle.update(row["location_angle"])
        observed_type.update(row["location_type"])
        observed_penalties.append(row["penalties"])
        observed_ot_games += int(row["has_overtime"])
        observed_so_games += int(row["has_shootout"])
    return {
        "observed_event_totals": {
            "accepted_attempts_by_side": dict(observed_attempts),
            "accepted_pbp_sog_by_side": dict(observed_sog),
            "accepted_reg_ot_goals_by_side": dict(observed_goals),
            "accepted_attempt_outcomes": {
                label: sum(int(actual[g.definition.game_id]["outcomes"].get(label, 0))
                           for g in games)
                for label in ("BLOCKED", "MISSED", "SAVED", "GOAL")},
            "overtime_games": observed_ot_games,
            "shootout_games": observed_so_games,
            "accepted_penalty_events": sum(observed_penalties),
        },
        "predicted_mean_per_game_totals": {
            "attempts": sum(total_attempts.values()) / float(len(games) * sims),
            "sog": sum(total_sog.values()) / float(len(games) * sims),
            "reg_ot_goals": sum(total_goals.values()) / float(len(games) * sims),
            "overtime_games": ot_games,
            "shootout_games": so_games,
            "penalties": statistics.fmean(penalties) if penalties else 0.0,
        },
        "strength_attempts_observed": dict(observed_strength_attempts),
        "strength_attempts_predicted_per_game": {
            key: value / float(len(games) * sims)
            for key, value in predicted_strength_attempts.items()},
        "strength_goals_observed": dict(observed_strength_goals),
        "strength_goals_predicted_per_game": {
            key: value / float(len(games) * sims)
            for key, value in predicted_strength_goals.items()},
        "goals_by_period_observed": dict(observed_period_goals),
        "goals_by_period_predicted_per_game": {
            key: value / float(len(games) * sims)
            for key, value in predicted_period_goals.items()},
        "penalties_observed_per_game": statistics.fmean(observed_penalties),
        "location_composition": {
            "observed_spatial_attempts": sum(observed_locations.values()),
            "predicted_spatial_attempts_per_simulation": sum(predicted_location.values()) / float(sims),
            "joint_distance_angle_type_total_variation": _distribution_tv(
                observed_locations, predicted_location),
            "distance_total_variation": _distribution_tv(observed_distance, predicted_distance),
            "angle_total_variation": _distribution_tv(observed_angle, predicted_angle),
            "shot_type_total_variation": _distribution_tv(observed_type, predicted_type),
        },
    }


def _event_metric_report(metric):
    n = int(metric["attempts"])
    on_target = int(metric["on_target_events"])
    return {
        "accepted_attempts": n,
        "observed_sog_per_attempt": metric["observed_sog"] / n if n else None,
        "predicted_sog_per_attempt_at_observed_states": metric["expected_sog"] / n if n else None,
        "sog_brier": metric["sog_brier_sum"] / n if n else None,
        "sog_log_loss": metric["sog_log_loss_sum"] / n if n else None,
        "on_target_events": on_target,
        "observed_goal_per_sog": metric["observed_goals"] / on_target if on_target else None,
        "predicted_goal_per_sog_at_observed_locations": metric["expected_goals"] / on_target if on_target else None,
        "goal_brier_conditional_on_sog": metric["goal_brier_sum"] / on_target if on_target else None,
        "goal_log_loss_conditional_on_sog": metric["goal_log_loss_sum"] / on_target if on_target else None,
        "four_outcome_brier": metric["multiclass_brier_sum"] / n if n else None,
        "four_outcome_log_loss": metric["multiclass_log_loss_sum"] / n if n else None,
    }


def _comparison_to_candidate(candidate, reference, seed):
    return phase2a._summarize_comparison(candidate, reference, seed)


def _load_frozen_artifacts():
    evaluation_path = PHASE2A / "EVALUATION.json"
    model_path = PHASE2A / "FITTED-MODEL.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    model = FittedParameters.from_json(json.loads(model_path.read_text(encoding="utf-8")))
    model_sha = phase2a.sha256_file(model_path)
    if evaluation.get("model_sha256") != model_sha:
        raise ValueError("FROZEN_PHASE2A_MODEL_HASH_MISMATCH")
    return evaluation, model, {
        "evaluation_sha256": phase2a.sha256_file(evaluation_path),
        "fitted_model_sha256": model_sha,
        "report_sha256": phase2a.sha256_file(PHASE2A / "REPORT.md"),
    }


def _decision_summary(candidate_results):
    candidates = {name: row for name, row in candidate_results.items()
                  if name != "Phase 2A"}
    best_name = min(candidates, key=lambda name:
                    candidates[name]["simulation_metrics"]["reg_ot_team_goal_crps"])
    best = candidates[best_name]
    phase2a_pair = best["paired_comparisons"]["Phase 2A"]["paired_comparisons"]
    goal = phase2a_pair["team_goal_crps_baseline_minus_candidate"]
    energy = phase2a_pair["final_score_energy_baseline_minus_candidate"]
    sog = phase2a_pair["team_sog_crps_baseline_minus_candidate"]
    goal_ci = goal["paired_game_bootstrap_ci95"]
    energy_ci = energy["paired_game_bootstrap_ci95"]
    sog_ci = sog["paired_game_bootstrap_ci95"]
    both_supported = goal_ci[0] > 0.0 and energy_ci[0] > 0.0
    shot_cost = ""
    if sog_ci[1] < 0.0:
        shot_cost = " It also worsens team SOG CRPS on this fold."
    elif sog_ci[0] > 0.0:
        shot_cost = " Team SOG CRPS remains better than Phase 2A on this fold."
    else:
        shot_cost = " Its SOG change is not resolved by the paired interval."
    if both_supported:
        evidence = (
            f"Best 2021 development candidate by goal CRPS is {best_name}: paired "
            f"goal-CRPS gain {goal['mean_delta']:+.4f} [{goal_ci[0]:+.4f}, "
            f"{goal_ci[1]:+.4f}] and final-energy gain {energy['mean_delta']:+.4f} "
            f"[{energy_ci[0]:+.4f}, {energy_ci[1]:+.4f}] versus matched Phase 2A."
            f"{shot_cost} These intervals are descriptive after candidate selection, "
            "so this remains a research result, not adoption evidence.")
    else:
        evidence = (
            f"Best 2021 development candidate by goal CRPS is {best_name}: paired "
            f"goal-CRPS gain {goal['mean_delta']:+.4f} [{goal_ci[0]:+.4f}, "
            f"{goal_ci[1]:+.4f}] and final-energy gain {energy['mean_delta']:+.4f} "
            f"[{energy_ci[0]:+.4f}, {energy_ci[1]:+.4f}] versus matched Phase 2A. "
            "At least one interval includes zero; the development fold does not "
            "establish a joint scoring improvement."
            f"{shot_cost}")
    return {
        "best_development_candidate_by_goal_crps": best_name,
        "goal_crps_delta_vs_phase2a": goal,
        "final_energy_delta_vs_phase2a": energy,
        "sog_crps_delta_vs_phase2a": sog,
        "joint_goal_and_energy_interval_above_zero": both_supported,
        "summary": evidence,
        "adoption": "NOT_ADOPTED: no independent later-season evaluation exists; 2021 is the candidate-selection fold and 2022 was exposed in Phase 2A.",
    }


def _write_report(result, path: Path):
    development = result["development"]
    diag = development["baseline_diagnostics"]
    components = development["candidate_results"]["Phase 2A"]["simulation_components"]
    event = development["event_level_diagnostics"]
    sims = development["simulations_per_game"]
    lines = [
        "# NHL V3 Phase 2B: scoring model diagnosis",
        "",
        f"- Base: `{result['base_commit']}`",
        f"- Research branch: `{result['branch']}`",
        f"- 2021 development simulations per game: {sims}; fixed seed: `{result['seed']}`",
        "- 2022 is historical Phase 2A evidence only. No Phase 2B candidate was selected or tuned on 2022.",
        "- Frozen Phase 2A simulator, fitted model, and evaluation hashes are recorded in `RESULTS.json`.",
        "",
        "## Decision",
        "",
        result["decision"]["summary"],
        "",
        "## Why the Phase 2B code exists",
        "",
        "The Phase 2A fit and evaluator provide the frozen shot generator and the 2021/2022 reference scores, but do not expose generated attempt counts, controlled conversion offsets, or a state-conditioned location pool. This research runner adds those measurements and isolated adapters. The fitted outcomes, SOG targets, scores, and model features still come from the hash-pinned NHL replay and official outcome artifacts; the derived values below are reconciled to those sources.",
        "",
        "## Component diagnosis on 2021",
        "",
        f"Accepted games: {development['games']}; official SOG eligible games: {development['sog_eligible_games']}. Attempt and event conversion diagnostics use {event['Phase 2A']['accepted_attempts']} accepted PBP shot attempts. Event-level probabilities condition on observed in-game states and observed locations for diagnosis only; the simulator never receives target-game events, locations, or shooters.",
        "",
        "| Measure | Observed | Phase 2A generated / predicted |",
        "|---|---:|---:|",
    ]
    for key, label in (("attempts", "Attempts per team-game"),
                       ("sog", "Official team SOG per team-game"),
                       ("goals", "Regulation + OT goals per team-game")):
        row = diag[key]
        lines.append(f"| {label} | {row['observed_mean']:.3f} | {row['predicted_mean']:.3f} |")
    lines.extend([
        f"| Final score margin (home minus away) | {diag['score_margin']['observed_mean']:.3f} | {diag['score_margin']['predicted_mean']:.3f} |",
        f"| Final margin variance | {diag['score_margin']['observed_variance_across_games']:.3f} | {diag['score_margin']['mean_within_game_predictive_variance']:.3f} within-game predictive |",
        f"| Goals per PBP SOG | {diag['shooting_percentage']['observed_pbp_goal_per_pbp_sog']:.4f} | {diag['shooting_percentage']['predicted_generated_goal_per_generated_sog']:.4f} generated |",
        "",
        "| Count | Observed variance | Mean predictive variance | 50% coverage | 80% coverage | 90% coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for key, label in (("attempts", "Team attempts"), ("sog", "Official team SOG"),
                       ("goals", "Team reg+OT goals")):
        row = diag[key]
        coverage = row["central_interval_coverage"]
        lines.append(
            f"| {label} | {row['observed_variance_across_team_games']:.3f} | "
            f"{row['mean_within_game_predictive_variance']:.3f} | "
            f"{coverage['50']['observed']:.3f} | {coverage['80']['observed']:.3f} | "
            f"{coverage['90']['observed']:.3f} |")
    base_event = event["Phase 2A"]
    base_comp = development["shot_quality_composition_by_candidate"]["Phase 2A"]
    quality_comp = development["shot_quality_composition_by_candidate"][
        "D state-conditioned quality"]
    lines.extend([
        "",
        "### Measured error attribution",
        "",
        f"The largest direct scoring mismatch is in even-strength goals: "
        f"{components['strength_goals_predicted_per_game']['EVEN']:.3f} generated versus "
        f"{components['strength_goals_observed']['EVEN'] / development['games']:.3f} observed per game "
        f"(+{components['strength_goals_predicted_per_game']['EVEN'] - components['strength_goals_observed']['EVEN'] / development['games']:.3f}). "
        f"The model generates {diag['goals']['predicted_mean'] - diag['goals']['observed_mean']:+.3f} "
        "regulation/OT goals per team-game overall. This excess is partly offset by zero generated "
        f"empty-net goals versus {components['strength_goals_observed']['EMPTY_NET'] / development['games']:.3f} observed per game, "
        f"and by advantage goals {components['strength_goals_predicted_per_game']['ADVANTAGE']:.3f} versus "
        f"{components['strength_goals_observed']['ADVANTAGE'] / development['games']:.3f}. "
        f"Generated penalties also undercount events ({components['predicted_mean_per_game_totals']['penalties']:.3f} vs "
        f"{components['penalties_observed_per_game']:.3f} per game).",
        f"Attempts are close in mean ({diag['attempts']['predicted_mean']:.3f} vs {diag['attempts']['observed_mean']:.3f}), "
        f"and SOG are modestly low ({diag['sog']['predicted_mean']:.3f} vs {diag['sog']['observed_mean']:.3f}); "
        f"their predictive variances are substantially low ({diag['attempts']['mean_within_game_predictive_variance']:.1f} vs "
        f"{diag['attempts']['observed_variance_across_team_games']:.1f} attempts and "
        f"{diag['sog']['mean_within_game_predictive_variance']:.1f} vs "
        f"{diag['sog']['observed_variance_across_team_games']:.1f} SOG). On generated SOG, conversion is "
        f"{diag['shooting_percentage']['predicted_generated_goal_per_generated_sog']:.4f}, above observed "
        f"{diag['shooting_percentage']['observed_pbp_goal_per_pbp_sog']:.4f}; at the actual event locations, "
        f"the conditional model predicts {base_event['predicted_goal_per_sog_at_observed_locations']:.4f} "
        f"versus {base_event['observed_goal_per_sog']:.4f} observed. This points toward the generated "
        "location/type and game-state mix compounding over a game, rather than a uniform excess in the "
        "per-shot conversion probability. It is a diagnostic attribution, not a causal decomposition.",
        f"Candidate D did not fix composition: joint distance-angle-type TV moved from "
        f"{base_comp['joint_distance_angle_type_total_variation']:.4f} to "
        f"{quality_comp['joint_distance_angle_type_total_variation']:.4f}, and its goal and energy scores "
        "did not improve over Phase 2A. The population intercept adjustment also failed to improve scoring.",
        "",
    ])
    observed_components = components["observed_event_totals"]
    predicted_components = components["predicted_mean_per_game_totals"]
    lines.extend([
        "",
        "### Regulation, overtime, and special teams",
        "",
        "| Measure | Observed | Phase 2A generated / predicted |",
        "|---|---:|---:|",
        f"| Games reaching overtime | {observed_components['overtime_games']} | {predicted_components['overtime_games']:.1f} expected games |",
        f"| Games reaching shootout | {observed_components['shootout_games']} | {predicted_components['shootout_games']:.1f} expected games |",
        f"| Accepted penalties per game | {components['penalties_observed_per_game']:.3f} | {predicted_components['penalties']:.3f} |",
        "",
        "| Goals per game by period / strength | Observed | Phase 2A generated |",
        "|---|---:|---:|",
    ])
    games_n = development["games"]
    for period in sorted(set(components["goals_by_period_observed"]) |
                         set(components["goals_by_period_predicted_per_game"])):
        observed = components["goals_by_period_observed"].get(period, 0) / games_n
        predicted = components["goals_by_period_predicted_per_game"].get(period, 0.0)
        lines.append(f"| Goals, {period} | {observed:.3f} | {predicted:.3f} |")
    for strength in sorted(set(components["strength_goals_observed"]) |
                           set(components["strength_goals_predicted_per_game"])):
        observed = components["strength_goals_observed"].get(strength, 0) / games_n
        predicted = components["strength_goals_predicted_per_game"].get(strength, 0.0)
        lines.append(f"| Goals, {strength} strength | {observed:.3f} | {predicted:.3f} |")
    lines.extend([
        "",
        "The conditional event check isolates conversion from game-level compounding. The generated count check includes the downstream effect of goals changing score-state shot rates.",
        "",
        "### Conditional probability checks",
        "",
        "| Candidate | P(SOG) observed | P(SOG) predicted at observed states | Goal/SOG observed | Goal/SOG predicted at observed locations | Goal Brier |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for name, values in event.items():
        lines.append(
            f"| {name} | {values['observed_sog_per_attempt']:.4f} | "
            f"{values['predicted_sog_per_attempt_at_observed_states']:.4f} | "
            f"{values['observed_goal_per_sog']:.4f} | "
            f"{values['predicted_goal_per_sog_at_observed_locations']:.4f} | "
            f"{values['goal_brier_conditional_on_sog']:.4f} |")
    lines.extend([
        "",
        "Attempt volume is measured independently from event-level SOG and goal conversion. Shot-quality composition is evaluated with joint and marginal total-variation distances against accepted 2021 spatial events. Strength, OT, and shootout counts are reported separately in `RESULTS.json`.",
        "",
        "## Controlled candidate comparison",
        "",
        "Positive paired deltas favor the candidate. Bootstrap intervals resample games. Every Phase 2B candidate and the matched Phase 2A/simple-rate simulations use identical game IDs, seeds, simulation counts, and full event validation. The same-window v2 score refit uses the identical 2018–2020 training games.",
        "",
        "| Candidate | Goal CRPS | Final energy | Winner Brier | Team SOG CRPS | Runtime (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for name, row in development["reference_results"].items():
        metrics = row["simulation_metrics"]
        sog = metrics.get("team_sog_crps")
        sog_cell = f"{sog:.4f}" if sog is not None else "n/a"
        lines.append(
            f"| {name} | {metrics['reg_ot_team_goal_crps']:.4f} | "
            f"{metrics['final_score_energy_score']:.4f} | {metrics['winner_brier']:.4f} | "
            f"{sog_cell} | {metrics['runtime_seconds']:.1f} |")
    for name, row in development["candidate_results"].items():
        metrics = row["simulation_metrics"]
        sog = metrics["team_sog_crps"]
        sog_cell = f"{sog:.4f}" if sog is not None else "n/a"
        lines.append(
            f"| {name} | {metrics['reg_ot_team_goal_crps']:.4f} | "
            f"{metrics['final_score_energy_score']:.4f} | {metrics['winner_brier']:.4f} | "
            f"{sog_cell} | {metrics['runtime_seconds']:.1f} |")
    hist = result["historical_exposed_2022_phase2a"]
    hist_v2 = hist["same_window_v2_comparison"]["metrics"]
    hist_simple = hist["simple_rate_simulation"]
    hist_model = hist["conditional_simulation"]
    lines.extend([
        "",
        "### Previously exposed 2022 diagnostic",
        "",
        "These frozen Phase 2A values are historical context only; no Phase 2B candidate used them for selection.",
        "",
        "| Model | Goal CRPS | Final energy | Winner Brier | Team SOG CRPS |",
        "|---|---:|---:|---:|---:|",
        f"| Frozen Phase 2A | {hist_model['reg_ot_team_goal_crps']:.4f} | {hist_model['final_score_energy_score']:.4f} | {hist_model['winner_brier']:.4f} | {hist_model['team_sog_crps']:.4f} |",
        f"| Simple historical-rate | {hist_simple['reg_ot_team_goal_crps']:.4f} | {hist_simple['final_score_energy_score']:.4f} | {hist_simple['winner_brier']:.4f} | {hist_simple['team_sog_crps']:.4f} |",
        f"| Same-window v2 refit | {hist_v2['reg_ot_team_goal_crps']:.4f} | {hist_v2['final_score_energy_score']:.4f} | {hist_v2['winner_brier']:.4f} | n/a |",
    ])
    lines.extend([
        "",
        "### Paired 95% game bootstrap deltas",
        "",
        "Each cell is baseline loss minus candidate loss, followed by the 95% game-bootstrap interval. Positive values favor the candidate. The intervals resample games and do not include finite Monte Carlo uncertainty; the comparison uses 16 common-seed simulations per game. The candidate was selected on this same development population, so intervals that exclude zero are descriptive and do not establish confirmatory significance.",
        "",
        "| Candidate | Reference | Goal CRPS | Final energy | Winner Brier | SOG CRPS |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for name, row in development["candidate_results"].items():
        for reference, comparison in row["paired_comparisons"].items():
            paired = comparison["paired_comparisons"]
            def fmt(key):
                item = paired[key]
                if item["mean_delta"] is None:
                    return "n/a"
                ci = item["paired_game_bootstrap_ci95"]
                return f"{item['mean_delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]"
            lines.append(
                f"| {name} | {reference} | "
                f"{fmt('team_goal_crps_baseline_minus_candidate')} | "
                f"{fmt('final_score_energy_baseline_minus_candidate')} | "
                f"{fmt('winner_brier_baseline_minus_candidate')} | "
                f"{fmt('team_sog_crps_baseline_minus_candidate')} |")
    lines.extend([
        "",
        "## Limits and next evaluation",
        "",
        "No accepted NHL source bundle on this host contains a later complete season: the pinned Phase 1 frame covers 2018–2022, with 2022 partial through November 27. The prospective 2026–27 directory contains forecasts but no settled outcomes. `UNSEEN-EVALUATION-PROTOCOL.md` freezes a later-season evaluation path; Phase 2B is not adopted without it.",
        "",
        result["decision"]["adoption"],
        "",
        "The generator still omits player identity and shooter skill, verified goalie response, possession and rebound chains, empty-net strategy, full penalty/manpower rules, team discipline, and line changes. It samples exponential event times and its minor-only special-teams process remains a known source of score-distribution error.",
        "",
        "## Reproduction and validation",
        "",
        "Run `python3 -m unittest discover -s research/nhl/nhl-v3-phase2b-scoring-2026-10-21 -p 'test_*.py' -v` and the exact command recorded in `RESULTS.json`. Simulation seeds, input hashes, candidate feature provenance, all paired scores, and full simulation validation counts are retained.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path,
                        default=phase2a.DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--official", type=Path,
                        default=phase2a.DEFAULT_OFFICIAL_DIR)
    parser.add_argument("--labels", type=Path,
                        default=phase2a.DEFAULT_LABEL_DIR / "research_label_quality.csv")
    parser.add_argument("--label-summary", type=Path)
    parser.add_argument("--v2-canonical", type=Path, default=phase2a.DEFAULT_V2_CANONICAL)
    parser.add_argument("--v2-frozen-model", type=Path, default=phase2a.DEFAULT_V2_FROZEN_MODEL)
    parser.add_argument("--sims", type=int, default=16)
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    parser.add_argument("--smoke-game", action="store_true",
                        help="fit on pinned data, then validate three adapters on one real development game")
    parser.add_argument("--out-dir", type=Path, default=HERE)
    args = parser.parse_args()
    if args.sims <= 0:
        raise SystemExit("--sims must be positive")
    output_path = args.out_dir.resolve()
    if PHASE2A.resolve() == output_path or PHASE2A.resolve() in output_path.parents:
        raise SystemExit("PHASE2A_OUTPUT_IS_FROZEN")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    frozen_evaluation, frozen_parameters, frozen_hashes = _load_frozen_artifacts()
    bundle = phase2a.load_bundle(
        artifact_dir=args.artifacts, official_dir=args.official,
        label_path=args.labels, label_summary_path=args.label_summary)
    canonical, v2_source = phase2a._load_v2_canonical(args.v2_canonical, args.v2_frozen_model)
    run_fingerprint = _sha256_json({
        "runner_sha256": phase2a.sha256_file(Path(__file__)),
        "experiment_adapter_sha256": phase2a.sha256_file(HERE / "scoring_experiments.py"),
        "phase2a_runner_sha256": phase2a.sha256_file(PHASE2A / "run_phase2a.py"),
        "phase2a_model_sha256": phase2a.sha256_file(PHASE2A / "stochastic_model.py"),
        "phase1_replay_sha256": phase2a.sha256_file(PHASE1 / "replay_model.py"),
        "bundle_pins": bundle.pins,
        "v2_source": v2_source,
        "simulations_per_game": args.sims,
        "seed": args.seed,
        "game_ids": sorted(game_id for game_id, game in bundle.games.items()
                            if game.season in DEVELOPMENT_SEASONS),
    })
    cache_dir = Path("/tmp") / f"nhl-v3-phase2b-cache-{run_fingerprint[:16]}"
    snapshots = phase2a._team_history_snapshots(bundle)
    fold, fit_capture = _capture_development_fold(bundle, snapshots, canonical)
    if len(fold.heldout_games) != 1312 or fold.train_counts.get("fit_games") != 3221:
        raise ValueError("PINNED_DEVELOPMENT_POPULATION_MISMATCH")

    calibration = _population_conversion_shift(fold.parameters,
                                               fit_capture["goal_counts"], shrinkage=0.5)
    phase2a_parameters = fold.parameters
    candidate_a = ExperimentParameters.from_base(
        phase2a_parameters,
        global_goal_logit_shift=calibration["applied_logit_intercept_shift"])
    rolling_offsets, rolling_meta, league_goal_mean = _rolling_goal_offsets(
        bundle, canonical, fold.heldout_games)
    rolling_sha = bundle.pins["official_artifacts"]["canonical_frame.csv"]
    rolling_games, rolling_feature_meta = _with_goal_offsets(
        fold.heldout_games, rolling_offsets, source_kind="forward_rolling_team_goals",
        source_sha256=rolling_sha, source_label="rolling_goal_rates_2018_2021")
    v2_offsets, v2_feature_values = _v2_offsets_from_canonical(
        fold, canonical, fold.heldout_games)
    v2_rating_sha = _sha256_json({
        "fit_seasons": FIT_SEASONS, "ratings": fold.v2_model.ratings(),
        "canonical_sha256": v2_source["canonical_games_sha256"],
        "reference_code_sha256": v2_source["reference_code_sha256"],
    })
    v2_strength_games, v2_feature_meta = _with_goal_offsets(
        fold.heldout_games, v2_offsets, source_kind="v2_forward_team_strength",
        source_sha256=v2_rating_sha, source_label="v2_team_strength_2018_2020")

    if args.smoke_game:
        game = fold.heldout_games[0]
        rolling_game = rolling_games[0]
        v2_game = v2_strength_games[0]
        outputs = {}
        for name, snapshot, parameters in (
                ("Phase 2A", game.snapshot, phase2a_parameters),
                ("A population conversion", game.snapshot, candidate_a),
                ("B rolling team goals", rolling_game.snapshot, ExperimentParameters.from_base(phase2a_parameters)),
                ("B v2 team strength", v2_game.snapshot, ExperimentParameters.from_base(phase2a_parameters))):
            request = phase2a.SimulationRequest(snapshot, args.seed)
            result = phase2a_model.simulate_game(request, parameters, validate=True)
            outcomes = dict(result.shot_outcomes)
            if (result.home_sog + result.away_sog != outcomes.get("SAVED", 0) + outcomes.get("GOAL", 0) or
                    result.home_reg_ot_goals + result.away_reg_ot_goals != outcomes.get("GOAL", 0)):
                raise ValueError(f"SMOKE_EVENT_ACCOUNTING_MISMATCH {name}")
            if any("goalie" in feature.key.lower() for feature in snapshot.features):
                raise ValueError(f"SMOKE_GOALIE_FEATURE_PRESENT {name}")
            outputs[name] = {
                "game_id": game.definition.game_id,
                "attempts": sum(outcomes.values()),
                "sog": result.home_sog + result.away_sog,
                "reg_ot_goals": result.home_reg_ot_goals + result.away_reg_ot_goals,
                "final_score": [result.home_final_goals, result.away_final_goals],
            }
        print(json.dumps({"smoke_game": game.definition.game_id,
                          "validated_simulations": len(outputs),
                          "results": outputs}, sort_keys=True))
        return 0

    original_metrics, original_trace = _run_cached_simulation_variant(
        cache_dir, run_fingerprint, "Phase 2A matched reference",
        fold.heldout_games, phase2a_parameters, args.sims, args.seed)
    simple_metrics, simple_trace = _run_cached_simulation_variant(
        cache_dir, run_fingerprint, "Simple historical-rate reference",
        fold.heldout_games, phase2a_parameters, args.sims, args.seed,
        conditional=False)
    print("RUN same-window v2 score refit", flush=True)
    v2_metrics = phase2a._evaluate_v2_score_distribution(
        fold.heldout_games, fold.v2_model, canonical,
        fold.v2_shootout_home_win_rate, args.sims,
        seed=args.seed + 2_000_000)

    base_rows = {row["game_id"]: row for row in original_metrics["paired_game_rows"]}
    v2_rows = {row["game_id"]: row for row in v2_metrics["per_game_predictions"]}
    if set(base_rows) != set(v2_rows):
        raise ValueError("V2_AND_PHASE2A_GAME_POPULATIONS_DIFFER")
    c_offsets = {}
    c_prior = {}
    for game in fold.heldout_games:
        game_id = game.definition.game_id
        source = canonical[game_id]
        v2_home, v2_away = fold.v2_model.mus(
            source.home_team, source.away_team, source.neutral_site)
        v3_home = max(0.05, float(base_rows[game_id]["predicted_home_reg_ot_goals_mean"]))
        v3_away = max(0.05, float(base_rows[game_id]["predicted_away_reg_ot_goals_mean"]))
        home_shift = math.log(max(0.05, v2_home) / v3_home)
        away_shift = math.log(max(0.05, v2_away) / v3_away)
        c_offsets[game_id] = (home_shift, away_shift)
        c_prior[game_id] = {
            "v2_home_expected_reg_ot_goals": float(v2_home),
            "v2_away_expected_reg_ot_goals": float(v2_away),
            "v3_home_pregame_simulated_mean": v3_home,
            "v3_away_pregame_simulated_mean": v3_away,
            "home_logit_offset": home_shift,
            "away_logit_offset": away_shift,
        }
    v3_model_sha = _sha256_bytes(
        (json.dumps(phase2a_parameters.to_json(), sort_keys=True,
                    separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    c_games, c_feature_meta = _with_goal_offsets(
        fold.heldout_games, c_offsets, source_kind="pregame_v2_goal_prior_offset",
        source_sha256=_sha256_json({"v2": v2_rating_sha, "v3": v3_model_sha}),
        source_label="v2_mu_over_v3_pregame_expected_goals", available_at_start=True)

    candidate_b_rolling = ExperimentParameters.from_base(phase2a_parameters)
    candidate_b_v2 = ExperimentParameters.from_base(phase2a_parameters)
    candidate_c = ExperimentParameters.from_base(phase2a_parameters)
    candidate_d = None
    variants = {
        "Phase 2A": (phase2a_parameters, {}),
        "A population conversion": (candidate_a, {}),
        "B rolling team goals": (candidate_b_rolling,
                                  {g.definition.game_id: g.snapshot for g in rolling_games}),
        "B v2 team strength": (candidate_b_v2,
                                {g.definition.game_id: g.snapshot for g in v2_strength_games}),
        "C v2 goal prior": (candidate_c,
                             {g.definition.game_id: g.snapshot for g in c_games}),
        "D state-conditioned quality": (phase2a_parameters, {}),
    }
    actual, event_raw, state_pools, period_pools, state_pool_counts, pool_metadata = (
        _scan_training_and_development(bundle, fold, snapshots, variants))
    print("DIAGNOSE accepted development events and build training-only shot-quality pools", flush=True)
    expected_attempts = fold.train_counts["evaluation_2021_accepted_shot_events"]
    if event_raw["Phase 2A"]["attempts"] != expected_attempts:
        raise ValueError(
            f"DEVELOPMENT_ATTEMPT_RECOUNT_MISMATCH {event_raw['Phase 2A']['attempts']}!={expected_attempts}")
    event_eval_attempts = sum(sum(counts) for counts in fold.event_eval_outcomes.values())
    if event_raw["Phase 2A"]["attempts"] != event_eval_attempts:
        raise ValueError(
            f"DEVELOPMENT_EVENT_EVAL_POPULATION_MISMATCH {event_raw['Phase 2A']['attempts']}!={event_eval_attempts}")
    for game in fold.heldout_games:
        observed_score = actual[game.definition.game_id]["goals"]
        if (observed_score["home"] != game.actual_home_reg_ot_goals or
                observed_score["away"] != game.actual_away_reg_ot_goals):
            raise ValueError(f"DEVELOPMENT_SCORE_TARGET_RECOUNT_MISMATCH {game.definition.game_id}")
    candidate_d = ExperimentParameters.from_base(
        phase2a_parameters, state_location_pools=state_pools,
        period_location_pools=period_pools, state_location_counts=state_pool_counts)

    candidates = {
        "Phase 2A": (fold.heldout_games, phase2a_parameters, False),
        "A population conversion": (fold.heldout_games, candidate_a, False),
        "B rolling team goals": (rolling_games, candidate_b_rolling, False),
        "B v2 team strength": (v2_strength_games, candidate_b_v2, False),
        "C v2 goal prior": (c_games, candidate_c, False),
        "D state-conditioned quality": (fold.heldout_games, candidate_d, True),
    }
    simulation_results = {
        "Phase 2A": {"metrics": original_metrics, "traces": original_trace},
        "Simple historical-rate": {"metrics": simple_metrics, "traces": simple_trace},
    }
    for index, (name, (games, parameters, context_locations)) in enumerate(candidates.items()):
        if name == "Phase 2A":
            continue
        metrics, traces = _run_cached_simulation_variant(
            cache_dir, run_fingerprint, name, games, parameters, args.sims, args.seed,
            context_locations=context_locations)
        simulation_results[name] = {"metrics": metrics, "traces": traces}

    # Candidate C's offsets are generated exclusively from the v2 fit and Phase 2A
    # pregame simulations, never from target-game goals or shot locations.
    candidate_results = {}
    references = {
        "Phase 2A": original_metrics,
        "Simple historical-rate": simple_metrics,
    }
    for index, name in enumerate(candidates):
        metrics = simulation_results[name]["metrics"]
        comparisons = {
            reference_name: _comparison_to_candidate(
                metrics, reference, args.seed + 1000 + index * 17 + ref_index * 101)
            for ref_index, (reference_name, reference) in enumerate(references.items())
        }
        raw_v2_comparison = phase2a._summarize_v2_comparison(
            metrics, v2_metrics, args.seed + 4000 + index * 31)
        v2_pairs = raw_v2_comparison["paired_comparisons"]
        comparisons["Same-window v2 refit"] = {
            "positive_delta_favors_candidate": True,
            "paired_comparisons": {
                "team_goal_crps_baseline_minus_candidate": {
                    "mean_delta": v2_pairs["reg_ot_team_goal_crps"]["v2_minus_candidate_mean"],
                    "paired_game_bootstrap_ci95": v2_pairs["reg_ot_team_goal_crps"]["paired_game_bootstrap_ci95"],
                    "n": v2_pairs["reg_ot_team_goal_crps"]["n"]},
                "winner_brier_baseline_minus_candidate": {
                    "mean_delta": v2_pairs["winner_brier"]["v2_minus_candidate_mean"],
                    "paired_game_bootstrap_ci95": v2_pairs["winner_brier"]["paired_game_bootstrap_ci95"],
                    "n": v2_pairs["winner_brier"]["n"]},
                "final_score_energy_baseline_minus_candidate": {
                    "mean_delta": v2_pairs["final_score_energy_score"]["v2_minus_candidate_mean"],
                    "paired_game_bootstrap_ci95": v2_pairs["final_score_energy_score"]["paired_game_bootstrap_ci95"],
                    "n": v2_pairs["final_score_energy_score"]["n"]},
                "team_sog_crps_baseline_minus_candidate": {
                    "mean_delta": None, "paired_game_bootstrap_ci95": None, "n": 0},
            },
        }
        trace = simulation_results[name]["traces"]
        candidate_results[name] = {
            "simulation_metrics": {key: value for key, value in metrics.items()
                                   if key not in {"paired_game_rows"}},
            "count_diagnostics": _count_diagnostics(
                fold.heldout_games, actual, trace),
            "simulation_components": _simulated_component_summary(
                fold.heldout_games, actual, trace, args.sims),
            "paired_comparisons": comparisons,
            "validated_simulations": metrics["validated_simulations"],
            "per_game_predictions": metrics["paired_game_rows"],
        }

    event_reports = {}
    for name, metric in event_raw.items():
        event_reports[name] = _event_metric_report(metric)
    event_reports["D state-conditioned quality"] = event_reports["Phase 2A"]
    baseline_diagnostics = candidate_results["Phase 2A"]["count_diagnostics"]
    location_composition = {
        name: row["simulation_components"]["location_composition"]
        for name, row in candidate_results.items()}

    frozen_development = frozen_evaluation["development_2021"]["conditional_simulation"]
    frozen_2022 = frozen_evaluation["final_holdout_2022"]
    v2_2022 = frozen_evaluation["existing_v2_comparison"]["final_holdout_2022"]
    later_data_status = {
        "pinned_frame_seasons": sorted({game.season for game in bundle.games.values()}),
        "pinned_frame_game_count": len(bundle.games),
        "later_complete_seasons_available": False,
        "prospective_2026_27_has_settled_outcomes": False,
        "local_sources_checked": [
            str(args.artifacts), str(args.official),
            "/root/lp-data/nhl-v3-phase1-replay-2026-10-21",
            str(REPO_ROOT / "research/nhl/prospective-2026-27"),
        ],
    }
    all_validations = sum(
        row["metrics"]["validated_simulations"] for row in simulation_results.values())
    if any(row["simulation_metrics"]["simulation_accounting_failures"] != 0
           for row in candidate_results.values()):
        raise ValueError("SIMULATION_ACCOUNTING_FAILURE_NONZERO")
    if any(row["validated_simulations"] != len(fold.heldout_games) * args.sims
           for row in candidate_results.values()):
        raise ValueError("CANDIDATE_VALIDATION_COVERAGE_FAILURE")

    result = {
        "base_commit": "19bb60cf8997abe1368b732983a4ed2ac1904cd3",
        "branch": "research/nhl-v3-phase2b-scoring-2026-10-21",
        "seed": args.seed,
        "simulations_per_game": args.sims,
        "selection_population": "2021 forward development; V3 and v2 fit only on 2018-2020",
        "selection_used_2022": False,
        "source_pins": bundle.pins,
        "v2_source_pins": v2_source,
        "frozen_phase2a_hashes": frozen_hashes,
        "frozen_phase2a_2021_metrics_128_sim": {
            key: frozen_development[key] for key in (
                "team_sog_crps", "reg_ot_team_goal_crps", "winner_brier",
                "final_score_energy_score", "runtime_seconds", "games",
                "eligible_team_sog_games", "validated_simulations")
        },
        "historical_exposed_2022_phase2a": {
            "conditional_simulation": {
                key: frozen_2022["conditional_simulation"].get(key)
                for key in ("team_sog_crps", "reg_ot_team_goal_crps", "winner_brier",
                            "final_score_energy_score", "runtime_seconds", "games",
                            "eligible_team_sog_games", "validated_simulations")},
            "paired_comparison_to_simple_rate": frozen_2022.get("paired_comparison"),
            "simple_rate_simulation": {
                key: frozen_2022["simple_rate_simulation"].get(key)
                for key in ("team_sog_crps", "reg_ot_team_goal_crps", "winner_brier",
                            "final_score_energy_score", "runtime_seconds", "games",
                            "eligible_team_sog_games", "validated_simulations")},
            "same_window_v2_comparison": {
                "metrics": {key: v2_2022["metrics"].get(key) for key in (
                    "reg_ot_team_goal_crps", "winner_brier", "final_score_energy_score",
                    "runtime_seconds", "games")},
                "paired_vs_stochastic": v2_2022.get("paired_vs_stochastic"),
            },
            "reused_for_tuning": False,
        },
        "development": {
            "games": len(fold.heldout_games),
            "sog_eligible_games": sum(game.sog_eligible for game in fold.heldout_games),
            "fit_games": fold.train_counts["fit_games"],
            "training_counts": fold.train_counts,
            "simulations_per_game": args.sims,
            "seed_formula": "seed + game_index * 1000003 + trial; same seed set for all V3 candidates and matched references",
            "same_window_v2_fit_games": fold.v2_training_games,
            "same_window_v2_metrics": {key: value for key, value in v2_metrics.items()
                                        if key not in {"per_game_predictions"}},
            "population_conversion_calibration": calibration,
            "rolling_goal_feature_protocol": {
                "window_games": ROLLING_WINDOW,
                "prior_games": ROLLING_PRIOR_GAMES,
                "fit_only_league_goal_mean": league_goal_mean,
                "per_game": rolling_feature_meta,
                "per_game_history_diagnostics": rolling_meta,
            },
            "v2_team_strength_features": {
                "training_seasons": list(FIT_SEASONS),
                "second_stage_fit": False,
                "source_sha256": v2_rating_sha,
                "per_game": v2_feature_meta,
                "per_game_rating_terms": v2_feature_values,
            },
            "v2_goal_prior_offsets": {
                "offset": "log(v2 pregame expected goals / Phase 2A pregame simulated goal mean)",
                "feature_sha256": _sha256_json({"v2": v2_rating_sha, "v3": v3_model_sha}),
                "per_game": c_prior,
                "feature_availability": c_feature_meta,
            },
            "state_location_pool": pool_metadata,
            "event_level_diagnostics": event_reports,
            "baseline_diagnostics": baseline_diagnostics,
            "candidate_results": candidate_results,
            "reference_results": {
                "Simple historical-rate": {
                    "simulation_metrics": {key: value for key, value in simple_metrics.items()
                                           if key != "paired_game_rows"},
                    "count_diagnostics": _count_diagnostics(
                        fold.heldout_games, actual, simple_trace),
                    "simulation_components": _simulated_component_summary(
                        fold.heldout_games, actual, simple_trace, args.sims),
                    "per_game_predictions": simple_metrics["paired_game_rows"],
                },
                "Same-window v2 refit": {
                    "simulation_metrics": {key: value for key, value in v2_metrics.items()
                                           if key != "per_game_predictions"},
                    "per_game_predictions": v2_metrics["per_game_predictions"],
                },
            },
            "shot_quality_composition_by_candidate": location_composition,
            "all_validated_simulations": all_validations,
            "all_simulation_validation_enabled": True,
            "all_prediction_features_pregame_eligible": True,
            "actual_goalie_information_used": False,
        },
        "later_evaluation_data_status": later_data_status,
        "decision": _decision_summary(candidate_results),
    }

    # Include per-game Phase 2A and candidate rows; remove bulky trace objects.
    result["command"] = {
        "script": str(HERE / "run_phase2b.py"),
        "arguments": ["--sims", str(args.sims), "--seed", str(args.seed)],
        "artifacts": str(args.artifacts), "official": str(args.official),
        "labels": str(args.labels), "v2_canonical": str(args.v2_canonical),
    }
    (args.out_dir / "RESULTS.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_report(result, args.out_dir / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
