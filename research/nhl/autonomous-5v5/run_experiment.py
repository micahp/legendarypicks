#!/usr/bin/env python3
"""Fit and evaluate the preregistered autonomous NHL 5v5 arrival candidates."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import data
from kernel import (BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, FAMILIES,
                    MODEL_VERSION, SOG_FAMILIES, SHOT_ATTEMPT_FAMILIES,
                    RenewalModel, common_random_seed, crps, paired_crps_bootstrap,
                    paired_game_bootstrap, sample_trace, trace_counts)


DEFAULT_OUTPUT = HERE / "results/nhl-autonomous-5v5-arrival-development-2026-10-27.json"
DEFAULT_REPORT = ROOT / "docs/research/NHL-AUTONOMOUS-5V5-ARRIVAL-REPORT-2026-10-27.md"
DRAW_REPLICATES = 10
METRIC_NAMES = ("bundle_count", "shot_attempts", "sog", "goals",
                *(f"family:{family}" for family in FAMILIES))


def _source_family_counts(periods: list[data.PeriodData]) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for period in periods:
        counts.update(period.other_source_types)
    return dict(counts.most_common())


def _eligible_family_counts(periods: list[data.PeriodData], seasons: set[int]) -> dict[str, int]:
    counts = collections.Counter()
    for period in periods:
        if period.season in seasons:
            counts.update(period.eligible_event_family_counts)
    return dict(sorted(counts.items()))


def _transition_family_counts(periods: list[data.PeriodData], seasons: set[int]) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for period in periods:
        if period.season not in seasons:
            continue
        for transition in period.transitions:
            counts.update(token.family for token in transition.mark)
    return dict(sorted(counts.items()))


def _event_state_v3_conditional_reference() -> dict[str, Any]:
    """Load eligible 5v5 event-row totals from the pinned audit diagnostics."""
    path = (data.BEHAVIOR_DIR / "results" /
            "nhl-behavior-evidence-event-state-v3-2026-10-27.json")
    digest = data.sha256_file(path)
    if digest != data.EXPECTED_EVENT_STATE_JSON_SHA256:
        raise ValueError(f"Event-State v3 result hash changed: {digest}")
    source = json.loads(path.read_text(encoding="utf-8"))
    populations = {}
    for section, label in (("training_2019_2020", "training_2019_2020"),
                           ("development_2021", "development_2021")):
        rows_by_family = source["event_rate_diagnostics"][section]
        count_key = "events" if section == "training_2019_2020" else "observed_events"
        populations[label] = {}
        for family in ("attempt", "sog", "goal"):
            row = next((item for item in rows_by_family[family]
                        if item.get("context") == "strength=5v5"), None)
            if row is None or count_key not in row:
                raise ValueError(f"Event-State v3 lacks {family} 5v5 reference for {section}")
            populations[label][family] = int(row[count_key])
    return {"sha256": digest, "populations": populations}


def _bundle_family_measures(families: dict[str, int]) -> dict[str, int]:
    return {
        "attempt": sum(families.get(name, 0) for name in
                       ("goal", "shot-on-goal", "missed-shot", "blocked-shot")),
        "sog": families.get("goal", 0) + families.get("shot-on-goal", 0),
        "goal": families.get("goal", 0),
    }


def _transitions_for_fit(periods: list[data.PeriodData], season: int) -> list[Any]:
    return [transition for period in periods if period.season == season
            for transition in period.transitions]


def _period_target(period: data.PeriodData, max_bundle_size: int) -> tuple[dict[str, float], int, collections.Counter[str]] | None:
    rows = [row for row in period.transitions if len(row.mark) <= max_bundle_size]
    exposure_seconds = sum(row.gap_seconds for row in rows)
    if exposure_seconds <= 0:
        return None
    counts: collections.Counter[str] = collections.Counter()
    for row in rows:
        counts["bundle_count"] += 1
        for token in row.mark:
            counts[f"family:{token.family}"] += 1
            if token.family in SHOT_ATTEMPT_FAMILIES:
                counts["shot_attempts"] += 1
            if token.family in SOG_FAMILIES:
                counts["sog"] += 1
            if token.family == "goal":
                counts["goals"] += 1
    targets = {metric: counts[metric] * 1200.0 / exposure_seconds
               for metric in METRIC_NAMES}
    return targets, exposure_seconds, counts


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _gap_summary(gaps: list[int]) -> dict[str, float | int | None]:
    if not gaps:
        return {"n": 0, "p50_seconds": None, "p90_seconds": None, "p95_seconds": None}
    return {"n": len(gaps), "p50_seconds": _quantile([float(x) for x in gaps], 0.50),
            "p90_seconds": _quantile([float(x) for x in gaps], 0.90),
            "p95_seconds": _quantile([float(x) for x in gaps], 0.95)}


def _nll_evaluation(model: RenewalModel, transitions: list[Any]) -> tuple[dict[str, Any], dict[str, tuple[float, float]], collections.Counter[str]]:
    game_losses: dict[str, tuple[float, float]] = {}
    fallback_counts: collections.Counter[str] = collections.Counter()
    gap_loss = 0.0
    mark_loss = 0.0
    exposure_seconds = 0
    for row in transitions:
        if len(row.mark) > model.max_bundle_size:
            continue
        p_gap = model.gap_log_probability(row.context, row.gap_seconds)
        p_mark = model.mark_log_probability(row.context, row.mark)
        loss_gap, loss_mark = -p_gap, -p_mark
        if not math.isfinite(loss_gap + loss_mark):
            raise ValueError(f"nonfinite held-out likelihood for {row.game_id} P{row.period}")
        gap_loss += loss_gap
        mark_loss += loss_mark
        exposure_seconds += row.gap_seconds
        fallback_counts[model.fallback_level(row.context)] += 1
        old_loss, old_exposure = game_losses.get(row.game_id, (0.0, 0.0))
        game_losses[row.game_id] = (old_loss + loss_gap + loss_mark,
                                   old_exposure + row.gap_seconds / 60.0)
    if exposure_seconds == 0:
        raise ValueError("no held-out 5v5 transition exposure remains for NLL")
    total = gap_loss + mark_loss
    metrics = {
        "transition_gaps": sum(1 for row in transitions if len(row.mark) <= model.max_bundle_size),
        "eligible_gap_exposure_seconds": exposure_seconds,
        "gap_nll_nats": gap_loss,
        "mark_nll_nats": mark_loss,
        "total_nll_nats": total,
        "nll_nats_per_5v5_minute": total / (exposure_seconds / 60.0),
        "fallback_counts": dict(sorted(fallback_counts.items())),
    }
    return metrics, game_losses, fallback_counts


def _sample_metrics(periods: list[data.PeriodData], models: dict[str, RenewalModel],
                    *, replicates: int = DRAW_REPLICATES) -> tuple[dict[str, Any], list[int]]:
    max_bundle_size = min(model.max_bundle_size for model in models.values())
    observed_by_metric: dict[str, dict[tuple[str, int], float]] = {
        metric: {} for metric in METRIC_NAMES
    }
    forecast_by_metric: dict[str, dict[str, dict[tuple[str, int], list[float]]]] = {
        name: {metric: {} for metric in METRIC_NAMES} for name in models
    }
    generated_gaps: dict[str, list[int]] = {name: [] for name in models}
    observed_gaps = [row.gap_seconds for period in periods
                     if period.season == 2021 for row in period.transitions
                     if len(row.mark) <= max_bundle_size]
    draw_count = 0
    replay_check: dict[str, Any] | None = None

    for period in periods:
        if period.season != 2021:
            continue
        period_key = (period.game_id, period.period)
        target = _period_target(period, max_bundle_size)
        if target is not None:
            targets, _, _ = target
            for metric, value in targets.items():
                observed_by_metric[metric][period_key] = value
        for replicate in range(replicates):
            seed = common_random_seed(period.game_id, period.period, replicate)
            candidate_traces = {}
            for name, model in models.items():
                trace = sample_trace(model, seed)
                candidate_traces[name] = trace
                draw_count += 1
                generated_gaps[name].extend(
                    next_second - previous_second
                    for previous_second, next_second in zip(
                        [0, *(second for second, _ in trace[:-1])],
                        [second for second, _ in trace])
                )
                counts = trace_counts(trace)
                for metric in METRIC_NAMES:
                    forecast_by_metric[name][metric].setdefault(period_key, []).append(
                        float(counts.get(metric, 0)))
            if replay_check is None:
                chosen = next(iter(models))
                replay = sample_trace(models[chosen], seed)
                replay_check = {
                    "game_id": period.game_id,
                    "period": period.period,
                    "replicate": replicate,
                    "candidate": chosen,
                    "byte_identical": candidate_traces[chosen] == replay,
                }

    metric_results: dict[str, Any] = {}
    for metric in METRIC_NAMES:
        candidate_summary = {}
        paired_scores: dict[str, dict[str, list[float]]] = {}
        for name in models:
            observed_period_values: list[float] = []
            forecast_period_means = []
            forecast_period_samples = []
            coverage80 = []
            game_scores: dict[str, list[float]] = {}
            for period_key, actual in observed_by_metric[metric].items():
                game_id, _ = period_key
                draws = forecast_by_metric[name][metric].get(period_key, [])
                if len(draws) != replicates:
                    raise AssertionError("trace draws do not form complete period replicate blocks")
                forecast_period_samples.append(draws)
                forecast_period_means.append(sum(draws) / len(draws))
                observed_period_values.append(actual)
                game_scores.setdefault(game_id, []).append(crps(draws, actual))
                low, high = _quantile(draws, 0.10), _quantile(draws, 0.90)
                coverage80.append(float(low <= actual <= high))
            if not observed_period_values:
                candidate_summary[name] = {"periods_scored": 0}
                continue
            crps_values = [score for game_rows in game_scores.values() for score in game_rows]
            actual_mean = sum(observed_period_values) / len(observed_period_values)
            forecast_mean = sum(forecast_period_means[:len(observed_period_values)]) / len(observed_period_values)
            observed_variance = statistics.pvariance(observed_period_values)
            forecast_variance = statistics.pvariance(forecast_period_means[:len(observed_period_values)])
            candidate_summary[name] = {
                "periods_scored": len(observed_period_values),
                "observed_mean_20m_equivalent": actual_mean,
                "forecast_mean_20m": forecast_mean,
                "observed_to_forecast_mean_ratio": actual_mean / forecast_mean if forecast_mean else None,
                "observed_period_variance": observed_variance,
                "forecast_period_mean_variance": forecast_variance,
                "mean_trace_variance": statistics.mean(
                    statistics.pvariance(block) for block in forecast_period_samples if len(block) > 1),
                "central_80pct_interval_coverage": sum(coverage80) / len(coverage80),
                "crps": sum(crps_values) / len(crps_values) if crps_values else None,
            }
            paired_scores[name] = game_scores
        comparison = None
        if set(models).issubset(paired_scores):
            names = list(models)
            comparison = paired_crps_bootstrap(
                paired_scores[names[0]], paired_scores[names[1]],
                replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        metric_results[metric] = {"candidates": candidate_summary,
                                  "paired_crps_delta_a1_minus_a0": comparison}

    return {
        "metrics": metric_results,
        "observed_interarrival_gap_seconds": _gap_summary(observed_gaps),
        "generated_interarrival_gap_seconds": {
            name: _gap_summary(values) for name, values in generated_gaps.items()
        },
        "trace_reproducibility_check": replay_check,
        "trace_count": draw_count,
        "trace_replicates_per_game_period": replicates,
    }, observed_gaps


def _load_or_build_cache(args: argparse.Namespace) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    if args.rebuild_cache or not args.cache.exists():
        payload = data.build_cache(args.data_root, args.boxscore_root)
        payload["cache_sha256"] = data.write_cache(payload, args.cache)
    else:
        payload = data.load_cache(args.cache)
        payload["cache_sha256"] = data.sha256_file(args.cache)
    return payload, time.perf_counter() - started


def _summary_exposure(periods: list[data.PeriodData], max_bundle_size: int) -> dict[str, Any]:
    dev = [row for row in periods if row.season == 2021]
    total_clock = len(dev) * 1200
    ambiguous = sum(row.ambiguous_seconds for row in dev)
    non5v5 = sum(row.shift_non5v5_seconds for row in dev)
    shift_ambiguous = sum(row.shift_ambiguous_seconds for row in dev)
    usable_gap_by_period = {
        (row.game_id, row.period): sum(transition.gap_seconds for transition in row.transitions
                                       if len(transition.mark) <= max_bundle_size)
        for row in dev
    }
    usable_gap = sum(usable_gap_by_period.values())
    periods_with_gaps = sum(value > 0 for value in usable_gap_by_period.values())
    unsupported_bundle_transitions = sum(
        len(transition.mark) > max_bundle_size for row in dev for transition in row.transitions)
    eligible_source_families = sum_counters(row.eligible_event_family_counts for row in dev)
    transition_destination_families: collections.Counter[str] = collections.Counter()
    for period in dev:
        for transition in period.transitions:
            for token in transition.mark:
                transition_destination_families[token.family] += 1
    omitted_eligible_families = {
        family: eligible_source_families.get(family, 0) - transition_destination_families.get(family, 0)
        for family in sorted(set(eligible_source_families) | set(transition_destination_families))
    }
    if any(count < 0 for count in omitted_eligible_families.values()):
        raise AssertionError("transition destinations exceed eligible source event bundles")
    eligible_bundle_count = sum(row.eligible_bundle_count for row in dev)
    transition_destination_bundle_count = sum(len(row.transitions) for row in dev)
    return {
        "eligible_development_games": len({row.game_id for row in dev}),
        "eligible_development_game_periods": len(dev),
        "full_regulation_clock_seconds": total_clock,
        "state_ambiguous_seconds_union": ambiguous,
        "state_ambiguity_fraction_of_regulation_clock": ambiguous / total_clock if total_clock else None,
        "shift_ambiguous_seconds": shift_ambiguous,
        "shift_non5v5_seconds": non5v5,
        "shift_5v5_seconds": sum(row.shift_5v5_seconds for row in dev),
        "eligible_interarrival_gap_exposure_seconds": usable_gap,
        "eligible_interarrival_gap_exposure_minutes": usable_gap / 60.0,
        "periods_with_eligible_gap_exposure": periods_with_gaps,
        "periods_without_eligible_gap_exposure": len(dev) - periods_with_gaps,
        "eligible_5v5_source_bundle_count": eligible_bundle_count,
        "eligible_5v5_source_bundles_without_qualifying_predecessor": (
            eligible_bundle_count - transition_destination_bundle_count),
        "eligible_5v5_source_event_family_counts": dict(sorted(eligible_source_families.items())),
        "transition_destination_event_family_counts": dict(sorted(transition_destination_families.items())),
        "eligible_events_omitted_without_qualifying_predecessor": omitted_eligible_families,
        "development_transitions_excluded_above_training_bundle_size": unsupported_bundle_transitions,
        "bundle_exclusions": dict(sorted(sum_counters(row.excluded_bundle_counts for row in dev).items())),
        "gap_exclusions": dict(sorted(sum_counters(row.gap_excluded_counts for row in dev).items())),
        "shift_source_anomalies": dict(sorted(sum_counters(row.shift_anomaly_counts for row in dev).items())),
        "other_source_types": _source_family_counts(dev),
    }


def sum_counters(counters):
    total = collections.Counter()
    for counter in counters:
        total.update(counter)
    return total


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    payload, cache_seconds = _load_or_build_cache(args)
    periods = data.period_records(payload)
    training = _transitions_for_fit(periods, 2019) + _transitions_for_fit(periods, 2020)
    development = _transitions_for_fit(periods, 2021)
    if not training or not development:
        raise ValueError("frozen populations produced no transitions")

    fit_start = time.perf_counter()
    models = {name: RenewalModel(name) for name in ("A0", "A1")}
    for model in models.values():
        model.fit(training)
    fit_seconds = time.perf_counter() - fit_start
    if models["A0"].max_bundle_size != models["A1"].max_bundle_size:
        raise AssertionError("paired candidates must use identical training marks")

    nll = {}
    game_losses = {}
    for name, model in models.items():
        metrics, game_rows, _ = _nll_evaluation(model, development)
        nll[name] = metrics
        game_losses[name] = game_rows
    nll_bootstrap = paired_game_bootstrap(
        game_losses["A0"], game_losses["A1"],
        replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)

    simulation_start = time.perf_counter()
    simulation, observed_gaps = _sample_metrics(periods, models)
    simulation_seconds = time.perf_counter() - simulation_start
    nll_ci_decision = nll_bootstrap["ci95_high"] < 0
    count_crps_a0 = simulation["metrics"]["bundle_count"]["candidates"]["A0"].get("crps")
    count_crps_a1 = simulation["metrics"]["bundle_count"]["candidates"]["A1"].get("crps")
    count_crps_not_worse = (count_crps_a0 is not None and count_crps_a1 is not None
                            and count_crps_a1 <= count_crps_a0)
    if nll_ci_decision and count_crps_not_worse:
        decision = "A1_CONTINUE_RESEARCH"
    else:
        decision = "A0_SIMPLER_REFERENCE_OR_NEITHER"

    exposure = _summary_exposure(periods, models["A0"].max_bundle_size)
    source_hashes = payload["source_hashes"]
    event_state_reference = _event_state_v3_conditional_reference()
    source_reconciliation = {}
    for label, seasons in (("training_2019_2020", {2019, 2020}),
                           ("development_2021", {2021})):
        extracted = _eligible_family_counts(periods, seasons)
        destinations = _transition_family_counts(periods, seasons)
        reference = event_state_reference["populations"][label]
        extracted_measures = _bundle_family_measures(extracted)
        destination_measures = _bundle_family_measures(destinations)
        source_reconciliation[label] = {
            "event_state_v3_eligible_individual_event_counts": reference,
            "eligible_bundle_extractor_event_counts": extracted_measures,
            "bundle_extractor_minus_event_state_v3": {
                measure: extracted_measures[measure] - reference[measure]
                for measure in ("attempt", "sog", "goal")
            },
            "transition_destination_event_counts": destination_measures,
            "eligible_bundle_events_omitted_without_qualifying_predecessor": {
                measure: extracted_measures[measure] - destination_measures[measure]
                for measure in ("attempt", "sog", "goal")
            },
        }
    source_hashes = {
        **source_hashes,
        "analysis_runner_code_sha256": data.sha256_file(HERE / "run_experiment.py"),
    }
    gap_prior_mass = data.PERIOD_SECONDS * models["A1"].alpha
    minimum_context_bundles = models["A1"].manifest()["minimum_context_bundles"]
    gap_smoothing_diagnostic = {
        "posthoc_diagnostic_only_no_retuning": True,
        "gap_support_seconds": data.PERIOD_SECONDS,
        "dirichlet_alpha_per_gap_value": models["A1"].alpha,
        "symmetric_pseudo_count_mass_per_context": gap_prior_mass,
        "minimum_context_bundle_count": minimum_context_bundles,
        "prior_mass_share_at_minimum_context_count": (
            gap_prior_mass / (gap_prior_mass + minimum_context_bundles)),
        "observed_gap_p95_seconds": simulation["observed_interarrival_gap_seconds"]["p95_seconds"],
        "a0_generated_gap_p95_seconds": simulation["generated_interarrival_gap_seconds"]["A0"]["p95_seconds"],
        "a1_generated_gap_p95_seconds": simulation["generated_interarrival_gap_seconds"]["A1"]["p95_seconds"],
        "interpretation": (
            "The wide symmetric gap prior places substantial mass on long unseen gaps in low-count contexts; "
            "this is consistent with A1's long generated tail and low event counts. This diagnosis does not alter the frozen model."
        ),
    }
    result = {
        "report": "nhl_autonomous_5v5_arrival_development",
        "date": "2026-10-27",
        "branch": "research/nhl-autonomous-5v5-2026-10-27",
        "original_preregistration_commit": "d97357c522a35b69a7f8c4d865217f2c90e420dc",
        "operational_addendum_commit": "70da7619783eb26a2ed6b90bf20bd97a03a004a0",
        "base": "da2475f1ea70648a1aeba805006776028368e8d5",
        "scope": "conditional fixed-strength 5v5 event-arrival research traces; not a valid full period/game",
        "training_population": payload["population"],
        "development_exposure": exposure,
        "event_state_v3_eligible_reference": event_state_reference,
        "source_reconciliation": source_reconciliation,
        "extraction_correction": {
            "status": "ZERO_DURATION_ANNOTATION_FIX_APPLIED_BEFORE_ACCEPTED_RESULTS",
            "zero_duration_policy": "Rows with equal parseable start/end or explicit 00:00 duration and a missing endpoint are counted as zero-duration annotations and contribute no interval.",
            "positive_interval_without_parseable_duration": "Fails closed by making that period shift state ambiguous.",
            "preliminary_run": "Invalidated; it treated zero-duration event annotations as unparseable active intervals and its scores are not used.",
            "development_zero_duration_annotations": exposure["shift_source_anomalies"].get("zero_duration_annotation", 0),
        },
        "source_hashes": source_hashes,
        "sequence_cache_sha256": payload.get("cache_sha256"),
        "candidate_manifests": {name: model.manifest() for name, model in models.items()},
        "development_nll": nll,
        "paired_nll_delta_a1_minus_a0": nll_bootstrap,
        "simulation_comparison": simulation,
        "frozen_gap_smoothing_diagnostic": gap_smoothing_diagnostic,
        "decision_rule": {
            "a1_nll_ci_entirely_better": nll_ci_decision,
            "a1_bundle_count_crps_not_worse": count_crps_not_worse,
            "decision": decision,
            "development_only": True,
        },
        "d0_b2_donor_slot_reference": {
            "status": "NOT_AVAILABLE",
            "reason": "No frozen event-level B2 donor-slot output was present in the pinned evaluation artifacts; aggregate score summaries cannot recover a matched clock-slot likelihood or event trace.",
        },
        "runtime_seconds": {
            "cache_load_or_build": cache_seconds,
            "model_fit": fit_seconds,
            "simulation_and_metrics": simulation_seconds,
            "total": time.perf_counter() - started,
        },
        "limitations": [
            "PBP whole-second clocks and sortOrder are not subsecond timing.",
            "Possession is a binary PBP-derived proxy, not continuous puck control.",
            "Every trace is conditional on uninterrupted 5v5 for a full 20-minute horizon.",
            "Penalties, stoppages affecting game legality, substitutions, teams, players, tactics, overtime, and physics are not simulated as a valid game.",
            "2021 was development-only and cannot support adoption or production claims.",
        ],
    }
    return result


def render_report(result: dict[str, Any]) -> str:
    population = result["training_population"]
    exposure = result["development_exposure"]
    nll = result["development_nll"]
    nll_delta = result["paired_nll_delta_a1_minus_a0"]
    metrics = result["simulation_comparison"]["metrics"]
    lines = [
        "# NHL Autonomous 5v5 Event-Arrival Experiment",
        "",
        f"- **Date:** {result['date']}",
        f"- **Branch:** `{result['branch']}`",
        f"- **Base:** `{result['base']}`",
        f"- **Preregistration:** `{result['original_preregistration_commit']}`; operational addendum `{result['operational_addendum_commit']}`",
        f"- **Decision:** `{result['decision_rule']['decision']}` (development-only)",
        "",
        "## Data and evaluation boundary",
        "",
        f"Training games: {population['eligible_games_by_start_season'].get('2019', 0) + population['eligible_games_by_start_season'].get('2020', 0):,} eligible 2019/20 games; development: {exposure['eligible_development_games']:,} eligible 2021 games and {exposure['eligible_development_game_periods']:,} regulation game-periods.",
        f"State-ambiguous clock: {exposure['state_ambiguous_seconds_union']:,}/{exposure['full_regulation_clock_seconds']:,} seconds ({100*exposure['state_ambiguity_fraction_of_regulation_clock']:.3f}%). Shift-derived non-5v5 time is {exposure['shift_non5v5_seconds']:,} seconds; usable adjacent 5v5 interarrival exposure is {exposure['eligible_interarrival_gap_exposure_minutes']:,.1f} minutes.",
        f"Eligible development transition gaps: {nll['A0']['transition_gaps']:,}; periods with eligible gap exposure: {exposure['periods_with_eligible_gap_exposure']:,}; periods without: {exposure['periods_without_eligible_gap_exposure']:,}.",
        f"Extractor-eligible 5v5 source bundles: {exposure['eligible_5v5_source_bundle_count']:,}; destination bundles with a qualifying preceding gap: {exposure['eligible_5v5_source_bundle_count'] - exposure['eligible_5v5_source_bundles_without_qualifying_predecessor']:,}; eligible source goals: {exposure['eligible_5v5_source_event_family_counts'].get('goal', 0):,}; goals retained as transition destinations: {exposure['transition_destination_event_family_counts'].get('goal', 0):,}; goals without a qualifying preceding gap: {exposure['eligible_events_omitted_without_qualifying_predecessor'].get('goal', 0):,}.",
        "",
        "This experiment models only event arrivals and source-family bundles during continuous 5v5 exposure. The fixed 20-minute traces assume 5v5 and both goalies remain present; they are not complete or rule-valid NHL periods. No 2021 events were used in fitting.",
        "",
        "## Primary held-out sequence score",
        "",
        "NLL includes the positive inter-bundle gap and the ordered destination bundle mark, normalized by eligible 5v5 interarrival minutes. Entry gaps and excluded/censored intervals are omitted and counted in the coverage fields.",
        "",
        "| Candidate | Transitions | Gap NLL | Mark NLL | Total NLL | NLL nats / 5v5 minute |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    dev_reconciliation = result["source_reconciliation"]["development_2021"]
    audit_reference = result["event_state_v3_eligible_reference"]
    reconciliation_lines = [
        "",
        "### Event-State and bundle coverage",
        "",
        "The pinned Event-State v3 diagnostics count individual events with an eligible reconciled 5v5 state and resolved team ownership. This extractor has a stricter bundle contract: all records at a whole-second timestamp must be eligible, map to a supported event mark, and have a supported owner; transition destinations additionally require a qualifying preceding 5v5 gap. The counts therefore use different eligibility units. Deltas below are exposed as coverage differences, not silently treated as exact reconciliation.",
        "Attempt counts include goals, shots on goal, missed shots, and blocked shots; SOG counts include goals and ordinary shots on goal.",
        "",
        "| 2021 measure | Event-State v3 eligible event rows | Extractor eligible bundle tokens | Difference | Transition destination tokens | Eligible tokens without qualifying predecessor |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for measure in ("attempt", "sog", "goal"):
        reference = audit_reference["populations"]["development_2021"][measure]
        extracted = dev_reconciliation["eligible_bundle_extractor_event_counts"][measure]
        destinations = dev_reconciliation["transition_destination_event_counts"][measure]
        omitted = dev_reconciliation["eligible_bundle_events_omitted_without_qualifying_predecessor"][measure]
        reconciliation_lines.append(
            f"| {measure} | {reference:,} | {extracted:,} | {extracted-reference:+,} | {destinations:,} | {omitted:,} |"
        )
    reconciliation_lines += [
        "",
        f"The first extraction run was invalidated before accepting its scores. {result['extraction_correction']['development_zero_duration_annotations']:,} development shift rows are zero-duration annotations; equal endpoints or an explicit zero duration with a missing endpoint are treated as no interval. Positive intervals missing a parseable duration remain fail-closed and make the period ambiguous.",
        f"Event-State v3 audit SHA-256: `{audit_reference['sha256']}`. The JSON contains the same reconciliation vectors for 2019/20 and 2021, the corrected cache hash, and source/extractor/runner hashes.",
        "",
    ]
    insertion = lines.index("## Primary held-out sequence score")
    lines[insertion:insertion] = reconciliation_lines
    for name in ("A0", "A1"):
        row = nll[name]
        lines.append(f"| {name} | {row['transition_gaps']:,} | {row['gap_nll_nats']:.2f} | {row['mark_nll_nats']:.2f} | {row['total_nll_nats']:.2f} | {row['nll_nats_per_5v5_minute']:.5f} |")
    lines += [
        "",
        f"Paired game-cluster bootstrap for A1 − A0: {nll_delta['mean_delta_b_minus_a']:.6f} nats/min, 95% interval [{nll_delta['ci95_low']:.6f}, {nll_delta['ci95_high']:.6f}] ({nll_delta['replicates']:,} replicates; seed {nll_delta['seed']}).",
        "",
        "## Per-20-minute event-count rates",
        "",
        "Observed period targets use event counts from eligible destination bundles divided by their eligible interarrival exposure, scaled to a 20-minute rate. Simulated traces use ten paired common-random-number replicates per 2021 game-period. CRPS uses the ten trace counts against the fractional 20-minute-equivalent observed target.",
        "",
        "| Metric | A0 CRPS | A1 CRPS | A1−A0 CRPS | A1−A0 95% interval | A0 observed/forecast | A1 observed/forecast |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, row in metrics.items():
        a0 = row["candidates"].get("A0", {})
        a1 = row["candidates"].get("A1", {})
        interval = row.get("paired_crps_delta_a1_minus_a0") or {}
        a0_ratio = a0.get("observed_to_forecast_mean_ratio")
        a1_ratio = a1.get("observed_to_forecast_mean_ratio")
        lines.append(f"| {metric} | {format_num(a0.get('crps'))} | {format_num(a1.get('crps'))} | {format_num(interval.get('mean_delta_b_minus_a'))} | [{format_num(interval.get('ci95_low'))}, {format_num(interval.get('ci95_high'))}] | {format_num(a0_ratio)} | {format_num(a1_ratio)} |")
    bundle_counts = metrics["bundle_count"]["candidates"]
    observed_bundle = bundle_counts["A0"]["observed_mean_20m_equivalent"]
    lines += [
        "",
        "Bundle-count calibration across 3,843 game-periods:",
        f"- Observed mean {observed_bundle:.2f} bundles per 20-minute-equivalent exposure; A0 forecast {bundle_counts['A0']['forecast_mean_20m']:.2f}, A1 forecast {bundle_counts['A1']['forecast_mean_20m']:.2f}.",
        f"- Observed period variance {bundle_counts['A0']['observed_period_variance']:.2f}; mean within-period trace variance A0 {bundle_counts['A0']['mean_trace_variance']:.2f}, A1 {bundle_counts['A1']['mean_trace_variance']:.2f}.",
        f"- Empirical central 80% coverage from ten traces per period: A0 {100*bundle_counts['A0']['central_80pct_interval_coverage']:.1f}%, A1 {100*bundle_counts['A1']['central_80pct_interval_coverage']:.1f}%.",
    ]
    gaps = result["simulation_comparison"]
    smoothing = result["frozen_gap_smoothing_diagnostic"]
    lines += [
        "",
        "## Arrival gaps, reproducibility, and runtime",
        "",
        f"Observed eligible gap distribution: {gaps['observed_interarrival_gap_seconds']}. Generated: {gaps['generated_interarrival_gap_seconds']}.",
        f"The frozen A1 gap prior assigns {smoothing['dirichlet_alpha_per_gap_value']} to each of {smoothing['gap_support_seconds']:,} possible integer gaps, or {smoothing['symmetric_pseudo_count_mass_per_context']:.0f} pseudo-counts per context. At the minimum eligible context size ({smoothing['minimum_context_bundle_count']} bundles), that is {100*smoothing['prior_mass_share_at_minimum_context_count']:.1f}% of posterior mass. Its generated p95 gap is {smoothing['a1_generated_gap_p95_seconds']:.0f}s versus {smoothing['observed_gap_p95_seconds']:.0f}s observed. This is a post-hoc diagnosis of the frozen smoothing choice; it was not retuned.",
        f"The fixed-seed replay check was byte-identical: `{gaps['trace_reproducibility_check']['byte_identical']}`. Generated traces: {gaps['trace_count']:,} ({gaps['trace_replicates_per_game_period']} per eligible game-period and candidate).",
        f"Runtime seconds: `{json.dumps(result['runtime_seconds'], sort_keys=True)}`. Sequence cache SHA-256: `{result['sequence_cache_sha256']}`; analysis runner SHA-256: `{result['source_hashes']['analysis_runner_code_sha256']}`.",
        "",
        "## Decision and limitations",
        "",
        f"Frozen decision rule: A1 primary NLL interval entirely below zero = `{result['decision_rule']['a1_nll_ci_entirely_better']}`; A1 bundle-count CRPS not worse than A0 = `{result['decision_rule']['a1_bundle_count_crps_not_worse']}`. Result: **{result['decision_rule']['decision']}**.",
        "",
        f"D0 B2 donor-slot reference: **{result['d0_b2_donor_slot_reference']['status']}** — {result['d0_b2_donor_slot_reference']['reason']}",
        "",
        "The training population is a research development sample, and 2021 is not an untouched test. The model does not generate penalties or handle exits from 5v5, stoppage restart legality, player deployment, teams, goalies, tactics, overtime, shootouts, or physical movement. No adoption or production change is supported by this comparison.",
        "",
        "Reproduce with `python3 research/nhl/autonomous-5v5/run_experiment.py` after verifying the source manifests. The derived transition cache is stored outside Git; its SHA-256 and frozen source hashes are in the result JSON.",
        "",
    ]
    return "\n".join(lines)


def format_num(value: Any) -> str:
    return "—" if value is None else f"{float(value):.5f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=data.DEFAULT_DATA_ROOT)
    parser.add_argument("--boxscore-root", type=Path, default=data.DEFAULT_BOXSCORE_ROOT)
    parser.add_argument("--cache", type=Path, default=data.DEFAULT_CACHE)
    parser.add_argument("--rebuild-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(body, encoding="utf-8")
    args.report.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "report": str(args.report),
        "decision": result["decision_rule"]["decision"],
        "training_games": result["training_population"]["eligible_games_by_start_season"],
        "development_games": result["development_exposure"]["eligible_development_games"],
        "sequence_cache_sha256": result["sequence_cache_sha256"],
        "runtime_seconds": result["runtime_seconds"]}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
