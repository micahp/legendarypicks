#!/usr/bin/env python3
"""Synthetic feasibility check for the Phase 2C allocation read criterion.

This consumes only the committed Phase 2A draw trace. It never imports or runs
the frozen simulator.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TRACE_PATH = HERE / "underdispersion-traces.json.gz"
RESULTS_PATH = HERE / "RESULTS.json"
PACE_PATH = HERE / "total_pace_split.json"
PREREG_PATH = HERE / "PHASE2C-ALLOC-PREREG.md"
SIGMA_GRID = (0.0, 0.10, 0.16, 0.24, 0.324, 0.45)
BASE_REPLICATE_SEED = 20261023
BOOTSTRAP_SEED = 20261022
BOOTSTRAP_BATCH_SIZE = 32
FROZEN_HASHES = {
    "EVALUATION.json": "24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930",
    "FITTED-MODEL.json": "8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb",
    "REPORT.md": "b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0",
}
FROZEN_DIR = ROOT / "research/nhl/nhl-v3-phase2a-stochastic-2026-10-21"
GH_NODES, GH_WEIGHTS = np.polynomial.hermite.hermgauss(32)
GH_U = math.sqrt(2.0) * GH_NODES
GH_WEIGHTS = GH_WEIGHTS / math.sqrt(math.pi)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_hashes() -> dict[str, str]:
    actual = {name: sha256_file(FROZEN_DIR / name) for name in FROZEN_HASHES}
    if actual != FROZEN_HASHES:
        raise RuntimeError(f"FROZEN_PHASE2A_HASH_MISMATCH: {actual}")
    return actual


def _expit(values: np.ndarray | float) -> np.ndarray:
    """Overflow-safe logistic function, preserving the input shape."""
    array = np.asarray(values, dtype=float)
    flat = array.reshape(-1)
    result = np.empty_like(flat)
    positive = flat >= 0.0
    result[positive] = 1.0 / (1.0 + np.exp(-flat[positive]))
    exp_values = np.exp(flat[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result.reshape(array.shape)


def mean_preserving_offset(p0: float | np.ndarray, sigma: float) -> float | np.ndarray:
    """Solve the 32-point Gauss-Hermite mean-preserving logit offset."""
    if not math.isfinite(sigma) or sigma < 0.0:
        raise ValueError("SIGMA_MUST_BE_FINITE_AND_NONNEGATIVE")
    source = np.asarray(p0, dtype=float)
    if np.any(~np.isfinite(source)) or np.any((source < 0.0) | (source > 1.0)):
        raise ValueError("P0_OUTSIDE_UNIT_INTERVAL")
    original_shape = source.shape
    flat = source.reshape(-1)
    offsets = np.zeros_like(flat)
    interior = (flat > 0.0) & (flat < 1.0)
    if sigma == 0.0 or not np.any(interior):
        return float(offsets[0]) if source.ndim == 0 else offsets.reshape(original_shape)

    target = flat[interior]
    logit = np.log(target) - np.log1p(-target)
    low = np.full_like(target, -40.0)
    high = np.full_like(target, 40.0)
    for _ in range(80):
        middle = (low + high) * 0.5
        probabilities = _expit(logit[:, None] + middle[:, None] + sigma * GH_U[None, :])
        expectation = probabilities @ GH_WEIGHTS
        too_low = expectation < target
        low = np.where(too_low, middle, low)
        high = np.where(too_low, high, middle)
    solved = (low + high) * 0.5
    calibrated = _expit(logit[:, None] + solved[:, None] + sigma * GH_U[None, :]) @ GH_WEIGHTS
    if float(np.max(np.abs(calibrated - target), initial=0.0)) >= 1e-12:
        raise RuntimeError("MEAN_PRESERVING_OFFSET_FAILED_1E12")
    offsets[interior] = solved
    return float(offsets[0]) if source.ndim == 0 else offsets.reshape(original_shape)


def crps_ensemble(samples: np.ndarray | list[int], observation: int) -> float:
    """Exact CRPS for an equally weighted empirical ensemble of integer counts."""
    values = np.asarray(samples)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("CRPS_REQUIRES_NONEMPTY_ONE_DIMENSIONAL_ENSEMBLE")
    if np.any(values < 0) or np.any(values != np.floor(values)):
        raise ValueError("CRPS_COUNTS_MUST_BE_NONNEGATIVE_INTEGERS")
    ordered = np.sort(values.astype(np.float64))
    count = ordered.size
    coefficients = 2.0 * np.arange(count, dtype=float) - count + 1.0
    pairwise_half = float(np.dot(coefficients, ordered) / (count * count))
    return float(np.mean(np.abs(ordered - observation)) - pairwise_half)


def crps_by_game(samples: np.ndarray, observed: np.ndarray) -> np.ndarray:
    """Return each game's mean of its two team CRPS values."""
    predictions = np.asarray(samples)
    targets = np.asarray(observed)
    if predictions.ndim != 3 or predictions.shape[2] != 2:
        raise ValueError("CRPS_PREDICTIONS_EXPECTED_GAMES_DRAWS_TEAMS")
    if targets.shape != (predictions.shape[0], 2):
        raise ValueError("CRPS_TARGET_SHAPE_MISMATCH")
    scores = np.empty((predictions.shape[0], 2), dtype=float)
    for game_index in range(predictions.shape[0]):
        for team_index in range(2):
            scores[game_index, team_index] = crps_ensemble(
                predictions[game_index, :, team_index], int(targets[game_index, team_index])
            )
    return scores.mean(axis=1)


