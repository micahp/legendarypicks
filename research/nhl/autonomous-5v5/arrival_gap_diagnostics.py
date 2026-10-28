#!/usr/bin/env python3
"""Separate NHL A1's conditional gap error from autonomous rollout effects.

The script is diagnostic only. It does not edit the frozen kernel or select a model.
"""

from __future__ import annotations

import argparse
import collections
import gc
import hashlib
import json
import math
import random
import sys
import time
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import data
import mechanism_diagnostics as mechanism
from kernel import (
    DIRICHLET_ALPHA,
    FAMILIES,
    OWNER_DOMAINS,
    PERIOD_SECONDS,
    RenewalModel,
    common_random_seed,
    crps,
    paired_crps_bootstrap,
    sample_trace,
    score_state_from_diff,
    trace_counts,
    update_context,
    validate_trace,
    _make_cdf,
    _sample_cdf,
)


EXPECTED_CACHE_SHA256 = "9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2"
EXPECTED_RESULT_SHA256 = "6116b755505fbfeca9dabd512b3a8db328202f78d4cf0345ed8c457763da3326"
EXPECTED_PRIOR_DIAGNOSTIC_SHA256 = "7a64d6d73cb3a2c8c23dbf53fc04ed93d4e09734fe5f29790a007f03aa3c13a6"
EXPECTED_KERNEL_SHA256 = "ea54dc59dd6df7a4372b506cc6a9105eda023abdf2de0017eece805722788773"
EXPECTED_EXTRACTOR_SHA256 = "dd19648ffbb3c5b3a74b98490e62f71dfd6c990a2d4093c42b22c583ce7280bb"
EXPECTED_RUNNER_SHA256 = "a120a1a0b21987853faa9e145b3c4631d99347b2322e40fd5c7150eef60fa7a6"
EXPECTED_MECHANISM_SHA256 = "cfe3743f0333b03d678d0aafa83f516a5bf87f0bd6b371e7708ada979ead6733"
EXPECTED_BEHAVIOR_SHA256 = "5b03df12a6e1dfd2bf546192c59c35b26c6bf2b75b04b338b14b57f85cc145a9"
EXPECTED_EVIDENCE_CORE_SHA256 = "cdcccbb1b4f5185df96178fccad4450a1bb3d8c9e5c4124389439c2281fc3490"
EXPECTED_EVENT_STATE_SHA256 = "1029c286cc3e20907338fea3f5f5bc612c6bb0bec793661f558ab57edd934f75"
EXPECTED_OUTPUT = HERE / "results/nhl-a1-arrival-gap-diagnosis-2026-10-27.json"
EXPECTED_REPORT = ROOT / "docs/research/NHL-A1-ARRIVAL-GAP-DIAGNOSIS-2026-10-27.md"
PREREG_PATH = ROOT / "docs/research/NHL-A1-ARRIVAL-GAP-DIAGNOSIS-PREREG-2026-10-27.md"
PREREG_SHA256 = "2f22f5b75e8317d10098878ada1eb009d75a8078dbd9cec76864007b8075ac96"
PREREG_COMMIT = "02c419d99065fe61085cb085a9eff60cb82d92fd"
DRAW_REPLICATES = 10
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261027
SMOOTHING_OFF_ALPHA = 0.0
SURVIVAL_THRESHOLDS = (10, 20, 30, 43, 60, 120, 300)
METRICS = ("bundles", "attempts", "sog", "goals", "faceoffs", "stoppages")
FAMILY_GAP_BINS = ((5, "1-5s"), (10, "6-10s"), (20, "11-20s"),
                   (30, "21-30s"), (60, "31-60s"), (120, "61-120s"),
                   (300, "121-300s"), (600, "301-600s"), (1200, "601-1200s"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"pinned hash mismatch for {path}: {actual} != {expected}")
    return actual


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def counter_quantile(counts: Mapping[int, int], probability: float) -> float | None:
    total = sum(counts.values())
    if total <= 0:
        return None
    rank = (total - 1) * probability
    low_rank, high_rank = math.floor(rank), math.ceil(rank)

    def at_rank(target: int) -> int:
        seen = 0
        for value in sorted(counts):
            seen += counts[value]
            if seen > target:
                return value
        raise AssertionError("quantile rank exceeded histogram count")

    low, high = at_rank(low_rank), at_rank(high_rank)
    return low + (high - low) * (rank - low_rank)


def counter_summary(counts: Mapping[int, int]) -> dict[str, float | int | None]:
    return {
        "n": sum(counts.values()),
        "p50_seconds": counter_quantile(counts, 0.50),
        "p90_seconds": counter_quantile(counts, 0.90),
        "p95_seconds": counter_quantile(counts, 0.95),
        "p99_seconds": counter_quantile(counts, 0.99),
    }


def observed_gap_partitions(periods: Iterable[Any], max_bundle_size: int) -> dict[str, list[Any]]:
    """Label the first scored transition separately from later scored transitions."""
    first: list[Any] = []
    later: list[Any] = []
    for period in periods:
        rows = [row for row in period.transitions if len(row.mark) <= max_bundle_size]
        if rows:
            first.append(rows[0])
            later.extend(rows[1:])
    return {"first_scored_transition": first, "later_scored_transitions": later}


def observed_exposure_summary(period_rows: Sequence[Mapping[str, int]]) -> dict[str, int]:
    """Reconcile full regulation, shift 5v5, retained gaps, and edge intervals."""
    result = collections.Counter()
    for row in period_rows:
        expected = int(row["shift_5v5_seconds"])
        pieces = (int(row["entry_5v5_seconds"])
                  + int(row["retained_gap_exposure_seconds"])
                  + int(row["terminal_5v5_seconds"])
                  + int(row["unpaired_5v5_seconds"]))
        if pieces != expected:
            raise ValueError(f"5v5 exposure components do not reconcile: {pieces} != {expected}")
        if int(row["regulation_seconds"]) != PERIOD_SECONDS:
            raise ValueError("regulation period clock must be 1,200 seconds")
        state_sum = (int(row["shift_5v5_seconds"])
                     + int(row["shift_non5v5_seconds"])
                     + int(row["shift_ambiguous_seconds"]))
        if state_sum != PERIOD_SECONDS:
            raise ValueError(f"shift state seconds do not reconcile to period: {state_sum}")
        result.update({key: int(row[key]) for key in (
            "regulation_seconds", "shift_5v5_seconds", "shift_non5v5_seconds",
            "shift_ambiguous_seconds", "entry_elapsed_seconds", "entry_5v5_seconds",
            "retained_gap_exposure_seconds", "terminal_elapsed_seconds",
            "terminal_5v5_seconds", "unpaired_5v5_seconds", "eligible_bundle_count",
            "transition_count")})
    return dict(result)


def prior_mass(training_count: int, categories: int = PERIOD_SECONDS,
               alpha: float = DIRICHLET_ALPHA) -> float:
    if training_count < 0 or categories < 1 or alpha < 0:
        raise ValueError("invalid Dirichlet prior parameters")
    denominator = training_count + categories * alpha
    return categories * alpha / denominator if denominator else 0.0


def gap_probability(model: RenewalModel, context: Any, seconds: int,
                    alpha_override: float | None = None) -> float:
    if not 1 <= seconds <= PERIOD_SECONDS:
        return 0.0
    if alpha_override is None:
        return model.gap_probability(context, seconds)
    if alpha_override < 0:
        raise ValueError("gap smoothing alpha cannot be negative")
    counts = model.stats[model.selected_key(context)].gaps
    denominator = sum(counts.values()) + alpha_override * PERIOD_SECONDS
    if denominator <= 0:
        raise ValueError("selected context has no gap training support")
    return (counts[seconds] + alpha_override) / denominator


def gap_survival(model: RenewalModel, context: Any, threshold: int,
                 alpha_override: float | None = None) -> float:
    if threshold < 0 or threshold > PERIOD_SECONDS:
        raise ValueError("survival threshold must be in 0..1,200")
    if alpha_override is None:
        alpha_override = model.alpha
    if alpha_override < 0:
        raise ValueError("gap smoothing alpha cannot be negative")
    selected_key = model.selected_key(context)
    cache = getattr(model, "_diagnostic_gap_survival_cache", None)
    if cache is None:
        cache = {}
        setattr(model, "_diagnostic_gap_survival_cache", cache)
    cache_key = (id(model.stats), selected_key, alpha_override)
    table = cache.get(cache_key)
    if table is None:
        counts = model.stats[selected_key].gaps
        denominator = sum(counts.values()) + alpha_override * PERIOD_SECONDS
        if denominator <= 0:
            raise ValueError("selected context has no gap training support")
        tails = [0.0] * (PERIOD_SECONDS + 1)
        tail_count = 0
        for current_threshold in range(PERIOD_SECONDS - 1, -1, -1):
            tail_count += counts[current_threshold + 1]
            tails[current_threshold] = (
                tail_count + alpha_override * (PERIOD_SECONDS - current_threshold)
            ) / denominator
        cache[cache_key] = table = tuple(tails)
    return table[threshold]


def selected_context_mix_summary(model: RenewalModel, rows: Sequence[Any]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot summarize an empty context population")
    selected = collections.Counter(model.selected_key(row.context) for row in rows)
    mixture = [0.0] * (PERIOD_SECONDS + 1)
    weighted_prior_mass = 0.0
    weighted_empirical_mean = 0.0
    weighted_posterior_mean = 0.0
    support_values: list[float] = []
    for key, frequency in selected.items():
        stats = model.stats[key]
        total = sum(stats.gaps.values())
        if total <= 0:
            raise ValueError(f"selected context has no training gaps: {key}")
        mass = prior_mass(total, PERIOD_SECONDS, model.alpha)
        empirical_mean = sum(second * count for second, count in stats.gaps.items()) / total
        posterior_mean = ((1 - mass) * empirical_mean + mass * ((PERIOD_SECONDS + 1) / 2))
        weight = frequency / len(rows)
        weighted_prior_mass += weight * mass
        weighted_empirical_mean += weight * empirical_mean
        weighted_posterior_mean += weight * posterior_mean
        support_values.extend([float(total)] * frequency)
        denominator = total + model.alpha * PERIOD_SECONDS
        for second in range(1, PERIOD_SECONDS + 1):
            mixture[second] += weight * (stats.gaps[second] + model.alpha) / denominator
    cdf = 0.0
    predicted_quantiles: dict[str, int | None] = {}
    for label, q in (("p50_seconds", .50), ("p90_seconds", .90),
                     ("p95_seconds", .95), ("p99_seconds", .99)):
        cdf = 0.0
        found = None
        for second in range(1, PERIOD_SECONDS + 1):
            cdf += mixture[second]
            if cdf >= q:
                found = second
                break
        predicted_quantiles[label] = found
    level_counts = collections.Counter(model.fallback_level(row.context) for row in rows)
    unseen = sum(
        1 for row in rows
        if model.stats[model.selected_key(row.context)].gaps[row.gap_seconds] == 0
    )
    supported_loss = 0.0
    supported_count = 0
    for row in rows:
        counts = model.stats[model.selected_key(row.context)].gaps
        if counts[row.gap_seconds] > 0:
            supported_loss -= math.log(counts[row.gap_seconds] / sum(counts.values()))
            supported_count += 1
    return {
        "rows": len(rows),
        "unique_selected_contexts": len(selected),
        "fallback_level_rows": dict(sorted(level_counts.items())),
        "selected_training_support": {
            "min": int(min(support_values)),
            "p50": percentile(support_values, .50),
            "p90": percentile(support_values, .90),
            "max": int(max(support_values)),
        },
        "uniform_prior_mass_weighted_mean": weighted_prior_mass,
        "uniform_prior_mass_by_selected_support": {
            "min": min(prior_mass(model.stats[key].n, PERIOD_SECONDS, model.alpha)
                       for key in selected),
            "p50": percentile([prior_mass(model.stats[key].n, PERIOD_SECONDS, model.alpha)
                               for key in selected], .50),
            "p90": percentile([prior_mass(model.stats[key].n, PERIOD_SECONDS, model.alpha)
                               for key in selected], .90),
            "max": max(prior_mass(model.stats[key].n, PERIOD_SECONDS, model.alpha)
                       for key in selected),
        },
        "mean_empirical_gap_seconds_weighted_by_observed_context": weighted_empirical_mean,
        "mean_smoothed_gap_seconds_weighted_by_observed_context": weighted_posterior_mean,
        "predicted_gap_quantiles_mixture_over_observed_contexts": predicted_quantiles,
        "observed_gap_quantiles": {
            "p50_seconds": percentile([row.gap_seconds for row in rows], .50),
            "p90_seconds": percentile([row.gap_seconds for row in rows], .90),
            "p95_seconds": percentile([row.gap_seconds for row in rows], .95),
            "p99_seconds": percentile([row.gap_seconds for row in rows], .99),
        },
        "heldout_gaps_absent_from_unsmoothed_selected_training_support": unseen,
        "heldout_gap_support_rate": 1 - unseen / len(rows),
        "unsmoothed_nll_on_supported_subset_only_nats_per_gap": (
            supported_loss / supported_count if supported_count else None),
        "unsmoothed_full_heldout_nll": (
            "infinite: at least one held-out gap has zero probability"
            if unseen else supported_loss),
    }


class TraceRandom(random.Random):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.last_random: float | None = None

    def random(self) -> float:
        self.last_random = super().random()
        return self.last_random


def sample_trace_diagnostic(model: RenewalModel, seed: int, *,
                            horizon: int = PERIOD_SECONDS,
                            initial: Any | None = None,
                            alpha_gap: float | None = None,
                            keep_steps: bool = False) -> dict[str, Any]:
    """Sample a frozen trace, optionally changing only the gap PMF smoothing."""
    if not 1 <= horizon <= PERIOD_SECONDS:
        raise ValueError("trace horizon must be in 1..1,200 seconds")
    if alpha_gap is not None and alpha_gap < 0:
        raise ValueError("gap alpha cannot be negative")
    context = initial or data.Context("faceoff", True, 0, 0)
    rng = TraceRandom(seed)
    now = 0
    trace: list[tuple[int, tuple[Any, ...]]] = []
    emitted_gaps: list[int] = []
    steps: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    occupancy: collections.Counter[tuple[Any, ...]] = collections.Counter()
    while now < horizon:
        before = context
        key = model.selected_key(before)
        stats = model.stats[key]
        support = stats.n
        if alpha_gap is None or alpha_gap == model.alpha:
            gap = model.sample_gap(before, rng)
        else:
            cdf_cache = getattr(model, "_diagnostic_gap_cdfs", None)
            if cdf_cache is None:
                cdf_cache = {}
                setattr(model, "_diagnostic_gap_cdfs", cdf_cache)
            cdf_key = (id(model.stats), key, alpha_gap)
            cdf = cdf_cache.get(cdf_key)
            if cdf is None:
                weights = [stats.gaps[second] + alpha_gap
                           for second in range(1, PERIOD_SECONDS + 1)]
                cdf = _make_cdf(weights)
                cdf_cache[cdf_key] = cdf
            gap = _sample_cdf(cdf, rng) + 1
        gap_uniform = rng.last_random
        probability = gap_probability(model, before, gap, alpha_gap)
        occupancy[(before.previous_family, before.possession_known,
                   before.score_state, before.clock_bucket,
                   model.fallback_level(before), support)] += 1
        arrival = now + gap
        if arrival >= horizon:
            terminal = {
                "gap_seconds": gap,
                "remaining_horizon_seconds": horizon - now,
                "gap_probability": probability,
                "gap_uniform": gap_uniform,
                "context_before": context_dict(before),
                "selected_context_key": list(key),
                "context_support": support,
                "censored_at_or_beyond_horizon": True,
            }
            break
        mark = model.sample_mark(before, rng)
        after = update_context(before, mark, arrival)
        trace.append((arrival, mark))
        emitted_gaps.append(gap)
        if keep_steps:
            steps.append({
                "relative_second": arrival,
                "gap_seconds": gap,
                "context_before": context_dict(before),
                "context_after": context_dict(after),
                "selected_context_key": list(key),
                "context_support": support,
                "gap_probability": probability,
                "gap_uniform": gap_uniform,
                "mark": [{"family": token.family, "owner": token.owner} for token in mark],
                "mark_log_probability": model.mark_log_probability(before, mark),
            })
        context = after
        now = arrival
    validate_trace(trace, horizon=horizon)
    return {
        "trace": trace,
        "emitted_gaps": emitted_gaps,
        "terminal_gap": terminal,
        "first_attempt_gap": (emitted_gaps[0] if emitted_gaps else
                              (terminal["gap_seconds"] if terminal else None)),
        "first_emitted_gap": emitted_gaps[0] if emitted_gaps else None,
        "subsequent_emitted_gaps": emitted_gaps[1:],
        "steps": steps,
        "state_occupancy": occupancy,
    }


def context_dict(context: Any) -> dict[str, Any]:
    return {
        "previous_family": context.previous_family,
        "possession_known": context.possession_known,
        "score_diff": context.score_diff,
        "score_state": context.score_state,
        "clock_bucket": context.clock_bucket,
    }


def period_start_score_diffs(pbp: dict[str, Any], owner_resolver: Any) -> dict[int, int]:
    """Reconstruct cutoff score from regulation goals in strictly earlier periods."""
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    if not home_id or not away_id or home_id == away_id:
        raise ValueError("PBP lacks two distinct stable team IDs")
    team_sides = {home_id: "home", away_id: "away"}
    scores = {"home": 0, "away": 0}
    starts: dict[int, int] = {}
    plays = sorted(enumerate(pbp.get("plays") or []),
                   key=lambda item: (int(item[1].get("sortOrder", item[0])), item[0]))
    for _, event in plays:
        descriptor = event.get("periodDescriptor") or {}
        if descriptor.get("periodType") != "REG":
            continue
        try:
            period = int(descriptor.get("number") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("unparseable regulation period in PBP") from exc
        if period not in (1, 2, 3):
            continue
        if period not in starts:
            starts[period] = scores["home"] - scores["away"]
        if event.get("typeDescKey") == "goal":
            side = owner_resolver(event, team_sides)
            if side not in scores:
                raise ValueError(
                    f"goal has unresolved owner before period {period}: "
                    f"game={pbp.get('id')} event={event.get('eventId')}"
                )
            scores[side] += 1
    if set(starts) != {1, 2, 3}:
        raise ValueError(f"PBP lacks a scored period-start boundary: {sorted(starts)}")
    if starts[1] != 0:
        raise AssertionError("period 1 must begin tied 0-0")
    return starts


def validate_source_clock_order(pbp: dict[str, Any], period_no: int,
                               clock_parser: Any) -> None:
    """Fail closed if source event order contradicts elapsed period-clock order."""
    plays = sorted(enumerate(pbp.get("plays") or []),
                   key=lambda item: (int(item[1].get("sortOrder", item[0])), item[0]))
    previous: int | None = None
    for _, event in plays:
        descriptor = event.get("periodDescriptor") or {}
        if (descriptor.get("periodType") != "REG"
                or int(descriptor.get("number") or 0) != period_no):
            continue
        try:
            second = int(clock_parser(str(event.get("timeInPeriod"))))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{pbp.get('id')} P{period_no}: unparseable source event clock"
            ) from exc
        if not 0 <= second <= PERIOD_SECONDS:
            raise ValueError(f"{pbp.get('id')} P{period_no}: source clock out of range: {second}")
        if previous is not None and second < previous:
            raise ValueError(
                f"{pbp.get('id')} P{period_no}: non-monotone source clock {previous} -> {second}"
            )
        previous = second


def assert_transition_reconciliation(extracted: Sequence[Any],
                                    independent: Sequence[tuple[Any, ...]],
                                    context: str) -> None:
    if transition_signature(extracted) != list(independent):
        raise ValueError(f"{context}: independent source transition count/content mismatch")


def initial_context_for_period(start_info: Mapping[str, Any],
                               score_aware: bool) -> Any:
    score_diff = int(start_info["score_diff"]) if score_aware else 0
    return data.Context("faceoff", True, score_diff, 0)


def _event_ambiguous_seconds(records: Sequence[dict[str, Any]], period: int) -> set[int]:
    return {
        int(row["time"]) for row in records
        if row.get("period_type") == "REG" and int(row.get("period") or 0) == period
        and row.get("type") not in data.BOUNDARY_TYPES
        and not (row.get("event_state_attribution") or {}).get("eligible_for_conditional_fit")
    }


def transition_signature(rows: Sequence[Any]) -> list[tuple[Any, ...]]:
    return [(row.gap_seconds, row.context, row.mark) for row in rows]


def source_period_metrics(game_id: str, period_no: int, pbp: dict[str, Any],
                          shifts: dict[str, Any], records: list[dict[str, Any]],
                          behavior: Any) -> tuple[Any, dict[str, Any], dict[str, Any] | None]:
    """Re-extract one source period and reconcile its cache/model exposure pieces."""
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home_id: "home", away_id: "away"}
    roster = {
        str(row.get("playerId")): (str(row.get("teamId") or ""),
                                    str(row.get("positionCode") or "?"))
        for row in pbp.get("rosterSpots") or [] if row.get("playerId") is not None
    }
    source = data._period_data(game_id, 2021, period_no, pbp, shifts,
                               {"event_records": records})
    states, _, _ = data._state_by_second(shifts, game_id, period_no, team_sides, roster)
    if len(states) != PERIOD_SECONDS:
        raise ValueError(f"{game_id} P{period_no}: state timeline is not 1,200 seconds")
    bundles, _ = data._make_bundles(
        {"event_records": records}, pbp, game_id, 2021, period_no,
        _event_ambiguous_seconds(records, period_no))
    eligible = [bundle for bundle in bundles if bundle.eligible]
    first_second = eligible[0].second if eligible else None
    last_second = eligible[-1].second if eligible else None
    entry_seconds = first_second if first_second is not None else PERIOD_SECONDS
    terminal_seconds = PERIOD_SECONDS - last_second if last_second is not None else 0
    entry_5v5 = sum(state == "5v5" for state in states[:entry_seconds])
    terminal_5v5 = (sum(state == "5v5" for state in states[last_second:])
                    if last_second is not None else 0)
    retained_exposure = sum(row.gap_seconds for row in source.transitions)
    unpaired = source.shift_5v5_seconds - entry_5v5 - terminal_5v5 - retained_exposure
    if unpaired < 0:
        raise ValueError(
            f"{game_id} P{period_no}: overlap or clock mismatch in source exposure partition"
        )
    detail = {
        "regulation_seconds": PERIOD_SECONDS,
        "shift_5v5_seconds": source.shift_5v5_seconds,
        "shift_non5v5_seconds": source.shift_non5v5_seconds,
        "shift_ambiguous_seconds": source.shift_ambiguous_seconds,
        "entry_elapsed_seconds": entry_seconds,
        "entry_5v5_seconds": entry_5v5,
        "retained_gap_exposure_seconds": retained_exposure,
        "terminal_elapsed_seconds": terminal_seconds,
        "terminal_5v5_seconds": terminal_5v5,
        "unpaired_5v5_seconds": unpaired,
        "eligible_bundle_count": source.eligible_bundle_count,
        "transition_count": len(source.transitions),
        "period_start_second_first_eligible_bundle": first_second,
        "period_end_second_last_eligible_bundle": last_second,
        "gap_excluded_counts": dict(sorted(source.gap_excluded_counts.items())),
        "excluded_bundle_counts": dict(sorted(source.excluded_bundle_counts.items())),
        "event_state_ambiguous_seconds_union": source.ambiguous_seconds,
    }
    first_destination = None
    valid_pairs = []
    for previous, current in zip(bundles, bundles[1:]):
        if not previous.eligible or not current.eligible:
            continue
        gap = current.second - previous.second
        between = states[previous.second:current.second]
        if any(state == "ambiguous" for state in between):
            continue
        if any(state != "5v5" for state in between):
            continue
        if not current.mark:
            continue
        valid_pairs.append((previous, current, gap))
    independent = [(gap, previous.context_after, current.mark)
                   for previous, current, gap in valid_pairs]
    assert_transition_reconciliation(source.transitions, independent,
                                     f"{game_id} P{period_no}")
    if valid_pairs:
        first_destination = valid_pairs[0][1]
    return source, detail, first_destination


def reconcile_source(cache: dict[str, Any], dev_periods: Sequence[Any],
                     data_root: Path) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any]]:
    behavior = data._load_behavior_module()
    audit_path = data.BEHAVIOR_DIR / "audit_behavior.py"
    core_path = data.BEHAVIOR_DIR / "evidence_core.py"
    event_state_path = (data.BEHAVIOR_DIR / "results" /
                        "nhl-behavior-evidence-event-state-v3-2026-10-27.json")
    require_hash(audit_path, EXPECTED_BEHAVIOR_SHA256)
    require_hash(core_path, EXPECTED_EVIDENCE_CORE_SHA256)
    require_hash(event_state_path, EXPECTED_EVENT_STATE_SHA256)
    pbp_manifest, shift_manifest = data._verified_manifests(data_root, behavior)
    cache_rows = {(row.game_id, row.period): row for row in dev_periods}
    game_ids = sorted({row.game_id for row in dev_periods})
    starts: dict[tuple[str, int], dict[str, Any]] = {}
    period_details: dict[tuple[str, int], dict[str, Any]] = {}
    totals = collections.Counter()
    destination_examples: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for index, game_id in enumerate(game_ids, 1):
        pbp, shifts = behavior._load_game_source(data_root, pbp_manifest, shift_manifest, game_id)
        if str(pbp.get("id")) != game_id:
            raise ValueError(f"verified PBP game ID mismatch: {game_id}")
        score_diffs = period_start_score_diffs(pbp, behavior._event_owner_side)
        for period_no in (1, 2, 3):
            validate_source_clock_order(pbp, period_no, behavior.parse_clock)
        records = data._extract_event_records(pbp, shifts, game_id, behavior)
        for period_no in (1, 2, 3):
            key = (game_id, period_no)
            expected = cache_rows.get(key)
            if expected is None:
                raise ValueError(f"cache is missing development period {key}")
            source, detail, first_dest = source_period_metrics(
                game_id, period_no, pbp, shifts, records, behavior)
            if transition_signature(source.transitions) != transition_signature(expected.transitions):
                raise ValueError(f"raw/source transition mismatch for {game_id} P{period_no}")
            for field in ("shift_5v5_seconds", "shift_non5v5_seconds",
                          "shift_ambiguous_seconds", "eligible_bundle_count",
                          "gap_excluded_counts", "excluded_bundle_counts"):
                if getattr(source, field) != getattr(expected, field):
                    raise ValueError(f"raw/cache {field} mismatch for {game_id} P{period_no}")
            start = {
                "score_diff": score_diffs[period_no],
                "score_aware_start_differs_from_default": score_diffs[period_no] != 0,
                "initial_context": context_dict(
                    data.Context("faceoff", True, score_diffs[period_no], 0)),
                "first_observed_transition": None,
                "first_destination_source_events": [],
            }
            filtered = [row for row in expected.transitions]
            if filtered:
                first = filtered[0]
                start["first_observed_transition"] = {
                    "gap_seconds": first.gap_seconds,
                    "context": context_dict(first.context),
                    "mark": [{"family": token.family, "owner": token.owner}
                             for token in first.mark],
                }
            if first_dest is not None:
                destination_second = first_dest.second
                start["first_destination_source_events"] = [
                    {"event_id": row.get("event_id"), "sort_order": row.get("sort_order"),
                     "type": row.get("type"), "side": row.get("side"),
                     "time_seconds_elapsed": int(row.get("time") or 0)}
                    for row in records
                    if row.get("period_type") == "REG"
                    and int(row.get("period") or 0) == period_no
                    and int(row.get("time") or -1) == destination_second
                    and row.get("type") not in data.BOUNDARY_TYPES
                ]
            starts[key] = start
            detail["game_id"] = game_id
            detail["period"] = period_no
            detail["period_start_score_diff"] = score_diffs[period_no]
            detail["score_aware_start_differs_from_default"] = score_diffs[period_no] != 0
            totals.update({field: detail[field] for field in (
                "regulation_seconds", "shift_5v5_seconds", "shift_non5v5_seconds",
                "shift_ambiguous_seconds", "entry_elapsed_seconds", "entry_5v5_seconds",
                "retained_gap_exposure_seconds", "terminal_elapsed_seconds",
                "terminal_5v5_seconds", "unpaired_5v5_seconds", "eligible_bundle_count",
                "transition_count")})
            detail["gap_excluded_counts"] = detail["gap_excluded_counts"]
            detail["excluded_bundle_counts"] = detail["excluded_bundle_counts"]
            detail["first_destination_source_events"] = start["first_destination_source_events"]
            period_details[key] = detail
            destination_examples[key] = start["first_destination_source_events"]
        if index % 100 == 0 or index == len(game_ids):
            print(f"source-reconciled {index}/{len(game_ids)} 2021 games", flush=True)
        del pbp, shifts, records
        if index % 100 == 0:
            gc.collect()
    if len(starts) != len(dev_periods):
        raise ValueError(f"reconciled {len(starts)} periods, expected {len(dev_periods)}")
    exposure = observed_exposure_summary(list(period_details.values()))
    if totals != collections.Counter(exposure):
        raise AssertionError("source exposure aggregate does not reconcile to period rows")
    gap_exclusions = collections.Counter()
    bundle_exclusions = collections.Counter()
    for period in dev_periods:
        gap_exclusions.update(period.gap_excluded_counts)
        bundle_exclusions.update(period.excluded_bundle_counts)
    summary = {
        "eligible_2021_games": len(game_ids),
        "periods_reconciled": len(starts),
        "raw_pbp_and_shift_bodies_hash_checked": True,
        "manifest_hashes": {
            "pbp": data.EXPECTED_PBP_MANIFEST_SHA256,
            "shifts": data.EXPECTED_SHIFT_MANIFEST_SHA256,
        },
        "raw_source_to_cache_transition_rows_exact": sum(len(row.transitions) for row in dev_periods),
        "raw_source_to_cache_transition_mismatches": 0,
        "score_aware_start_differs_from_0_0_periods": sum(
            bool(row["score_aware_start_differs_from_default"]) for row in starts.values()),
        "period_start_score_state_counts": dict(collections.Counter(
            score_state_from_diff(row["score_diff"]) for row in starts.values())),
        "exposure_seconds": exposure,
        "gap_exclusions": dict(sorted(gap_exclusions.items())),
        "bundle_exclusions": dict(sorted(bundle_exclusions.items())),
    }
    return starts, {"summary": summary, "period_details": period_details,
                    "source_examples": destination_examples}


