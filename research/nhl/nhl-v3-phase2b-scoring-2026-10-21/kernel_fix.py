#!/usr/bin/env python3
"""Physically valid conditional-SOG feasibility diagnostic.

Uses only the committed Phase 2A count trace. Attempts remain fixed; SOG is
generated conditionally from each side's Phase 2A SOG/attempt rate.
"""

from __future__ import annotations

import argparse
import math
import platform
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import binom

from rule_feasibility import (
    BASE_REPLICATE_SEED,
    BOOTSTRAP_SEED,
    GH_U,
    GH_WEIGHTS,
    SIGMA_GRID,
    _load_inputs,
    _make_bootstrap_indices,
    _rate_summary,
    _expit,
    crps_by_game,
    mean_preserving_offset,
    moments,
    paired_margin_variance_bootstrap,
    sha256_file,
    verify_frozen_hashes,
)


HERE = Path(__file__).resolve().parent
RESULT_PATH = HERE / "kernel_fix.json"
REPORT_PATH = HERE / "KERNEL-FIX.md"
BOOTSTRAP_REPLICATES = 2000


def baseline_conversion_rates(attempts: np.ndarray, sog: np.ndarray) -> np.ndarray:
    """Return side rates SOG/attempts; zero attempts imply the only valid rate, 0."""
    n = np.asarray(attempts)
    y = np.asarray(sog)
    if n.shape != y.shape or n.ndim != 3 or n.shape[-1] != 2:
        raise ValueError("ATTEMPT_SOG_SHAPE_MISMATCH")
    if np.any(n < 0) or np.any(y < 0) or np.any(y > n):
        raise ValueError("INVALID_ATTEMPT_CONDITIONAL_SOG_COUNTS")
    return np.divide(y, n, out=np.zeros(y.shape, dtype=float), where=n > 0)


def conditional_conversion_probabilities(
    p0: np.ndarray,
    sigma: float,
    shared_u: np.ndarray,
    *,
    centered_offsets: np.ndarray | None = None,
) -> np.ndarray:
    """Mean-preserving opposite logit shifts for home and away conversion rates.

    For each side, E_U[p_sigma] = p0 under a standard normal U. The same U is
    shared with opposite signs so sigma changes the home-away conversion split
    while preserving each side's marginal rate. At sigma=0 this returns p0.
    """
    rates = np.asarray(p0, dtype=float)
    latent = np.asarray(shared_u, dtype=float)
    if rates.ndim != 3 or rates.shape[-1] != 2 or latent.shape != rates.shape[:2]:
        raise ValueError("CONVERSION_RATE_OR_LATENT_SHAPE_MISMATCH")
    if np.any(~np.isfinite(rates)) or np.any((rates < 0.0) | (rates > 1.0)):
        raise ValueError("CONVERSION_RATE_OUTSIDE_UNIT_INTERVAL")
    if np.any(~np.isfinite(latent)):
        raise ValueError("NONFINITE_SHARED_LATENT")
    if not math.isfinite(sigma) or sigma < 0.0:
        raise ValueError("SIGMA_MUST_BE_FINITE_AND_NONNEGATIVE")
    if sigma == 0.0:
        return rates.copy()

    offsets = (
        np.asarray(mean_preserving_offset(rates, sigma), dtype=float)
        if centered_offsets is None
        else np.asarray(centered_offsets, dtype=float)
    )
    if offsets.shape != rates.shape or np.any(~np.isfinite(offsets)):
        raise ValueError("CONVERSION_OFFSET_SHAPE_OR_VALUE_INVALID")
    logits = np.full_like(rates, np.inf)
    interior = (rates > 0.0) & (rates < 1.0)
    logits[rates == 0.0] = -np.inf
    logits[interior] = np.log(rates[interior]) - np.log1p(-rates[interior])
    signs = np.asarray([1.0, -1.0])
    adjusted_logits = logits + offsets + sigma * latent[..., None] * signs
    probabilities = _expit(adjusted_logits)
    if np.any(~np.isfinite(probabilities)) or np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise RuntimeError("INVALID_CONDITIONAL_CONVERSION_PROBABILITY")
    return probabilities