def moments(pairs: np.ndarray) -> dict[str, float]:
    values = np.asarray(pairs, dtype=float).reshape(-1, 2)
    home = values[:, 0]
    away = values[:, 1]
    return {
        "variance_home": float(np.var(home)),
        "variance_away": float(np.var(away)),
        "covariance_home_away": float(np.mean((home - home.mean()) * (away - away.mean()))),
        "variance_home_minus_away": float(np.var(home - away)),
    }


def _kernel(pairs: np.ndarray) -> dict[str, np.ndarray]:
    values = np.asarray(pairs, dtype=np.int64)
    if values.ndim != 3 or values.shape[2] != 2:
        raise ValueError("SPLIT_INPUT_EXPECTED_GAMES_DRAWS_TEAMS")
    total = values.sum(axis=2)
    home = values[:, :, 0]
    p0 = np.zeros(total.shape, dtype=float)
    nonzero = total > 0
    p0[nonzero] = home[nonzero] / total[nonzero]
    logit = np.zeros_like(p0)
    interior = (p0 > 0.0) & (p0 < 1.0)
    logit[interior] = np.log(p0[interior]) - np.log1p(-p0[interior])
    logit[p0 == 0.0] = -np.inf
    logit[p0 == 1.0] = np.inf
    unique, inverse = np.unique(p0, return_inverse=True)
    return {
        "pairs": values,
        "total": total,
        "p0": p0,
        "logit": logit,
        "unique_p0": unique,
        "inverse": inverse.reshape(p0.shape),
        "interior": interior,
    }


def _centered_logits(kernel: dict[str, np.ndarray], sigma: float) -> np.ndarray:
    unique_offsets = np.asarray(mean_preserving_offset(kernel["unique_p0"], sigma))
    offsets = unique_offsets[kernel["inverse"]]
    return kernel["logit"] + offsets


def resplit_counts(
    pairs: np.ndarray,
    sigma: float,
    u: np.ndarray,
    rng: np.random.Generator,
    *,
    centered_logits: np.ndarray | None = None,
) -> np.ndarray:
    """Reallocate a fixed total; σ=0 is an exact no-RNG identity branch."""
    source = np.asarray(pairs, dtype=np.int64)
    if sigma == 0.0:
        return source.copy()
    if not math.isfinite(sigma) or sigma < 0.0:
        raise ValueError("SIGMA_MUST_BE_FINITE_AND_NONNEGATIVE")
    model = _kernel(source) if centered_logits is None else None
    center = _centered_logits(model, sigma) if centered_logits is None else centered_logits
    latent = np.asarray(u, dtype=float)
    if latent.shape != source.shape[:2]:
        raise ValueError("SHARED_LATENT_SHAPE_MISMATCH")
    probability = _expit(center + sigma * latent)
    total = source.sum(axis=2)
    home = rng.binomial(total, probability)
    away = total - home
    result = np.stack((home, away), axis=2)
    if not np.array_equal(result.sum(axis=2), total):
        raise RuntimeError("RESPLIT_TOTAL_DID_NOT_RECONCILE")
    return result