def _gap_bin(seconds: int) -> str:
    for upper, label in FAMILY_GAP_BINS:
        if seconds <= upper:
            return label
    raise AssertionError("gap is outside the preregistered range")


def _add_group_loss(groups: dict[str, Any], candidate: str, group: str,
                    label: str, loss: float, seconds: int) -> None:
    slot = groups.setdefault(candidate, {}).setdefault(group, {}).setdefault(
        label, {"loss_nats": 0.0, "exposure_seconds": 0, "n": 0})
    slot["loss_nats"] += loss
    slot["exposure_seconds"] += seconds
    slot["n"] += 1


def _finish_group_losses(groups: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for candidate, candidate_groups in groups.items():
        result[candidate] = {}
        for group, labels in candidate_groups.items():
            result[candidate][group] = {}
            for label, values in labels.items():
                exposure = values["exposure_seconds"]
                result[candidate][group][label] = {
                    **values,
                    "nll_nats_per_5v5_minute": (
                        values["loss_nats"] / (exposure / 60) if exposure else None),
                }
    return result


def historical_state_replay(models: Mapping[str, RenewalModel],
                            dev_periods: Sequence[Any], max_bundle_size: int) -> dict[str, Any]:
    """Score gaps and marks on actual development contexts, without sampling states."""
    groups: dict[str, Any] = {}
    component: dict[str, Any] = {}
    survival: dict[str, Any] = {}
    context_rows = {"all": [], "first_scored_transition": [],
                    "later_scored_transitions": []}
    first_partitions = observed_gap_partitions(dev_periods, max_bundle_size)
    first_ids = {(row.game_id, row.period, id(row)) for row in first_partitions["first_scored_transition"]}
    totals_by_model: dict[str, dict[str, float]] = {}
    mark_by_model: dict[str, dict[str, Any]] = {}
    per_game_gap_loss: dict[str, dict[str, dict[str, list[float]]]] = {
        name: {} for name in models
    }
    survival_thresholds = SURVIVAL_THRESHOLDS

    for name, model in models.items():
        totals_by_model[name] = {
            "gap_nll_nats": 0.0,
            "mark_nll_nats": 0.0,
            "gap_exposure_seconds": 0,
            "eligible_transitions": 0,
            "first_gap_nll_nats": 0.0,
            "first_gap_exposure_seconds": 0,
            "first_gap_count": 0,
            "later_gap_nll_nats": 0.0,
            "later_gap_exposure_seconds": 0,
            "later_gap_count": 0,
        }
        mark_by_model[name] = {
            "bundle_size_nll_nats": 0.0,
            "first_token_family_nll_nats": 0.0,
            "later_token_family_nll_nats": 0.0,
            "owner_nll_nats": 0.0,
            "faceoff_first_token_nll_nats": 0.0,
            "faceoff_later_token_nll_nats": 0.0,
            "faceoff_first_tokens": 0,
            "faceoff_later_tokens": 0,
            "total_faceoff_tokens": 0,
            "next_bundle_first_family_nll_nats": 0.0,
            "tokens": 0,
            "transitions": 0,
        }
        survival[name] = {
            group: {str(threshold): {"predicted_sum": 0.0, "observed_sum": 0,
                                     "brier_sum": 0.0, "n": 0}
                    for threshold in survival_thresholds}
            for group in context_rows
        }

    for period in dev_periods:
        scored = [row for row in period.transitions if len(row.mark) <= max_bundle_size]
        for index, row in enumerate(scored):
            first = index == 0
            partition = "first_scored_transition" if first else "later_scored_transitions"
            context_rows["all"].append(row)
            context_rows[partition].append(row)
            for name, model in models.items():
                gap_loss = -model.gap_log_probability(row.context, row.gap_seconds)
                mark_loss = -model.mark_log_probability(row.context, row.mark)
                if not math.isfinite(gap_loss + mark_loss):
                    raise ValueError(f"nonfinite historical replay score: {row.game_id} P{row.period}")
                totals = totals_by_model[name]
                totals["gap_nll_nats"] += gap_loss
                totals["mark_nll_nats"] += mark_loss
                totals["gap_exposure_seconds"] += row.gap_seconds
                totals["eligible_transitions"] += 1
                if first:
                    totals["first_gap_nll_nats"] += gap_loss
                    totals["first_gap_exposure_seconds"] += row.gap_seconds
                    totals["first_gap_count"] += 1
                else:
                    totals["later_gap_nll_nats"] += gap_loss
                    totals["later_gap_exposure_seconds"] += row.gap_seconds
                    totals["later_gap_count"] += 1
                game_rows = per_game_gap_loss[name].setdefault(
                    row.game_id,
                    {"all": [0.0, 0.0], "first": [0.0, 0.0], "later": [0.0, 0.0]})
                for component_name in ("all", "first" if first else "later"):
                    game_rows[component_name][0] += gap_loss
                    game_rows[component_name][1] += row.gap_seconds

                key = model.selected_key(row.context)
                support = model.stats[key].n
                for group, label in (
                    ("transition_position", partition),
                    ("previous_family", row.context.previous_family),
                    ("possession_known", str(row.context.possession_known).lower()),
                    ("score_state", row.context.score_state),
                    ("clock_bucket", str(row.context.clock_bucket)),
                    ("gap_bin", _gap_bin(row.gap_seconds)),
                    ("selected_support", ("100-499" if support < 500 else
                                           "500-999" if support < 1000 else
                                           "1000-4999" if support < 5000 else "5000+")),
                    ("fallback_level", model.fallback_level(row.context)),
                ):
                    _add_group_loss(groups, name, group, label, gap_loss, row.gap_seconds)

                mark = mark_by_model[name]
                size_probability = model._size_probability(key, len(row.mark))
                size_loss = -math.log(size_probability)
                mark["bundle_size_nll_nats"] += size_loss
                prefix: list[str] = []
                first_family_loss = None
                for token_index, token in enumerate(row.mark):
                    prefix_key = tuple(prefix)
                    family_counts = model._family_counts(key, token_index, prefix_key)
                    family_support = sum(family_counts.values())
                    family_probability = model._probability(
                        family_counts[token.family], family_support, len(FAMILIES))
                    family_loss = -math.log(family_probability)
                    owner_counts = model._owner_counts(key, token_index, prefix_key, token.family)
                    owner_probability = model._probability(
                        owner_counts[token.owner], sum(owner_counts.values()),
                        len(OWNER_DOMAINS[token.family]))
                    owner_loss = -math.log(owner_probability)
                    if token_index == 0:
                        first_family_loss = family_loss
                        mark["first_token_family_nll_nats"] += family_loss
                        if token.family == "faceoff":
                            mark["faceoff_first_token_nll_nats"] += family_loss
                            mark["faceoff_first_tokens"] += 1
                    else:
                        mark["later_token_family_nll_nats"] += family_loss
                        if token.family == "faceoff":
                            mark["faceoff_later_token_nll_nats"] += family_loss
                            mark["faceoff_later_tokens"] += 1
                    if token.family == "faceoff":
                        mark["total_faceoff_tokens"] += 1
                    mark["owner_nll_nats"] += owner_loss
                    mark["tokens"] += 1
                    prefix.append(token.family)
                mark["transitions"] += 1
                if first_family_loss is None:
                    raise AssertionError("nonempty bundle has no first token")
                mark["next_bundle_first_family_nll_nats"] += first_family_loss

                for group in ("all", partition):
                    for threshold in survival_thresholds:
                        probability = gap_survival(model, row.context, threshold)
                        event = int(row.gap_seconds > threshold)
                        slot = survival[name][group][str(threshold)]
                        slot["predicted_sum"] += probability
                        slot["observed_sum"] += event
                        slot["brier_sum"] += (probability - event) ** 2
                        slot["n"] += 1

    replay: dict[str, Any] = {}
    for name, model in models.items():
        totals = totals_by_model[name]
        exposure_minutes = totals["gap_exposure_seconds"] / 60
        totals["gap_nll_nats_per_5v5_minute"] = totals["gap_nll_nats"] / exposure_minutes
        totals["mark_nll_nats_per_5v5_minute"] = totals["mark_nll_nats"] / exposure_minutes
        totals["first_gap_nll_nats_per_5v5_minute"] = (
            totals["first_gap_nll_nats"] / (totals["first_gap_exposure_seconds"] / 60))
        totals["later_gap_nll_nats_per_5v5_minute"] = (
            totals["later_gap_nll_nats"] / (totals["later_gap_exposure_seconds"] / 60))
        mark = mark_by_model[name]
        mark["mark_component_sum_nats"] = sum(mark[key] for key in (
            "bundle_size_nll_nats", "first_token_family_nll_nats",
            "later_token_family_nll_nats", "owner_nll_nats"))
        factorization_error = abs(mark["mark_component_sum_nats"] - totals["mark_nll_nats"])
        mark["mark_factorization_abs_error_nats"] = factorization_error
        if not math.isclose(mark["mark_component_sum_nats"], totals["mark_nll_nats"],
                            rel_tol=1e-10, abs_tol=1e-6):
            raise AssertionError(
                f"{name}: mark factorization differs from mark NLL by "
                f"{factorization_error:.12g} nats"
            )
        survival_out = {}
        for group, thresholds in survival[name].items():
            survival_out[group] = {}
            for threshold, values in thresholds.items():
                n = values["n"]
                survival_out[group][threshold] = {
                    "n": n,
                    "mean_predicted_p_gap_gt_threshold": values["predicted_sum"] / n,
                    "observed_rate_gap_gt_threshold": values["observed_sum"] / n,
                    "brier": values["brier_sum"] / n,
                }
        mix = {
            group: selected_context_mix_summary(model, rows)
            for group, rows in context_rows.items()
        }
        replay[name] = {
            "nll": totals,
            "gap_nll_by_group": _finish_group_losses(
                {name: groups.get(name, {})}).get(name, {}),
            "survival_calibration": survival_out,
            "selected_context_mixture": mix,
            "mark_decomposition": mark,
        }
    return {
        "mode": "historical-state replay on observed pre-gap contexts; no autonomous state transition",
        "gap_domain": "categorical integer-second PMF 1..1200; no continuous hazard",
        "development_gap_partitions": {
            name: {"n": len(rows), **counter_summary(collections.Counter(
                row.gap_seconds for row in rows))}
            for name, rows in context_rows.items()
        },
        "models": replay,
        "paired_game_clustered_gap_nll_intervals": paired_game_clustered_gap_nll_bootstrap(
            per_game_gap_loss, "A0", "A1"),
    }


def _trace_metrics(trace: Sequence[tuple[int, Sequence[Any]]]) -> dict[str, int]:
    family_counts = collections.Counter(token.family for _, mark in trace for token in mark)
    attempts = sum(family_counts[family] for family in
                   ("goal", "shot-on-goal", "missed-shot", "blocked-shot"))
    sog = family_counts["goal"] + family_counts["shot-on-goal"]
    return {
        "bundles": len(trace),
        "attempts": attempts,
        "sog": sog,
        "goals": family_counts["goal"],
        "faceoffs": family_counts["faceoff"],
        "stoppages": family_counts["stoppage"],
        **{family: family_counts[family] for family in FAMILIES},
    }


def _observed_targets(period: Any, max_bundle_size: int) -> tuple[dict[str, float], int, list[Any]] | None:
    rows = [row for row in period.transitions if len(row.mark) <= max_bundle_size]
    exposure = sum(row.gap_seconds for row in rows)
    if not exposure:
        return None
    counts = collections.Counter(token.family for row in rows for token in row.mark)
    raw = {"bundles": len(rows),
           "attempts": sum(counts[family] for family in
                           ("goal", "shot-on-goal", "missed-shot", "blocked-shot")),
           "sog": counts["goal"] + counts["shot-on-goal"],
           "goals": counts["goal"],
           "faceoffs": counts["faceoff"],
           "stoppages": counts["stoppage"],
           **{family: counts[family] for family in FAMILIES}}
    return ({metric: value * PERIOD_SECONDS / exposure for metric, value in raw.items()},
            exposure, rows)


def _state_key_string(key: Sequence[Any]) -> str:
    return json.dumps(list(key), separators=(",", ":"))


def run_arm(name: str, model: RenewalModel, dev_periods: Sequence[Any],
            starts: Mapping[tuple[str, int], dict[str, Any]],
            max_bundle_size: int, draws: int, *,
            alpha_gap: float | None = None,
            score_aware_initial: bool = False,
            progress: bool = True) -> dict[str, Any]:
    """Run one frozen or one-factor diagnostic arm, streaming trace detail."""
    period_rows: list[dict[str, Any]] = []
    emitted_gap_hist = collections.Counter()
    first_gap_hist = collections.Counter()
    later_gap_hist = collections.Counter()
    terminal_gap_hist = collections.Counter()
    attempt_gap_hist = collections.Counter()
    first_emitted_hist = collections.Counter()
    state_occupancy = collections.Counter()
    state_by_clock = collections.Counter()
    gap_context_support = collections.Counter()
    family_totals = collections.Counter()
    trace_count = 0
    terminal_count = 0
    no_event_trace_count = 0
    parity_checked = False
    n_scored = 0
    for period in dev_periods:
        target_result = _observed_targets(period, max_bundle_size)
        if target_result is None:
            continue
        targets, exposure, rows = target_result
        start_info = starts[(period.game_id, period.period)]
        initial = initial_context_for_period(start_info, score_aware_initial)
        samples: dict[str, list[float]] = {metric: [] for metric in targets}
        first_vs_later_samples: list[dict[str, Any]] = []
        seeds = []
        for replicate in range(draws):
            seed = common_random_seed(period.game_id, period.period, replicate)
            seeds.append(seed)
            details = sample_trace_diagnostic(
                model, seed, initial=initial, alpha_gap=alpha_gap, keep_steps=False)
            trace = details["trace"]
            if not parity_checked and alpha_gap in (None, model.alpha):
                if trace != sample_trace(model, seed, initial=initial):
                    raise AssertionError(f"{name}: diagnostic sampler differs from frozen trace")
                parity_checked = True
            counts = _trace_metrics(trace)
            for metric in targets:
                samples[metric].append(float(counts.get(metric, 0)))
            family_totals.update({family: counts.get(family, 0) for family in FAMILIES})
            terminal = details["terminal_gap"]
            if terminal:
                terminal_count += 1
                terminal_gap_hist[int(terminal["gap_seconds"])] += 1
            if not trace:
                no_event_trace_count += 1
            attempt_gap = details["first_attempt_gap"]
            if attempt_gap is not None:
                attempt_gap_hist[int(attempt_gap)] += 1
            if details["first_emitted_gap"] is not None:
                first_emitted_hist[int(details["first_emitted_gap"])] += 1
            for gap in details["emitted_gaps"]:
                emitted_gap_hist[int(gap)] += 1
            if details["emitted_gaps"]:
                first_gap_hist[int(details["emitted_gaps"][0])] += 1
                for gap in details["emitted_gaps"][1:]:
                    later_gap_hist[int(gap)] += 1
            state_occupancy.update(details["state_occupancy"])
            for state_key, count in details["state_occupancy"].items():
                state_by_clock[(state_key[3], state_key[4])] += count
                gap_context_support[("support", int(state_key[5]))] += count
            first_vs_later_samples.append({
                "first_attempt_gap": details["first_attempt_gap"],
                "first_emitted_gap": details["first_emitted_gap"],
                "subsequent_emitted_gap_count": len(details["subsequent_emitted_gaps"]),
            })
            trace_count += 1
        metric_rows = {
            metric: {
                "observed_target_per_20m_equivalent": target,
                "forecast_mean": sum(samples[metric]) / draws,
                "forecast_within_period_variance": statistics.pvariance(samples[metric]),
                "crps": crps(samples[metric], target),
            }
            for metric, target in targets.items()
        }
        period_rows.append({
            "game_id": period.game_id,
            "period": period.period,
            "start_score_diff": int(start_info["score_diff"]),
            "start_score_state": score_state_from_diff(int(start_info["score_diff"])),
            "observed_interarrival_exposure_seconds": exposure,
            "observed_destination_bundles": len(rows),
            "metrics": metric_rows,
            "draws": draws,
            "seeds": seeds,
        })
        n_scored += 1
        if progress and n_scored % 500 == 0:
            print(f"{name}: simulated {n_scored}/{len(dev_periods)} scored periods", flush=True)

    if n_scored == 0 or trace_count != n_scored * draws:
        raise ValueError(f"{name}: rollout count does not reconcile")
    metric_summary: dict[str, Any] = {}
    for metric in METRICS + FAMILIES:
        values = [row["metrics"][metric] for row in period_rows]
        if not values:
            continue
        targets = [row["observed_target_per_20m_equivalent"] for row in values]
        forecasts = [row["forecast_mean"] for row in values]
        metric_summary[metric] = {
            "periods": len(values),
            "mean_observed_20m_equivalent_target": sum(targets) / len(targets),
            "mean_forecast_count_per_1200s_trace": sum(forecasts) / len(forecasts),
            "mean_forecast_to_observed_ratio": (
                (sum(forecasts) / sum(targets)) if sum(targets) else None),
            "observed_between_period_variance": statistics.pvariance(targets),
            "mean_within_period_trace_variance": statistics.mean(
                row["forecast_within_period_variance"] for row in values),
            "mean_period_crps": statistics.mean(row["crps"] for row in values),
        }
    return {
        "name": name,
        "model": model.name,
        "gap_alpha": model.alpha if alpha_gap is None else alpha_gap,
        "gap_smoothing_changed_only": alpha_gap is not None and alpha_gap != model.alpha,
        "score_aware_start_only": score_aware_initial,
        "periods": n_scored,
        "draws_per_period": draws,
        "trace_count": trace_count,
        "sample_trace_parity_checked": parity_checked,
        "terminal_censored_trace_count": terminal_count,
        "terminal_censor_fraction": terminal_count / trace_count,
        "empty_trace_count": no_event_trace_count,
        "metrics": metric_summary,
        "gap_quantiles_emitted_complete_gaps": counter_summary(emitted_gap_hist),
        "gap_quantiles_first_emitted_gap": counter_summary(first_emitted_hist),
        "gap_quantiles_subsequent_emitted_gaps": counter_summary(later_gap_hist),
        "gap_quantiles_first_attempt_including_no_event_trace": counter_summary(attempt_gap_hist),
        "terminal_censored_gap_quantiles_not_counted_as_events": counter_summary(terminal_gap_hist),
        "emitted_gap_survival": {
            str(t): sum(count for gap, count in emitted_gap_hist.items() if gap > t)
            / max(1, sum(emitted_gap_hist.values())) for t in SURVIVAL_THRESHOLDS},
        "observed_family_tokens_across_all_scored_periods": None,
        "generated_family_tokens_total_across_traces": dict(sorted(family_totals.items())),
        "state_occupancy_by_family_possession_score_clock_and_fallback": {
            json.dumps(list(key), separators=(",", ":")): count
            for key, count in sorted(state_occupancy.items(), key=lambda item: repr(item[0]))
        },
        "state_occupancy_by_clock_bucket_and_fallback": {
            f"clock={key[0]}|fallback={key[1]}": count
            for key, count in sorted(state_by_clock.items())
        },
        "context_support_selection_frequency": {
            str(key): count for key, count in sorted(gap_context_support.items())
        },
        "period_rows": period_rows,
    }


def _game_cluster_scores(arm: dict[str, Any], metric: str) -> dict[str, list[float]]:
    result: dict[str, list[float]] = collections.defaultdict(list)
    for row in arm["period_rows"]:
        result[row["game_id"]].append(row["metrics"][metric]["crps"])
    return dict(result)


def _paired_arm_intervals(arms: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    comparisons = (
        ("A1_frozen", "A0_frozen", "A1-A0"),
        ("A1_gap_prior_off", "A1_frozen", "A1_prior_off-A1_frozen"),
        ("A1_period_score_start", "A1_frozen", "A1_score_start-A1_frozen"),
    )
    result: dict[str, Any] = {}
    for metric in ("bundles", "attempts", "sog", "goals", "faceoffs", "stoppages"):
        result[metric] = {}
        for candidate, reference, label in comparisons:
            result[metric][label] = paired_crps_bootstrap(
                _game_cluster_scores(arms[reference], metric),
                _game_cluster_scores(arms[candidate], metric),
                replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
    return result


def paired_game_clustered_gap_nll_bootstrap(
        per_game: Mapping[str, Mapping[str, Sequence[float]]],
        reference: str, candidate: str, *,
        components: Sequence[str] = ("all", "first", "later"),
        replicates: int = BOOTSTRAP_REPLICATES,
        seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Paired game-cluster bootstrap for gap NLL rate, candidate minus reference."""
    if replicates < 1:
        raise ValueError("gap-NLL bootstrap needs positive replicates")
    common_games = sorted(set(per_game[reference]) & set(per_game[candidate]))
    if not common_games:
        raise ValueError("gap-NLL bootstrap has no common games")
    result: dict[str, Any] = {}
    for component in components:
        rng = random.Random(seed)
        deltas: list[float] = []
        for _ in range(replicates):
            sampled_games = [common_games[rng.randrange(len(common_games))]
                             for _ in common_games]
            rates = {}
            for model_name in (reference, candidate):
                loss = sum(per_game[model_name][game][component][0]
                           for game in sampled_games)
                exposure = sum(per_game[model_name][game][component][1]
                               for game in sampled_games)
                if exposure <= 0:
                    raise ValueError("gap-NLL bootstrap sampled zero exposure")
                rates[model_name] = loss / (exposure / 60)
            deltas.append(rates[candidate] - rates[reference])
        deltas.sort()
        total_loss = {
            model_name: sum(per_game[model_name][game][component][0]
                            for game in common_games)
            for model_name in (reference, candidate)
        }
        total_exposure = {
            model_name: sum(per_game[model_name][game][component][1]
                            for game in common_games)
            for model_name in (reference, candidate)
        }
        point_delta = (
            total_loss[candidate] / (total_exposure[candidate] / 60)
            - total_loss[reference] / (total_exposure[reference] / 60))
        result[component] = {
            "candidate_minus_reference_nats_per_5v5_minute": point_delta,
            "bootstrap_mean_delta": sum(deltas) / len(deltas),
            "ci95_low": deltas[int(0.025 * (len(deltas) - 1))],
            "ci95_high": deltas[int(0.975 * (len(deltas) - 1))],
            "replicates": len(deltas),
            "seed": seed,
            "game_clusters": len(common_games),
            "direction": f"{candidate} minus {reference}; positive means worse NLL rate",
        }
    return result


def _gap_prior_diagnostic(model: RenewalModel,
                          rows: Sequence[Any]) -> dict[str, Any]:
    selected = collections.Counter(model.selected_key(row.context) for row in rows)
    support_rows = []
    for key, frequency in selected.items():
        n = model.stats[key].n
        mass = prior_mass(n, PERIOD_SECONDS, model.alpha)
        counts = model.stats[key].gaps
        empirical_mean = sum(gap * count for gap, count in counts.items()) / sum(counts.values())
        prior_mean = (PERIOD_SECONDS + 1) / 2
        support_rows.append({
            "selected_key": list(key),
            "selected_rows": frequency,
            "training_support": n,
            "prior_mass": mass,
            "empirical_mean_gap_seconds": empirical_mean,
            "uniform_prior_mean_gap_seconds": prior_mean,
            "smoothed_mean_gap_seconds": (1 - mass) * empirical_mean + mass * prior_mean,
            "prior_tail_probability": {
                str(t): (model.alpha * (PERIOD_SECONDS - t)
                         / (n + model.alpha * PERIOD_SECONDS))
                for t in (30, 43, 60, 120, 300, 600)},
            "selected_weight": frequency / len(rows),
        })
    return {
        "contexts": len(selected),
        "observed_context_rows": len(rows),
        "context_weighted_prior_mass": sum(row["selected_weight"] * row["prior_mass"]
                                            for row in support_rows),
        "context_weighted_prior_tail_probability": {
            str(t): sum(row["selected_weight"] * row["prior_tail_probability"][str(t)]
                        for row in support_rows)
            for t in (30, 43, 60, 120, 300, 600)},
        "selected_context_support_weighted_quantiles": {
            "p10": percentile([float(model.stats[key].n) for key in selected
                               for _ in range(selected[key])], .10),
            "p50": percentile([float(model.stats[key].n) for key in selected
                               for _ in range(selected[key])], .50),
            "p90": percentile([float(model.stats[key].n) for key in selected
                               for _ in range(selected[key])], .90),
        },
        "context_rows": sorted(support_rows, key=lambda row: (row["training_support"], row["selected_key"])),
    }


def build_traces(model: RenewalModel, arm: dict[str, Any],
                 starts: Mapping[tuple[str, int], dict[str, Any]],
                 dev_lookup: Mapping[tuple[str, int], Any],
                 max_bundle_size: int, top_n: int = 10) -> list[dict[str, Any]]:
    ranked = sorted(
        (row for row in arm["period_rows"] if row["metrics"]["bundles"]),
        key=lambda row: row["metrics"]["bundles"]["crps"], reverse=True)[:top_n]
    cases = []
    for rank, row in enumerate(ranked, 1):
        period = dev_lookup[(row["game_id"], row["period"])]
        observed = [transition for transition in period.transitions
                    if len(transition.mark) <= max_bundle_size]
        target = row["metrics"]["bundles"]["observed_target_per_20m_equivalent"]
        replicate = max(range(arm["draws_per_period"]),
                        key=lambda i: abs(
                            # Seeds are stable; regenerate this one draw to retain a full trace.
                            len(sample_trace(model, row["seeds"][i], initial=data.Context(
                                "faceoff", True, 0, 0))) - target))
        seed = row["seeds"][replicate]
        initial_info = starts[(row["game_id"], row["period"])]
        initial = data.Context("faceoff", True, 0, 0)
        details = sample_trace_diagnostic(model, seed, initial=initial, keep_steps=True)
        actual_first = initial_info.get("first_observed_transition")
        simulated_first = details["steps"][0] if details["steps"] else details["terminal_gap"]
        context_match = bool(actual_first and
                             actual_first["context"] == context_dict(initial))
        first_gap_match = bool(actual_first and details["steps"] and
                               actual_first["gap_seconds"] == details["steps"][0]["gap_seconds"])
        first_family_match = bool(actual_first and details["steps"] and actual_first["mark"] and
                                  actual_first["mark"][0]["family"] ==
                                  details["steps"][0]["mark"][0]["family"])
        cases.append({
            "rank": rank,
            "game_id": row["game_id"],
            "period": row["period"],
            "period_start_score_diff_from_prior_periods": initial_info["score_diff"],
            "observed_target_bundles_20m_equivalent": target,
            "a1_draw_bundle_count": len(details["trace"]),
            "draw_replicate": replicate,
            "seed": seed,
            "synthetic_start_context": context_dict(initial),
            "score_aware_start_context": initial_info["initial_context"],
            "first_observed_transition": actual_first,
            "first_observed_destination_source_events": initial_info[
                "first_destination_source_events"],
            "first_step_context_matches_synthetic_start": context_match,
            "first_gap_matches_observed_first_scored_gap": first_gap_match,
            "first_family_matches_observed_first_token_family": first_family_match,
            "first_step_classification": (
                "initial-context mismatch" if actual_first and not context_match else
                "stochastic first gap/mark mismatch" if not (first_gap_match and first_family_match) else
                "first scored gap/first family match"),
            "full_generated_steps": details["steps"],
            "terminal_censored_gap": details["terminal_gap"],
            "interpretation": (
                "Observed and generated paths are independent after initialization; the first "
                "mismatch locates where this realization differs, not a causal counterfactual."
            ),
        })
    return cases


def _score_frozen_inputs(args: argparse.Namespace) -> dict[str, str]:
    expected = {
        args.cache: EXPECTED_CACHE_SHA256,
        args.frozen_result: EXPECTED_RESULT_SHA256,
        args.prior_diagnostic: EXPECTED_PRIOR_DIAGNOSTIC_SHA256,
        HERE / "kernel.py": EXPECTED_KERNEL_SHA256,
        HERE / "data.py": EXPECTED_EXTRACTOR_SHA256,
        HERE / "run_experiment.py": EXPECTED_RUNNER_SHA256,
        HERE / "mechanism_diagnostics.py": EXPECTED_MECHANISM_SHA256,
        data.BEHAVIOR_DIR / "audit_behavior.py": EXPECTED_BEHAVIOR_SHA256,
        data.BEHAVIOR_DIR / "evidence_core.py": EXPECTED_EVIDENCE_CORE_SHA256,
        (data.BEHAVIOR_DIR / "results" /
         "nhl-behavior-evidence-event-state-v3-2026-10-27.json"): EXPECTED_EVENT_STATE_SHA256,
        PREREG_PATH: PREREG_SHA256,
    }
    return {str(path): require_hash(path, digest) for path, digest in expected.items()}


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.perf_counter()
    hashes = _score_frozen_inputs(args)
    payload = data.load_cache(args.cache)
    all_periods = data.period_records(payload)
    train_periods = [row for row in all_periods if row.season in (2019, 2020)]
    all_dev_periods = [row for row in all_periods if row.season == 2021]
    if len(train_periods) != 5763 or len(all_dev_periods) != 3876:
        raise ValueError("pinned training/development period population changed")
    training = [transition for period in train_periods for transition in period.transitions]
    if len(training) != 329667:
        raise ValueError(f"training transition count changed: {len(training)}")
    models = {name: RenewalModel(name) for name in ("A0", "A1")}
    for model in models.values():
        model.fit(training)
    max_bundle_size = models["A1"].max_bundle_size
    if models["A0"].max_bundle_size != max_bundle_size:
        raise AssertionError("frozen candidates do not share maximum bundle size")
    del payload, all_periods, train_periods, training
    gc.collect()

    dev_periods = [row for row in all_dev_periods if row.transitions]
    if args.limit_games:
        selected_games = sorted({row.game_id for row in dev_periods})[:args.limit_games]
        dev_periods = [row for row in dev_periods if row.game_id in selected_games]
    if not dev_periods:
        raise ValueError("diagnostic population is empty")
    if args.limit_games:
        selected_games = {row.game_id for row in dev_periods}
        source_periods = [row for row in all_dev_periods if row.game_id in selected_games]
    else:
        source_periods = all_dev_periods
    starts, source_result = reconcile_source(args.cache, source_periods, args.data_root)
    source_info = source_result["summary"]
    period_details = source_result["period_details"]
    exposure_report = observed_exposure_summary(list(period_details.values()))
    if exposure_report != source_info["exposure_seconds"]:
        raise AssertionError("period and aggregate exposure summaries differ")

    full_population = not args.limit_games
    if full_population and (len(dev_periods) != 3843
                            or source_info["eligible_2021_games"] != 1292
                            or source_info["periods_reconciled"] != 3876):
        raise ValueError("full development scored population changed")
    mode_a = historical_state_replay(models, dev_periods, max_bundle_size)
    frozen = json.loads(args.frozen_result.read_text(encoding="utf-8"))
    for name in ("A0", "A1"):
        actual = mode_a["models"][name]["nll"]["gap_nll_nats"]
        expected = frozen["development_nll"][name]["gap_nll_nats"]
        if full_population and abs(actual - expected) > 1e-5:
            raise AssertionError(f"{name} historical-state replay gap NLL changed: {actual} != {expected}")
    a1_rows = [row for period in dev_periods for row in period.transitions
               if len(row.mark) <= max_bundle_size]
    smoothing = _gap_prior_diagnostic(models["A1"], a1_rows)

    arms: dict[str, dict[str, Any]] = {}
    for name, model, alpha_gap, score_start in (
        ("A0_frozen", models["A0"], None, False),
        ("A1_frozen", models["A1"], None, False),
        ("A1_gap_prior_off", models["A1"], SMOOTHING_OFF_ALPHA, False),
        ("A1_period_score_start", models["A1"], None, True),
    ):
        arms[name] = run_arm(name, model, dev_periods, starts,
                             max_bundle_size, args.draws,
                             alpha_gap=alpha_gap,
                             score_aware_initial=score_start)
    bundle_metric_a1 = arms["A1_frozen"]["metrics"]["bundles"]
    if full_population and args.draws == DRAW_REPLICATES:
        expected_crps = frozen["simulation_comparison"]["metrics"]["bundle_count"]["candidates"]["A1"]["crps"]
        if abs(bundle_metric_a1["mean_period_crps"] - expected_crps) > 1e-9:
            raise AssertionError(
                f"frozen A1 bundle CRPS mismatch: {bundle_metric_a1['mean_period_crps']} != {expected_crps}")
        expected_a0 = frozen["simulation_comparison"]["metrics"]["bundle_count"]["candidates"]["A0"]["crps"]
        if abs(arms["A0_frozen"]["metrics"]["bundles"]["mean_period_crps"] - expected_a0) > 1e-9:
            raise AssertionError("frozen A0 bundle CRPS did not reproduce")

    period_start_strata: dict[str, Any] = {}
    for state in ("tied", "home-leading", "away-leading"):
        period_start_strata[state] = {}
        for arm_name in ("A1_frozen", "A1_period_score_start"):
            rows = [row for row in arms[arm_name]["period_rows"]
                    if row["start_score_state"] == state]
            period_start_strata[state][arm_name] = {
                "periods": len(rows),
                "bundle_crps": statistics.mean(row["metrics"]["bundles"]["crps"] for row in rows)
                if rows else None,
                "mean_forecast_bundles": statistics.mean(row["metrics"]["bundles"]["forecast_mean"]
                                                          for row in rows) if rows else None,
                "mean_target_bundles": statistics.mean(row["metrics"]["bundles"]["observed_target_per_20m_equivalent"]
                                                        for row in rows) if rows else None,
            }

    intervals = _paired_arm_intervals(arms) if full_population and args.draws == DRAW_REPLICATES else {}
    dev_lookup = {(row.game_id, row.period): row for row in dev_periods}
    traces = build_traces(models["A1"], arms["A1_frozen"], starts,
                          dev_lookup, max_bundle_size)
    expected_coverage = 3843 if full_population else len(dev_periods)
    if len(traces) != min(10, expected_coverage):
        raise AssertionError("high-error trace count does not reconcile")

    result = {
        "schema": "nhl-a1-arrival-gap-diagnosis-v1",
        "scope": "diagnostic only; A0/A1 frozen; no candidate selection, tuning, gate change, or production forecast change",
        "base_audit_commit": "3c3afb9dc15155de6d006517b2ea833038ddb260",
        "preregistration": {
            "path": str(PREREG_PATH.relative_to(ROOT)),
            "sha256": PREREG_SHA256,
            "commit": PREREG_COMMIT,
            "committed_before_new_diagnostic_metrics": True,
        },
        "input_sha256": hashes,
        "population": {
            "eligible_training_periods": 5763,
            "training_transition_gaps": 329667,
            "eligible_2021_regulation_periods": len(all_dev_periods),
            "2021_periods_with_transition_exposure": len(dev_periods),
            "scored_2021_games": len({row.game_id for row in dev_periods}),
            "scored_2021_periods": len(dev_periods),
            "eligible_2021_transition_gaps_scored": sum(
                len([row for row in period.transitions if len(row.mark) <= max_bundle_size])
                for period in dev_periods),
            "max_training_bundle_size": max_bundle_size,
            "draws_per_period": args.draws,
            "partial_run": not full_population,
        },
        "definitions": {
            "bundle": "supported eligible event tokens at one whole-second timestamp",
            "observed_gap": "positive interval between adjacent eligible bundles only when the full interval is unambiguous 5v5",
            "observed_gap_exposure": "sum of retained transition gaps; excludes period-entry, terminal, and invalid-state intervals",
            "rollout_horizon": PERIOD_SECONDS,
            "rollout_censoring": "sampled arrival at or beyond 1,200 seconds is not emitted; reported as terminal censor proposal",
            "arrival_model": "categorical PMF over integer gaps 1..1200; no continuous hazard",
            "first_gap": "first retained transition gap in historical replay; first sampled gap in autonomous trace. Not necessarily a period-entry gap.",
            "count_target": "retained destination bundle count * 1,200 / retained interarrival exposure; a 20-minute-equivalent rate target, not literal observed period count",
        },
        "source_clock_exposure_reconciliation": source_info,
        "historical_state_replay": mode_a,
        "smoothing_mechanism": smoothing,
        "autonomous_rollout": {
            "arms": arms,
            "paired_game_clustered_crps_intervals": intervals,
            "score_at_period_start_strata": period_start_strata,
            "start_score_rule": "count regulation goals only in completed earlier periods; no event from the target period and no opening-faceoff winner used",
            "gap_smoothing_ablation": "A1 gap alpha=0 on the same selected key only; mark alpha, fit rows, key hierarchy, starts, state update, seeds, and horizon unchanged",
            "gap_smoothing_ablation_warning": "diagnostic only; held-out unseen gap values have zero probability and the arm is not an admissible candidate",
        },
        "first_divergence_examples": traces,
        "runtime_seconds": time.perf_counter() - started_at,
        "decision": "DIAGNOSTIC_ONLY_NO_CANDIDATE_SELECTION",
    }
    return result


def render_report(result: dict[str, Any]) -> str:
    mode_a = result["historical_state_replay"]
    replay_models = mode_a["models"]
    arms = result["autonomous_rollout"]["arms"]
    exposure = result["source_clock_exposure_reconciliation"]["exposure_seconds"]

    def quantiles(row: Mapping[str, Any], prefix: str = "") -> str:
        keys = ("p50_seconds", "p90_seconds", "p95_seconds", "p99_seconds")
        return " / ".join(str(round(row[f"{prefix}{key}"])) for key in keys)

    def interval_cell(row: Mapping[str, Any]) -> str:
        return (f"{row['mean_delta_b_minus_a']:+.3f} "
                f"[{row['ci95_low']:+.3f}, {row['ci95_high']:+.3f}]")

    lines = [
        "# NHL A1 Arrival-Gap Diagnosis",
        "",
        "**Date:** 2026-10-27",
        "**Branch:** `research/nhl-a1-arrival-gap-diagnosis-2026-10-27`",
        f"**Diagnostic preregistration:** `{result['preregistration']['commit']}` (SHA-256 `{result['preregistration']['sha256']}`)",
        f"**Base:** `{result['base_audit_commit']}`",
        f"**Scope:** {result['scope']}.",
        "",
        "## Finding",
        "",
        "**The largest measured cause is A1's smoothed categorical interarrival-gap distribution.** On actual 2021 pre-gap states, A1's predicted gap tail is already much too long: the context-mixture p90/p95/p99 are 375/788/1,118 seconds versus observed 33/43/66. The gap-NLL rate is +0.37777 nats per 5v5 minute worse than A0 (game-clustered 95% CI +0.36931 to +0.38667). Later observed transitions account for the excess; the first scored transition is slightly better under A1. Autonomous feedback is therefore not needed to produce the main conditional timing failure.",
        "",
        "A1 puts a uniform pseudocount of 0.5 on every integer gap from 1 to 1,200 seconds. Its observed-context-weighted prior mass is 14.53%, versus 0.18% for pooled A0, and the smoothed A1 mean gap rises to 100.31 seconds from the context-weighted empirical 15.22 seconds. Removing only that gap pseudocount restores the rollout mean from 18.24 to 82.31 bundles per full-period trace and lowers bundle CRPS from 56.31 to 8.38. That arm gives zero probability to 951 held-out gaps, however, so its full historical-state gap NLL is infinite; it diagnoses the mechanism and is not a usable fix.",
        "",
        "Score-aware period initialization does not explain the shortage: it reduces the A1 mean to 17.03 and worsens bundle CRPS by 1.479 (95% CI +1.403 to +1.555). Shot-on-target conversion is also not the primary shortage: A1's SOG/attempt ratio is 0.553 versus 0.552 observed, while its goal/SOG ratio is somewhat high (0.101 versus 0.084). The low absolute goal count is chiefly downstream of too few generated bundles and shot opportunities; event composition and faceoff marking remain separate defects.",
        "",
        "## Population, clock, and censoring",
        "",
        f"- Re-extracted source population: {result['source_clock_exposure_reconciliation']['eligible_2021_games']:,} games and {result['source_clock_exposure_reconciliation']['periods_reconciled']:,} regulation periods; {result['source_clock_exposure_reconciliation']['raw_source_to_cache_transition_rows_exact']:,} cached transitions matched raw PBP/shift reconstruction, with zero mismatches.",
        f"- Scored rollouts: {result['population']['scored_2021_games']:,} games / {result['population']['scored_2021_periods']:,} periods; {result['population']['eligible_2021_regulation_periods'] - result['population']['scored_2021_periods']:,} periods had no qualifying retained transition exposure. Training used {result['population']['training_transition_gaps']:,} 2019–20 transitions; evaluation scored {result['population']['eligible_2021_transition_gaps_scored']:,} 2021 gaps.",
        f"- Regulation clock: {exposure['regulation_seconds']:,} seconds. Shift-derived 5v5 / non-5v5 / ambiguous exposure: {exposure['shift_5v5_seconds']:,} / {exposure['shift_non5v5_seconds']:,} / {exposure['shift_ambiguous_seconds']:,} seconds.",
        f"- Retained event-to-event exposure: {exposure['retained_gap_exposure_seconds']:,} seconds; period-entry 5v5 edge {exposure['entry_5v5_seconds']:,}, terminal edge {exposure['terminal_5v5_seconds']:,}, and other unpaired 5v5 exposure {exposure['unpaired_5v5_seconds']:,} seconds.",
        f"- Source exclusions across 2021: `{json.dumps(result['source_clock_exposure_reconciliation']['gap_exclusions'], sort_keys=True)}`. The clock is validated as nondecreasing whole seconds within each source period, in `[0, 1200]`.",
        "",
        "The observed target remains the frozen 20-minute-equivalent rate: retained destination bundles × 1,200 / retained eligible gap seconds. It is not a literal full-period event count. Rollouts use a 1,200-second horizon. Each trace records its next sampled gap at or beyond the horizon as one terminal right-censored proposal; it is not emitted as an event. There is no minutes/seconds mismatch, cache/source mismatch, or hidden addition of period-edge exposure to the denominator.",
        "",
        "## Mode A: historical-state replay",
        "",
        "Each observed next gap is scored using its actual pre-gap context; generated states do not feed this replay. The first scored gap per period is not the interval from period start to its first event.",
        "",
        "| Model | Gap NLL (nats) | NLL / 5v5 min | First scored / min | Later / min |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("A0", "A1"):
        nll = replay_models[name]["nll"]
        lines.append(
            f"| {name} | {nll['gap_nll_nats']:.2f} | "
            f"{nll['gap_nll_nats_per_5v5_minute']:.5f} | "
            f"{nll['first_gap_nll_nats_per_5v5_minute']:.5f} | "
            f"{nll['later_gap_nll_nats_per_5v5_minute']:.5f} |"
        )
    all_ci = mode_a["paired_game_clustered_gap_nll_intervals"]["all"]
    first_ci = mode_a["paired_game_clustered_gap_nll_intervals"]["first"]
    later_ci = mode_a["paired_game_clustered_gap_nll_intervals"]["later"]
    lines += [
        f"| A1 − A0 difference | +21,776.81 | {all_ci['candidate_minus_reference_nats_per_5v5_minute']:+.5f} [{all_ci['ci95_low']:+.5f}, {all_ci['ci95_high']:+.5f}] | {first_ci['candidate_minus_reference_nats_per_5v5_minute']:+.5f} [{first_ci['ci95_low']:+.5f}, {first_ci['ci95_high']:+.5f}] | {later_ci['candidate_minus_reference_nats_per_5v5_minute']:+.5f} [{later_ci['ci95_low']:+.5f}, {later_ci['ci95_high']:+.5f}] |",
        "",
        "The first-transition gap-rate difference favors A1 (95% CI entirely below zero); the later-gap difference favors A0 (95% CI entirely above zero). Thus a poor synthetic period start is not required to create the A1 loss. Later gaps contribute +22,119.86 nats of the net +21,776.81 excess, partly offset by A1's −343.05 first-gap advantage.",
        "",
        "### Gap quantiles and survival calibration",
        "",
        "| Population / model | N | Observed p50 / p90 / p95 / p99 (s) | Predicted p50 / p90 / p95 / p99 (s) |",
        "|---|---:|---|---|",
    ]
    for model_name in ("A0", "A1"):
        for group in ("all", "first_scored_transition", "later_scored_transitions"):
            row = replay_models[model_name]["selected_context_mixture"][group]
            observed = quantiles(row["observed_gap_quantiles"])
            predicted = quantiles(row["predicted_gap_quantiles_mixture_over_observed_contexts"])
            lines.append(f"| {model_name} {group} | {row['rows']:,} | {observed} | {predicted} |")
    lines += [
        "",
        "| Threshold t | Observed P(gap > t) | A0 predicted | A1 predicted |",
        "|---:|---:|---:|---:|",
    ]
    for threshold in (10, 20, 30, 43, 60, 120, 300):
        threshold_key = str(threshold)
        observed = replay_models["A1"]["survival_calibration"]["all"][threshold_key]["observed_rate_gap_gt_threshold"]
        a0 = replay_models["A0"]["survival_calibration"]["all"][threshold_key]["mean_predicted_p_gap_gt_threshold"]
        a1 = replay_models["A1"]["survival_calibration"]["all"][threshold_key]["mean_predicted_p_gap_gt_threshold"]
        lines.append(f"| {threshold} s | {observed:.4f} | {a0:.4f} | {a1:.4f} |")
    lines += [
        "",
        "A1's 95th percentile is 788 seconds versus 43 observed. On real contexts, A1 predicts P(gap > 60 s)=0.1511 versus 0.0146 observed; at 120 s it predicts 0.1310 versus 0.0003 observed. These are categorical PMF survival probabilities, not continuous-time hazards.",
        "",
        "### Where the conditional gap NLL excess occurs",
        "",
        "| Observed gap bin | Transitions | A1 − A0 gap NLL (nats) |",
        "|---|---:|---:|",
    ]
    a0_bins = replay_models["A0"]["gap_nll_by_group"]["gap_bin"]
    a1_bins = replay_models["A1"]["gap_nll_by_group"]["gap_bin"]
    for label in ("1-5s", "6-10s", "11-20s", "21-30s", "31-60s", "61-120s", "121-300s"):
        if label not in a1_bins:
            continue
        delta = a1_bins[label]["loss_nats"] - a0_bins[label]["loss_nats"]
        lines.append(f"| {label} | {a1_bins[label]['n']:,} | {delta:+.2f} |")
    lines += [
        "",
        "A1's proper-score penalty is not dominated by a few observed extreme waits: its excess is concentrated in the common 6–60 second bins (+23,963.46 nats combined). The uniform prior's long tail is instead exposed most clearly by the conditional survival calibration and autonomous count collapse. State/clock/score breakdowns, complete survival Brier tables, and all support levels are preserved in the JSON.",
        "",
        "### Smoothing support",
        "",
        f"A1 selected {result['smoothing_mechanism']['contexts']} contexts; their training-support median was {result['smoothing_mechanism']['selected_context_support_weighted_quantiles']['p50']:,}. The context-weighted uniform prior mass was {result['smoothing_mechanism']['context_weighted_prior_mass']:.3%}; A0's pooled prior mass was {replay_models['A0']['selected_context_mixture']['all']['uniform_prior_mass_weighted_mean']:.3%}. A1's weighted empirical mean gap was {replay_models['A1']['selected_context_mixture']['all']['mean_empirical_gap_seconds_weighted_by_observed_context']:.2f} seconds, versus {replay_models['A1']['selected_context_mixture']['all']['mean_smoothed_gap_seconds_weighted_by_observed_context']:.2f} after smoothing.",
        "",
        f"A1 assigned zero raw training support to {replay_models['A1']['selected_context_mixture']['all']['heldout_gaps_absent_from_unsmoothed_selected_training_support']:,}/{replay_models['A1']['selected_context_mixture']['all']['rows']:,} observed 2021 gaps ({1 - replay_models['A1']['selected_context_mixture']['all']['heldout_gap_support_rate']:.3%}). Removing the prior repairs counts but creates infinite held-out gap NLL; it is not an acceptable calibrated model.",
        "",
        "## Mode B: autonomous rollouts",
        "",
        "A0 and A1 are distinct frozen fitted models. Within the three A1 arms, fit rows, hierarchy, state update, mark sampler, horizon, and common seeds are fixed; only the named gap smoothing or initial score changes.",
        "",
        "| Arm | Generated bundles / 1,200 s | Observed target | Bundle CRPS | Emitted gap p50 / p90 / p95 / p99 (s) | First attempted gap p50 / p90 / p95 / p99 (s) |",
        "|---|---:|---:|---:|---|---|",
    ]
    for arm_name in ("A0_frozen", "A1_frozen", "A1_gap_prior_off", "A1_period_score_start"):
        arm = arms[arm_name]
        metric = arm["metrics"]["bundles"]
        lines.append(
            f"| {arm_name} | {metric['mean_forecast_count_per_1200s_trace']:.2f} | "
            f"{metric['mean_observed_20m_equivalent_target']:.2f} | {metric['mean_period_crps']:.5f} | "
            f"{quantiles(arm['gap_quantiles_emitted_complete_gaps'])} | "
            f"{quantiles(arm['gap_quantiles_first_attempt_including_no_event_trace'])} |"
        )
    lines += [
        "",
        "The smoothing-off arm's bundle CRPS change versus A1 is −47.939 (95% paired game-cluster CI −48.564 to −47.315). Score-aware initialization changes CRPS by +1.479 (+1.403 to +1.555), a supported deterioration. A1 versus A0 is +47.697 (+47.209 to +48.179), also worse. Intervals use 2,000 paired game-cluster bootstrap replicates with seed 20261027; full intervals for all metrics and contrasts are in the JSON.",
        "",
        "### Bundle-count variance",
        "",
        "| Arm | Observed between-period variance | Mean generated within-period variance |",
        "|---|---:|---:|",
    ]
    for arm_name in ("A0_frozen", "A1_frozen", "A1_gap_prior_off", "A1_period_score_start"):
        metric = arms[arm_name]["metrics"]["bundles"]
        lines.append(f"| {arm_name} | {metric['observed_between_period_variance']:.2f} | {metric['mean_within_period_trace_variance']:.2f} |")
    lines += [
        "",
        "A1's within-period bundle variance is below the observed between-period variance (111.75 vs 179.41). The alpha-zero arm is more underdispersed (69.70), despite matching the mean. Count recovery alone is insufficient.",
        "",
        "### Event-family counts per 20-minute equivalent",
        "",
        "| Family | Observed target | A0 | A1 | A1 gap prior off |",
        "|---|---:|---:|---:|---:|",
    ]
    family_names = ("faceoff", "hit", "giveaway", "takeaway", "shot-on-goal",
                    "missed-shot", "blocked-shot", "goal", "stoppage", "other")
    for family in family_names:
        observed = arms["A0_frozen"]["metrics"][family]["mean_observed_20m_equivalent_target"]
        values = [arms[name]["metrics"][family]["mean_forecast_count_per_1200s_trace"]
                  for name in ("A0_frozen", "A1_frozen", "A1_gap_prior_off")]
        lines.append(f"| {family} | {observed:.2f} | {values[0]:.2f} | {values[1]:.2f} | {values[2]:.2f} |")
    observed_sog_ratio = (arms["A0_frozen"]["metrics"]["sog"]["mean_observed_20m_equivalent_target"]
                          / arms["A0_frozen"]["metrics"]["attempts"]["mean_observed_20m_equivalent_target"])
    observed_goal_ratio = (arms["A0_frozen"]["metrics"]["goals"]["mean_observed_20m_equivalent_target"]
                           / arms["A0_frozen"]["metrics"]["sog"]["mean_observed_20m_equivalent_target"])
    lines += [
        "",
        f"Aggregate SOG/attempt and goal/SOG ratios are {observed_sog_ratio:.4f} and {observed_goal_ratio:.4f} observed. A0 produces {arms['A0_frozen']['metrics']['sog']['mean_forecast_count_per_1200s_trace'] / arms['A0_frozen']['metrics']['attempts']['mean_forecast_count_per_1200s_trace']:.4f} and {arms['A0_frozen']['metrics']['goals']['mean_forecast_count_per_1200s_trace'] / arms['A0_frozen']['metrics']['sog']['mean_forecast_count_per_1200s_trace']:.4f}; A1 produces {arms['A1_frozen']['metrics']['sog']['mean_forecast_count_per_1200s_trace'] / arms['A1_frozen']['metrics']['attempts']['mean_forecast_count_per_1200s_trace']:.4f} and {arms['A1_frozen']['metrics']['goals']['mean_forecast_count_per_1200s_trace'] / arms['A1_frozen']['metrics']['sog']['mean_forecast_count_per_1200s_trace']:.4f}. These aggregate ratios show that attempt-to-SOG conversion is close, while goal conversion is somewhat high in A1; they do not replace per-shot calibration. The large absolute SOG and goal shortfall tracks the event-volume deficit.",
        "",
        "### Faceoff mark likelihood is a separate problem",
        "",
        f"All {replay_models['A1']['mark_decomposition']['total_faceoff_tokens']:,} observed faceoff tokens occur after the first token within their event bundle; there are zero first-token faceoffs. A1's within-bundle faceoff NLL is {replay_models['A1']['mark_decomposition']['faceoff_later_token_nll_nats']:.2f} nats ({replay_models['A1']['mark_decomposition']['faceoff_later_token_nll_nats'] / replay_models['A1']['mark_decomposition']['total_faceoff_tokens']:.4f} per faceoff token), versus A0's {replay_models['A0']['mark_decomposition']['faceoff_later_token_nll_nats']:.2f} ({replay_models['A0']['mark_decomposition']['faceoff_later_token_nll_nats'] / replay_models['A0']['mark_decomposition']['total_faceoff_tokens']:.4f}). A1's next-bundle first-family NLL improves by {replay_models['A0']['mark_decomposition']['next_bundle_first_family_nll_nats'] - replay_models['A1']['mark_decomposition']['next_bundle_first_family_nll_nats']:.2f} nats, but that score contains no faceoffs. In rollout, faceoffs are 1.20 for A1 and only 5.54 with gap smoothing off, versus 17.00 observed. This is an independent mark/within-bundle sequencing gap, not evidence against the arrival diagnosis.",
        "",
        "## First divergence: source-linked examples",
        "",
        "The ten highest A1 count-error traces, their full generated paths, seeds, sampled gap probabilities/uniforms, context transitions, terminal censor proposals, and first observed source event IDs are in the JSON. Two long-wait examples:",
        "",
    ]
    for rank in (7, 8):
        trace = next(row for row in result["first_divergence_examples"] if row["rank"] == rank)
        step = trace["full_generated_steps"][0]
        source_events = trace["first_observed_destination_source_events"]
        source = ", ".join(
            f"event {event['event_id']} sortOrder {event['sort_order']} at {event['time_seconds_elapsed']}s ({event['type']})"
            for event in source_events)
        bundle_word = "bundle" if trace["a1_draw_bundle_count"] == 1 else "bundles"
        lines.append(
            f"- `{trace['game_id']}` period {trace['period']}: observed first eligible bundle after "
            f"{trace['first_observed_transition']['gap_seconds']}s ({source}); A1 sampled a "
            f"{step['gap_seconds']}s first wait with probability {step['gap_probability']:.8f} "
            f"at uniform {step['gap_uniform']:.8f}, then emitted {trace['a1_draw_bundle_count']} {bundle_word} "
            f"against a {trace['observed_target_bundles_20m_equivalent']:.1f} target. Selected "
            f"context `{json.dumps(step['selected_context_key'])}` had support {step['context_support']:,}."
        )
    lines += [
        "",
        "These are realization traces, not paired counterfactuals. The first mismatch may be stochastic or an initialization-context mismatch; after it, trajectories diverge. The JSON records that distinction and does not attribute downstream differences causally to the first sampled event.",
        "",
        "## Ranked next experiments and decision",
        "",
        "1. **Supported gap-tail calibration.** Keep the integer-gap model and positive probability for unseen development gaps, but test one preregistered sparse-context pooling/shrinkage mechanism on a new development split. Measure Mode A tail calibration and NLL, autonomous count CRPS, mean, and variance. Falsify if tail calibration improves only by worsening held-out NLL or if the rollout remains underdispersed.",
        "2. **Within-bundle faceoff process.** Separately diagnose the observed ordered bundle structure and conditional faceoff token probability. Evaluate faceoff incidence and likelihood without changing gap arrival probabilities. Falsify if faceoff counts do not improve on identical sequences or if other bundle-family calibration degrades.",
        "3. **Initialization/context support.** Do not prioritize score-only initialization: its paired interval shows worse CRPS, and tied starts are unchanged. A later test can address the mismatch between the synthetic opening context and the first retained transition, without using the target-period future faceoff winner.",
        "",
        "No correction is adopted and no candidate is selected. The A1 gap-prior-off arm is not adoptable because its full historical-state NLL is infinite and its trace variance is low. Keep the frozen A0/A1 controls and current gate unchanged. The 2021 population is exposed development data, not an independent adoption test.",
        "",
        "## Data boundary and reproduction",
        "",
        "No new source was needed to identify this timing failure: verified GameCenter PBP clocks/events and shift-derived 5v5 exposure were sufficient. PBP still does not observe every pass, continuous possession, or spatial puck/player state; those remain limits for future tactical and causal behavior, not blockers to this diagnosis. Source manifests and bodies were hash-checked read-only. No production forecast, gate, A0/A1 source, or frozen Phase 2A artifact changed.",
        "",
        "- Preregistration: [protocol](NHL-A1-ARRIVAL-GAP-DIAGNOSIS-PREREG-2026-10-27.md).",
        "- Diagnostic implementation and tests: [script](../../research/nhl/autonomous-5v5/arrival_gap_diagnostics.py), [tests](../../research/nhl/autonomous-5v5/tests/test_arrival_gap_diagnostics.py).",
        "- Complete machine-readable decomposition: [result JSON](../../research/nhl/autonomous-5v5/results/nhl-a1-arrival-gap-diagnosis-2026-10-27.json).",
        "- Frozen controls: [A1 report](NHL-AUTONOMOUS-5V5-ARRIVAL-REPORT-2026-10-27.md), [mechanism audit](NHL-AUTONOMOUS-MECHANISM-DATA-GAP-AUDIT-2026-10-27.md).",
        "",
        f"Full raw-source and rollout run: {result['runtime_seconds']:.2f}s; Mode A NLL interval postprocess: {result.get('nll_uncertainty_postprocess_seconds', 0.0):.2f}s; combined reported runtime: {result.get('total_runtime_seconds_including_postprocess', result['runtime_seconds']):.2f}s. Result JSON SHA-256: `{result.get('result_sha256', 'written after report render')}`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=data.DEFAULT_CACHE)
    parser.add_argument("--data-root", type=Path, default=data.DEFAULT_DATA_ROOT)
    parser.add_argument("--frozen-result", type=Path, default=mechanism.RESULT_PATH)
    parser.add_argument("--prior-diagnostic", type=Path, default=mechanism.DEFAULT_OUT)
    parser.add_argument("--output", type=Path, default=EXPECTED_OUTPUT)
    parser.add_argument("--report", type=Path, default=EXPECTED_REPORT)
    parser.add_argument("--limit-games", type=int, default=None,
                        help="run a partial smoke sample; output must not be used as the report")
    parser.add_argument("--draws", type=int, default=DRAW_REPLICATES)
    args = parser.parse_args()
    if args.draws < 1:
        parser.error("--draws must be positive")
    if args.limit_games is not None and args.limit_games < 1:
        parser.error("--limit-games must be positive")
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result_body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(result_body, encoding="utf-8")
    result_sha = sha256_file(args.output)
    result["result_sha256"] = result_sha
    args.report.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "output_sha256": result_sha,
        "report": str(args.report), "partial": result["population"]["partial_run"],
        "periods": result["population"]["scored_2021_periods"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