def conditional_sog_draws(
    attempts: np.ndarray,
    phase2a_sog: np.ndarray,
    sigma: float,
    shared_u: np.ndarray,
    uniforms: np.ndarray,
    *,
    centered_offsets: np.ndarray | None = None,
) -> np.ndarray:
    """Draw side SOG counts from Binomial(attempts, adjusted Phase 2A rate)."""
    n = np.asarray(attempts, dtype=np.int64)
    baseline = np.asarray(phase2a_sog, dtype=np.int64)
    u = np.asarray(shared_u, dtype=float)
    unit = np.asarray(uniforms, dtype=float)
    if n.shape != baseline.shape or n.ndim != 3 or n.shape[-1] != 2:
        raise ValueError("ATTEMPT_SOG_SHAPE_MISMATCH")
    if u.shape != n.shape[:2] or unit.shape != n.shape:
        raise ValueError("COMMON_RANDOM_NUMBER_SHAPE_MISMATCH")
    if np.any(~np.isfinite(unit)) or np.any((unit < 0.0) | (unit >= 1.0)):
        raise ValueError("BINOMIAL_UNIFORMS_OUTSIDE_HALF_OPEN_UNIT_INTERVAL")
    rates = baseline_conversion_rates(n, baseline)
    probabilities = conditional_conversion_probabilities(
        rates, sigma, u, centered_offsets=centered_offsets
    )
    result = binom.ppf(unit, n, probabilities)
    if np.any(~np.isfinite(result)) or np.any(result != np.floor(result)):
        raise RuntimeError("BINOMIAL_QUANTILE_DID_NOT_RETURN_FINITE_INTEGER_COUNTS")
    output = result.astype(np.int64)
    if np.any(output < 0) or np.any(output > n):
        raise RuntimeError("CONDITIONAL_SOG_EXCEEDS_ATTEMPTS")
    return output


def mean_preservation_audit(p0: np.ndarray, sigmas: tuple[float, ...]) -> dict[str, Any]:
    """Check the Gaussian expectation using the same fixed GH rule as Phase 2C."""
    rates = np.asarray(p0, dtype=float).reshape(-1)
    unique = np.unique(rates)
    rows: list[dict[str, float]] = []
    for sigma in sigmas:
        interior = unique[(unique > 0.0) & (unique < 1.0)]
        if interior.size:
            offsets = np.asarray(mean_preserving_offset(interior, sigma), dtype=float)
            logits = np.log(interior) - np.log1p(-interior)
            gh_means = _expit(logits[:, None] + offsets[:, None] + sigma * GH_U[None, :]) @ GH_WEIGHTS
            max_probability_error = float(np.max(np.abs(gh_means - interior), initial=0.0))
        else:
            max_probability_error = 0.0
        rows.append({"sigma": float(sigma), "max_abs_rate_error_32_point_GH": max_probability_error})
    return {
        "quadrature": "32-point Gauss-Hermite, same nodes and weights as feasibility harness",
        "unique_baseline_rates": int(unique.size),
        "sigma_checks": rows,
        "maximum_abs_rate_error": max(row["max_abs_rate_error_32_point_GH"] for row in rows),
        "expected_team_sog_count_at_sigma_zero_equals_phase2a_per_draw": True,
        "sigma_zero_expected_count_max_abs_error": None,
    }


def _bootstrap_mean_ci(game_deltas: np.ndarray, indices: np.ndarray) -> dict[str, Any]:
    means = np.asarray(game_deltas, dtype=float)[indices].mean(axis=1)
    lower, upper = np.quantile(means, (0.025, 0.975))
    return {
        "lower_95": float(lower),
        "upper_95": float(upper),
        "bootstrap_replicates": int(indices.shape[0]),
        "interval_wholly_above_zero": bool(lower > 0.0),
        "interval_wholly_below_zero": bool(upper < 0.0),
    }