def _population_variance_from_game_moments(
    first: np.ndarray, second: np.ndarray, indices: np.ndarray
) -> np.ndarray:
    means = first[indices].mean(axis=1)
    seconds = second[indices].mean(axis=1)
    return seconds - means * means


def paired_margin_variance_bootstrap(
    baseline_pairs: np.ndarray,
    candidate_pairs: np.ndarray,
    bootstrap_indices: np.ndarray,
    *,
    batch_size: int = BOOTSTRAP_BATCH_SIZE,
) -> dict[str, float]:
    """Paired game-cluster percentile interval, retaining every draw per game."""
    baseline_margin = np.asarray(baseline_pairs, dtype=float)[:, :, 0] - np.asarray(
        baseline_pairs, dtype=float
    )[:, :, 1]
    candidate_margin = np.asarray(candidate_pairs, dtype=float)[:, :, 0] - np.asarray(
        candidate_pairs, dtype=float
    )[:, :, 1]
    if baseline_margin.shape != candidate_margin.shape:
        raise ValueError("PAIRED_MARGIN_SHAPE_MISMATCH")
    base_first = baseline_margin.mean(axis=1)
    base_second = np.square(baseline_margin).mean(axis=1)
    cand_first = candidate_margin.mean(axis=1)
    cand_second = np.square(candidate_margin).mean(axis=1)
    deltas = np.empty(bootstrap_indices.shape[0], dtype=float)
    for start in range(0, bootstrap_indices.shape[0], batch_size):
        stop = min(start + batch_size, bootstrap_indices.shape[0])
        sampled_ids = bootstrap_indices[start:stop]
        base_var = _population_variance_from_game_moments(base_first, base_second, sampled_ids)
        cand_var = _population_variance_from_game_moments(cand_first, cand_second, sampled_ids)
        deltas[start:stop] = cand_var - base_var
    lower, upper = np.quantile(deltas, (0.025, 0.975))
    return {
        "lower_95": float(lower),
        "upper_95": float(upper),
        "bootstrap_replicates": int(bootstrap_indices.shape[0]),
        "interval_wholly_above_zero": bool(lower > 0.0),
    }


def wilson_interval(successes: int, trials: int, confidence_z: float = 1.959963984540054) -> list[float]:
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("INVALID_WILSON_COUNTS")
    if successes == 0:
        z2 = confidence_z * confidence_z
        upper = z2 / (trials + z2)
        return [0.0, float(upper)]
    if successes == trials:
        z2 = confidence_z * confidence_z
        lower = trials / (trials + z2)
        return [float(lower), 1.0]
    proportion = successes / trials
    z2 = confidence_z * confidence_z
    denominator = 1.0 + z2 / trials
    center = (proportion + z2 / (2.0 * trials)) / denominator
    half_width = confidence_z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z2 / (4.0 * trials * trials)
    ) / denominator
    return [float(max(0.0, center - half_width)), float(min(1.0, center + half_width))]


def _rate_summary(values: list[bool]) -> dict[str, Any]:
    passed = int(sum(values))
    trials = len(values)
    return {
        "passed": passed,
        "trials": trials,
        "rate": passed / trials,
        "wilson_95": wilson_interval(passed, trials),
    }


