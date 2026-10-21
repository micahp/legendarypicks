#!/usr/bin/env python3
"""Diagnose whether Phase 2A count dispersion is in total pace or home share.

Uses the frozen Phase 2B game/draw snapshot and a fresh scan of the hash-pinned
2021 event source. It does not rerun Monte Carlo or change a model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PHASE1 = REPO / "research/nhl/nhl-v3-phase1-replay-2026-10-21"
PHASE2A = REPO / "research/nhl/nhl-v3-phase2a-stochastic-2026-10-21"
for path in (PHASE1, PHASE2A):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_phase2a as phase2a  # noqa: E402
from replay_model import SHOT_EVENTS  # noqa: E402

TRACE_PATH = HERE / "underdispersion-traces.json.gz"
PRIOR_JSON = HERE / "underdispersion.json"
RESULTS_PATH = HERE / "RESULTS.json"
OUTPUT_JSON = HERE / "total_pace_split.json"
OUTPUT_MD = HERE / "TOTAL-PACE-SPLIT.md"
BOOTSTRAP_SEED = 20261024
DEFAULT_BOOTSTRAP_REPLICATES = 2000
SIMS_PER_GAME = 16
EXPECTED_GAMES = 1312
EXPECTED_SOG_GAMES = 1292
PHASE2A_HASHES = {
    "evaluation_sha256": "24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930",
    "fitted_model_sha256": "8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb",
    "report_sha256": "b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0",
}
SIDES = ("home", "away")
PERIODS = ("P1", "P2", "P3", "OT")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_inputs() -> tuple[dict, dict, list[dict], dict]:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_JSON.read_text(encoding="utf-8"))
    if results.get("branch") != "research/nhl-v3-phase2b-scoring-2026-10-21":
        raise ValueError("PHASE2B_RESULTS_BRANCH_MISMATCH")
    if results.get("development", {}).get("games") != EXPECTED_GAMES:
        raise ValueError("PHASE2B_2021_GAME_COUNT_MISMATCH")
    if results.get("simulations_per_game") != SIMS_PER_GAME or results.get("seed") != 20261021:
        raise ValueError("PHASE2B_SIMULATION_TRACE_METADATA_MISMATCH")
    if prior.get("phase2b_results_sha256") != sha256(RESULTS_PATH):
        raise ValueError("PHASE2B_RESULTS_HASH_MISMATCH")
    if prior.get("input_snapshot", {}).get("sha256") != sha256(TRACE_PATH):
        raise ValueError("FROZEN_TRACE_HASH_MISMATCH")
    trace_hashes = prior.get("frozen_phase2a_hashes", {})
    if trace_hashes != PHASE2A_HASHES:
        raise ValueError("FROZEN_PHASE2A_RECORDED_HASHES_MISMATCH")
    if results.get("frozen_phase2a_hashes") != PHASE2A_HASHES:
        raise ValueError("PHASE2B_RESULTS_FROZEN_PHASE2A_HASH_MISMATCH")
    current_hashes = {
        "evaluation_sha256": sha256(PHASE2A / "EVALUATION.json"),
        "fitted_model_sha256": sha256(PHASE2A / "FITTED-MODEL.json"),
        "report_sha256": sha256(PHASE2A / "REPORT.md"),
    }
    if current_hashes != PHASE2A_HASHES:
        raise ValueError("FROZEN_PHASE2A_FILE_CHANGED")
    with gzip.open(TRACE_PATH, "rt", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    if snapshot.get("metadata", {}).get("phase2a_hashes") != PHASE2A_HASHES:
        raise ValueError("TRACE_FROZEN_PHASE2A_HASH_MISMATCH")
    games = snapshot.get("games")
    if not isinstance(games, list) or len(games) != EXPECTED_GAMES:
        raise ValueError("FROZEN_TRACE_GAME_COUNT_MISMATCH")
    metadata = snapshot["metadata"]
    if metadata.get("simulations_per_game") != SIMS_PER_GAME or metadata.get("monte_carlo_rerun") is not False:
        raise ValueError("FROZEN_TRACE_SIMULATION_PROVENANCE_MISMATCH")
    if metadata.get("source_pins") != prior.get("source_pins") or prior.get("source_pins") != results.get("source_pins"):
        raise ValueError("PINNED_SOURCE_METADATA_MISMATCH")
    return results, prior, games, metadata


def source_period_scan(results: dict, games: list[dict]) -> tuple[dict, dict]:
    """Rescan pinned 2021 PBP, reconcile attempts/SOG, and count periods."""
    command = results["command"]
    bundle = phase2a.load_bundle(
        artifact_dir=Path(command["artifacts"]),
        official_dir=Path(command["official"]),
        label_path=Path(command["labels"]),
    )
    definitions = {gid: definition for gid, definition in bundle.games.items()
                   if definition.season == 2021}
    if len(definitions) != EXPECTED_GAMES:
        raise ValueError(f"PINNED_2021_GAME_POPULATION_MISMATCH {len(definitions)}")
    by_id = {row["game_id"]: row for row in games}
    if set(definitions) != set(by_id):
        raise ValueError("TRACE_AND_PINNED_SOURCE_GAME_ID_MISMATCH")

    observed_attempts: dict[str, Counter[str]] = {gid: Counter() for gid in definitions}
    observed_pbp_sog: dict[str, Counter[str]] = {gid: Counter() for gid in definitions}
    periods = {period: {"attempts": Counter(), "sog": Counter()} for period in PERIODS}
    source_rows = 0
    scanned_games: set[str] = set()

    for gid, events in phase2a.iter_game_event_groups(bundle, game_ids=set(definitions)):
        if gid in scanned_games:
            raise ValueError(f"DUPLICATE_PINNED_SOURCE_GAME_GROUP {gid}")
        scanned_games.add(gid)
        definition = definitions[gid]
        trace_row = by_id[gid]
        if bool(definition.sog_disposition == "ACCEPT") != bool(trace_row["sog_eligible"]):
            raise ValueError(f"SOG_ELIGIBILITY_DISAGREEMENT {gid}")
        source_rows += len(events)
        for event in events:
            if (event.period_type not in {"REG", "OT"} or
                    event.quality.event != "ACCEPT" or
                    event.quality.period_number != "ACCEPT"):
                continue
            side = phase2a._event_side(definition, event)
            if side not in SIDES:
                continue
            if event.period_type == "REG":
                if event.period_number not in (1, 2, 3):
                    raise ValueError(f"UNEXPECTED_ACCEPTED_REGULATION_PERIOD {gid}/{event.period_number}")
                period = f"P{event.period_number}"
            else:
                period = "OT"
            if event.event_type not in SHOT_EVENTS or event.ordinary_shot_eligible is not True:
                continue
            if event.quality.team_count != "ACCEPT":
                continue
            label = phase2a._attempt_label(event.event_type)
            observed_attempts[gid][side] += 1
            periods[period]["attempts"][side] += 1
            if label in {"SAVED", "GOAL"}:
                observed_pbp_sog[gid][side] += 1
                if trace_row["sog_eligible"]:
                    periods[period]["sog"][side] += 1

    if scanned_games != set(definitions):
        raise ValueError(f"PINNED_SOURCE_GAME_SCAN_COVERAGE_MISMATCH {len(scanned_games)}/{len(definitions)}")
    for gid, definition in definitions.items():
        trace_row = by_id[gid]
        for side in SIDES:
            actual_attempts = int(observed_attempts[gid][side])
            frozen_attempts = int(trace_row["observed"]["attempts"][side])
            if actual_attempts != frozen_attempts:
                raise ValueError(f"SOURCE_TRACE_ATTEMPT_MISMATCH {gid}/{side}/{actual_attempts}/{frozen_attempts}")
        if trace_row["sog_eligible"]:
            official = {
                "home": int(definition.official_home_sog),
                "away": int(definition.official_away_sog),
            }
            if official != trace_row["observed"]["official_sog"]:
                raise ValueError(f"PINNED_OFFICIAL_SOG_TRACE_MISMATCH {gid}")
            for side in SIDES:
                if int(observed_pbp_sog[gid][side]) != official[side]:
                    raise ValueError(f"PBP_OFFICIAL_SOG_RECONCILIATION_FAILED {gid}/{side}")

    expected_attempt_totals = {
        side: sum(int(row["observed"]["attempts"][side]) for row in games)
        for side in SIDES
    }
    scanned_attempt_totals = {
        side: sum(int(counts[side]) for counts in observed_attempts.values())
        for side in SIDES
    }
    if expected_attempt_totals != scanned_attempt_totals:
        raise ValueError("PINNED_SOURCE_FULL_ATTEMPT_TOTAL_MISMATCH")
    period_output = {}
    for period in PERIODS:
        attempt_by_side = {side: int(periods[period]["attempts"][side]) for side in SIDES}
        sog_by_side = {side: int(periods[period]["sog"][side]) for side in SIDES}
        period_output[period] = {
            "attempts_by_side": attempt_by_side,
            "attempts_total": sum(attempt_by_side.values()),
            "attempts_per_attempt_population_game": sum(attempt_by_side.values()) / EXPECTED_GAMES,
            "official_sog_by_side_from_reconciled_pbp": sog_by_side,
            "official_sog_total_from_reconciled_pbp": sum(sog_by_side.values()),
            "official_sog_per_sog_eligible_game": sum(sog_by_side.values()) / EXPECTED_SOG_GAMES,
        }
    if sum(row["attempts_total"] for row in period_output.values()) != sum(expected_attempt_totals.values()):
        raise ValueError("PERIOD_ATTEMPT_TOTALS_DO_NOT_RECONCILE")
    return period_output, {
        "games_scanned": len(scanned_games),
        "source_event_rows_in_2021_groups": source_rows,
        "attempts_by_side": scanned_attempt_totals,
        "sog_pbp_by_side_sog_eligible": {
            side: sum(int(periods[p]["sog"][side]) for p in PERIODS) for side in SIDES
        },
        "official_sog_reconciled_games": EXPECTED_SOG_GAMES,
        "full_source_event_rows_verified_by_stream_reader": int(
            bundle.pins["expected_population"]["pbp_events"]),
    }


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sum(values * weights) / np.sum(weights))


def measure(pairs: np.ndarray, game_weights: np.ndarray) -> dict[str, float | int]:
    """Population moments of paired game outcomes under cluster multiplicities."""
    if pairs.ndim != 3 or pairs.shape[2] != 2 or len(game_weights) != pairs.shape[0]:
        raise ValueError("PAIR_ARRAY_OR_CLUSTER_WEIGHT_SHAPE_MISMATCH")
    draws = pairs.shape[1]
    weights = np.repeat(game_weights.astype(float), draws)
    flat = pairs.reshape(-1, 2).astype(float)
    home, away = flat[:, 0], flat[:, 1]
    total = home + away
    total_denom = float(weights.sum())
    mean_total = _weighted_mean(total, weights)
    variance_total = _weighted_mean((total - mean_total) ** 2, weights)
    valid = total > 0
    zero_count = int(np.sum(weights[~valid]))
    share_weights = weights[valid]
    share_denom = float(share_weights.sum())
    if share_denom == 0:
        raise ValueError("HOME_SHARE_UNDEFINED_FOR_ALL_ROWS")
    share = home[valid] / total[valid]
    mean_share = _weighted_mean(share, share_weights)
    variance_share = _weighted_mean((share - mean_share) ** 2, share_weights)
    inverse_total_mean = _weighted_mean(1.0 / total[valid], share_weights)
    binomial_share_variance = mean_share * (1.0 - mean_share) * inverse_total_mean
    share_index = variance_share / binomial_share_variance if binomial_share_variance > 0 else math.nan
    mean_total_share_rows = _weighted_mean(total[valid], share_weights)
    cov_total_share = _weighted_mean(
        (total[valid] - mean_total_share_rows) * (share - mean_share), share_weights)

    mean_home = _weighted_mean(home, weights)
    mean_away = _weighted_mean(away, weights)
    variance_home = _weighted_mean((home - mean_home) ** 2, weights)
    variance_away = _weighted_mean((away - mean_away) ** 2, weights)
    covariance_home_away = _weighted_mean((home - mean_home) * (away - mean_away), weights)
    variance_margin = _weighted_mean(((home - away) - (mean_home - mean_away)) ** 2, weights)

    # For N=0, H=N*s for every s. Assign the observed nonzero-row mean share
    # solely for the algebraic decomposition; retain a separate valid-row share N.
    product_share = np.divide(home, total, out=np.full_like(total, mean_share), where=valid)
    mean_product_share = _weighted_mean(product_share, weights)
    variance_product_share = _weighted_mean((product_share - mean_product_share) ** 2, weights)
    covariance_product = _weighted_mean(
        (total - mean_total) * (product_share - mean_product_share), weights)
    pace_component = mean_product_share ** 2 * variance_total
    share_component = mean_total ** 2 * variance_product_share
    raw_cov_component = 2.0 * mean_total * mean_product_share * covariance_product
    joint_component = variance_home - pace_component - share_component
    interaction_component = joint_component - raw_cov_component
    denominator = variance_home if variance_home else math.nan

    return {
        "rows": int(total_denom),
        "share_defined_rows": int(share_denom),
        "zero_total_rows": zero_count,
        "mean_total": mean_total,
        "variance_total": variance_total,
        "sd_total": math.sqrt(max(0.0, variance_total)),
        "fano_total": variance_total / mean_total if mean_total else math.nan,
        "mean_home_share": mean_share,
        "variance_home_share": variance_share,
        "sd_home_share": math.sqrt(max(0.0, variance_share)),
        "binomial_null_share_variance": binomial_share_variance,
        "share_overdispersion_index": share_index,
        "covariance_total_home_share": cov_total_share,
        "mean_home": mean_home,
        "mean_away": mean_away,
        "variance_home": variance_home,
        "variance_away": variance_away,
        "covariance_home_away": covariance_home_away,
        "variance_home_minus_away": variance_margin,
        "pace_component_home_variance": pace_component,
        "share_component_home_variance": share_component,
        "direct_covariance_component_home_variance": raw_cov_component,
        "product_interaction_component_home_variance": interaction_component,
        "joint_covariance_interaction_component_home_variance": joint_component,
        "pace_component_home_variance_pct": 100.0 * pace_component / denominator,
        "share_component_home_variance_pct": 100.0 * share_component / denominator,
        "joint_component_home_variance_pct": 100.0 * joint_component / denominator,
    }


def counterfactuals(observed: np.ndarray, generated: np.ndarray,
                    game_weights: np.ndarray) -> dict[str, float]:
    obs = measure(observed, game_weights)
    gen = measure(generated, game_weights)
    n_fixed = float(gen["mean_total"])
    s_obs_var = float(obs["variance_home_share"])
    s_gen_mean = float(gen["mean_home_share"])
    n_obs_var = float(obs["variance_total"])
    n_gen_var = float(gen["variance_total"])
    s_obs_mean = float(obs["mean_home_share"])
    s_obs_var = float(obs["variance_home_share"])
    gen_total_second_moment = n_fixed ** 2 + n_gen_var
    return {
        "fixed_generated_mean_total_observed_share_distribution_variance_home": n_fixed ** 2 * s_obs_var,
        "fixed_generated_mean_total_observed_share_distribution_covariance_home_away": -n_fixed ** 2 * s_obs_var,
        "fixed_generated_mean_share_observed_total_distribution_variance_home": s_gen_mean ** 2 * n_obs_var,
        "fixed_generated_mean_share_observed_total_distribution_covariance_home_away": s_gen_mean * (1.0 - s_gen_mean) * n_obs_var,
        "generated_total_distribution_observed_share_distribution_independent_variance_home": n_gen_var * s_obs_mean ** 2 + gen_total_second_moment * s_obs_var,
        "generated_total_distribution_observed_share_distribution_independent_variance_away": n_gen_var * (1.0 - s_obs_mean) ** 2 + gen_total_second_moment * s_obs_var,
        "generated_total_distribution_observed_share_distribution_independent_covariance_home_away": n_gen_var * s_obs_mean * (1.0 - s_obs_mean) - gen_total_second_moment * s_obs_var,
        "generated_mean_total_used": n_fixed,
        "generated_total_variance_used": n_gen_var,
        "observed_share_variance_used": s_obs_var,
        "observed_mean_share_used": s_obs_mean,
        "generated_mean_share_used": s_gen_mean,
        "observed_total_variance_used": n_obs_var,
    }


def percentile_interval(values: list[float]) -> list[float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return [math.nan, math.nan]
    return [float(value) for value in np.quantile(vals, [0.025, 0.975])]


def format_ci(interval: list[float], digits: int = 3) -> str:
    return f"[{interval[0]:.{digits}f}, {interval[1]:.{digits}f}]"


def logistic_normal_moments(mean_probability: float, sigma: float) -> tuple[float, float]:
    """Return calibrated intercept and variance for a logit-normal share."""
    nodes, weights = np.polynomial.hermite.hermgauss(64)
    z = math.sqrt(2.0) * nodes
    w = weights / math.sqrt(math.pi)

    def logistic(value: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(value, -700, 700)))

    lo, hi = -32.0, 32.0
    for _ in range(80):
        midpoint = 0.5 * (lo + hi)
        if float(np.sum(w * logistic(midpoint + sigma * z))) < mean_probability:
            lo = midpoint
        else:
            hi = midpoint
    intercept = 0.5 * (lo + hi)
    values = logistic(intercept + sigma * z)
    mean = float(np.sum(w * values))
    variance = float(np.sum(w * (values - mean) ** 2))
    return intercept, variance


def sigma_for_share_variance(mean_probability: float, target_variance: float) -> float | None:
    maximum = mean_probability * (1.0 - mean_probability)
    if not (0.0 < target_variance < maximum):
        return None
    lo, hi = 0.0, 12.0
    if logistic_normal_moments(mean_probability, hi)[1] < target_variance:
        return None
    for _ in range(55):
        mid = 0.5 * (lo + hi)
        if logistic_normal_moments(mean_probability, mid)[1] < target_variance:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def latent_moment_fit(observed: dict[str, float]) -> dict:
    """Overdetermined sizing fit under independent N and logistic-normal s."""
    mu = float(observed["mean_total"])
    p = float(observed["mean_home"]) / mu
    q = p * (1.0 - p)
    tau = math.sqrt(max(0.0, float(observed["variance_total"]))) / mu
    tau2 = tau * tau
    var_h = float(observed["variance_home"])
    var_a = float(observed["variance_away"])
    cov_ha = float(observed["covariance_home_away"])
    scale = mu * mu
    v_from_home = (var_h / scale - tau2 * p * p) / (1.0 + tau2)
    v_from_away = (var_a / scale - tau2 * (1.0 - p) ** 2) / (1.0 + tau2)
    v_from_cov = (tau2 * q - cov_ha / scale) / (1.0 + tau2)
    implied = [v_from_home, v_from_away, v_from_cov]
    v_fit_raw = float(np.mean(implied))
    epsilon = max(1e-12, q * 1e-10)
    v_fit = min(max(v_fit_raw, epsilon), q - epsilon)
    sigma = sigma_for_share_variance(p, v_fit)

    pred_h = scale * (tau2 * p * p + (1.0 + tau2) * v_fit)
    pred_a = scale * (tau2 * (1.0 - p) ** 2 + (1.0 + tau2) * v_fit)
    pred_cov = scale * (tau2 * q - (1.0 + tau2) * v_fit)
    predicted = {"variance_home": pred_h, "variance_away": pred_a,
                 "covariance_home_away": pred_cov}
    targets = {"variance_home": var_h, "variance_away": var_a,
               "covariance_home_away": cov_ha}
    residuals = {key: predicted[key] - targets[key] for key in targets}
    scale_residual = max(1.0, var_h, var_a, abs(cov_ha))
    exact = max(abs(value) for value in residuals.values()) <= 1e-8 * scale_residual

    min_sigma_at_tau_zero = None
    min_sigma_search_tau = None
    if cov_ha < 0:
        scaled_covariance = cov_ha / scale
        if q + scaled_covariance >= 0.0:
            required_v_at_zero = -scaled_covariance
            min_sigma_at_tau_zero = sigma_for_share_variance(p, required_v_at_zero)
            min_sigma_search_tau = 0.0
    crossover_tau = math.sqrt(v_fit / (q - v_fit)) if 0.0 < v_fit < q else None
    _, realized_share_variance = logistic_normal_moments(p, sigma) if sigma is not None else (None, None)
    return {
        "model": "N and s independent; E[N]=observed mean total; CV(N)=tau; s is logit-normal with calibrated mean p=observed mean home count / mean total and logit SD sigma; H=N*s and A=N*(1-s)",
        "fit_fold": "2021 development population; descriptive-after-selection",
        "mean_total_mu": mu,
        "mean_home_count_share_p": p,
        "empirical_unweighted_mean_game_share": float(observed["mean_home_share"]),
        "tau_from_observed_total_variance": tau,
        "share_variance_implied_by_home_variance": v_from_home,
        "share_variance_implied_by_away_variance": v_from_away,
        "share_variance_implied_by_team_covariance": v_from_cov,
        "share_variance_balanced_fit": v_fit,
        "sigma_logit": sigma,
        "logistic_normal_realized_share_variance": realized_share_variance,
        "interior_exact_solution_exists": bool(exact and sigma is not None and tau > 0),
        "predicted_triplet": predicted,
        "observed_triplet": targets,
        "prediction_minus_observation": residuals,
        "minimum_sigma_reaching_observed_negative_covariance_at_any_tau": min_sigma_at_tau_zero,
        "minimum_sigma_search_tau": min_sigma_search_tau,
        "covariance_zero_crossing_tau_at_balanced_sigma": crossover_tau,
        "covariance_sign_as_tau_grows": (
            "negative below the reported crossing, zero at the crossing, positive above it"
            if crossover_tau is not None else "not defined for this fitted share variance"
        ),
        "tau_sigma_identifiability": "Under the stated independent-margin moment model, tau is identified by Var(N)/mu^2 and sigma by the split variance/covariance. A nonzero empirical Cov(N,s), or a nonzero residual in the three-moment fit, shows that this two-parameter layer is not a complete description of the observed joint distribution.",
    }


def build_report(data: dict) -> str:
    lines = [
        "# NHL V3 total pace and home-share diagnostic",
        "",
        "Diagnostic only. The frozen Phase 2A simulator and its predictions were not changed, no new Monte Carlo was run, and no candidate, gate, or promotion rule was selected.",
        "",
        f"The analysis uses the 2021 development population: {data['population']['attempt_games']:,} games for attempts and {data['population']['sog_eligible_games']:,} games for official SOG. The 16 existing Phase 2A draws per game are held fixed. All intervals are 95% game-ID cluster bootstrap intervals, resampling games with both teams and every stored draw kept together. Every fitted value below is descriptive-after-selection on this same 2021 fold.",
        "",
        "## Total pace and share margins",
        "",
        "The total-count index is the Fano factor, Var(N)/E[N]. The bounded-share index is Var(s) divided by the variance expected from a binomial split at the observed mean share, s̄(1−s̄)E[1/N]; 1 is that conditional-binomial reference. Share moments use N>0 rows; zero-total rows are counted separately.",
        "",
        "| Outcome | Source | N mean [95% CI] | N variance [95% CI] | N SD [95% CI] | N Fano [95% CI] |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        for source in ("observed", "generated"):
            s = result[source]
            ci = result["bootstrap_95"][source]
            lines.append(
                f"| {outcome} | {source} | {s['mean_total']:.3f} {format_ci(ci['mean_total'])} | "
                f"{s['variance_total']:.3f} {format_ci(ci['variance_total'])} | "
                f"{s['sd_total']:.3f} {format_ci(ci['sd_total'])} | "
                f"{s['fano_total']:.3f} {format_ci(ci['fano_total'])} |"
            )
    lines += [
        "",
        "| Outcome | Source | Mean home share [95% CI] | Share variance [95% CI] | Share SD [95% CI] | Share index [95% CI] | Cov(N,s) [95% CI] |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        for source in ("observed", "generated"):
            s = result[source]
            ci = result["bootstrap_95"][source]
            lines.append(
                f"| {outcome} | {source} | {s['mean_home_share']:.4f} {format_ci(ci['mean_home_share'], 4)} | "
                f"{s['variance_home_share']:.6f} {format_ci(ci['variance_home_share'], 6)} | "
                f"{s['sd_home_share']:.4f} {format_ci(ci['sd_home_share'], 4)} | "
                f"{s['share_overdispersion_index']:.3f} {format_ci(ci['share_overdispersion_index'])} | "
                f"{s['covariance_total_home_share']:.4f} {format_ci(ci['covariance_total_home_share'], 4)} |"
            )
    lines += [
        "",
        "Team-pair moments and exact home-variance decomposition:",
        "",
        "| Outcome | Source | Var(H) | Var(A) | Cov(H,A) | Var(H−A) | Pace term | Share term | Direct 2μNμsCov(N,s) | Product interaction | Joint term |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        for source in ("observed", "generated"):
            s = result[source]
            lines.append(
                f"| {outcome} | {source} | {s['variance_home']:.3f} | {s['variance_away']:.3f} | "
                f"{s['covariance_home_away']:.3f} | {s['variance_home_minus_away']:.3f} | "
                f"{s['pace_component_home_variance']:.3f} ({s['pace_component_home_variance_pct']:.1f}%) | "
                f"{s['share_component_home_variance']:.3f} ({s['share_component_home_variance_pct']:.1f}%) | "
                f"{s['direct_covariance_component_home_variance']:.3f} | "
                f"{s['product_interaction_component_home_variance']:.3f} | "
                f"{s['joint_covariance_interaction_component_home_variance']:.3f} ({s['joint_component_home_variance_pct']:.1f}%) |"
            )
    lines += [
        "",
        "Paired generated-minus-observed differences use the same game-cluster resamples:",
        "",
        "| Outcome | Δ Var(N) [95% CI] | Δ Var(s) [95% CI] | Δ Var(H) [95% CI] | Δ Cov(H,A) [95% CI] | Δ Var(H−A) [95% CI] |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        diff = result["generated_minus_observed"]
        ci = result["bootstrap_95"]["generated_minus_observed"]
        lines.append(
            f"| {outcome} | {diff['variance_total']:.3f} {format_ci(ci['variance_total'])} | "
            f"{diff['variance_home_share']:.6f} {format_ci(ci['variance_home_share'], 6)} | "
            f"{diff['variance_home']:.3f} {format_ci(ci['variance_home'])} | "
            f"{diff['covariance_home_away']:.3f} {format_ci(ci['covariance_home_away'])} | "
            f"{diff['variance_home_minus_away']:.3f} {format_ci(ci['variance_home_minus_away'])} |"
        )
    lines += [
        "",
        "Diagnostic reading:",
    ]
    for outcome, result in data["outcomes"].items():
        obs, gen = result["observed"], result["generated"]
        diff = result["generated_minus_observed"]
        diff_ci = result["bootstrap_95"]["generated_minus_observed"]
        cf = result["counterfactuals"]
        observed_share_excess = -float(diff["variance_home_share"])
        observed_share_ci = [-float(diff_ci["variance_home_share"][1]),
                             -float(diff_ci["variance_home_share"][0])]
        share_ci_result = "excludes zero" if observed_share_ci[0] > 0 or observed_share_ci[1] < 0 else "crosses zero"
        total_deficit_pct = 100.0 * (float(obs["variance_total"]) - float(gen["variance_total"])) / float(obs["variance_total"])
        lines.append(
            f"\nFor {outcome}, generated total variance is {total_deficit_pct:.1f}% below observed, while observed share variance exceeds generated by {observed_share_excess:.6f} {format_ci(observed_share_ci, 6)} (paired interval {share_ci_result}). The generated-minus-observed Cov(N,s) interval is {format_ci(result['bootstrap_95']['generated_minus_observed']['covariance_total_home_share'], 4)}. Keeping V3's N distribution and replacing the share distribution under independence gives Var(H) {cf['generated_total_distribution_observed_share_distribution_independent_variance_home']:.2f} and Cov(H,A) {cf['generated_total_distribution_observed_share_distribution_independent_covariance_home_away']:.2f}, against observed {obs['variance_home']:.2f} and {obs['covariance_home_away']:.2f}."
        )
    lines += [
        "",
        "The decomposition is exact: Var(H) = s̄²Var(N) + N̄²Var(s) + Cjoint. Cjoint is the exact remainder; it includes the direct N–s covariance term plus product interaction terms. The direct term and interaction are shown separately, so the three headline terms sum exactly even when a component is negative. Component percentages are signed and can fall outside 0–100%.",
        "",
        "## Margin-swap counterfactuals",
        "",
        "These are moment counterfactuals, not simulations. Fixed-total holds N constant at the generated mean and inserts the observed game-share distribution. Fixed-share holds s constant at the generated mean and inserts the observed total-count distribution.",
        "",
        "| Outcome | Fixed generated-mean N: Var(H) | Fixed generated-mean N: Cov(H,A) | Fixed generated-mean s: Var(H) | Fixed generated-mean s: Cov(H,A) |",
        "|---|---:|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        cf = result["counterfactuals"]
        lines.append(
            f"| {outcome} | {cf['fixed_generated_mean_total_observed_share_distribution_variance_home']:.3f} | "
            f"{cf['fixed_generated_mean_total_observed_share_distribution_covariance_home_away']:.3f} | "
            f"{cf['fixed_generated_mean_share_observed_total_distribution_variance_home']:.3f} | "
            f"{cf['fixed_generated_mean_share_observed_total_distribution_covariance_home_away']:.3f} |"
        )
    lines += [
        "",
        "Holding V3's generated total-count distribution while replacing the share mean and variance with observed values gives this independent-margin moment counterfactual:",
        "",
        "| Outcome | Var(H) [95% CI] | Var(A) [95% CI] | Cov(H,A) [95% CI] |",
        "|---|---:|---:|---:|",
    ]
    for outcome, result in data["outcomes"].items():
        cf = result["counterfactuals"]
        ci = result["bootstrap_95"]["counterfactuals"]
        lines.append(
            f"| {outcome} | {cf['generated_total_distribution_observed_share_distribution_independent_variance_home']:.3f} "
            f"{format_ci(ci['generated_total_distribution_observed_share_distribution_independent_variance_home'])} | "
            f"{cf['generated_total_distribution_observed_share_distribution_independent_variance_away']:.3f} "
            f"{format_ci(ci['generated_total_distribution_observed_share_distribution_independent_variance_away'])} | "
            f"{cf['generated_total_distribution_observed_share_distribution_independent_covariance_home_away']:.3f} "
            f"{format_ci(ci['generated_total_distribution_observed_share_distribution_independent_covariance_home_away'])} |"
        )
    lines += [
        "",
        "This margin swap assumes N and s are independent; it is a sizing comparison, not a simulation. It preserves generated pace variation while substituting the observed share distribution.",
        "",
        "## Two-parameter latent sizing",
        "",
        "The sizing model assumes independent total N and share s. It fixes μ to the observed mean N and p to observed mean home count divided by mean N, sets τ from the observed Var(N), and calibrates a logit-normal share mean p with logit SD σ. Because the three observed second moments constrain two free parameters, an exact solution exists only when the three independently implied share variances agree. H=N·s and A=N·(1−s) are moment quantities here; this is not an integer event generator.",
        "",
        "| Outcome | τ | σ | Exact interior solution? | Min σ to reach observed Cov(H,A) at any τ | Covariance zero-crossing τ at fitted σ |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for outcome, outcome_data in data["outcomes"].items():
        fit = outcome_data["latent_moment_fit"]
        min_sigma = fit["minimum_sigma_reaching_observed_negative_covariance_at_any_tau"]
        cross = fit["covariance_zero_crossing_tau_at_balanced_sigma"]
        lines.append(
            f"| {outcome} | {fit['tau_from_observed_total_variance']:.5f} | "
            f"{fit['sigma_logit'] if fit['sigma_logit'] is not None else float('nan'):.5f} | "
            f"{'yes' if fit['interior_exact_solution_exists'] else 'no'} | "
            f"{min_sigma if min_sigma is not None else float('nan'):.5f} | "
            f"{cross if cross is not None else float('nan'):.5f} |"
        )
    for outcome, outcome_data in data["outcomes"].items():
        fit = outcome_data["latent_moment_fit"]
        lines.append(
            f"\n{outcome} fit residuals (model minus observed): "
            f"Var(H) {fit['prediction_minus_observation']['variance_home']:.4f}; "
            f"Var(A) {fit['prediction_minus_observation']['variance_away']:.4f}; "
            f"Cov(H,A) {fit['prediction_minus_observation']['covariance_home_away']:.4f}. "
            f"The covariance is negative below the reported crossing and turns positive as τ increases at fixed σ."
        )
    lines += [
        "",
        "Under this independent-margin model, τ is identifiable from total-count variance and σ from the split moments. That identification is conditional on the independence assumption; the observed Cov(N,s) and any nonzero triplet residual show what the two-parameter layer leaves unexplained. These fitted values use the same 2021 selection fold and are descriptive-after-selection, not validation.",
        "",
        "## Observed period totals",
        "",
        "Pinned accepted PBP attempts and reconciled official SOG by period:",
        "",
        "| Period | Attempts total (home/away) | Attempts per 1,312 games | SOG total (home/away) | SOG per 1,292 eligible games |",
        "|---|---:|---:|---:|---:|",
    ]
    for period, row in data["observed_period_totals"].items():
        a = row["attempts_by_side"]
        s = row["official_sog_by_side_from_reconciled_pbp"]
        lines.append(
            f"| {period} | {row['attempts_total']:,} ({a['home']:,}/{a['away']:,}) | "
            f"{row['attempts_per_attempt_population_game']:.3f} | "
            f"{row['official_sog_total_from_reconciled_pbp']:,} ({s['home']:,}/{s['away']:,}) | "
            f"{row['official_sog_per_sog_eligible_game']:.3f} |"
        )
    lines += [
        "",
        "Generated period totals are unavailable in the frozen compact snapshot: it stores game-level attempts and SOG counts but no period breakdown. Recovering generated period counts would require replaying simulations, which this diagnostic did not do.",
        "",
        "## Reproduction and limits",
        "",
        f"Command: `{data['provenance']['reproduction_command']}`",
        f"Analysis script SHA-256: `{data['provenance']['analysis_script_sha256']}`",
        f"Runtime: {data['provenance']['runtime_seconds']:.2f} seconds; {data['provenance']['bootstrap_replicates']:,} cluster bootstrap replicates; no Monte Carlo rerun.",
        f"Pinned 2021 source scan: {data['source_validation']['games_scanned']:,} games and {data['source_validation']['source_event_rows_in_2021_groups']:,} PBP event rows. Attempt counts reconciled to all {EXPECTED_GAMES:,} trace games; official team SOG reconciled to all {EXPECTED_SOG_GAMES:,} eligible games.",
        "",
        "This report diagnoses count margins only. It does not select or implement a candidate, change a gate, tune on 2022, make an adoption claim, or modify the Phase 2A artifacts.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    args = parser.parse_args()
    if args.bootstrap_replicates < 100:
        raise ValueError("BOOTSTRAP_REPLICATES_MUST_BE_AT_LEAST_100")
    started = time.monotonic()
    results, prior, games, trace_metadata = read_inputs()
    period_totals, source_validation = source_period_scan(results, games)

    eligible = {
        "attempts": games,
        "sog": [row for row in games if row["sog_eligible"]],
    }
    outcomes: dict[str, dict] = {}
    for outcome, selected_games in eligible.items():
        observed_pairs = np.asarray([
            [row["observed"]["attempts" if outcome == "attempts" else "official_sog"][side]
             for side in SIDES]
            for row in selected_games
        ], dtype=float)[:, None, :]
        generated_pairs = np.asarray([
            row["phase2a"]["attempts" if outcome == "attempts" else "sog"]
            for row in selected_games
        ], dtype=float)
        if generated_pairs.shape != (len(selected_games), SIMS_PER_GAME, 2):
            raise ValueError(f"FROZEN_TRACE_DRAW_SHAPE_MISMATCH {outcome}/{generated_pairs.shape}")
        if np.any(generated_pairs < 0) or np.any(generated_pairs != np.floor(generated_pairs)):
            raise ValueError(f"GENERATED_NONINTEGER_OR_NEGATIVE_COUNTS {outcome}")
        if np.any(observed_pairs < 0) or np.any(observed_pairs != np.floor(observed_pairs)):
            raise ValueError(f"OBSERVED_NONINTEGER_OR_NEGATIVE_COUNTS {outcome}")
        if outcome == "sog" and len(selected_games) != EXPECTED_SOG_GAMES:
            raise ValueError(f"SOG_ELIGIBLE_GAME_COUNT_MISMATCH {len(selected_games)}")
        weights = np.ones(len(selected_games), dtype=int)
        observed_point = measure(observed_pairs, weights)
        generated_point = measure(generated_pairs, weights)
        latent_fit = latent_moment_fit(observed_point)

        rng = np.random.default_rng(BOOTSTRAP_SEED + (0 if outcome == "attempts" else 1))
        samples = {
            "observed": defaultdict(list),
            "generated": defaultdict(list),
            "generated_minus_observed": defaultdict(list),
            "counterfactuals": defaultdict(list),
        }
        metric_names = [key for key, value in observed_point.items()
                        if isinstance(value, (float, int)) and key not in {"rows", "share_defined_rows", "zero_total_rows"}]
        cf_names = list(counterfactuals(observed_pairs, generated_pairs, weights))
        for _ in range(args.bootstrap_replicates):
            selected = rng.integers(0, len(selected_games), size=len(selected_games))
            cluster_weights = np.bincount(selected, minlength=len(selected_games))
            obs_boot = measure(observed_pairs, cluster_weights)
            gen_boot = measure(generated_pairs, cluster_weights)
            cf_boot = counterfactuals(observed_pairs, generated_pairs, cluster_weights)
            for name in metric_names:
                samples["observed"][name].append(float(obs_boot[name]))
                samples["generated"][name].append(float(gen_boot[name]))
                samples["generated_minus_observed"][name].append(
                    float(gen_boot[name]) - float(obs_boot[name]))
            for name in cf_names:
                samples["counterfactuals"][name].append(float(cf_boot[name]))
        ci = {
            source: {name: percentile_interval(values) for name, values in metric_map.items()}
            for source, metric_map in samples.items()
        }
        outcomes[outcome] = {
            "population_games": len(selected_games),
            "generated_draws_per_game": SIMS_PER_GAME,
            "observed": observed_point,
            "generated": generated_point,
            "generated_minus_observed": {
                name: float(generated_point[name]) - float(observed_point[name])
                for name in metric_names
            },
            "bootstrap_95": ci,
            "counterfactuals": counterfactuals(observed_pairs, generated_pairs, weights),
            "latent_moment_fit": latent_fit,
        }

    runtime = time.monotonic() - started
    reproduction = (
        f"/root/legendarypicks/backend/venv/bin/python {Path(__file__).resolve().relative_to(REPO)} "
        f"--bootstrap-replicates {args.bootstrap_replicates}"
    )
    data = {
        "title": "NHL V3 total pace and home-share diagnostic",
        "scope": "diagnostic only; no candidate selection, gate change, promotion, adoption, or Phase 2A modification",
        "population": {
            "season": 2021,
            "attempt_games": EXPECTED_GAMES,
            "sog_eligible_games": EXPECTED_SOG_GAMES,
            "cluster_unit": "game_id; both team outcomes and all 16 fixed generated draws remain together",
            "draws_per_game": SIMS_PER_GAME,
            "draw_seed": 20261021,
            "2022_used_for_tuning": False,
        },
        "definitions": {
            "count_overdispersion_index": "Fano factor Var(N)/E[N]",
            "share_overdispersion_index": "Var(s) / (s_bar*(1-s_bar)*E[1/N]); binomial split reference equals 1",
            "variance_convention": "population moments (ddof=0), equally weighted game outcomes; generated rows are the fixed game-by-draw mixture",
            "home_share": "s=H/N; share moments use N>0 rows, and zero-total rows are counted separately",
            "variance_decomposition": "Var(H)=s_bar^2 Var(N)+N_bar^2 Var(s)+C_joint; C_joint is the exact remainder and includes 2*N_bar*s_bar*Cov(N,s) plus product-interaction terms",
            "counterfactuals": "fixed generated-mean total with observed share distribution; fixed generated-mean share with observed total distribution",
        },
        "outcomes": outcomes,
        "observed_period_totals": period_totals,
        "generated_period_totals": {
            "available": False,
            "reason": "The immutable compact Phase 2A trace has no generated per-period attempt or SOG arrays; this run did not replay Monte Carlo.",
        },
        "source_validation": source_validation,
        "provenance": {
            "analysis_script": str(Path(__file__).resolve().relative_to(REPO)),
            "analysis_script_sha256": sha256(Path(__file__).resolve()),
            "runtime_seconds": runtime,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_replicates": args.bootstrap_replicates,
            "reproduction_command": reproduction,
            "base_worktree_commit": "d2be9408d45cebc067c53c19ecf4e74c29fa19dd",
            "phase2a_frozen_hashes": PHASE2A_HASHES,
            "phase2b_results_sha256": sha256(RESULTS_PATH),
            "underdispersion_trace_sha256": sha256(TRACE_PATH),
            "underdispersion_reported_source_pins": prior["source_pins"],
            "trace_metadata": trace_metadata,
            "monte_carlo_rerun": False,
            "fit_selection_note": "All latent moment fits use the 2021 development population and are descriptive-after-selection.",
        },
    }
    OUTPUT_JSON.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(build_report(data), encoding="utf-8")
    print(json.dumps({
        "json": str(OUTPUT_JSON.relative_to(REPO)),
        "report": str(OUTPUT_MD.relative_to(REPO)),
        "script_sha256": data["provenance"]["analysis_script_sha256"],
        "runtime_seconds": round(runtime, 3),
        "attempt_games": EXPECTED_GAMES,
        "sog_eligible_games": EXPECTED_SOG_GAMES,
        "bootstrap_replicates": args.bootstrap_replicates,
        "monte_carlo_rerun": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
