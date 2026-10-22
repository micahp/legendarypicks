#!/usr/bin/env python3
"""Diagnose home/away attempt allocation from the saved Phase 2A draws.

This analysis is deliberately count-level: it reuses the existing 16 draws per
2021 game and does not rerun the simulator.  Its cluster bootstrap resamples
game IDs while retaining both teams and all 16 draws for each sampled game.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "research/nhl/nhl-v3-phase2b-scoring-2026-10-21"
TRACE = BASE / "underdispersion-traces.json.gz"
PACE_JSON = BASE / "total_pace_split.json"
UNDERDISPERSION_JSON = BASE / "underdispersion.json"
SIMULATOR = ROOT / "research/nhl/nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py"
OUTPUT = BASE / "share_mechanism.json"
EXPECTED_TRACE_SHA256 = "7a86fba3f66f7a90bfbf1b653c0871d67a43a99dd073f6fe2d86e9c71527d0e7"
EXPECTED_PHASE2A_HASHES = {
    "evaluation_sha256": "24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930",
    "fitted_model_sha256": "8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb",
    "report_sha256": "b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def population_covariance(left: np.ndarray, right: np.ndarray) -> float:
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    if left.shape != right.shape or left.size == 0:
        raise ValueError("COVARIANCE_INPUT_SHAPE_MISMATCH")
    return float(np.mean((left - left.mean()) * (right - right.mean())))


def nested_covariance_components(draws: np.ndarray) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    """Decompose Cov(H,A) over game × draw rows, conditioning next on game and N."""
    if draws.ndim != 3 or draws.shape[1:] != (16, 2):
        raise ValueError("EXPECTED_GAME_BY_16_DRAWS_BY_HOME_AWAY_ARRAY")

    game_fixed_total: list[float] = []
    game_within_total_means: list[float] = []
    game_means = draws.mean(axis=1)

    for game_draws in draws:
        totals = game_draws.sum(axis=1)
        conditional_covariance = 0.0
        conditional_means: list[np.ndarray] = []
        conditional_weights: list[float] = []
        for total in np.unique(totals):
            group = game_draws[totals == total]
            weight = len(group) / len(game_draws)
            if len(group) > 1:
                conditional_covariance += weight * population_covariance(group[:, 0], group[:, 1])
            conditional_means.append(group.mean(axis=0))
            conditional_weights.append(weight)

        means = np.asarray(conditional_means, dtype=float)
        weights = np.asarray(conditional_weights, dtype=float)
        game_mean = np.average(means, axis=0, weights=weights)
        within_total = float(
            np.sum(weights * (means[:, 0] - game_mean[0]) * (means[:, 1] - game_mean[1]))
        )
        game_fixed_total.append(conditional_covariance)
        game_within_total_means.append(within_total)

    home_game_mean = game_means[:, 0]
    away_game_mean = game_means[:, 1]
    components = {
        "conditional_covariance_given_game_and_total_attempts": float(np.mean(game_fixed_total)),
        "within_game_covariance_of_conditional_means_across_total_attempts": float(
            np.mean(game_within_total_means)
        ),
        "between_game_covariance_of_16_draw_means": population_covariance(
            home_game_mean, away_game_mean
        ),
    }
    components["sum"] = sum(components.values())
    direct = population_covariance(draws[:, :, 0].reshape(-1), draws[:, :, 1].reshape(-1))
    if not math.isclose(components["sum"], direct, rel_tol=0.0, abs_tol=1e-10):
        raise ValueError("NESTED_COVARIANCE_DECOMPOSITION_DID_NOT_RECONCILE")
    return components, np.asarray(game_fixed_total), np.asarray(game_within_total_means)


def independent_margin_moments(
    mean_total: float,
    variance_total: float,
    mean_share: float,
    variance_share: float,
) -> dict[str, float]:
    """Moments under independent N and S, with H=N*S and A=N*(1-S)."""
    second_total = mean_total**2 + variance_total
    variance_home = variance_total * mean_share**2 + second_total * variance_share
    variance_away = variance_total * (1.0 - mean_share) ** 2 + second_total * variance_share
    covariance = variance_total * mean_share * (1.0 - mean_share) - second_total * variance_share
    return {
        "variance_home": float(variance_home),
        "variance_away": float(variance_away),
        "covariance_home_away": float(covariance),
        "variance_home_minus_away": float(variance_home + variance_away - 2.0 * covariance),
    }


def interval(samples: list[float] | np.ndarray) -> list[float]:
    values = np.asarray(samples, dtype=float)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("BOOTSTRAP_INTERVAL_HAS_NO_FINITE_VALUES")
    return [float(v) for v in np.quantile(values, [0.025, 0.975], method="linear")]


def load_data() -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    actual_trace_hash = sha256(TRACE)
    if actual_trace_hash != EXPECTED_TRACE_SHA256:
        raise ValueError("SAVED_TRACE_SHA256_MISMATCH")

    pace_data = json.loads(PACE_JSON.read_text())
    underdispersion = json.loads(UNDERDISPERSION_JSON.read_text())
    if underdispersion["input_snapshot"]["sha256"] != actual_trace_hash:
        raise ValueError("UNDERDISPERSION_TRACE_PIN_MISMATCH")
    if underdispersion["frozen_phase2a_hashes"] != EXPECTED_PHASE2A_HASHES:
        raise ValueError("FROZEN_PHASE2A_HASH_PIN_MISMATCH")

    with gzip.open(TRACE, "rt", encoding="utf-8") as handle:
        trace = json.load(handle)
    metadata = trace["metadata"]
    if metadata["simulations_per_game"] != 16 or metadata["games"] != 1312:
        raise ValueError("UNEXPECTED_SAVED_DRAW_POPULATION")
    if metadata["phase2a_hashes"] != EXPECTED_PHASE2A_HASHES:
        raise ValueError("TRACE_PHASE2A_HASH_PIN_MISMATCH")

    rows = trace["games"]
    game_ids: list[str] = []
    attempts: list[np.ndarray] = []
    observed_shares: list[float] = []
    observed_pairs: list[list[float]] = []
    for row in rows:
        game_id = str(row["game_id"])
        generated = np.asarray(row["phase2a"]["attempts"], dtype=float)
        if generated.shape != (16, 2) or not np.isfinite(generated).all() or (generated < 0).any():
            raise ValueError(f"INVALID_SAVED_ATTEMPTS:{game_id}")
        observed = row["observed"]["attempts"]
        home = float(observed["home"])
        away = float(observed["away"])
        if home < 0 or away < 0 or home + away <= 0:
            raise ValueError(f"INVALID_OBSERVED_ATTEMPTS:{game_id}")
        game_ids.append(game_id)
        attempts.append(generated)
        observed_pairs.append([home, away])
        observed_shares.append(home / (home + away))

    if len(game_ids) != 1312 or len(set(game_ids)) != len(game_ids):
        raise ValueError("GAME_ID_POPULATION_OR_UNIQUENESS_FAILURE")
    attempt_array = np.stack(attempts)
    observed_pair_array = np.asarray(observed_pairs, dtype=float)
    observed_share_array = np.asarray(observed_shares, dtype=float)
    if (attempt_array.sum(axis=2) <= 0).any():
        raise ValueError("ZERO_GENERATED_ATTEMPT_TOTAL_PREVENTS_SHARE_ANALYSIS")

    # The existing pace report is an independent committed diagnostic; these checks
    # fail loudly if this script's input selection or population changes.
    expected = pace_data["outcomes"]["attempts"]
    generated_home = attempt_array[:, :, 0].reshape(-1)
    generated_away = attempt_array[:, :, 1].reshape(-1)
    generated_total = generated_home + generated_away
    if not math.isclose(float(generated_total.mean()), expected["generated"]["mean_total"], abs_tol=1e-10):
        raise ValueError("GENERATED_ATTEMPT_MEAN_CROSSCHECK_FAILED")
    if not math.isclose(population_covariance(generated_home, generated_away),
                         expected["generated"]["covariance_home_away"], abs_tol=1e-10):
        raise ValueError("GENERATED_ATTEMPT_COVARIANCE_CROSSCHECK_FAILED")
    if not math.isclose(float(observed_share_array.var()),
                         expected["observed"]["variance_home_share"], abs_tol=1e-12):
        raise ValueError("OBSERVED_SHARE_VARIANCE_CROSSCHECK_FAILED")

    return game_ids, attempt_array, observed_pair_array, observed_share_array, {
        "trace_sha256": actual_trace_hash,
        "phase2a_hashes": EXPECTED_PHASE2A_HASHES,
        "pace_report_sha256": sha256(PACE_JSON),
        "underdispersion_report_sha256": sha256(UNDERDISPERSION_JSON),
        "simulator_sha256": sha256(SIMULATOR),
        "trace_metadata": metadata,
    }


def analyze(bootstrap_replicates: int, seed: int) -> dict[str, Any]:
    started = time.perf_counter()
    game_ids, attempts, observed_pairs, observed_shares, pins = load_data()
    games = len(game_ids)
    generated_home = attempts[:, :, 0].reshape(-1)
    generated_away = attempts[:, :, 1].reshape(-1)
    generated_total = generated_home + generated_away
    generated_share = generated_home / generated_total
    observed_home = observed_pairs[:, 0]
    observed_away = observed_pairs[:, 1]
    observed_total = observed_home + observed_away

    point_components, per_game_a, per_game_b = nested_covariance_components(attempts)
    per_game_means = attempts.mean(axis=1)
    observed_covariance = population_covariance(observed_home, observed_away)
    observed_share_mean = float(observed_shares.mean())
    observed_share_variance = float(observed_shares.var())
    generated_share_mean = float(generated_share.mean())
    generated_share_variance = float(generated_share.var())
    generated_inverse_total = float(np.mean(1.0 / generated_total))
    observed_inverse_total = float(np.mean(1.0 / observed_total))
    observed_share_index = observed_share_variance / (
        observed_share_mean * (1.0 - observed_share_mean) * observed_inverse_total
    )
    generated_share_index = generated_share_variance / (
        generated_share_mean * (1.0 - generated_share_mean) * generated_inverse_total
    )

    mean_total = float(generated_total.mean())
    variance_total = float(generated_total.var())
    share_only = independent_margin_moments(
        mean_total, variance_total, observed_share_mean, observed_share_variance
    )
    share_variance_for_observed_covariance = float(
        (variance_total * observed_share_mean * (1.0 - observed_share_mean) - observed_covariance)
        / (mean_total**2 + variance_total)
    )
    covariance_target_share = independent_margin_moments(
        mean_total, variance_total, observed_share_mean, share_variance_for_observed_covariance
    )

    rng = np.random.default_rng(seed)
    bootstrap = {
        "decomposition": {name: [] for name in point_components},
        "within_game_predictive_covariance": [],
        "share_only": {name: [] for name in share_only},
        "covariance_matched_share": {name: [] for name in covariance_target_share},
        "share_only_covariance_minus_observed": [],
        "share_only_variance_margin_minus_observed": [],
        "share_variance_for_observed_covariance": [],
        "share_variance_for_observed_covariance_minus_empirical_share_variance": [],
        "observed_covariance_home_away": [],
        "generated_mean_total": [],
        "generated_variance_total": [],
        "generated_minus_observed_variance_total": [],
        "observed_share_mean": [],
        "observed_share_variance": [],
    }
    for _ in range(bootstrap_replicates):
        index = rng.integers(0, games, size=games)
        a_component = float(per_game_a[index].mean())
        b_component = float(per_game_b[index].mean())
        means = per_game_means[index]
        c_component = population_covariance(means[:, 0], means[:, 1])
        bootstrap["decomposition"]["conditional_covariance_given_game_and_total_attempts"].append(a_component)
        bootstrap["decomposition"]["within_game_covariance_of_conditional_means_across_total_attempts"].append(b_component)
        bootstrap["decomposition"]["between_game_covariance_of_16_draw_means"].append(c_component)
        bootstrap["decomposition"]["sum"].append(a_component + b_component + c_component)
        bootstrap["within_game_predictive_covariance"].append(a_component + b_component)

        sampled_totals = attempts[index].sum(axis=2).reshape(-1)
        mu_n = float(sampled_totals.mean())
        var_n = float(sampled_totals.var())
        p_share = float(observed_shares[index].mean())
        var_share = float(observed_shares[index].var())
        observed_covariance_sample = population_covariance(
            observed_pairs[index, 0], observed_pairs[index, 1]
        )
        moments = independent_margin_moments(mu_n, var_n, p_share, var_share)
        target_variance = float(
            (var_n * p_share * (1.0 - p_share) - observed_covariance_sample)
            / (mu_n**2 + var_n)
        )
        target_moments = independent_margin_moments(mu_n, var_n, p_share, target_variance)
        observed_margin_variance_sample = float(
            (observed_pairs[index, 0] - observed_pairs[index, 1]).var()
        )
        for name, value in moments.items():
            bootstrap["share_only"][name].append(value)
        bootstrap["share_only_covariance_minus_observed"].append(
            moments["covariance_home_away"] - observed_covariance_sample
        )
        bootstrap["share_only_variance_margin_minus_observed"].append(
            moments["variance_home_minus_away"] - observed_margin_variance_sample
        )
        for name, value in target_moments.items():
            bootstrap["covariance_matched_share"][name].append(value)
        bootstrap["share_variance_for_observed_covariance"].append(target_variance)
        bootstrap["share_variance_for_observed_covariance_minus_empirical_share_variance"].append(
            target_variance - var_share
        )
        bootstrap["observed_covariance_home_away"].append(observed_covariance_sample)
        bootstrap["generated_mean_total"].append(mu_n)
        bootstrap["generated_variance_total"].append(var_n)
        bootstrap["generated_minus_observed_variance_total"].append(
            var_n - float((observed_pairs[index].sum(axis=1)).var())
        )
        bootstrap["observed_share_mean"].append(p_share)
        bootstrap["observed_share_variance"].append(var_share)

    def summarize_moments(point: dict[str, float], samples: dict[str, list[float]]) -> dict[str, Any]:
        return {name: {"estimate": value, "cluster_bootstrap_95_ci": interval(samples[name])}
                for name, value in point.items()}

    output: dict[str, Any] = {
        "title": "NHL V3 home-away attempt share mechanism diagnosis",
        "scope": {
            "diagnostic_only": True,
            "candidate_selected": False,
            "gate_changed": False,
            "phase2a_modified": False,
            "monte_carlo_rerun": False,
            "2022_used_for_tuning": False,
            "draws_per_game": 16,
            "games": games,
            "bootstrap_unit": "game ID; each selected game retains both teams and all 16 saved draws",
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": seed,
            "interval_conditioning": "All intervals condition on the realized 16-draw set and exclude simulator Monte Carlo error.",
        },
        "provenance": {
            **pins,
            "inputs": [TRACE.relative_to(ROOT).as_posix(), PACE_JSON.relative_to(ROOT).as_posix(),
                       UNDERDISPERSION_JSON.relative_to(ROOT).as_posix()],
            "analysis_script_sha256": sha256(Path(__file__).resolve()),
            "runtime_seconds": time.perf_counter() - started,
        },
        "generated_attempt_covariance_decomposition": {
            "definition": "Exact finite-snapshot law of total covariance: first condition on game and total attempts N; then mix over N within game; finally mix the 16-draw game means across games.",
            "within_game_predictive_covariance_across_16_draws": {
                "estimate": point_components["conditional_covariance_given_game_and_total_attempts"]
                + point_components["within_game_covariance_of_conditional_means_across_total_attempts"],
                "cluster_bootstrap_95_ci": interval(bootstrap["within_game_predictive_covariance"]),
            },
            "components": summarize_moments(
                point_components,
                {name: values for name, values in bootstrap["decomposition"].items()},
            ),
            "direct_generated_covariance": float(population_covariance(generated_home, generated_away)),
            "state_path_identifiability": (
                "The trace stores game-level counts, not event-level intensity/state paths. The within-game term across N therefore includes allocation, score/manpower feedback, clock exposure, and OT; it cannot identify a causal shared-state-only component."
            ),
        },
        "attempt_share_and_pace": {
            "generated": {
                "mean_total_attempts": mean_total,
                "variance_total_attempts": variance_total,
                "cv_total_attempts": float(math.sqrt(variance_total) / mean_total),
                "mean_home_share": generated_share_mean,
                "variance_home_share": generated_share_variance,
                "sd_home_share": float(math.sqrt(generated_share_variance)),
                "share_overdispersion_index": float(generated_share_index),
                "variance_home": float(generated_home.var()),
                "variance_away": float(generated_away.var()),
                "covariance_home_away": float(population_covariance(generated_home, generated_away)),
                "variance_home_minus_away": float((generated_home - generated_away).var()),
            },
            "observed": {
                "mean_total_attempts": float(observed_total.mean()),
                "variance_total_attempts": float(observed_total.var()),
                "mean_home_share": observed_share_mean,
                "variance_home_share": observed_share_variance,
                "sd_home_share": float(math.sqrt(observed_share_variance)),
                "share_overdispersion_index": float(observed_share_index),
                "variance_home": float(observed_home.var()),
                "variance_away": float(observed_away.var()),
                "covariance_home_away": observed_covariance,
                "variance_home_minus_away": float((observed_home - observed_away).var()),
            },
        },
        "share_only_moment_counterfactual": {
            "assumption": "Keep the empirical generated total-attempt distribution; take the observed game-level home-share mean and variance independent of N.",
            "moments": summarize_moments(share_only, bootstrap["share_only"]),
            "mean_total_attempts": {"estimate": mean_total, "cluster_bootstrap_95_ci": interval(bootstrap["generated_mean_total"])},
            "variance_total_attempts": {"estimate": variance_total, "cluster_bootstrap_95_ci": interval(bootstrap["generated_variance_total"])},
            "variance_total_difference_generated_minus_observed": {
                "estimate": float(variance_total - observed_total.var()),
                "cluster_bootstrap_95_ci": interval(bootstrap["generated_minus_observed_variance_total"]),
            },
            "observed_covariance_home_away": {
                "estimate": observed_covariance,
                "cluster_bootstrap_95_ci": interval(bootstrap["observed_covariance_home_away"]),
            },
            "observed_share_mean": {"estimate": observed_share_mean, "cluster_bootstrap_95_ci": interval(bootstrap["observed_share_mean"])},
            "observed_share_variance": {"estimate": observed_share_variance, "cluster_bootstrap_95_ci": interval(bootstrap["observed_share_variance"])},
            "covariance_residual_vs_observed": float(share_only["covariance_home_away"] - observed_covariance),
            "covariance_difference_generated_share_only_minus_observed": {
                "estimate": float(share_only["covariance_home_away"] - observed_covariance),
                "cluster_bootstrap_95_ci": interval(bootstrap["share_only_covariance_minus_observed"]),
            },
            "variance_home_minus_away_difference_vs_observed": {
                "estimate": float(share_only["variance_home_minus_away"] - (observed_home - observed_away).var()),
                "cluster_bootstrap_95_ci": interval(bootstrap["share_only_variance_margin_minus_observed"]),
            },
            "variance_total_shortfall_vs_observed": float(variance_total - observed_total.var()),
            "share_variance_required_to_match_observed_covariance": {
                "estimate": share_variance_for_observed_covariance,
                "cluster_bootstrap_95_ci": interval(bootstrap["share_variance_for_observed_covariance"]),
                "difference_from_observed_share_variance": {
                    "estimate": float(share_variance_for_observed_covariance - observed_share_variance),
                    "cluster_bootstrap_95_ci": interval(
                        bootstrap["share_variance_for_observed_covariance_minus_empirical_share_variance"]
                    ),
                },
                "moments_at_that_variance": summarize_moments(covariance_target_share, bootstrap["covariance_matched_share"]),
            },
            "joint_exact_match_possible_under_independent_N_and_S": math.isclose(
                share_variance_for_observed_covariance, observed_share_variance, rel_tol=0.0, abs_tol=1e-12
            ),
        },
        "limits": [
            "The fixed-exogenous-path independent Poisson result is a conditional rate-process identity; the simulator's score, manpower, and OT path is endogenous to generated events.",
            "No event-level state paths are present in the saved count trace, so the shared-state contribution cannot be separated causally without replaying or rerunning paths, which was prohibited.",
            "Share-only moments leave generated total-attempt variance unchanged and assume N is independent of home share.",
        ],
    }
    output["provenance"]["runtime_seconds"] = time.perf_counter() - started
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.bootstrap_replicates != 2000:
        raise ValueError("THIS_DIAGNOSTIC_REQUIRES_2000_CLUSTER_BOOTSTRAP_REPLICATES")
    if args.seed < 0:
        raise ValueError("BOOTSTRAP_SEED_MUST_BE_NONNEGATIVE")
    result = analyze(args.bootstrap_replicates, args.seed)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "games": result["scope"]["games"],
        "draws_per_game": result["scope"]["draws_per_game"],
        "generated_covariance": result["generated_attempt_covariance_decomposition"]["direct_generated_covariance"],
        "decomposition": {key: value["estimate"] for key, value in result["generated_attempt_covariance_decomposition"]["components"].items()},
        "share_only": {key: value["estimate"] for key, value in result["share_only_moment_counterfactual"]["moments"].items()},
        "runtime_seconds": result["provenance"]["runtime_seconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
