#!/usr/bin/env python3
"""Moment-matched Beta-Binomial SOG noise-floor diagnostic.

This reuses only the committed Phase 2A count trace. It does not run the
simulator, change attempts, or use actual-game predictors.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import betaln
from scipy.stats import binom

from rule_feasibility import (
    BASE_REPLICATE_SEED,
    BOOTSTRAP_SEED,
    GH_U,
    GH_WEIGHTS,
    SIGMA_GRID,
    _expit,
    _load_inputs,
    _make_bootstrap_indices,
    _rate_summary,
    mean_preserving_offset,
    sha256_file,
    verify_frozen_hashes,
)


HERE = Path(__file__).resolve().parent
RESULT_PATH = HERE / "kernel_noise_floor.json"
BOOTSTRAP_REPLICATES = 2000
DISPERSION_RATIO_BAND = (0.98, 1.02)


def _betabinomial_ppf_recurrence(
    uniforms: np.ndarray,
    attempts: np.ndarray,
    alpha: np.ndarray,
    beta: np.ndarray,
) -> np.ndarray:
    """Vectorized exact discrete inverse CDF using the beta-binomial PMF ratio."""
    unit, n, a, b = np.broadcast_arrays(
        np.asarray(uniforms, dtype=float),
        np.asarray(attempts, dtype=np.int64),
        np.asarray(alpha, dtype=float),
        np.asarray(beta, dtype=float),
    )
    if (
        np.any(~np.isfinite(unit))
        or np.any((unit < 0.0) | (unit >= 1.0))
        or np.any(n < 0)
        or np.any(~np.isfinite(a))
        or np.any(~np.isfinite(b))
        or np.any(a <= 0.0)
        or np.any(b <= 0.0)
    ):
        raise ValueError("INVALID_BETA_BINOMIAL_QUANTILE_INPUT")

    mass = np.exp(betaln(a, b + n) - betaln(a, b))
    mass = np.where(n == 0, 1.0, mass)
    cdf = np.minimum(mass, 1.0)
    output = np.zeros(n.shape, dtype=np.int64)
    unresolved = unit > cdf
    max_attempts = int(n.max(initial=0))
    for k in range(max_attempts):
        indices = np.flatnonzero(unresolved & (n > k))
        if indices.size == 0:
            break
        next_mass = mass[indices] * (
            (n[indices] - k)
            / float(k + 1)
            * (a[indices] + k)
            / (b[indices] + n[indices] - k - 1.0)
        )
        mass[indices] = next_mass
        cdf[indices] = np.minimum(1.0, cdf[indices] + next_mass)
        reached = unit[indices] <= cdf[indices]
        output[indices[reached]] = k + 1
        unresolved[indices[reached]] = False
    # At the final support point the exact CDF is one; roundoff can leave it a
    # few ulps below one for quantiles adjacent to one.
    output[unresolved] = n[unresolved]
    return output


def crps_by_game_vectorized(samples: np.ndarray, observed: np.ndarray) -> np.ndarray:
    """Vectorized empirical CRPS, algebraically identical to the reference helper."""
    predictions = np.asarray(samples)
    targets = np.asarray(observed)
    if predictions.ndim != 3 or predictions.shape[2] != 2:
        raise ValueError("CRPS_PREDICTIONS_EXPECTED_GAMES_DRAWS_TEAMS")
    if targets.shape != (predictions.shape[0], 2):
        raise ValueError("CRPS_TARGET_SHAPE_MISMATCH")
    if predictions.shape[1] == 0:
        raise ValueError("CRPS_REQUIRES_NONEMPTY_ENSEMBLE")
    ordered = np.sort(predictions.astype(np.float64), axis=1)
    draws = predictions.shape[1]
    coefficients = (2.0 * np.arange(draws) - draws + 1.0)[None, :, None]
    pairwise_half = np.sum(coefficients * ordered, axis=1) / float(draws * draws)
    absolute_term = np.mean(np.abs(predictions - targets[:, None, :]), axis=1)
    return np.mean(absolute_term - pairwise_half, axis=1)


def fit_beta_binomial_moments(
    attempts: np.ndarray, sog: np.ndarray
) -> dict[str, np.ndarray | int | float]:
    """Fit one Beta-Binomial per game-side by ensemble mean and variance.

    Attempt counts may vary across the 16 draws. The pooled conversion mean is
    sum(SOG)/sum(attempts). The sample variance uses ddof=1. Its method-of-
    moments baseline includes binomial conditional variance and the variation
    in expected counts caused by the fixed attempt sequence. Nonpositive excess
    variance falls back to Binomial; rho is capped just below one for a finite
    Beta concentration.
    """
    n = np.asarray(attempts, dtype=np.int64)
    y = np.asarray(sog, dtype=np.int64)
    if n.shape != y.shape or n.ndim != 3 or n.shape[-1] != 2:
        raise ValueError("ATTEMPT_SOG_SHAPE_MISMATCH")
    if n.shape[1] < 2:
        raise ValueError("BETA_BINOMIAL_MOMENTS_NEED_MULTIPLE_DRAWS")
    if np.any(n < 0) or np.any(y < 0) or np.any(y > n):
        raise ValueError("INVALID_CONDITIONAL_SOG_COUNTS")

    draws = n.shape[1]
    n_float = n.astype(float)
    y_float = y.astype(float)
    total_attempts = n_float.sum(axis=1)
    mean_rate = np.divide(
        y_float.sum(axis=1), total_attempts,
        out=np.zeros_like(total_attempts), where=total_attempts > 0,
    )
    observed_sample_variance = np.var(y_float, axis=1, ddof=1)
    mean_attempts = n_float.mean(axis=1)
    attempt_variance = np.var(n_float, axis=1, ddof=0)
    binomial_and_attempt_variance = (
        mean_rate * (1.0 - mean_rate) * mean_attempts
        + mean_rate * mean_rate * (draws / (draws - 1.0)) * attempt_variance
    )
    second_factorial_moment = np.mean(n_float * (n_float - 1.0), axis=1)
    excess_variance = observed_sample_variance - binomial_and_attempt_variance
    raw_probability_variance = np.divide(
        excess_variance,
        second_factorial_moment,
        out=np.zeros_like(excess_variance),
        where=second_factorial_moment > 0.0,
    )

    max_probability_variance = mean_rate * (1.0 - mean_rate)
    fallback = (excess_variance <= 0.0) | (second_factorial_moment <= 0.0) | (max_probability_variance <= 0.0)
    rho = np.divide(
        np.maximum(raw_probability_variance, 0.0),
        max_probability_variance,
        out=np.zeros_like(raw_probability_variance),
        where=max_probability_variance > 0.0,
    )
    upper_capped = (~fallback) & (rho >= 1.0)
    rho = np.where(fallback, 0.0, np.minimum(rho, 1.0 - 1e-8))
    concentration = np.divide(
        1.0 - rho, rho,
        out=np.full_like(rho, np.inf),
        where=rho > 0.0,
    )
    concentration = np.where(rho > 0.0, np.maximum(concentration, 1e-8), np.inf)

    return {
        "mean_rate": mean_rate,
        "rho": rho,
        "concentration": concentration,
        "observed_sample_variance": observed_sample_variance,
        "binomial_and_attempt_variance": binomial_and_attempt_variance,
        "second_factorial_moment": second_factorial_moment,
        "fallback_count": int(fallback.sum()),
        "upper_capped_count": int(upper_capped.sum()),
        "game_side_count": int(rho.size),
        "draw_count": int(draws),
    }


def beta_binomial_sog_draws(
    attempts: np.ndarray,
    fitted_mean_rate: np.ndarray,
    fitted_concentration: np.ndarray,
    sigma: float,
    shared_u: np.ndarray,
    uniforms: np.ndarray,
    *,
    centered_offsets: np.ndarray | None = None,
) -> np.ndarray:
    """Draw valid SOG counts with a fitted Beta-Binomial or Binomial fallback."""
    n = np.asarray(attempts, dtype=np.int64)
    mean = np.asarray(fitted_mean_rate, dtype=float)
    concentration = np.asarray(fitted_concentration, dtype=float)
    latent = np.asarray(shared_u, dtype=float)
    unit = np.asarray(uniforms, dtype=float)
    if n.ndim != 3 or n.shape[-1] != 2 or mean.shape != (n.shape[0], 2):
        raise ValueError("BETA_BINOMIAL_INPUT_SHAPE_MISMATCH")
    if concentration.shape != mean.shape or latent.shape != n.shape[:2] or unit.shape != n.shape:
        raise ValueError("BETA_BINOMIAL_RANDOM_INPUT_SHAPE_MISMATCH")
    if np.any(~np.isfinite(mean)) or np.any((mean < 0.0) | (mean > 1.0)):
        raise ValueError("BETA_BINOMIAL_MEAN_OUTSIDE_UNIT_INTERVAL")
    if np.any(np.isnan(concentration)) or np.any(concentration <= 0.0):
        raise ValueError("INVALID_BETA_CONCENTRATION")
    if not math.isfinite(sigma) or sigma < 0.0:
        raise ValueError("SIGMA_MUST_BE_FINITE_AND_NONNEGATIVE")
    if np.any(~np.isfinite(unit)) or np.any((unit < 0.0) | (unit >= 1.0)):
        raise ValueError("BINOMIAL_UNIFORMS_OUTSIDE_HALF_OPEN_UNIT_INTERVAL")

    mean_3d = np.broadcast_to(mean[:, None, :], n.shape)
    if sigma == 0.0:
        q = mean_3d
    else:
        offsets = (
            np.asarray(mean_preserving_offset(mean, sigma), dtype=float)
            if centered_offsets is None
            else np.asarray(centered_offsets, dtype=float)
        )
        if offsets.shape != mean.shape or np.any(~np.isfinite(offsets)):
            raise ValueError("BETA_BINOMIAL_OFFSET_SHAPE_OR_VALUE_INVALID")
        logits = np.full_like(mean, np.inf)
        interior = (mean > 0.0) & (mean < 1.0)
        logits[mean == 0.0] = -np.inf
        logits[interior] = np.log(mean[interior]) - np.log1p(-mean[interior])
        signs = np.asarray([1.0, -1.0])
        q_side = _expit(
            logits[:, None, :]
            + offsets[:, None, :]
            + sigma * latent[..., None] * signs
        )
        q = q_side

    bb_mask = (
        np.isfinite(concentration[:, None, :])
        & (concentration[:, None, :] > 0.0)
        & (q > 0.0)
        & (q < 1.0)
    )
    output = np.empty(n.shape, dtype=np.int64)
    if np.any(bb_mask):
        bb_values = _betabinomial_ppf_recurrence(
            unit[bb_mask],
            n[bb_mask],
            (q * concentration[:, None, :])[bb_mask],
            ((1.0 - q) * concentration[:, None, :])[bb_mask],
        )
        if np.any(~np.isfinite(bb_values)) or np.any(bb_values != np.floor(bb_values)):
            raise RuntimeError("BETA_BINOMIAL_QUANTILE_INVALID")
        output[bb_mask] = bb_values.astype(np.int64)
    zero_mask = q == 0.0
    one_mask = q == 1.0
    output[zero_mask] = 0
    output[one_mask] = n[one_mask]
    bin_mask = (~bb_mask) & (q > 0.0) & (q < 1.0)
    if np.any(bin_mask):
        bin_values = binom.ppf(unit[bin_mask], n[bin_mask], q[bin_mask])
        if np.any(~np.isfinite(bin_values)) or np.any(bin_values != np.floor(bin_values)):
            raise RuntimeError("BINOMIAL_QUANTILE_INVALID")
        output[bin_mask] = bin_values.astype(np.int64)
    if np.any(output < 0) or np.any(output > n):
        raise RuntimeError("BETA_BINOMIAL_SOG_EXCEEDS_ATTEMPTS")
    return output


def _bootstrap_mean_ci(game_deltas: np.ndarray, indices: np.ndarray) -> dict[str, Any]:
    means = np.asarray(game_deltas, dtype=float)[indices].mean(axis=1)
    lower, upper = np.quantile(means, (0.025, 0.975))
    return {
        "lower_95": float(lower),
        "upper_95": float(upper),
        "bootstrap_replicates": int(indices.shape[0]),
        "interval_contains_zero": bool(lower <= 0.0 <= upper),
        "interval_wholly_above_zero": bool(lower > 0.0),
        "interval_wholly_below_zero": bool(upper < 0.0),
    }


def _common_random_numbers(seed: int, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(shape[:2]), rng.random(shape)


def _dispersion_summary(values: np.ndarray, baseline_sd: float) -> dict[str, Any]:
    ratios = np.asarray(values, dtype=float) / baseline_sd
    return {
        "baseline_mean_per_side_ensemble_sd_ddof1": float(baseline_sd),
        "candidate_mean_per_side_ensemble_sd_ddof1": float(np.mean(values)),
        "candidate_to_phase2a_dispersion_ratio_mean": float(np.mean(ratios)),
        "candidate_to_phase2a_dispersion_ratio_replicate_percentiles_2_5_50_97_5": [
            float(v) for v in np.quantile(ratios, (0.025, 0.5, 0.975))
        ],
        "replicates_inside_required_0_98_1_02_band": int(
            np.count_nonzero((ratios >= DISPERSION_RATIO_BAND[0]) & (ratios <= DISPERSION_RATIO_BAND[1]))
        ),
        "replicates": int(ratios.size),
    }


def run_experiment(
    replicates: int = 100,
    sigmas: tuple[float, ...] = SIGMA_GRID,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    *,
    output_path: Path | None = RESULT_PATH,
) -> dict[str, Any]:
    if replicates < 100:
        raise ValueError("NOISE_FLOOR_REQUIRES_AT_LEAST_100_REPLICATES")
    if bootstrap_replicates != BOOTSTRAP_REPLICATES:
        raise ValueError("NOISE_FLOOR_REQUIRES_2000_BOOTSTRAPS")
    if tuple(sigmas) != tuple(SIGMA_GRID):
        raise ValueError("NOISE_FLOOR_REQUIRES_PREREGISTERED_SIGMA_GRID")

    started = time.perf_counter()
    frozen_before = verify_frozen_hashes()
    trace, inputs, targets = _load_inputs()
    eligible = inputs["sog_eligible"]
    attempts = inputs["attempts"][eligible]
    phase2a_sog = inputs["sog"][eligible]
    labels = inputs["official_sog"]
    baseline_game_crps = crps_by_game_vectorized(phase2a_sog, labels)
    baseline_crps = float(baseline_game_crps.mean())
    if abs(baseline_crps - float(targets["phase2a_sog_crps"])) > 1e-10:
        raise RuntimeError("PHASE2A_SOG_CRPS_BASELINE_MISMATCH")

    fit = fit_beta_binomial_moments(attempts, phase2a_sog)
    mean_rate = np.asarray(fit["mean_rate"], dtype=float)
    rho = np.asarray(fit["rho"], dtype=float)
    concentration = np.asarray(fit["concentration"], dtype=float)
    baseline_side_sd = np.std(phase2a_sog, axis=1, ddof=1).mean()
    bootstrap_indices = _make_bootstrap_indices(
        int(eligible.sum()), bootstrap_replicates, BOOTSTRAP_SEED
    )

    scores_by_sigma: dict[float, np.ndarray] = {}
    dispersions_by_sigma: dict[float, np.ndarray] = {}
    replicate_rows_by_sigma: dict[float, list[dict[str, Any]]] = {}
    violation_counts: dict[float, int] = {}
    for sigma in sigmas:
        if sigma == 0.0:
            centered_offsets = np.zeros_like(mean_rate)
        else:
            centered_offsets = np.asarray(mean_preserving_offset(mean_rate, float(sigma)), dtype=float)
        scores = np.empty((replicates, int(eligible.sum())), dtype=float)
        dispersions = np.empty(replicates, dtype=float)
        replicate_rows: list[dict[str, Any]] = []
        total_violations = 0
        for replicate_index in range(replicates):
            seed = BASE_REPLICATE_SEED + replicate_index
            latent, uniforms = _common_random_numbers(seed, attempts.shape)
            candidate_sog = beta_binomial_sog_draws(
                attempts,
                mean_rate,
                concentration,
                float(sigma),
                latent,
                uniforms,
                centered_offsets=centered_offsets,
            )
            violations = candidate_sog > attempts
            if np.any(violations):
                total_violations += int(violations.sum())
                raise RuntimeError("BETA_BINOMIAL_GENERATED_SOG_GREATER_THAN_ATTEMPTS")
            game_crps = crps_by_game_vectorized(candidate_sog, labels)
            scores[replicate_index] = game_crps
            dispersions[replicate_index] = float(np.std(candidate_sog, axis=1, ddof=1).mean())
            replicate_rows.append({
                "replicate": replicate_index,
                "seed": seed,
                "mean_sog_crps": float(game_crps.mean()),
                "raw_delta_vs_phase2a": float((game_crps - baseline_game_crps).mean()),
                "mean_per_side_ensemble_sd_ddof1": float(dispersions[replicate_index]),
                "dispersion_ratio_vs_phase2a": float(dispersions[replicate_index] / baseline_side_sd),
                "sog_greater_than_attempts_cells": int(violations.sum()),
            })
        scores_by_sigma[float(sigma)] = scores
        dispersions_by_sigma[float(sigma)] = dispersions
        replicate_rows_by_sigma[float(sigma)] = replicate_rows
        violation_counts[float(sigma)] = total_violations

    floor_scores = scores_by_sigma[0.0]
    floor_raw_by_game = (floor_scores - baseline_game_crps[None, :]).mean(axis=0)
    floor_raw_ci = _bootstrap_mean_ci(floor_raw_by_game, bootstrap_indices)
    floor_dispersion = _dispersion_summary(dispersions_by_sigma[0.0], baseline_side_sd)
    floor_ratio_mean = floor_dispersion["candidate_to_phase2a_dispersion_ratio_mean"]
    floor_criteria_dispersion = DISPERSION_RATIO_BAND[0] <= floor_ratio_mean <= DISPERSION_RATIO_BAND[1]
    floor_criteria_crps = floor_raw_ci["interval_contains_zero"]
    floor_achieved = bool(floor_criteria_dispersion and floor_criteria_crps)

    rows: list[dict[str, Any]] = []
    floor_passes = [
        bool((floor_scores[r] - baseline_game_crps).mean() <= 0.0)
        for r in range(replicates)
    ]
    for sigma in sigmas:
        sigma = float(sigma)
        scores = scores_by_sigma[sigma]
        raw_by_rep_game = scores - baseline_game_crps[None, :]
        adjusted_by_rep_game = scores - floor_scores
        raw_rep_means = raw_by_rep_game.mean(axis=1)
        adjusted_rep_means = adjusted_by_rep_game.mean(axis=1)
        raw_pooled_by_game = raw_by_rep_game.mean(axis=0)
        adjusted_pooled_by_game = adjusted_by_rep_game.mean(axis=0)
        raw_ci = _bootstrap_mean_ci(raw_pooled_by_game, bootstrap_indices)
        adjusted_ci = _bootstrap_mean_ci(adjusted_pooled_by_game, bootstrap_indices)
        raw_passes = [bool(v <= 0.0) for v in raw_rep_means]
        adjusted_passes = [bool(v <= 0.0) for v in adjusted_rep_means]
        rows.append({
            "sigma": sigma,
            "condition_a_raw_passes": int(sum(raw_passes)),
            "condition_a_raw_trials": replicates,
            "condition_a_raw_pass_rate": _rate_summary(raw_passes),
            "floor_adjusted_nonworsening_passes": int(sum(adjusted_passes)),
            "floor_adjusted_nonworsening_trials": replicates,
            "floor_adjusted_nonworsening_pass_rate": _rate_summary(adjusted_passes),
            "raw_sog_crps": {
                "phase2a_baseline": baseline_crps,
                "mean_candidate": float(scores.mean()),
                "mean_delta_vs_phase2a": float(raw_rep_means.mean()),
                "paired_game_cluster_bootstrap_ci95": raw_ci,
                "replicate_delta_percentiles_2_5_50_97_5": [
                    float(v) for v in np.quantile(raw_rep_means, (0.025, 0.5, 0.975))
                ],
            },
            "sigma_zero_noise_floor": {
                "mean_raw_delta_vs_phase2a": float(raw_rep_means.mean()) if sigma == 0.0 else float(floor_raw_by_game.mean()),
                "paired_game_cluster_bootstrap_ci95": floor_raw_ci,
                "reported_at_every_sigma": True,
            },
            "floor_adjusted_sog_crps": {
                "definition": "paired per-game candidate CRPS minus the same replicate's sigma-zero CRPS",
                "mean_delta_minus_sigma_zero_floor": float(adjusted_rep_means.mean()),
                "paired_game_cluster_bootstrap_ci95": adjusted_ci,
                "replicate_delta_percentiles_2_5_50_97_5": [
                    float(v) for v in np.quantile(adjusted_rep_means, (0.025, 0.5, 0.975))
                ],
            },
            "within_game_dispersion": _dispersion_summary(dispersions_by_sigma[sigma], baseline_side_sd),
            "floor_criteria": {
                "dispersion_ratio_mean_in_0_98_1_02": bool(floor_criteria_dispersion),
                "sigma_zero_crps_interval_contains_zero": bool(floor_criteria_crps),
                "floor_achieved": floor_achieved,
            },
            "sog_greater_than_attempts_cells": violation_counts[sigma],
            "replicates": replicate_rows_by_sigma[sigma],
        })

    frozen_after = verify_frozen_hashes()
    if frozen_before != frozen_after:
        raise RuntimeError("FROZEN_PHASE2A_CHANGED_DURING_RUN")
    result: dict[str, Any] = {
        "title": "Phase 2C Beta-Binomial SOG kernel noise-floor diagnostic",
        "classification": "DIAGNOSTIC_ONLY_NO_CANDIDATE_SELECTION_NO_GATE_CHANGE",
        "branch": "research/nhl-v3-kernel-noise-floor-2026-10-21",
        "base_commit": "8d76fb426a4275c19c92c8d5b982201430b80b3b",
        "input_hashes_sha256": {
            str(path.relative_to(HERE.parents[2])): sha256_file(path)
            for path in (
                Path(__file__).resolve(),
                HERE / "underdispersion-traces.json.gz",
                HERE / "RESULTS.json",
                HERE / "total_pace_split.json",
                HERE / "PHASE2C-ALLOC-PREREG.md",
                HERE / "PREREG-RULE-FEASIBILITY.md",
            )
        },
        "frozen_phase2a_hashes_before": frozen_before,
        "frozen_phase2a_hashes_after": frozen_after,
        "population": {
            "trace_games": int(inputs["attempts"].shape[0]),
            "sog_eligible_games": int(eligible.sum()),
            "draws_per_game": int(attempts.shape[1]),
            "eligible_team_side_fits": int(fit["game_side_count"]),
            "quarantined_sog_games_excluded_from_fit_and_score": int((~eligible).sum()),
        },
        "model_fit": {
            "method": "one Beta-Binomial per eligible game-side, method of moments from the 16 Phase 2A SOG counts and their fixed, varying attempt counts",
            "mean_rate": "sum of the 16 SOG counts / sum of the 16 attempt counts",
            "variance_estimator": "ddof=1 ensemble sample variance; binomial and attempt-mean variation are removed before estimating Beta probability variance",
            "fallback": "Binomial when observed sample variance is at or below the method-of-moments binomial-plus-attempt variance, or no second factorial attempt moment exists",
            "rho_definition": "Var(Beta probability)/(mean_rate*(1-mean_rate)); concentration=(1-rho)/rho",
            "rho_upper_cap": 1.0 - 1e-8,
            "fallback_game_sides": int(fit["fallback_count"]),
            "fallback_fraction": float(fit["fallback_count"] / fit["game_side_count"]),
            "upper_capped_game_sides": int(fit["upper_capped_count"]),
            "mean_rho": float(rho.mean()),
            "rho_percentiles_0_25_50_75_100": [float(v) for v in np.quantile(rho, (0, .25, .5, .75, 1))],
            "per_game_side_parameters": [
                {"game_index": int(g), "side": "home" if side == 0 else "away",
                 "mean_rate": float(mean_rate[g, side]), "rho": float(rho[g, side]),
                 "concentration": None if not np.isfinite(concentration[g, side]) else float(concentration[g, side]),
                 "binomial_fallback": bool(rho[g, side] == 0.0)}
                for g in range(mean_rate.shape[0]) for side in range(2)
            ],
        },
        "protocol": {
            "sigma_grid": [float(v) for v in sigmas],
            "replicates_per_sigma": replicates,
            "replicate_seed_formula": str(BASE_REPLICATE_SEED) + " + zero_based_replicate_index",
            "replicate_seeds": [BASE_REPLICATE_SEED + i for i in range(replicates)],
            "numpy_rng": "PCG64 via numpy.random.default_rng",
            "common_random_numbers": "same per-game-draw normal and per-side inverse-CDF uniforms at every sigma within a replicate",
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "eligible game ID; both teams and all 16 draws stay together",
            "crps": "vectorized exact discrete empirical-ensemble CRPS; parity-tested against the previously cross-checked feasibility helper",
            "condition_a_raw": "per-replicate mean paired team-SOG CRPS delta versus Phase 2A <= 0",
            "floor_adjusted_delta": "same-replicate, same-game candidate CRPS minus sigma-zero candidate CRPS; report as diagnostic sensitivity, not a changed preregistered gate",
            "floor_achievement_rule": "mean sigma-zero dispersion ratio is in [0.98, 1.02] AND its paired 95% game-cluster CRPS interval contains zero",
            "sog_eligibility": "fit and score only the 1,292 games with accepted official team SOG",
        },
        "baseline": {
            "phase2a_team_sog_crps": baseline_crps,
            "phase2a_mean_per_side_ensemble_sd_ddof1": float(baseline_side_sd),
        },
        "attempt_allocation_scope": {
            "condition_b": "UNTESTABLE_OUT_OF_SCOPE",
            "reason": "this kernel holds each committed Phase 2A attempt count and side split fixed; it contains no attempt-allocation mechanism",
            "condition_b_or_joint_pass_rate_reported": False,
        },
        "floor_summary": {
            "sigma_zero_mean_raw_crps_delta": float(floor_raw_by_game.mean()),
            "sigma_zero_raw_crps_cluster_ci95": floor_raw_ci,
            "sigma_zero_dispersion_ratio_mean": floor_ratio_mean,
            "sigma_zero_dispersion_ratio_replicate_percentiles_2_5_50_97_5": floor_dispersion["candidate_to_phase2a_dispersion_ratio_replicate_percentiles_2_5_50_97_5"],
            "sigma_zero_replicates_inside_dispersion_band": floor_dispersion["replicates_inside_required_0_98_1_02_band"],
            "dispersion_criterion_met": bool(floor_criteria_dispersion),
            "crps_interval_criterion_met": bool(floor_criteria_crps),
            "floor_achieved": floor_achieved,
            "smallest_observed_floor_for_this_moment_fit": float(floor_raw_by_game.mean()),
        },
        "results_by_sigma": rows,
        "runtime": {
            "seconds": float(time.perf_counter() - started),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "thread_limits": {
                name: os.environ.get(name)
                for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
            },
        },
        "limits": [
            "This is a count-level diagnostic and does not replay or alter the Phase 2A simulator.",
            "Beta-Binomial moment parameters are fitted to the 16 committed model draws, not to actual game SOG labels.",
            "A floor is claimed achieved only when both the preregistered dispersion band and the sigma-zero CRPS interval criterion pass.",
            "Condition B and any joint rule conclusion are out of scope because this kernel has no attempt-allocation layer.",
        ],
    }
    if output_path is not None:
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=100)
    parser.add_argument("--output", type=Path, default=RESULT_PATH)
    args = parser.parse_args()
    result = run_experiment(replicates=args.replicates, output_path=args.output)
    print(json.dumps({
        "output": str(args.output),
        "runtime_seconds": result["runtime"]["seconds"],
        "floor_summary": result["floor_summary"],
        "sigma_results": [
            {
                "sigma": row["sigma"],
                "A_raw": row["condition_a_raw_pass_rate"],
                "A_floor_adjusted": row["floor_adjusted_nonworsening_pass_rate"],
                "raw_delta": row["raw_sog_crps"]["mean_delta_vs_phase2a"],
                "adjusted_delta": row["floor_adjusted_sog_crps"]["mean_delta_minus_sigma_zero_floor"],
                "raw_ci": row["raw_sog_crps"]["paired_game_cluster_bootstrap_ci95"],
                "adjusted_ci": row["floor_adjusted_sog_crps"]["paired_game_cluster_bootstrap_ci95"],
                "dispersion_ratio": row["within_game_dispersion"]["candidate_to_phase2a_dispersion_ratio_mean"],
                "floor_achieved": row["floor_criteria"]["floor_achieved"],
            }
            for row in result["results_by_sigma"]
        ],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