def _common_random_numbers(seed: int, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    shared_u = rng.standard_normal(shape[:2])
    uniforms = rng.random(shape)
    return shared_u, uniforms


def run_experiment(
    replicates: int = 100,
    sigmas: tuple[float, ...] = SIGMA_GRID,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    *,
    output_path: Path | None = RESULT_PATH,
) -> dict[str, Any]:
    if replicates < 50:
        raise ValueError("PREREGISTERED_REPLICATES_REQUIRE_R_AT_LEAST_50")
    if bootstrap_replicates != BOOTSTRAP_REPLICATES:
        raise ValueError("KERNEL_FIX_REQUIRES_2000_BOOTSTRAPS")
    if not sigmas or any(not math.isfinite(s) or s < 0.0 for s in sigmas):
        raise ValueError("INVALID_SIGMA_GRID")

    started = time.perf_counter()
    frozen_before = verify_frozen_hashes()
    trace, inputs, targets = _load_inputs()
    attempts = inputs["attempts"]
    baseline_sog = inputs["sog"]
    eligible = inputs["sog_eligible"]
    baseline_crps_by_game = crps_by_game(baseline_sog[eligible], inputs["official_sog"])
    baseline_attempt_variance = moments(attempts)["variance_home_minus_away"]
    baseline_rates = baseline_conversion_rates(attempts, baseline_sog)
    bootstrap_indices = _make_bootstrap_indices(
        int(eligible.sum()), bootstrap_replicates, BOOTSTRAP_SEED
    )
    attempt_bootstrap_indices = _make_bootstrap_indices(
        int(attempts.shape[0]), bootstrap_replicates, BOOTSTRAP_SEED
    )

    # Since candidate attempts are required to be byte-identical to Phase 2A,
    # every paired attempt-margin bootstrap replicate is exactly zero-width.
    attempt_ci = paired_margin_variance_bootstrap(
        attempts, attempts.copy(), attempt_bootstrap_indices
    )
    if attempt_ci["lower_95"] != 0.0 or attempt_ci["upper_95"] != 0.0:
        raise RuntimeError("FIXED_ATTEMPT_MARGIN_BOOTSTRAP_NOT_DEGENERATE")

    rows: list[dict[str, Any]] = []
    total_cells = 0
    violation_cells = 0
    exact_attempt_comparisons = 0
    max_sigma_zero_mean_count_error = 0.0

    for sigma in sigmas:
        unique_rates, rate_inverse = np.unique(baseline_rates, return_inverse=True)
        unique_offsets = np.asarray(mean_preserving_offset(unique_rates, float(sigma)), dtype=float)
        centered_offsets = unique_offsets[rate_inverse].reshape(baseline_rates.shape)
        replicate_means: list[float] = []
        replicate_rows: list[dict[str, Any]] = []
        sum_game_deltas = np.zeros(int(eligible.sum()), dtype=float)
        sigma_violation_cells = 0
        sigma_total_cells = 0
        for replicate_index in range(replicates):
            seed = BASE_REPLICATE_SEED + replicate_index
            shared_u, uniforms = _common_random_numbers(seed, attempts.shape)
            candidate_attempts = attempts.copy()
            candidate_sog = conditional_sog_draws(
                candidate_attempts,
                baseline_sog,
                float(sigma),
                shared_u,
                uniforms,
                centered_offsets=centered_offsets,
            )
            if not np.array_equal(candidate_attempts, attempts):
                raise RuntimeError("ATTEMPT_TRACE_CHANGED")
            exact_attempt_comparisons += 1
            violations = candidate_sog > attempts
            sigma_violation_cells += int(violations.sum())
            sigma_total_cells += int(violations.size)
            game_delta = (
                crps_by_game(candidate_sog[eligible], inputs["official_sog"])
                - baseline_crps_by_game
            )
            mean_delta = float(game_delta.mean())
            sum_game_deltas += game_delta
            replicate_means.append(mean_delta)
            replicate_rows.append({
                "replicate": replicate_index,
                "seed": seed,
                "mean_paired_team_sog_crps_delta_candidate_minus_phase2a": mean_delta,
                "condition_a_sog_crps_nonworsening": bool(mean_delta <= 0.0),
                "attempt_margin_variance": baseline_attempt_variance,
                "attempt_margin_variance_delta_vs_phase2a": 0.0,
                "condition_b_attempt_variance_target": bool(
                    baseline_attempt_variance >= targets["target_attempt_variance_margin"]
                ),
                "condition_b_interval_wholly_above_zero_as_written": bool(
                    attempt_ci["interval_wholly_above_zero"]
                ),
                "condition_b_interval_subcriterion_degenerate_undefined": True,
                "condition_b_as_written": False,
                "joint_pass_as_written": False,
                "team_draw_cells_with_sog_greater_than_attempts": int(violations.sum()),
                "game_draws_with_any_team_sog_greater_than_attempts": int(violations.any(axis=2).sum()),
            })

        mean_deltas = np.asarray(replicate_means, dtype=float)
        pooled_game_delta = sum_game_deltas / replicates
        pooled_bootstrap = _bootstrap_mean_ci(pooled_game_delta, bootstrap_indices)
        a_passes = [r["condition_a_sog_crps_nonworsening"] for r in replicate_rows]
        b_passes = [r["condition_b_as_written"] for r in replicate_rows]
        interval_passes = [r["condition_b_interval_wholly_above_zero_as_written"] for r in replicate_rows]
        joint_passes = [r["joint_pass_as_written"] for r in replicate_rows]
        total_cells += sigma_total_cells
        violation_cells += sigma_violation_cells

        rows.append({
            "sigma": float(sigma),
            "kernel_point": (
                "conditional-binomial zero-sigma limit; not exact Phase 2A trace identity"
                if sigma == 0.0 else "conditional-binomial allocation family"
            ),
            "rates": {
                "condition_a_sog_crps_nonworsening": _rate_summary(a_passes),
                "condition_b_as_written": _rate_summary(b_passes),
                "condition_b_interval_component_as_written": _rate_summary(interval_passes),
                "joint_as_written": _rate_summary(joint_passes),
                "condition_b_interval_component_undefined_count": replicates,
                "condition_b_as_written_when_degenerate_interval_is_undefined": _rate_summary(b_passes),
                "joint_when_degenerate_interval_is_undefined": _rate_summary(joint_passes),
            },
            "sog_crps": {
                "phase2a_baseline": float(baseline_crps_by_game.mean()),
                "mean_candidate": float(baseline_crps_by_game.mean() + mean_deltas.mean()),
                "mean_paired_delta_candidate_minus_phase2a": float(mean_deltas.mean()),
                "paired_game_cluster_bootstrap_ci95_of_mc_averaged_game_delta": pooled_bootstrap,
                "replicate_delta_percentiles_2_5_50_97_5": [
                    float(x) for x in np.quantile(mean_deltas, (0.025, 0.5, 0.975))
                ],
                "condition_a_passes": int(sum(a_passes)),
                "condition_a_trials": replicates,
                "mc_averaged_per_game_delta_count": int(pooled_game_delta.size),
            },
            "attempt_margin_variance": {
                "phase2a_baseline": baseline_attempt_variance,
                "target": targets["target_attempt_variance_margin"],
                "candidate": baseline_attempt_variance,
                "paired_delta": 0.0,
                "paired_game_cluster_bootstrap_ci95": attempt_ci,
                "point_target_reached": bool(
                    baseline_attempt_variance >= targets["target_attempt_variance_margin"]
                ),
            },
            "conditional_sog_accounting": {
                "team_draw_cells": int(sigma_total_cells),
                "team_draw_cells_sog_greater_than_attempts": int(sigma_violation_cells),
                "team_draw_cell_violation_fraction": float(sigma_violation_cells / sigma_total_cells),
                "game_draws_with_any_violation": 0,
                "game_draw_violation_fraction": 0.0,
            },
            "replicates": replicate_rows,
        })

    if violation_cells != 0:
        raise RuntimeError(f"PHYSICAL_SOG_ATTEMPT_VIOLATIONS: {violation_cells}/{total_cells}")
    if not np.array_equal(attempts, inputs["attempts"]):
        raise RuntimeError("PHASE2A_ATTEMPTS_NOT_PRESERVED")

    # Expected count at sigma=0 is A * (S/A) = S per committed draw; report the
    # arithmetic check separately from the random binomial realization.
    expected_zero_counts = attempts.astype(float) * baseline_rates
    max_sigma_zero_mean_count_error = float(np.max(np.abs(expected_zero_counts - baseline_sog)))
    if max_sigma_zero_mean_count_error > 1e-12:
        raise RuntimeError("SIGMA_ZERO_CONDITIONAL_EXPECTATION_NOT_PHASE2A")
    quadrature = mean_preservation_audit(baseline_rates, sigmas)
    if quadrature["maximum_abs_rate_error"] > 1e-12:
        raise RuntimeError("GAUSSIAN_RATE_MEAN_PRESERVATION_FAILED")
    quadrature["sigma_zero_expected_count_max_abs_error"] = max_sigma_zero_mean_count_error

    frozen_after = verify_frozen_hashes()
    if frozen_before != frozen_after:
        raise RuntimeError("FROZEN_PHASE2A_CHANGED_DURING_RUN")

    result: dict[str, Any] = {
        "title": "Phase 2C feasibility kernel fix: conditional SOG diagnostic",
        "classification": "DIAGNOSTIC_ONLY_NO_CANDIDATE_SELECTION_NO_GATE_CHANGE",
        "branch": "research/nhl-v3-prereg-feasibility-kernel-fix-2026-10-21",
        "base_commit": "c87b0def6f2006bb9b67dea499a01f35f3ed1ef7",
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
            "trace_games": int(attempts.shape[0]),
            "draws_per_game": int(attempts.shape[1]),
            "official_sog_eligible_games": int(eligible.sum()),
            "ineligible_sog_games": int((~eligible).sum()),
        },
        "baseline": {
            "phase2a_team_sog_crps": float(baseline_crps_by_game.mean()),
            "phase2a_attempt_margin_variance": baseline_attempt_variance,
            "target_attempt_margin_variance": float(targets["target_attempt_variance_margin"]),
            "expected_sog_counts_at_sigma_zero_equal_phase2a_per_game_draw": True,
            "expected_sog_count_max_abs_error": max_sigma_zero_mean_count_error,
        },
        "kernel": {
            "attempts": "held byte-for-byte at committed Phase 2A home/away attempt counts for each stored draw",
            "baseline_probability": "p_side = Phase 2A side SOG / side attempts for that same draw; zero attempts map to p=0",
            "sigma_effect": "mean-preserving Gaussian logit shifts of side conversion probability; one U per game-draw, +sigma*U home and -sigma*U away",
            "probability_centering": "32-point Gauss-Hermite offsets; each side's marginal conversion probability remains its Phase 2A p",
            "outcome_draw": "SOG_side ~ Binomial(attempts_side, adjusted p_side), sampled by inverse CDF with common uniforms across sigma",
            "zero_sigma": "the conditional-binomial family limit, not exact Phase 2A SOG-trace identity; exact expected SOG count equals the Phase 2A count for every draw",
            "continuity": "conditional probabilities converge to Phase 2A side rates as sigma tends to zero; SOG counts remain bounded by attempts at every sigma",
            "conditional_mean_quadrature_audit": quadrature,
            "per_draw_attempt_splits_fixed": True,
            "per_side_sog_le_attempts_proven_by_binomial_support": True,
        },
        "protocol": {
            "sigma_grid": [float(x) for x in sigmas],
            "replicates_per_sigma": replicates,
            "replicate_seed_formula": f"{BASE_REPLICATE_SEED} + zero_based_replicate_index",
            "replicate_seeds": [BASE_REPLICATE_SEED + i for i in range(replicates)],
            "numpy_rng": "PCG64 via numpy.random.default_rng",
            "binomial_inverse_cdf": "scipy.stats.binom.ppf",
            "common_random_numbers": "each replicate regenerates the same shared normal and side-specific uniforms at every sigma",
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "eligible game ID; both teams and all 16 stored draws stay together",
            "attempt_bootstrap_population": int(attempts.shape[0]),
            "sog_bootstrap_population": int(eligible.sum()),
            "sog_eligibility": "the 1,292 accepted official-SOG games are used for both model CRPS and labels",
            "crps": "same discrete empirical-ensemble CRPS implementation as Phase 2A feasibility harness, previously cross-checked against Phase 2A _crps_discrete",
            "condition_a": "per-replicate mean paired team-SOG CRPS delta <= 0",
            "condition_b_as_written": "attempt Var(H-A) >= 244.667 and paired 95% game-cluster interval for candidate-minus-Phase2A attempt Var(H-A) wholly above zero",
            "degenerate_interval_predeclaration": "a zero-width interval is undefined for the interval-only subcriterion and never a pass; B as a conjunction still fails if its point-variance threshold fails",
        },
        "accounting": {
            "candidate_team_draw_cells": total_cells,
            "team_draw_cells_sog_greater_than_attempts": violation_cells,
            "fraction_team_draw_cells_sog_greater_than_attempts": 0.0,
            "game_draws_with_any_team_violation": 0,
            "attempt_trace_equality_checks": exact_attempt_comparisons,
            "attempt_trace_equality_failures": 0,
            "pair_total_assertions_required": False,
            "reason_pair_total_changes_under_conditional_binomial": "each side's valid binomial outcome count is generated from its fixed attempts; total SOG is consequently random, not independently resplit or forced to an impossible pair total",
        },
        "results_by_sigma": rows,
        "runtime": {
            "seconds": float(time.perf_counter() - started),
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "limits": [
            "This is a count-level conditional kernel, not an event-stream or simulator replay.",
            "The Phase 2A per-draw SOG/attempt ratio is a committed model-output rate, not a separately estimated pregame conversion probability.",
            "A binomial conditional redraw adds outcome variation relative to the finite 16-draw Phase 2A trace; the sigma-zero point is not exact trace identity, though its expected counts match the trace exactly.",
            "Because attempt splits are fixed, the preregistered attempt-margin-variance condition B cannot pass; the bootstrap interval is structurally [0,0].",
            "The old invalid kernel's SOG CRPS uses only its SOG marginal predictions and labels. SOG>attempt violations do not enter that score directly; the corrected-kernel score difference is not a causal decomposition of the old +0.154630 penalty.",
            "No event paths, locations, shooter identities, goals, special-teams outcomes, clocks, regulation, overtime, or shootouts are reconstructed.",
        ],
    }
    if output_path is not None:
        output_path.write_text(json_dumps(result), encoding="utf-8")
    return result


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=100)
    parser.add_argument("--output", type=Path, default=RESULT_PATH)
    args = parser.parse_args()
    result = run_experiment(replicates=args.replicates, output_path=args.output)
    print(json_dumps({
        "output": str(args.output),
        "runtime_seconds": result["runtime"]["seconds"],
        "sigma_results": [
            {
                "sigma": row["sigma"],
                "A": row["rates"]["condition_a_sog_crps_nonworsening"],
                "B": row["rates"]["condition_b_as_written"],
                "joint": row["rates"]["joint_as_written"],
                "mean_delta": row["sog_crps"]["mean_paired_delta_candidate_minus_phase2a"],
                "ci95": row["sog_crps"]["paired_game_cluster_bootstrap_ci95_of_mc_averaged_game_delta"],
                "invalid_fraction": row["conditional_sog_accounting"]["team_draw_cell_violation_fraction"],
            }
            for row in result["results_by_sigma"]
        ],
    }))


if __name__ == "__main__":
    main()