def _load_inputs() -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    with gzip.open(TRACE_PATH, "rt", encoding="utf-8") as handle:
        trace = json.load(handle)
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    pace = json.loads(PACE_PATH.read_text(encoding="utf-8"))
    games = trace["games"]
    if trace.get("metadata", {}).get("monte_carlo_rerun") is not False:
        raise RuntimeError("TRACE_MUST_BE_COMMITTED_NO_RERUN_PHASE2A_OUTPUT")
    game_ids = [str(row["game_id"]) for row in games]
    if len(game_ids) != 1312 or len(set(game_ids)) != len(game_ids):
        raise RuntimeError(f"UNEXPECTED_GAME_POPULATION: {len(game_ids)}")
    eligible = np.asarray([bool(row["sog_eligible"]) for row in games], dtype=bool)
    if int(eligible.sum()) != 1292:
        raise RuntimeError(f"UNEXPECTED_SOG_ELIGIBILITY: {int(eligible.sum())}")
    attempts = np.asarray([row["phase2a"]["attempts"] for row in games], dtype=np.int64)
    sog = np.asarray([row["phase2a"]["sog"] for row in games], dtype=np.int64)
    if attempts.shape != (1312, 16, 2) or sog.shape != (1312, 16, 2):
        raise RuntimeError(f"UNEXPECTED_TRACE_SHAPE: attempts={attempts.shape} sog={sog.shape}")
    if np.any(attempts < 0) or np.any(sog < 0) or np.any(sog > attempts):
        raise RuntimeError("INVALID_BASELINE_TRACE_COUNTS")
    official_sog = np.asarray(
        [[row["observed"]["official_sog"]["home"], row["observed"]["official_sog"]["away"]]
         for row in games if row["sog_eligible"]], dtype=np.int64
    )
    baseline_score = float(
        results["development"]["candidate_results"]["Phase 2A"]["simulation_metrics"]["team_sog_crps"]
    )
    expected_attempt = pace["outcomes"]["attempts"]["generated"]
    expected_sog = pace["outcomes"]["sog"]["generated"]
    inputs = {
        "game_ids": np.asarray(game_ids, dtype=object),
        "sog_eligible": eligible,
        "attempts": attempts,
        "sog": sog,
        "official_sog": official_sog,
    }
    targets = {
        "phase2a_sog_crps": baseline_score,
        "generated_attempt_moments": expected_attempt,
        "generated_sog_moments": expected_sog,
        "observed_attempt_moments": pace["outcomes"]["attempts"]["observed"],
        "observed_sog_moments": pace["outcomes"]["sog"]["observed"],
        "target_attempt_variance_margin": 244.667,
        "trace_population": int(len(games)),
        "sog_eligible_games": int(eligible.sum()),
    }
    return trace, inputs, targets


def baseline_check(inputs: dict[str, np.ndarray], targets: dict[str, Any]) -> dict[str, Any]:
    attempts = inputs["attempts"]
    sog = inputs["sog"][inputs["sog_eligible"]]
    sog_crps_by_game = crps_by_game(sog, inputs["official_sog"])
    attempt_moments = moments(attempts)
    sog_moments = moments(sog)
    discrepancies: dict[str, float] = {}
    for label, actual, expected in (
        ("sog_crps", float(sog_crps_by_game.mean()), targets["phase2a_sog_crps"]),
        *[(f"attempt_{name}", attempt_moments[name], float(targets["generated_attempt_moments"][name]))
          for name in attempt_moments],
        *[(f"sog_{name}", sog_moments[name], float(targets["generated_sog_moments"][name]))
          for name in sog_moments],
    ):
        discrepancies[label] = float(actual - expected)
    if max((abs(value) for value in discrepancies.values()), default=0.0) > 1e-10:
        raise RuntimeError(f"BASELINE_REPRODUCTION_FAILED: {discrepancies}")
    return {
        "passed": True,
        "phase2a_sog_crps": float(sog_crps_by_game.mean()),
        "phase2a_sog_crps_target": targets["phase2a_sog_crps"],
        "attempt_generated_moments": attempt_moments,
        "attempt_observed_moments": {
            key: float(targets["observed_attempt_moments"][key]) for key in attempt_moments
        },
        "sog_generated_moments_eligible_games_only": sog_moments,
        "sog_observed_moments": {
            key: float(targets["observed_sog_moments"][key]) for key in sog_moments
        },
        "max_abs_discrepancy_from_committed_targets": max(map(abs, discrepancies.values())),
        "discrepancies": discrepancies,
        "sog_eligibility_applied_to_generated_and_observed_moments": True,
    }


def _make_bootstrap_indices(game_count: int, count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, game_count, size=(count, game_count), dtype=np.int32)


def _interpolated_crossing(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row["sigma"])
    for row in ordered:
        if row["rates"]["joint"]["rate"] >= threshold:
            sigma = row["sigma"]
            prior = [item for item in ordered if item["sigma"] < sigma]
            if not prior:
                return {"first_tested_sigma": sigma, "linear_interpolation": sigma}
            low = max(prior, key=lambda item: item["sigma"])
            x0, y0 = low["sigma"], low["rates"]["joint"]["rate"]
            x1, y1 = sigma, row["rates"]["joint"]["rate"]
            interpolated = x1 if y1 == y0 else x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
            return {"first_tested_sigma": sigma, "linear_interpolation": float(interpolated)}
    return {"first_tested_sigma": None, "linear_interpolation": None, "within_tested_grid": False}


def run_experiment(
    replicates: int = 100,
    sigmas: tuple[float, ...] = SIGMA_GRID,
    bootstrap_replicates: int = 2000,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if replicates < 50:
        raise ValueError("PREREGISTERED_REPLICATES_REQUIRE_R_AT_LEAST_50")
    if bootstrap_replicates != 2000:
        raise ValueError("PREREGISTERED_RULE_REQUIRES_2000_BOOTSTRAPS")
    if not sigmas or any((not math.isfinite(value) or value < 0.0) for value in sigmas):
        raise ValueError("INVALID_SIGMA_GRID")

    started = time.perf_counter()
    frozen_before = verify_frozen_hashes()
    trace, inputs, targets = _load_inputs()
    base_attempts = inputs["attempts"]
    base_sog = inputs["sog"]
    sog_mask = inputs["sog_eligible"]
    baseline_crps = crps_by_game(base_sog[sog_mask], inputs["official_sog"])
    baseline_attempt_margin_variance = moments(base_attempts)["variance_home_minus_away"]
    check = baseline_check(inputs, targets)
    if not check["passed"]:
        raise RuntimeError("BASELINE_CHECK_DID_NOT_PASS")

    attempt_kernel = _kernel(base_attempts)
    sog_kernel = _kernel(base_sog)
    seed_list = [BASE_REPLICATE_SEED + index for index in range(replicates)]
    bootstrap_indices = _make_bootstrap_indices(
        base_attempts.shape[0], bootstrap_replicates, BOOTSTRAP_SEED
    )
    per_sigma: list[dict[str, Any]] = []
    sigma_zero_identity_validation: dict[str, Any] | None = None
    total_pair_total_assertions = 0

    for sigma in sigmas:
        attempt_center = _centered_logits(attempt_kernel, sigma)
        sog_center = _centered_logits(sog_kernel, sigma)
        replicate_rows: list[dict[str, Any]] = []
        for replicate_index, seed in enumerate(seed_list):
            if sigma == 0.0:
                candidate_attempts = base_attempts.copy()
                candidate_sog = base_sog.copy()
                sigma_zero_identity_validation = {
                    "attempt_trace_byte_equal": candidate_attempts.tobytes() == base_attempts.tobytes(),
                    "sog_trace_byte_equal": candidate_sog.tobytes() == base_sog.tobytes(),
                    "attempt_moments_float_equal": moments(candidate_attempts) == moments(base_attempts),
                    "sog_eligible_moments_float_equal": (
                        moments(candidate_sog[sog_mask]) == moments(base_sog[sog_mask])
                    ),
                }
                if not all(sigma_zero_identity_validation.values()):
                    raise RuntimeError("SIGMA_ZERO_IDENTITY_ASSERTION_FAILED")
            else:
                rng = np.random.default_rng(seed)
                shared_u = rng.standard_normal(base_attempts.shape[:2])
                candidate_attempts = resplit_counts(
                    base_attempts, sigma, shared_u, rng, centered_logits=attempt_center
                )
                candidate_sog = resplit_counts(
                    base_sog, sigma, shared_u, rng, centered_logits=sog_center
                )
            if not np.array_equal(candidate_attempts.sum(axis=2), base_attempts.sum(axis=2)):
                raise RuntimeError(f"ATTEMPT_TOTAL_CHANGED/{sigma}/{seed}")
            if not np.array_equal(candidate_sog.sum(axis=2), base_sog.sum(axis=2)):
                raise RuntimeError(f"SOG_TOTAL_CHANGED/{sigma}/{seed}")
            total_pair_total_assertions += 2
            team_draw_violations = candidate_sog > candidate_attempts
            violating_team_draw_cells = int(team_draw_violations.sum())
            game_draws_with_any_violation = int(team_draw_violations.any(axis=2).sum())

            crps_delta = crps_by_game(candidate_sog[sog_mask], inputs["official_sog"]) - baseline_crps
            mean_crps_delta = float(crps_delta.mean())
            candidate_margin_variance = moments(candidate_attempts)["variance_home_minus_away"]
            margin_bootstrap = paired_margin_variance_bootstrap(
                base_attempts, candidate_attempts, bootstrap_indices
            )
            condition_a = mean_crps_delta <= 0.0
            condition_b = (
                candidate_margin_variance >= targets["target_attempt_variance_margin"]
                and margin_bootstrap["interval_wholly_above_zero"]
            )
            replicate_rows.append({
                "replicate": replicate_index,
                "seed": seed,
                "mean_paired_team_sog_crps_delta_candidate_minus_phase2a": mean_crps_delta,
                "condition_a_sog_crps_nonworsening": bool(condition_a),
                "attempt_variance_home_minus_away": candidate_margin_variance,
                "attempt_margin_variance_delta_vs_phase2a": (
                    candidate_margin_variance - baseline_attempt_margin_variance
                ),
                "paired_game_cluster_bootstrap_margin_variance_delta_ci95": margin_bootstrap,
                "condition_b_margin_target_and_interval": bool(condition_b),
                "joint_pass": bool(condition_a and condition_b),
                "team_draw_cells_with_sog_greater_than_attempts": violating_team_draw_cells,
                "game_draws_with_any_team_sog_greater_than_attempts": game_draws_with_any_violation,
            })

        a_passes = [row["condition_a_sog_crps_nonworsening"] for row in replicate_rows]
        b_passes = [row["condition_b_margin_target_and_interval"] for row in replicate_rows]
        interval_passes = [
            row["paired_game_cluster_bootstrap_margin_variance_delta_ci95"]["interval_wholly_above_zero"]
            for row in replicate_rows
        ]
        joint_passes = [row["joint_pass"] for row in replicate_rows]
        crps_deltas = np.asarray([
            row["mean_paired_team_sog_crps_delta_candidate_minus_phase2a"] for row in replicate_rows
        ])
        candidate_variances = np.asarray([
            row["attempt_variance_home_minus_away"] for row in replicate_rows
        ])
        violating_cells = np.asarray([
            row["team_draw_cells_with_sog_greater_than_attempts"] for row in replicate_rows
        ])
        violating_game_draws = np.asarray([
            row["game_draws_with_any_team_sog_greater_than_attempts"] for row in replicate_rows
        ])
        per_sigma.append({
            "sigma": float(sigma),
            "rates": {
                "condition_a_sog_crps_nonworsening": _rate_summary(a_passes),
                "condition_b_margin_target_and_interval": _rate_summary(b_passes),
                "condition_b_interval_only": _rate_summary(interval_passes),
                "joint": _rate_summary(joint_passes),
            },
            "sog_crps": {
                "phase2a_baseline": float(baseline_crps.mean()),
                "mean_candidate": float(baseline_crps.mean() + crps_deltas.mean()),
                "mean_paired_delta_candidate_minus_phase2a": float(crps_deltas.mean()),
                "replicate_delta_percentiles_2_5_50_97_5": [
                    float(value) for value in np.quantile(crps_deltas, (0.025, 0.5, 0.975))
                ],
            },
            "attempt_margin_variance": {
                "phase2a_baseline": baseline_attempt_margin_variance,
                "target": targets["target_attempt_variance_margin"],
                "candidate_replicate_mean": float(candidate_variances.mean()),
                "candidate_replicate_percentiles_2_5_50_97_5": [
                    float(value) for value in np.quantile(candidate_variances, (0.025, 0.5, 0.975))
                ],
                "fraction_meeting_point_target": float(np.mean(
                    candidate_variances >= targets["target_attempt_variance_margin"]
                )),
            },
            "synthetic_side_level_sog_attempt_relation": {
                "team_draw_cells_possible_per_dataset": int(base_attempts.shape[0] * base_attempts.shape[1] * 2),
                "mean_team_draw_cells_with_sog_greater_than_attempts": float(violating_cells.mean()),
                "datasets_with_any_team_draw_violation": int(np.count_nonzero(violating_cells)),
                "datasets": replicates,
                "mean_game_draws_with_any_team_violation": float(violating_game_draws.mean()),
            },
            "replicates": replicate_rows,
        })

    frozen_after = verify_frozen_hashes()
    if frozen_before != frozen_after:
        raise RuntimeError("FROZEN_PHASE2A_CHANGED_DURING_RUN")

    thresholds = {
        "joint_pass_rate_50_percent": _interpolated_crossing(per_sigma, 0.50),
        "joint_pass_rate_80_percent": _interpolated_crossing(per_sigma, 0.80),
    }
    sigma_zero = next((row for row in per_sigma if row["sigma"] == 0.0), None)
    if sigma_zero is None:
        sigma_zero_false_positive = None
    else:
        sigma_zero_false_positive = sigma_zero["rates"]["condition_b_interval_only"]["rate"]
    diagnostic_row = next((row for row in per_sigma if math.isclose(row["sigma"], 0.324, abs_tol=1e-12)), None)
    result: dict[str, Any] = {
        "title": "Phase 2C pre-registered rule feasibility, synthetic only",
        "classification": "DIAGNOSTIC_ONLY_NO_CANDIDATE_SELECTION_NO_GATE_CHANGE",
        "base_commit": "7cd37e0c8562dcfd4e75d8485dc09b92461f9b14",
        "branch": "research/nhl-v3-prereg-feasibility-2026-10-21",
        "input_hashes_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in (TRACE_PATH, RESULTS_PATH, PACE_PATH, PREREG_PATH)
        },
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "frozen_phase2a_hashes_before": frozen_before,
        "frozen_phase2a_hashes_after": frozen_after,
        "baseline_reproduction": check,
        "sigma_zero_identity_validation": sigma_zero_identity_validation,
        "synthetic_accounting": {
            "attempt_and_sog_pair_totals_preserved_for_every_game_draw": True,
            "pair_total_equality_assertions": total_pair_total_assertions,
            "pair_total_equality_assertion_failures": 0,
            "side_level_sog_exceeds_attempts_is_measured_not_rejected": True,
        },
        "protocol": {
            "sigma_grid": [float(value) for value in sigmas],
            "replicates_per_sigma": replicates,
            "replicate_seed_formula": f"{BASE_REPLICATE_SEED} + zero_based_replicate_index",
            "replicate_seeds": seed_list,
            "numpy_rng": "PCG64 via numpy.random.default_rng",
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "game ID; both teams and all 16 fixed draws retained together",
            "bootstrap_pairing": "same game-ID resample indices for candidate and Phase 2A; same indices reused across all synthetic replicates",
            "bootstrap_memory": "32 bootstrap resamples processed at a time; no replicate-by-game-by-bootstrap tensor",
            "quadrature": "32-point Gauss-Hermite; calibrated mean absolute error < 1e-12",
            "common_random_numbers": "within replicate, all positive sigma values reuse the replicate seed; one standard-normal u per game draw is shared by attempts and SOG",
            "sog_eligibility": "1292 accepted official-SOG games; same mask used for Phase 2A and every synthetic SOG CRPS",
        },
        "rules": {
            "condition_a": "mean paired per-game average-of-two-team SOG CRPS delta (synthetic - Phase 2A) <= 0",
            "condition_b": "attempt Var(H-A) >= 244.667 and paired 95% game-cluster percentile interval for synthetic-minus-Phase-2A Var(H-A) wholly above zero",
            "joint": "condition_a AND condition_b",
            "interval_only_false_positive_rate_at_sigma_zero": sigma_zero_false_positive,
            "sigma_zero_condition_b_rate": (
                None if sigma_zero is None else sigma_zero["rates"]["condition_b_margin_target_and_interval"]["rate"]
            ),
            "sigma_zero_joint_rate": (
                None if sigma_zero is None else sigma_zero["rates"]["joint"]["rate"]
            ),
            "diagnostic_sigma_0_324": None if diagnostic_row is None else {
                "condition_a": diagnostic_row["rates"]["condition_a_sog_crps_nonworsening"],
                "condition_b": diagnostic_row["rates"]["condition_b_margin_target_and_interval"],
                "condition_b_interval_only": diagnostic_row["rates"]["condition_b_interval_only"],
                "joint": diagnostic_row["rates"]["joint"],
                "attempt_margin_variance": diagnostic_row["attempt_margin_variance"],
                "sog_crps": diagnostic_row["sog_crps"],
            },
            "joint_rate_crossings": thresholds,
        },
        "interpretation_limits": [
            "This is a synthetic redistribution of committed Phase 2A per-draw team counts, not a simulator run.",
            "Event-level dependence is ignored; attempt totals remain the exact Phase 2A draw totals; there is no per-period redraw.",
            "Attempts and SOG pairs are resplit separately. This can produce a side-level SOG count greater than that side's attempt count; the rate is measured per sigma and is not a physically valid event reconstruction.",
            "For sigma > 0, H' is newly sampled from Binomial(N,pH). At sigma = 0, exact identity is required. The positive-sigma resampling therefore has an extra conditional-binomial noise component and a discontinuity at zero.",
            "The synthetic generator reuses only stored Phase 2A totals and splits. It does not reconstruct event paths, locations, shooter identities, goals, special teams, regulation, overtime, or shootouts.",
            "A paired sigma-zero bootstrap is degenerate under exact identity: every paired variance difference is exactly zero, so the interval-only false-positive rate is 0%, not approximately 2.5%. The brief's 2.5% expectation conflicts with its identity and paired-bootstrap requirements.",
            "Wilson intervals quantify Monte Carlo pass-rate precision across the R synthetic datasets, not uncertainty from a future season.",
        ],
        "runtime_seconds": float(time.perf_counter() - started),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "results_by_sigma": per_sigma,
    }
    if output_path is not None:
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=100)
    parser.add_argument("--sigmas", type=float, nargs="+", default=list(SIGMA_GRID))
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=HERE / "rule_feasibility.json")
    args = parser.parse_args()
    result = run_experiment(
        replicates=args.replicates,
        sigmas=tuple(args.sigmas),
        bootstrap_replicates=args.bootstrap_replicates,
        output_path=args.output,
    )
    print(json.dumps({
        "output": str(args.output),
        "runtime_seconds": result["runtime_seconds"],
        "replicates_per_sigma": args.replicates,
        "results_by_sigma": [
            {
                "sigma": row["sigma"],
                "condition_a_rate": row["rates"]["condition_a_sog_crps_nonworsening"]["rate"],
                "condition_b_rate": row["rates"]["condition_b_margin_target_and_interval"]["rate"],
                "condition_b_interval_only_rate": row["rates"]["condition_b_interval_only"]["rate"],
                "joint_rate": row["rates"]["joint"]["rate"],
            }
            for row in result["results_by_sigma"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
