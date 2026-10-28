#!/usr/bin/env python3
"""Compare frozen NHL A0/A1 timing with pooled-shrinkage and censored estimators."""

from __future__ import annotations

import argparse
import bisect
import collections
import gzip
import hashlib
import json
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import data
import kernel
from kernel import (BOOTSTRAP_REPLICATES, FAMILIES, PERIOD_SECONDS, Context,
                    RenewalModel, Transition, common_random_seed, crps,
                    sample_trace, trace_counts)
import run_experiment


PREREG_COMMIT = "f5d682007133be69127a34077f972c5c1c816d7b"
PREREG_INPUT_PIN_COMMIT = "aa6fa660c9cdf92eb962c97f9815e5a364288cb5"
PREREG_CENSOR_CONVENTION_COMMIT = "7dbe2bb7555627f275a0a23cf3ba95304045b04a"
PREREG_BOUNDARY_TIE_COMMIT = "03aea31b9abdfc210b510f45a0cdd40798f21295"
PARENT_COMMIT = "38e181418500be26df61a8b12fe42c78750d9292"
PARENT_RESULT_SHA256 = "23edf72783ae694062051ec5adac53509eff22e3772bc28b5ebfd1e2ab6280a9"
SEQUENCE_CACHE_SHA256 = "9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2"
KERNEL_SHA256 = "ea54dc59dd6df7a4372b506cc6a9105eda023abdf2de0017eece805722788773"
DATA_SHA256 = "dd19648ffbb3c5b3a74b98490e62f71dfd6c990a2d4093c42b22c583ce7280bb"
BOOTSTRAP_SEED = 20261028
POOL_PRIOR_MASS = 600.0
GAP_ALPHA = 0.5
DURATION_BINS = ((1, 5), (6, 10), (11, 20), (21, 30), (31, 60),
                  (61, 120), (121, 300), (301, 600), (601, 900), (901, 1200))
THRESHOLDS = (10, 20, 30, 43, 60, 120, 300, 600)
RISK_CACHE_SCHEMA = "nhl-a1-gap-estimator-risk-spells-v2"

DEFAULT_DATA_ROOT = data.DEFAULT_DATA_ROOT
DEFAULT_CACHE = data.DEFAULT_CACHE
DEFAULT_RISK_CACHE = Path(
    "/root/lp-data/nhl-a1-gap-estimator-comparison-2026-10-28/risk-spells-v2.json.gz"
)
DEFAULT_HISTORICAL = HERE / "results/nhl-a1-gap-estimator-comparison-historical-2026-10-28.json"
DEFAULT_ROLLOUT = HERE / "results/nhl-a1-gap-estimator-comparison-rollout-2026-10-28.json"
DEFAULT_REPORT = ROOT / "docs/research/NHL-A1-GAP-ESTIMATOR-COMPARISON-2026-10-28.md"


@dataclass(frozen=True)
class RiskSpell:
    game_id: str
    season: int
    period: int
    context: Context
    duration_seconds: int
    event_observed: bool
    censor_reason: str | None
    origin_second: int
    endpoint_second: int
    origin_index: int

    @property
    def complete_risk_seconds(self) -> int:
        # A right-censor at integer age d leaves the event at d unresolved;
        # d-1 full seconds are known event-free. Event observations contribute d.
        return self.duration_seconds if self.event_observed else max(0, self.duration_seconds - 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "season": self.season,
            "period": self.period,
            "context": {
                "previous_family": self.context.previous_family,
                "possession_known": self.context.possession_known,
                "score_diff": self.context.score_diff,
                "clock_bucket": self.context.clock_bucket,
            },
            "duration_seconds": self.duration_seconds,
            "event_observed": self.event_observed,
            "censor_reason": self.censor_reason,
            "origin_second": self.origin_second,
            "endpoint_second": self.endpoint_second,
            "origin_index": self.origin_index,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "RiskSpell":
        context = row["context"]
        return cls(
            str(row["game_id"]), int(row["season"]), int(row["period"]),
            Context(str(context["previous_family"]), bool(context["possession_known"]),
                    int(context["score_diff"]), int(context["clock_bucket"])),
            int(row["duration_seconds"]), bool(row["event_observed"]),
            None if row["censor_reason"] is None else str(row["censor_reason"]),
            int(row["origin_second"]), int(row["endpoint_second"]), int(row["origin_index"]),
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hashes(actual: Mapping[str, str], expected: Mapping[str, str]) -> None:
    if dict(actual) != dict(expected):
        raise ValueError(f"frozen input hash mismatch: {dict(actual)}")


def _assert_transition_reconciliation(event_signatures: Sequence[tuple[Any, ...]],
                                     boundary_tie_signatures: Sequence[tuple[Any, ...]],
                                     cached_signatures: Sequence[tuple[Any, ...]],
                                     source_label: str) -> None:
    if collections.Counter(event_signatures + boundary_tie_signatures) != collections.Counter(
            cached_signatures):
        raise ValueError(
            f"{source_label}: complete event spells plus boundary ties do not cover cached transitions"
        )


def verify_frozen_inputs(cache_path: Path, data_root: Path) -> tuple[dict[str, Any], list[Any]]:
    parent_result = ROOT / "research/nhl/autonomous-5v5/results/nhl-a1-arrival-gap-diagnosis-2026-10-27.json"
    kernel_path = HERE / "kernel.py"
    data_path = HERE / "data.py"
    actual = {
        "parent_result_sha256": sha256_file(parent_result),
        "sequence_cache_sha256": sha256_file(cache_path),
        "kernel_sha256": sha256_file(kernel_path),
        "data_sha256": sha256_file(data_path),
    }
    expected = {
        "parent_result_sha256": PARENT_RESULT_SHA256,
        "sequence_cache_sha256": SEQUENCE_CACHE_SHA256,
        "kernel_sha256": KERNEL_SHA256,
        "data_sha256": DATA_SHA256,
    }
    _verify_hashes(actual, expected)
    payload = data.load_cache(cache_path)
    if not payload.get("periods"):
        raise ValueError("frozen sequence cache has no periods")
    if len(payload["periods"]) != 9639:
        raise ValueError(f"frozen period count changed: {len(payload['periods'])}")
    return payload, data.period_records(payload)


def _transition_signature(rows: Sequence[Transition]) -> list[tuple[Any, ...]]:
    return [(row.gap_seconds, row.context, row.mark) for row in rows]


def _source_transitions(bundles: Sequence[Any], states: Sequence[str],
                        game_id: str, period: int) -> list[Transition]:
    transitions: list[Transition] = []
    for previous, current in zip(bundles, bundles[1:]):
        if not previous.eligible or not current.eligible:
            continue
        between = states[previous.second:current.second]
        if any(state == "ambiguous" for state in between):
            continue
        if any(state != "5v5" for state in between):
            continue
        if not current.mark:
            continue
        gap = current.second - previous.second
        if gap <= 0:
            raise ValueError(f"{game_id} P{period}: nonpositive source event gap")
        transitions.append(Transition(game_id, period, gap, previous.context_after, current.mark))
    return transitions


def _spell_endpoint(start: int, next_event: int | None, boundary: int,
                    boundary_causes: Sequence[str]) -> tuple[bool, int, str | None, bool]:
    """Resolve whole-second event/censor ties conservatively as censor-first."""
    if start < 0 or boundary <= start:
        raise ValueError(f"invalid risk-spell interval start={start}, boundary={boundary}")
    if next_event is not None and next_event < boundary:
        duration = next_event - start
        if duration < 1:
            raise ValueError(f"nonpositive event duration: {duration}")
        return True, duration, None, False
    tied = next_event == boundary
    causes = tuple(sorted(set(boundary_causes)))
    if not causes:
        raise ValueError("risk-spell boundary has no source cause")
    if tied:
        return False, boundary - start, "same_second_eligible_event_" + "_and_".join(causes), True
    return False, boundary - start, "_and_".join(causes), False


def _origin_exposure_reason(start: int, states: Sequence[str]) -> str | None:
    if start < 0 or start > len(states):
        raise ValueError(f"risk-spell origin is outside the state vector: {start}")
    if start == len(states):
        return "origin_at_period_end"
    if states[start] != "5v5":
        return "origin_not_verified_5v5"
    return None


def _period_spells(game_id: str, season: int, period: int, pbp: dict[str, Any],
                   shifts: dict[str, Any], records: list[dict[str, Any]],
                   behavior: Any, cached_period: Any) -> tuple[list[RiskSpell], dict[str, Any], list[dict[str, Any]]]:
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home_id: "home", away_id: "away"}
    roster = {
        str(row.get("playerId") or ""): (str(row.get("teamId") or ""),
                                            str(row.get("positionCode") or "?"))
        for row in pbp.get("rosterSpots") or [] if row.get("playerId") is not None
    }
    states, _, _ = data._state_by_second(shifts, game_id, period, team_sides, roster)
    event_ambiguous = {
        int(row["time"]) for row in records
        if row.get("period_type") == "REG" and int(row.get("period") or 0) == period
        and row.get("type") not in data.BOUNDARY_TYPES
        and not (row.get("event_state_attribution") or {}).get("eligible_for_conditional_fit")
    }
    bundles, _ = data._make_bundles(
        {"event_records": records}, pbp, game_id, season, period, event_ambiguous)
    source_transitions = _source_transitions(bundles, states, game_id, period)
    if _transition_signature(source_transitions) != _transition_signature(cached_period.transitions):
        raise ValueError(f"{game_id} P{period}: reconstructed event transitions differ from cache")

    eligible = [bundle for bundle in bundles if bundle.eligible]
    eligible_seconds = [bundle.second for bundle in eligible]
    ineligible_seconds = sorted({bundle.second for bundle in bundles if not bundle.eligible})
    bad_state_seconds = [second for second, state in enumerate(states) if state != "5v5"]
    spells: list[RiskSpell] = []
    censor_counts: collections.Counter[str] = collections.Counter()
    zero_exposure: collections.Counter[str] = collections.Counter()
    event_signatures: list[tuple[Any, ...]] = []
    boundary_tie_signatures: list[tuple[Any, ...]] = []

    for index, origin in enumerate(eligible):
        start = origin.second
        next_event_second = eligible_seconds[index + 1] if index + 1 < len(eligible_seconds) else None
        ineligible_index = bisect.bisect_right(ineligible_seconds, start)
        next_ineligible = (ineligible_seconds[ineligible_index]
                           if ineligible_index < len(ineligible_seconds) else PERIOD_SECONDS)
        bad_index = bisect.bisect_right(bad_state_seconds, start)
        next_bad_state = (bad_state_seconds[bad_index]
                          if bad_index < len(bad_state_seconds) else PERIOD_SECONDS)
        origin_reason = _origin_exposure_reason(start, states)
        if origin_reason is not None:
            zero_exposure[origin_reason] += 1
            continue

        boundary = min(next_ineligible, next_bad_state, PERIOD_SECONDS)
        # The frozen source transition definition excludes state at the destination
        # second, so a qualifying event exactly on a shift boundary is an event.
        boundary_causes = []
        if next_ineligible == boundary and boundary < PERIOD_SECONDS:
            boundary_causes.append("ineligible_bundle")
        if next_bad_state == boundary and boundary < PERIOD_SECONDS:
            boundary_causes.append(
                "ambiguous_state" if states[boundary] == "ambiguous" else "5v5_exit")
        if boundary == PERIOD_SECONDS:
            boundary_causes.append("period_end")
        is_event, duration, reason, tied_eligible_event = _spell_endpoint(
            start, next_event_second, boundary, boundary_causes)
        if is_event:
            target = eligible[index + 1]
            spell = RiskSpell(game_id, season, period, origin.context_after, duration,
                              True, None, start, next_event_second, index)
            spells.append(spell)
            event_signatures.append((duration, origin.context_after, target.mark))
            continue
        assert reason is not None
        if duration <= 0:
            zero_exposure[reason] += 1
            continue
        spells.append(RiskSpell(game_id, season, period, origin.context_after, duration,
                                False, reason, start, boundary, index))
        censor_counts[reason] += 1
        if tied_eligible_event:
            boundary_tie_signatures.append((duration, origin.context_after,
                                            eligible[index + 1].mark))

    cached_signatures = _transition_signature(cached_period.transitions)
    _assert_transition_reconciliation(event_signatures, boundary_tie_signatures,
                                      cached_signatures, f"{game_id} P{period}")

    entry_rows = _segment_entry_diagnostics(game_id, season, period, states, bundles)
    summary = {
        "game_id": game_id,
        "season": season,
        "period": period,
        "eligible_origins": len(eligible),
        "event_observed_spells": sum(spell.event_observed for spell in spells),
        "right_censored_spells": sum(not spell.event_observed for spell in spells),
        "boundary_tied_eligible_transition_spells": len(boundary_tie_signatures),
        "frozen_complete_gap_transitions": len(cached_period.transitions),
        "event_and_boundary_tie_reconciliation": (
            sum(spell.event_observed for spell in spells) + len(boundary_tie_signatures)
        ),
        "censor_reasons": dict(sorted(censor_counts.items())),
        "zero_exposure_origins": dict(sorted(zero_exposure.items())),
        "risk_spells": len(spells),
        "verified_5v5_seconds": states.count("5v5"),
        "ambiguous_seconds": states.count("ambiguous"),
        "non5v5_seconds": states.count("non5v5"),
    }
    return spells, summary, entry_rows


def _segment_entry_diagnostics(game_id: str, season: int, period: int,
                               states: Sequence[str], bundles: Sequence[Any]) -> list[dict[str, Any]]:
    eligible = [bundle for bundle in bundles if bundle.eligible]
    ineligible = [bundle for bundle in bundles if not bundle.eligible]
    entries: list[dict[str, Any]] = []
    second = 0
    while second < PERIOD_SECONDS:
        if states[second] != "5v5":
            second += 1
            continue
        start = second
        while second < PERIOD_SECONDS and states[second] == "5v5":
            second += 1
        end = second
        first_event = next((b for b in eligible if start <= b.second < end), None)
        first_ineligible = next((b for b in ineligible if start < b.second <= end), None)
        if first_event is not None and (first_ineligible is None or first_event.second < first_ineligible.second):
            elapsed = first_event.second - start
            outcome = "event_at_entry" if elapsed == 0 else "first_event"
            endpoint = first_event.second
        elif first_ineligible is not None:
            elapsed = max(0, first_ineligible.second - start)
            outcome = "censored_ineligible_bundle"
            endpoint = first_ineligible.second
        else:
            elapsed = max(0, end - start)
            outcome = "censored_5v5_exit_or_period_end"
            endpoint = end
        entries.append({
            "game_id": game_id, "season": season, "period": period,
            "entry_kind": "period_entry" if start == 0 else "5v5_reentry",
            "start_second": start, "endpoint_second": endpoint,
            "elapsed_seconds": elapsed, "outcome": outcome,
        })
    return entries


def reconstruct_risk_spells(cache_periods: Sequence[Any], data_root: Path,
                            *, game_limit: int | None = None) -> tuple[list[RiskSpell], dict[str, Any], list[dict[str, Any]]]:
    """Reconstruct event/censor spells from verified local PBP and shift sources."""
    behavior = data._load_behavior_module()
    pbp_manifest, shift_manifest = data._verified_manifests(data_root, behavior)
    by_game: dict[str, list[Any]] = collections.defaultdict(list)
    for period in cache_periods:
        by_game[period.game_id].append(period)
    game_ids = sorted(by_game)
    if game_limit is not None:
        if game_limit < 1:
            raise ValueError("game limit must be positive")
        game_ids = game_ids[:game_limit]
    all_spells: list[RiskSpell] = []
    period_summaries: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    games_by_season: collections.Counter[int] = collections.Counter()
    started = time.perf_counter()
    if game_limit is None:
        print(f"source reconstruction: 0/{len(game_ids)} games", file=sys.stderr, flush=True)
    for game_index, game_id in enumerate(game_ids, start=1):
        game_periods = {row.period: row for row in by_game[game_id]}
        season = int(game_periods[1].season)
        pbp, shifts = behavior._load_game_source(data_root, pbp_manifest, shift_manifest, game_id)
        if str(pbp.get("id")) != game_id:
            raise ValueError(f"{game_id}: verified PBP body game ID mismatch")
        records = data._extract_event_records(pbp, shifts, game_id, behavior)
        games_by_season[season] += 1
        for period in (1, 2, 3):
            if period not in game_periods:
                raise ValueError(f"{game_id}: cache missing regulation period {period}")
            spells, summary, entries = _period_spells(
                game_id, season, period, pbp, shifts, records, behavior, game_periods[period])
            all_spells.extend(spells)
            period_summaries.append(summary)
            entry_rows.extend(entries)
        if game_limit is None and (game_index % 250 == 0 or game_index == len(game_ids)):
            print(f"source reconstruction: {game_index}/{len(game_ids)} games; "
                  f"{time.perf_counter() - started:.1f}s elapsed",
                  file=sys.stderr, flush=True)
    if game_limit is None and dict(sorted(games_by_season.items())) != {2019: 1064, 2020: 857, 2021: 1292}:
        raise ValueError(f"source games did not reconcile to pinned population: {dict(games_by_season)}")
    counts = collections.Counter()
    exposure = collections.Counter()
    event_gaps_by_season = collections.Counter()
    censors_by_season = collections.Counter()
    for spell in all_spells:
        counts[(spell.season, "event" if spell.event_observed else spell.censor_reason)] += 1
        exposure[(spell.season, "known_risk_seconds")] += spell.complete_risk_seconds
        exposure[(spell.season, "elapsed_to_endpoint_seconds")] += spell.duration_seconds
        if spell.event_observed:
            event_gaps_by_season[spell.season] += 1
        else:
            censors_by_season[spell.season] += 1
    boundary_ties_by_season = collections.Counter()
    zero_exposure_by_season = collections.Counter()
    frozen_transitions_by_season = collections.Counter()
    for row in period_summaries:
        season = int(row["season"])
        boundary_ties_by_season[season] += int(row["boundary_tied_eligible_transition_spells"])
        zero_exposure_by_season[season] += sum(row["zero_exposure_origins"].values())
    selected_games = set(game_ids)
    for period in cache_periods:
        if period.game_id in selected_games:
            frozen_transitions_by_season[int(period.season)] += len(period.transitions)
    for season, transitions in frozen_transitions_by_season.items():
        reconciled = event_gaps_by_season[season] + boundary_ties_by_season[season]
        if reconciled != transitions:
            raise ValueError(
                f"{season}: event spells {event_gaps_by_season[season]} + boundary ties "
                f"{boundary_ties_by_season[season]} != frozen transitions {transitions}"
            )
    summary = {
        "schema": RISK_CACHE_SCHEMA,
        "source_roots_outside_repository": str(data_root),
        "games_processed_by_start_season": {str(k): int(v) for k, v in sorted(games_by_season.items())},
        "periods_processed": len(period_summaries),
        "event_observed_spells_by_season": {str(k): int(v) for k, v in sorted(event_gaps_by_season.items())},
        "right_censored_spells_by_season": {str(k): int(v) for k, v in sorted(censors_by_season.items())},
        "same_second_boundary_tied_transition_spells_by_season": {
            str(k): int(v) for k, v in sorted(boundary_ties_by_season.items())},
        "frozen_complete_gap_transitions_by_season": {
            str(k): int(v) for k, v in sorted(frozen_transitions_by_season.items())},
        "zero_exposure_origin_counts_by_season": {
            str(k): int(v) for k, v in sorted(zero_exposure_by_season.items())},
        "spells_by_season_and_status": {
            f"{season}:{status}": int(value) for (season, status), value in sorted(counts.items())
        },
        "exposure_by_season": {
            f"{season}:{kind}": int(value) for (season, kind), value in sorted(exposure.items())
        },
        "censor_reason_totals": dict(sorted(collections.Counter(
            spell.censor_reason for spell in all_spells if not spell.event_observed).items())),
        "zero_length_spell_policy": "zero-risk source ties are counted by period summary and excluded from duration likelihoods",
        "period_summaries": period_summaries,
    }
    return all_spells, summary, entry_rows


class TimingCandidate:
    """Gap model wrapper that delegates all event-mark behavior to frozen A1."""

    def __init__(self, name: str, mark_model: RenewalModel, kind: str,
                 *, prior_mass: float = POOL_PRIOR_MASS,
                 hazards: Mapping[tuple[object, ...], float] | None = None,
                 weibull: Mapping[tuple[object, ...], tuple[float, float]] | None = None,
                 pool_pmf: Sequence[float] | None = None):
        self.name = name
        self.mark_model = mark_model
        self.kind = kind
        self.alpha = mark_model.alpha
        self.max_bundle_size = mark_model.max_bundle_size
        self.prior_mass = float(prior_mass)
        self.hazards = dict(hazards or {})
        self.weibull = dict(weibull or {})
        self.pool_pmf = tuple(pool_pmf or ())
        self._cdf_cache: dict[tuple[object, ...], tuple[float, ...]] = {}

    @property
    def stats(self):
        return self.mark_model.stats

    def selected_key(self, context: Context):
        return self.mark_model.selected_key(context)

    def _weibull_parameters(self, key: tuple[object, ...]) -> tuple[float, float]:
        if key not in self.weibull:
            raise ValueError(f"{self.name} has no fitted Weibull parameters for selected key {key}")
        return self.weibull[key]

    @staticmethod
    def weibull_survival(age: int, scale: float, shape: float) -> float:
        if age <= 0:
            return 1.0
        exponent = (age / scale) ** shape
        return 0.0 if exponent > 745 else math.exp(-exponent)

    def gap_probability(self, context: Context, seconds: int) -> float:
        if seconds < 1:
            return 0.0
        key = self.selected_key(context)
        if self.kind == "B1_pooled_shrinkage":
            counts = self.mark_model.stats[key].gaps
            n = sum(counts.values())
            pool = self.pool_pmf[seconds - 1] if seconds <= PERIOD_SECONDS else 0.0
            if seconds > PERIOD_SECONDS:
                return 0.0
            return (counts[seconds] + self.prior_mass * pool) / (n + self.prior_mass)
        if self.kind == "B2_exponential":
            hazard = self.hazards[key]
            return hazard * ((1.0 - hazard) ** (seconds - 1))
        if self.kind == "B2_weibull":
            scale, shape = self._weibull_parameters(key)
            return max(0.0, self.weibull_survival(seconds - 1, scale, shape)
                       - self.weibull_survival(seconds, scale, shape))
        raise ValueError(f"unknown timing candidate kind {self.kind}")

    def gap_log_probability(self, context: Context, seconds: int) -> float:
        probability = self.gap_probability(context, seconds)
        return math.log(probability) if probability > 0 else -math.inf

    def survival_left(self, context: Context, censor_age: int) -> float:
        """P(T >= censor age), honoring discrete second-resolution right censoring."""
        if censor_age <= 1:
            return 1.0
        key = self.selected_key(context)
        if self.kind == "B2_exponential":
            return (1.0 - self.hazards[key]) ** (censor_age - 1)
        if self.kind == "B2_weibull":
            scale, shape = self._weibull_parameters(key)
            return self.weibull_survival(censor_age - 1, scale, shape)
        return sum(self.gap_probability(context, gap)
                   for gap in range(censor_age, PERIOD_SECONDS + 1))

    def sample_gap(self, context: Context, rng: random.Random) -> int:
        key = self.selected_key(context)
        u = rng.random()
        if self.kind == "B2_exponential":
            hazard = self.hazards[key]
            if hazard >= 1.0:
                return 1
            return max(1, int(math.ceil(math.log1p(-u) / math.log1p(-hazard))))
        if self.kind == "B2_weibull":
            scale, shape = self._weibull_parameters(key)
            if u >= 1.0:
                return 10**9
            return max(1, int(math.ceil(scale * (-math.log1p(-u)) ** (1.0 / shape))))
        cdf = self._cdf_cache.get(key)
        if cdf is None:
            acc = 0.0
            values = []
            for gap in range(1, PERIOD_SECONDS + 1):
                acc += self.gap_probability(context, gap)
                values.append(acc)
            if acc <= 0:
                raise ValueError(f"{self.name} has empty gap support for {key}")
            self._cdf_cache[key] = cdf = tuple(value / acc for value in values)
        return bisect.bisect_left(cdf, u) + 1

    def mark_log_probability(self, context: Context, mark: Sequence[Any]) -> float:
        return self.mark_model.mark_log_probability(context, mark)

    def sample_mark(self, context: Context, rng: random.Random):
        return self.mark_model.sample_mark(context, rng)


def _fit_timing_models(training: Sequence[Transition], training_spells: Sequence[RiskSpell]):
    a0 = RenewalModel("A0")
    a1 = RenewalModel("A1")
    a0.fit(training)
    a1.fit(training)
    pooled_counts = a0.stats[("pooled",)].gaps
    pooled_n = sum(pooled_counts.values())
    pool_pmf = tuple((pooled_counts[gap] + GAP_ALPHA) /
                     (pooled_n + GAP_ALPHA * PERIOD_SECONDS)
                     for gap in range(1, PERIOD_SECONDS + 1))
    b1 = TimingCandidate("B1", a1, "B1_pooled_shrinkage",
                         pool_pmf=pool_pmf)

    grouped: dict[tuple[object, ...], list[RiskSpell]] = collections.defaultdict(list)
    for spell in training_spells:
        grouped[a1.selected_key(spell.context)].append(spell)
    expected_event_transitions = len(training)
    observed_risk_events = sum(spell.event_observed for spell in training_spells)
    training_boundary_ties = sum(
        spell.censor_reason is not None
        and spell.censor_reason.startswith("same_second_eligible_event_")
        for spell in training_spells
    )
    if observed_risk_events + training_boundary_ties != expected_event_transitions:
        raise ValueError(
            "training event-spell count plus boundary ties "
            f"{observed_risk_events}+{training_boundary_ties} != frozen transition count {expected_event_transitions}"
        )

    hazards: dict[tuple[object, ...], float] = {}
    weibull: dict[tuple[object, ...], tuple[float, float]] = {}
    optimizer_diagnostics: dict[str, dict[str, Any]] = {}
    for key, spells in sorted(grouped.items(), key=lambda item: repr(item[0])):
        events = sum(spell.event_observed for spell in spells)
        exposure = sum(spell.complete_risk_seconds for spell in spells)
        if events <= 0 or exposure < events:
            raise ValueError(f"invalid B2 training support for {key}: events={events}, risk={exposure}")
        hazard = events / exposure
        if not 0.0 < hazard < 1.0:
            raise ValueError(f"B2-E hazard out of open unit interval for {key}: {hazard}")
        hazards[key] = hazard
        parameters, fit_info = fit_discrete_weibull(spells)
        weibull[key] = parameters
        optimizer_diagnostics[repr(key)] = {
            "events": events,
            "censored": len(spells) - events,
            "risk_seconds": exposure,
            **fit_info,
        }
    b2e = TimingCandidate("B2-E", a1, "B2_exponential", hazards=hazards)
    b2w = TimingCandidate("B2-W", a1, "B2_weibull", weibull=weibull)
    return {"A0": a0, "A1": a1, "B1": b1, "B2-E": b2e, "B2-W": b2w}, {
        "b2_selected_contexts": len(grouped),
        "b2_training_event_spells": observed_risk_events,
        "b2_training_censored_spells": len(training_spells) - observed_risk_events,
        "b2_training_same_second_boundary_ties": training_boundary_ties,
        "b2_weibull_optimizer_by_context": optimizer_diagnostics,
    }


def _weibull_loglik(hist_event: Mapping[int, int], hist_censor: Mapping[int, int],
                    log_scale: float, log_shape: float) -> float:
    scale = math.exp(log_scale)
    shape = math.exp(log_shape)
    total = 0.0
    for duration, count in hist_event.items():
        if duration < 1 or count <= 0:
            continue
        a = 0.0 if duration == 1 else ((duration - 1) / scale) ** shape
        b = (duration / scale) ** shape
        delta = b - a
        if delta <= 0:
            return -math.inf
        # log(S(d-1) - S(d)), stable for small one-second hazards.
        log_mass = -a + math.log(-math.expm1(-delta))
        total += count * log_mass
    for duration, count in hist_censor.items():
        if duration < 1 or count <= 0:
            continue
        age = duration - 1
        if age:
            total -= count * ((age / scale) ** shape)
    return total


def _clamp_weibull_point(point: tuple[float, float]) -> tuple[float, float]:
    return (min(math.log(1_000_000.0), max(math.log(0.25), point[0])),
            min(math.log(10.0), max(math.log(0.1), point[1])))


def _nelder_mead_maximize(function, start: tuple[float, float], *,
                          max_iterations: int = 240, tolerance: float = 1e-7
                          ) -> tuple[tuple[float, float], float, bool, int]:
    p0 = _clamp_weibull_point(start)
    simplex = [p0,
               _clamp_weibull_point((p0[0] + 0.18, p0[1])),
               _clamp_weibull_point((p0[0], p0[1] + 0.12))]
    values = [function(*point) for point in simplex]
    for iteration in range(1, max_iterations + 1):
        order = sorted(range(3), key=lambda index: values[index], reverse=True)
        simplex = [simplex[index] for index in order]
        values = [values[index] for index in order]
        coord_spread = max(max(abs(simplex[0][axis] - simplex[i][axis]) for axis in (0, 1))
                           for i in (1, 2))
        score_spread = max(abs(values[0] - values[i]) for i in (1, 2))
        if coord_spread < tolerance and score_spread < tolerance:
            return simplex[0], values[0], True, iteration

        best, second, worst = simplex
        centroid = ((best[0] + second[0]) / 2.0, (best[1] + second[1]) / 2.0)
        reflected = _clamp_weibull_point((centroid[0] + (centroid[0] - worst[0]),
                                           centroid[1] + (centroid[1] - worst[1])))
        reflected_value = function(*reflected)
        if values[0] >= reflected_value > values[1]:
            simplex[2], values[2] = reflected, reflected_value
            continue
        if reflected_value > values[0]:
            expanded = _clamp_weibull_point((centroid[0] + 2.0 * (reflected[0] - centroid[0]),
                                              centroid[1] + 2.0 * (reflected[1] - centroid[1])))
            expanded_value = function(*expanded)
            if expanded_value > reflected_value:
                simplex[2], values[2] = expanded, expanded_value
            else:
                simplex[2], values[2] = reflected, reflected_value
            continue

        if reflected_value > values[2]:
            contracted = _clamp_weibull_point((centroid[0] + 0.5 * (reflected[0] - centroid[0]),
                                                centroid[1] + 0.5 * (reflected[1] - centroid[1])))
        else:
            contracted = _clamp_weibull_point((centroid[0] + 0.5 * (worst[0] - centroid[0]),
                                                centroid[1] + 0.5 * (worst[1] - centroid[1])))
        contracted_value = function(*contracted)
        if contracted_value > max(reflected_value, values[2]):
            simplex[2], values[2] = contracted, contracted_value
            continue
        simplex = [best,
                   _clamp_weibull_point((best[0] + 0.5 * (second[0] - best[0]),
                                         best[1] + 0.5 * (second[1] - best[1]))),
                   _clamp_weibull_point((best[0] + 0.5 * (worst[0] - best[0]),
                                         best[1] + 0.5 * (worst[1] - best[1])))]
        values = [function(*point) for point in simplex]
    best_index = max(range(3), key=lambda index: values[index])
    return simplex[best_index], values[best_index], False, max_iterations


def fit_discrete_weibull(spells: Sequence[RiskSpell]
                         ) -> tuple[tuple[float, float], dict[str, Any]]:
    event_hist: collections.Counter[int] = collections.Counter()
    censor_hist: collections.Counter[int] = collections.Counter()
    for spell in spells:
        if spell.event_observed:
            event_hist[spell.duration_seconds] += 1
        else:
            censor_hist[spell.duration_seconds] += 1
    events = sum(event_hist.values())
    if events < 1:
        raise ValueError("discrete Weibull requires at least one observed event")
    sorted_events = sorted(event_hist.elements())
    median = sorted_events[(len(sorted_events) - 1) // 2]
    best: tuple[tuple[float, float], float, bool, int] | None = None
    starts = []
    for shape in (0.5, 1.0, 2.0):
        scale = max(0.25, median / (math.log(2.0) ** (1.0 / shape)))
        starts.append((math.log(scale), math.log(shape)))
    for start in starts:
        result = _nelder_mead_maximize(
            lambda log_scale, log_shape: _weibull_loglik(
                event_hist, censor_hist, log_scale, log_shape), start)
        if best is None or result[1] > best[1]:
            best = result
    assert best is not None
    (log_scale, log_shape), loglik, converged, iterations = best
    scale, shape = math.exp(log_scale), math.exp(log_shape)
    return (scale, shape), {
        "scale_seconds": scale,
        "shape": shape,
        "training_log_likelihood": loglik,
        "converged": converged,
        "iterations": iterations,
        "starts": 3,
        "event_durations": len(sorted_events),
        "censored_durations": sum(censor_hist.values()),
        "boundary_hit": (abs(log_scale - math.log(0.25)) < 1e-6
                         or abs(log_scale - math.log(1_000_000.0)) < 1e-6
                         or abs(log_shape - math.log(0.1)) < 1e-6
                         or abs(log_shape - math.log(10.0)) < 1e-6),
    }


def _write_risk_cache(path: Path, spells: Sequence[RiskSpell],
                      summary: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
                      frozen_hashes: Mapping[str, str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": RISK_CACHE_SCHEMA,
        "frozen_hashes": dict(frozen_hashes),
        "source_summary": dict(summary),
        "segment_entry_diagnostics": list(entries),
        "spells": [spell.to_dict() for spell in spells],
    }
    body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write(body)
    return sha256_file(path)


def _read_risk_cache(path: Path, expected_sha256: str,
                     frozen_hashes: Mapping[str, str]) -> tuple[list[RiskSpell], dict[str, Any], list[dict[str, Any]]]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"risk-spell cache hash mismatch: {actual}")
    with gzip.open(path, "rt", encoding="utf-8") as source:
        payload = json.load(source)
    if payload.get("schema") != RISK_CACHE_SCHEMA:
        raise ValueError(f"unsupported risk-spell cache schema: {payload.get('schema')}")
    if payload.get("frozen_hashes") != dict(frozen_hashes):
        raise ValueError("risk-spell cache frozen input hashes changed")
    spells = [RiskSpell.from_dict(row) for row in payload["spells"]]
    return spells, payload["source_summary"], payload["segment_entry_diagnostics"]


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = int(math.floor(position)), int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    frac = position - lower
    return ordered[lower] * (1.0 - frac) + ordered[upper] * frac


def _distribution_quantiles(model: Any, contexts: Sequence[Context]) -> dict[str, float | None]:
    if not contexts:
        raise ValueError("cannot average predictive quantiles over no contexts")
    keys: collections.Counter[tuple[object, ...]] = collections.Counter()
    representatives: dict[tuple[object, ...], Context] = {}
    for context in contexts:
        key = model.selected_key(context)
        keys[key] += 1
        representatives.setdefault(key, context)
    weighted = collections.Counter()
    for key, count in keys.items():
        context = representatives[key]
        weight = count / len(contexts)
        survival = 1.0
        cdf = 0.0
        for second in range(1, 12001):
            probability = model.gap_probability(context, second)
            cdf += probability
            if probability:
                weighted[second] += weight * probability
            if cdf >= 0.999999:
                break
    total = sum(weighted.values())
    if total <= 0:
        raise ValueError(f"{model.name} predictive distribution has no mass")
    result: dict[str, float | None] = {}
    for label, q in (("p50_seconds", .50), ("p90_seconds", .90),
                     ("p95_seconds", .95), ("p99_seconds", .99)):
        cumulative = 0.0
        answer = None
        for second in sorted(weighted):
            cumulative += weighted[second]
            if cumulative >= q:
                answer = float(second)
                break
        result[label] = answer
    return result


def _predicted_survival(model: Any, context: Context, threshold: int) -> float:
    if getattr(model, "kind", None) == "B2_exponential":
        key = model.selected_key(context)
        return max(0.0, (1.0 - model.hazards[key]) ** threshold)
    if getattr(model, "kind", None) == "B2_weibull":
        scale, shape = model._weibull_parameters(model.selected_key(context))
        return model.weibull_survival(threshold, scale, shape)
    return sum(model.gap_probability(context, second)
               for second in range(threshold + 1, PERIOD_SECONDS + 1))


def _observed_kaplan_meier(spells: Sequence[RiskSpell], *, censor_first: bool
                           ) -> dict[str, Any]:
    events: collections.Counter[int] = collections.Counter()
    censors: collections.Counter[int] = collections.Counter()
    boundary_ties: collections.Counter[int] = collections.Counter()
    for spell in spells:
        if spell.event_observed:
            events[spell.duration_seconds] += 1
        else:
            censors[spell.duration_seconds] += 1
            if spell.censor_reason and spell.censor_reason.startswith(
                    "same_second_eligible_event_"):
                boundary_ties[spell.duration_seconds] += 1
    survival = 1.0
    curve: dict[int, float] = {}
    max_duration = max([0, *events.keys(), *censors.keys()])
    for age in range(1, max_duration + 1):
        event_count = events[age]
        if censor_first:
            risk = sum(n for d, n in events.items() if d >= age)
            risk += sum(n for d, n in censors.items() if d > age)
        else:
            risk = sum(n for d, n in events.items() if d >= age)
            risk += sum(n for d, n in censors.items() if d >= age)
            event_count += boundary_ties[age]
        if risk > 0 and event_count:
            if event_count > risk:
                raise ValueError(f"KM event count exceeds risk set at age {age}")
            survival *= 1.0 - event_count / risk
        curve[age] = survival
    quantiles = {}
    for label, cutoff in (("p50_seconds", .50), ("p90_seconds", .10),
                          ("p95_seconds", .05), ("p99_seconds", .01)):
        value = next((age for age, tail in curve.items() if tail <= cutoff), None)
        quantiles[label] = value
    terminal_survival = next(reversed(curve.values()), 1.0)
    return {"n_events": sum(events.values()),
            "n_events_including_boundary_ties": sum(events.values()) + (
                0 if censor_first else sum(boundary_ties.values())),
            "n_boundary_ties": sum(boundary_ties.values()),
            "n_censored": sum(censors.values()),
            "quantiles": quantiles, "survival_at_threshold": {
                str(threshold): curve.get(threshold, terminal_survival) for threshold in THRESHOLDS},
            "tie_convention": "censor_before_event" if censor_first else "event_before_censor"}


def _support_summary(model: Any, rows: Sequence[Transition]) -> dict[str, Any]:
    counts = collections.Counter(model.selected_key(row.context) for row in rows)
    support = [model.stats[key].n for key, n_rows in counts.items()
               for _ in range(n_rows)]
    prior_mass = []
    unseen = 0
    for row in rows:
        key = model.selected_key(row.context)
        n = model.stats[key].n
        if model.name == "A1":
            prior_mass.append((1200 * model.alpha) / (n + 1200 * model.alpha))
        elif getattr(model, "kind", None) == "B1_pooled_shrinkage":
            prior_mass.append(model.prior_mass / (n + model.prior_mass))
        if model.stats[key].gaps[row.gap_seconds] == 0:
            unseen += 1
    return {
        "unique_selected_keys": len(counts),
        "selected_key_row_counts": {repr(key): n for key, n in sorted(counts.items(), key=lambda x: repr(x[0]))},
        "training_support_weighted_by_development_rows": {
            "min": min(support), "p50": _quantile(support, .50),
            "p90": _quantile(support, .90), "max": max(support),
        },
        "context_prior_mass_weighted_by_development_rows": {
            "min": min(prior_mass) if prior_mass else None,
            "p50": _quantile(prior_mass, .50),
            "p90": _quantile(prior_mass, .90),
            "max": max(prior_mass) if prior_mass else None,
            "mean": statistics.mean(prior_mass) if prior_mass else None,
        },
        "heldout_event_gaps_without_raw_selected_key_support": unseen,
    }


def _mix_distribution(model: Any, rows: Sequence[Transition], *, raw_empirical: bool = False
                      ) -> list[float]:
    if not rows:
        raise ValueError("cannot mix distributions over no observed contexts")
    keys = collections.Counter(model.selected_key(row.context) for row in rows)
    mixture = [0.0] * PERIOD_SECONDS
    for key, count in keys.items():
        context = next(row.context for row in rows if model.selected_key(row.context) == key)
        weight = count / len(rows)
        if raw_empirical:
            gap_counts = model.stats[key].gaps
            denominator = sum(gap_counts.values())
            for seconds in range(1, PERIOD_SECONDS + 1):
                mixture[seconds - 1] += weight * gap_counts[seconds] / denominator
        else:
            for seconds in range(1, PERIOD_SECONDS + 1):
                mixture[seconds - 1] += weight * model.gap_probability(context, seconds)
    return mixture


def _histogram(gaps: Iterable[int]) -> dict[str, int]:
    counts = collections.Counter(gaps)
    return {f"{low}-{high}s": sum(counts[second] for second in range(low, high + 1))
            for low, high in DURATION_BINS}


def _prior_mass_allocation(a1: RenewalModel, a0: RenewalModel,
                           development: Sequence[Transition]) -> dict[str, Any]:
    keys = collections.Counter(a1.selected_key(row.context) for row in development)
    prior_by_key = {}
    weighted_prior = [0.0] * PERIOD_SECONDS
    raw = [0.0] * PERIOD_SECONDS
    smooth = [0.0] * PERIOD_SECONDS
    pool = [0.0] * PERIOD_SECONDS
    pooled_shrink = [0.0] * PERIOD_SECONDS
    for key, row_count in keys.items():
        counts = a1.stats[key].gaps
        n = sum(counts.values())
        prior_n = PERIOD_SECONDS * a1.alpha
        weight = row_count / len(development)
        prior_share = prior_n / (n + prior_n)
        prior_by_key[repr(key)] = {
            "development_rows": row_count,
            "training_gap_count": n,
            "prior_pseudocount_total": prior_n,
            "prior_mass_share": prior_share,
            "prior_mass_by_duration_bin": {
                f"{low}-{high}s": prior_share * (high - low + 1) / PERIOD_SECONDS
                for low, high in DURATION_BINS
            },
        }
        denominator = n + prior_n
        for second in range(1, PERIOD_SECONDS + 1):
            base_raw = counts[second] / n
            base_smooth = (counts[second] + a1.alpha) / denominator
            weighted_prior[second - 1] += weight * (prior_n / denominator) * (1 / PERIOD_SECONDS)
            raw[second - 1] += weight * base_raw
            smooth[second - 1] += weight * base_smooth
    pooled = a0.stats[("pooled",)].gaps
    pooled_n = sum(pooled.values())
    for second in range(1, PERIOD_SECONDS + 1):
        pool[second - 1] = (pooled[second] + a0.alpha) / (pooled_n + a0.alpha * PERIOD_SECONDS)
    for key, row_count in keys.items():
        counts = a1.stats[key].gaps
        n = sum(counts.values())
        weight = row_count / len(development)
        for second in range(1, PERIOD_SECONDS + 1):
            pooled_shrink[second - 1] += weight * (
                counts[second] + POOL_PRIOR_MASS * pool[second - 1]
            ) / (n + POOL_PRIOR_MASS)

    def tail_curve(pmf: Sequence[float]) -> list[float]:
        total = 0.0
        result = [0.0] * len(pmf)
        for index in range(len(pmf) - 1, -1, -1):
            result[index] = total
            total += pmf[index]
        return result

    observed_hist = collections.Counter(row.gap_seconds for row in development)
    observed_pmf = [observed_hist[second] / len(development)
                    for second in range(1, PERIOD_SECONDS + 1)]
    return {
        "a1_selected_contexts": len(keys),
        "a1_context_support_distribution": {
            "min": min(a1.stats[key].n for key in keys),
            "p50": _quantile([a1.stats[key].n for key in keys], .50),
            "p90": _quantile([a1.stats[key].n for key in keys], .90),
            "max": max(a1.stats[key].n for key in keys),
        },
        "a1_prior_mass_weighted_by_observed_context": sum(
            row_count / len(development) * prior_by_key[repr(key)]["prior_mass_share"]
            for key, row_count in keys.items()),
        "a1_prior_mean_gap_seconds": sum((i + 1) * p for i, p in enumerate(weighted_prior))
            / sum(weighted_prior),
        "a1_context_mixture_empirical_mean_seconds": sum((i + 1) * p for i, p in enumerate(raw)),
        "a1_context_mixture_smoothed_mean_seconds": sum((i + 1) * p for i, p in enumerate(smooth)),
        "a0_pooled_mean_seconds": sum((i + 1) * p for i, p in enumerate(pool)),
        "prior_mass_by_duration_bin": {
            f"{low}-{high}s": sum(weighted_prior[low - 1:high])
            for low, high in DURATION_BINS
        },
        "prior_probability_by_duration_bin": {
            f"{low}-{high}s": sum(weighted_prior[low - 1:high])
            for low, high in DURATION_BINS
        },
        "distribution_by_duration_bin": {
            "observed_development_counts": _histogram(row.gap_seconds for row in development),
            "a1_raw_context_empirical": {
                f"{low}-{high}s": sum(raw[low - 1:high]) for low, high in DURATION_BINS},
            "a1_smoothed_context": {
                f"{low}-{high}s": sum(smooth[low - 1:high]) for low, high in DURATION_BINS},
            "a0_pooled": {
                f"{low}-{high}s": sum(pool[low - 1:high]) for low, high in DURATION_BINS},
            "b1_pooled_shrinkage": {
                f"{low}-{high}s": sum(pooled_shrink[low - 1:high]) for low, high in DURATION_BINS},
        },
        "full_integer_second_distributions": {
            "duration_seconds_1_to_1200": list(range(1, PERIOD_SECONDS + 1)),
            "observed_development_pmf": observed_pmf,
            "a1_raw_context_empirical_pmf": raw,
            "a1_uniform_prior_contribution_pmf": weighted_prior,
            "a1_smoothed_context_pmf": smooth,
            "a0_pooled_pmf": pool,
            "b1_pooled_shrinkage_pmf": pooled_shrink,
            "observed_development_survival_gt_second": tail_curve(observed_pmf),
            "a1_raw_context_empirical_survival_gt_second": tail_curve(raw),
            "a1_uniform_prior_contribution_survival_gt_second": tail_curve(weighted_prior),
            "a1_smoothed_context_survival_gt_second": tail_curve(smooth),
            "a0_pooled_survival_gt_second": tail_curve(pool),
            "b1_pooled_shrinkage_survival_gt_second": tail_curve(pooled_shrink),
        },
        "selected_key_details": prior_by_key,
    }


def _group_transition_rows(periods: Sequence[Any], season: int) -> dict[str, list[Transition]]:
    result: dict[str, list[Transition]] = {"first": [], "later": []}
    for period in periods:
        if period.season != season:
            continue
        for index, row in enumerate(period.transitions):
            result["first" if index == 0 else "later"].append(row)
    return result


def _score_transitions(models: Mapping[str, Any], transitions: Sequence[Transition]
                      ) -> dict[str, Any]:
    contexts = [row.context for row in transitions]
    observed = [row.gap_seconds for row in transitions]
    result: dict[str, Any] = {"n": len(transitions), "observed_gap_quantiles": {
        "p50_seconds": _quantile(observed, .50), "p90_seconds": _quantile(observed, .90),
        "p95_seconds": _quantile(observed, .95), "p99_seconds": _quantile(observed, .99),
    }, "models": {}}
    for name, model in models.items():
        nll = sum(-model.gap_log_probability(row.context, row.gap_seconds) for row in transitions)
        prediction = _distribution_quantiles(model, contexts)
        key_counts: collections.Counter[tuple[object, ...]] = collections.Counter()
        representatives: dict[tuple[object, ...], Context] = {}
        for context in contexts:
            key = model.selected_key(context)
            key_counts[key] += 1
            representatives.setdefault(key, context)
        survival = {}
        for threshold in THRESHOLDS:
            observed_rate = sum(gap > threshold for gap in observed) / len(observed)
            predicted_rate = sum(
                count * _predicted_survival(model, representatives[key], threshold)
                for key, count in key_counts.items()
            ) / len(contexts)
            survival[str(threshold)] = {
                "observed_proportion_gap_gt_threshold": observed_rate,
                "predicted_mean_probability": predicted_rate,
                "absolute_calibration_error": abs(predicted_rate - observed_rate),
            }
        result["models"][name] = {
            "event_gap_nll_nats": nll,
            "event_gap_nll_nats_per_5v5_minute": nll / (sum(observed) / 60.0),
            "predicted_gap_quantiles": prediction,
            "survival_calibration": survival,
            "support": _support_summary(model, transitions) if name in {"A0", "A1", "B1"} else {
                "unique_selected_keys": len(collections.Counter(model.selected_key(c) for c in contexts)),
                "all_event_gaps_positive_support": all(
                    model.gap_probability(row.context, row.gap_seconds) > 0 for row in transitions),
            },
        }
    return result


def _paired_event_gap_bootstrap(models: Mapping[str, Any], transitions: Sequence[Transition],
                                reference: str = "A0", *,
                                replicates: int = BOOTSTRAP_REPLICATES,
                                seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    per_model: dict[str, dict[str, tuple[float, float]]] = {name: {} for name in models}
    by_game: dict[str, list[Transition]] = collections.defaultdict(list)
    for row in transitions:
        by_game[row.game_id].append(row)
    for game_id, rows in by_game.items():
        exposure = sum(row.gap_seconds for row in rows)
        for name, model in models.items():
            loss = sum(-model.gap_log_probability(row.context, row.gap_seconds) for row in rows)
            per_model[name][game_id] = (loss, exposure)
    games = sorted(by_game)
    result = {}
    for name in models:
        if name == reference:
            continue
        rng = random.Random(seed)
        deltas = []
        for _ in range(replicates):
            sample = [games[rng.randrange(len(games))] for _ in games]
            numerator_a = denominator_a = numerator_b = denominator_b = 0.0
            for game in sample:
                loss_a, exposure_a = per_model[reference][game]
                loss_b, exposure_b = per_model[name][game]
                numerator_a += loss_a
                denominator_a += exposure_a
                numerator_b += loss_b
                denominator_b += exposure_b
            deltas.append(numerator_b / (denominator_b / 60.0)
                          - numerator_a / (denominator_a / 60.0))
        deltas.sort()
        result[name] = {
            "status": "ok",
            "replicates": len(deltas),
            "seed": seed,
            "candidate_minus_reference_mean": statistics.mean(deltas),
            "ci95_low": deltas[int(.025 * (len(deltas) - 1))],
            "ci95_high": deltas[int(.975 * (len(deltas) - 1))],
        }
    return result


def _censor_survival_calibration(models: Mapping[str, Any], spells: Sequence[RiskSpell]
                                 ) -> dict[str, Any]:
    groups = {
        "all_event_origins": list(spells),
        "first_event_origin_per_period": [spell for spell in spells if spell.origin_index == 0],
        "later_event_origins": [spell for spell in spells if spell.origin_index > 0],
    }
    result: dict[str, Any] = {}
    for label, rows in groups.items():
        if not rows:
            result[label] = {"n": 0}
            continue
        result[label] = {
            "n": len(rows),
            "events": sum(spell.event_observed for spell in rows),
            "censored": sum(not spell.event_observed for spell in rows),
            "observed_kaplan_meier_censor_first": _observed_kaplan_meier(rows, censor_first=True),
            "observed_kaplan_meier_event_first": _observed_kaplan_meier(rows, censor_first=False),
            "models": {},
        }
        key_counts_by_model = {}
        for name, model in models.items():
            counts: collections.Counter[tuple[object, ...]] = collections.Counter()
            representatives: dict[tuple[object, ...], Context] = {}
            for spell in rows:
                key = model.selected_key(spell.context)
                counts[key] += 1
                representatives.setdefault(key, spell.context)
            key_counts_by_model[name] = (counts, representatives)
        for name, model in models.items():
            counts, representatives = key_counts_by_model[name]
            values = {}
            for threshold in THRESHOLDS:
                predicted = sum(
                    count * _predicted_survival(model, representatives[key], threshold)
                    for key, count in counts.items()
                ) / len(rows)
                km_early = result[label]["observed_kaplan_meier_censor_first"][
                    "survival_at_threshold"][str(threshold)]
                km_late = result[label]["observed_kaplan_meier_event_first"][
                    "survival_at_threshold"][str(threshold)]
                values[str(threshold)] = {
                    "predicted_mean_survival": predicted,
                    "observed_km_range_from_same_second_tie_order": [km_early, km_late],
                    "absolute_error_to_km_range": [abs(predicted - km_early), abs(predicted - km_late)],
                }
            result[label]["models"][name] = values
    return result


def _joint_spell_scores(models: Mapping[str, Any], spells: Sequence[RiskSpell]
                       ) -> dict[str, Any]:
    by_model: dict[str, Any] = {}
    for name, model in models.items():
        nll = 0.0
        event_nll = 0.0
        censor_nll = 0.0
        by_game: dict[str, dict[str, float]] = collections.defaultdict(
            lambda: {"nll": 0.0, "event_nll": 0.0, "censor_nll": 0.0, "risk_seconds": 0.0})
        failed_support = 0
        for spell in spells:
            if spell.event_observed:
                logp = model.gap_log_probability(spell.context, spell.duration_seconds)
                if not math.isfinite(logp):
                    failed_support += 1
                    continue
                loss = -logp
                event_nll += loss
                by_game[spell.game_id]["event_nll"] += loss
            else:
                if isinstance(model, TimingCandidate):
                    probability = model.survival_left(spell.context, spell.duration_seconds)
                else:
                    probability = sum(model.gap_probability(spell.context, gap)
                                      for gap in range(spell.duration_seconds, PERIOD_SECONDS + 1))
                if probability <= 0 or not math.isfinite(probability):
                    failed_support += 1
                    continue
                loss = -math.log(probability)
                censor_nll += loss
                by_game[spell.game_id]["censor_nll"] += loss
            nll += loss
            by_game[spell.game_id]["nll"] += loss
            by_game[spell.game_id]["risk_seconds"] += spell.complete_risk_seconds
        risk_seconds = sum(spell.complete_risk_seconds for spell in spells)
        finite = failed_support == 0
        for row in by_game.values():
            row["risk_seconds"] = float(row["risk_seconds"])
        by_model[name] = {
            "finite": finite,
            "support_failures": failed_support,
            "event_spell_nll_nats": event_nll if finite else None,
            "censored_spell_nll_nats": censor_nll if finite else None,
            "joint_nll_nats": nll if finite else None,
            "risk_seconds": risk_seconds,
            "joint_nll_nats_per_risk_minute": nll / (risk_seconds / 60.0) if finite and risk_seconds else None,
            "game_contributions": by_game,
        }
    return by_model


def _paired_joint_bootstrap(scores: Mapping[str, Any], reference: str,
                            *, replicates: int = BOOTSTRAP_REPLICATES,
                            seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    ref = scores[reference]
    if not ref["finite"]:
        return {"status": "reference_has_zero_survival_support"}
    games = sorted(ref["game_contributions"])
    output = {}
    for name, candidate in scores.items():
        if name == reference:
            continue
        if not candidate["finite"]:
            output[name] = {"status": "candidate_has_zero_survival_support"}
            continue
        rng = random.Random(seed)
        samples = []
        for _ in range(replicates):
            selected = [games[rng.randrange(len(games))] for _ in games]
            totals = {reference: [0.0, 0.0], name: [0.0, 0.0]}
            for game in selected:
                for model_name in (reference, name):
                    row = scores[model_name]["game_contributions"][game]
                    totals[model_name][0] += row["nll"]
                    totals[model_name][1] += row["risk_seconds"]
            ref_rate = totals[reference][0] / (totals[reference][1] / 60.0)
            candidate_rate = totals[name][0] / (totals[name][1] / 60.0)
            samples.append(candidate_rate - ref_rate)
        samples.sort()
        output[name] = {
            "status": "ok",
            "replicates": len(samples),
            "seed": seed,
            "candidate_minus_reference_mean": statistics.mean(samples),
            "ci95_low": samples[int(.025 * (len(samples) - 1))],
            "ci95_high": samples[int(.975 * (len(samples) - 1))],
        }
    return output


def _fit_population(cache_periods: Sequence[Any], spells: Sequence[RiskSpell]):
    training = [row for period in cache_periods if period.season in data.TRAIN_SEASONS
                for row in period.transitions]
    development_periods = [period for period in cache_periods if period.season == 2021]
    development = [row for period in development_periods for row in period.transitions]
    training_spells = [spell for spell in spells if spell.season in data.TRAIN_SEASONS]
    development_spells = [spell for spell in spells if spell.season == 2021]
    if len(training) != 329667 or len(development) != 229842:
        raise ValueError(f"transition population changed: train={len(training)}, dev={len(development)}")
    for label, transitions, rows in (("training", training, training_spells),
                                     ("development", development, development_spells)):
        event_spells = sum(spell.event_observed for spell in rows)
        boundary_ties = sum(
            spell.censor_reason is not None
            and spell.censor_reason.startswith("same_second_eligible_event_")
            for spell in rows
        )
        if event_spells + boundary_ties != len(transitions):
            raise ValueError(
                f"{label} source event spells plus boundary ties do not reconcile: "
                f"{event_spells}+{boundary_ties}!={len(transitions)}"
            )
    models, fit = _fit_timing_models(training, training_spells)
    return models, fit, training, development_periods, development, development_spells


def historical_evaluation(cache_periods: Sequence[Any], spells: Sequence[RiskSpell],
                          source_summary: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
                          frozen_hashes: Mapping[str, str], risk_cache_sha256: str) -> dict[str, Any]:
    models, fit, training, development_periods, development, development_spells = _fit_population(
        cache_periods, spells)
    grouped = _group_transition_rows(development_periods, 2021)
    mode_a = {name: _score_transitions(models, rows)
              for name, rows in (("first_retained_transition_per_period", grouped["first"]),
                                 ("later_retained_transitions", grouped["later"]),
                                 ("all_retained_transitions", development))}
    for label, rows in (("first_retained_transition_per_period", grouped["first"]),
                        ("later_retained_transitions", grouped["later"]),
                        ("all_retained_transitions", development)):
        mode_a[label]["paired_game_clustered_event_gap_nll_delta"] = {
            reference: _paired_event_gap_bootstrap(
                models, rows, reference=reference, seed=BOOTSTRAP_SEED)
            for reference in ("A0", "A1")
        }
    joint_scores = _joint_spell_scores(models, development_spells)
    support_keys = {name: _support_summary(model, development) if name in {"A0", "A1", "B1"}
                    else {"unique_selected_keys": len({model.selected_key(row.context) for row in development})}
                    for name, model in models.items()}
    mark_nll = sum(-models["A1"].mark_log_probability(row.context, row.mark)
                   for row in development)
    prior_detail = _prior_mass_allocation(models["A1"], models["A0"], development)
    censor_calibration = _censor_survival_calibration(models, development_spells)
    censor_reason = collections.Counter(spell.censor_reason for spell in development_spells
                                         if not spell.event_observed)
    censor_seconds = collections.Counter()
    for spell in development_spells:
        if not spell.event_observed:
            censor_seconds[spell.censor_reason] += spell.duration_seconds
    by_period_entry = collections.Counter((row["entry_kind"], row["outcome"])
                                          for row in entries if row["season"] == 2021)
    first_entry_times = [row["elapsed_seconds"] for row in entries
                         if row["season"] == 2021 and row["entry_kind"] == "period_entry"
                         and row["outcome"] in {"first_event", "event_at_entry"}]
    result = {
        "stage": "historical_state_replay",
        "date": "2026-10-28",
        "branch": "research/nhl-a1-gap-estimator-comparison-2026-10-28",
        "preregistration_commit": PREREG_COMMIT,
        "input_pin_commit": PREREG_INPUT_PIN_COMMIT,
        "censor_convention_commit": PREREG_CENSOR_CONVENTION_COMMIT,
        "boundary_tie_commit": PREREG_BOUNDARY_TIE_COMMIT,
        "preregistration_commits": [
            PREREG_COMMIT, PREREG_INPUT_PIN_COMMIT,
            PREREG_CENSOR_CONVENTION_COMMIT, PREREG_BOUNDARY_TIE_COMMIT,
        ],
        "parent_commit": PARENT_COMMIT,
        "frozen_hashes": dict(frozen_hashes),
        "risk_spell_cache_sha256": risk_cache_sha256,
        "training_transition_count": len(training),
        "development_transition_count": len(development),
        "training_risk_spell_count": len([s for s in spells if s.season in data.TRAIN_SEASONS]),
        "development_risk_spell_count": len(development_spells),
        "source_censor_and_exposure_summary": {
            key: value for key, value in source_summary.items() if key != "period_summaries"
        },
        "training_fit_diagnostics": fit,
        "pseudocount_allocation": prior_detail,
        "historical_state_replay": mode_a,
        "joint_event_and_censor_log_likelihood": {
            "models": {name: {k: v for k, v in item.items() if k != "game_contributions"}
                       for name, item in joint_scores.items()},
            "paired_game_clustered_ci": {
                reference: _paired_joint_bootstrap(joint_scores, reference, seed=BOOTSTRAP_SEED)
                for reference in ("A0", "A1")
            },
        },
        "censor_reasons_2021": dict(sorted(censor_reason.items())),
        "censored_elapsed_seconds_2021": dict(sorted(censor_seconds.items())),
        "censor_aware_survival_calibration": censor_calibration,
        "period_entry_observations_2021": {
            "entry_segment_outcomes": {f"{kind}:{outcome}": count
                                       for (kind, outcome), count in sorted(by_period_entry.items())},
            "period_entry_first_event_count": len(first_entry_times),
            "period_entry_first_event_elapsed_quantiles": {
                "p50_seconds": _quantile(first_entry_times, .50),
                "p90_seconds": _quantile(first_entry_times, .90),
                "p95_seconds": _quantile(first_entry_times, .95),
            },
            "interpretation": "initial/re-entry segment gaps are separate from post-event gaps; they are not pooled into candidate training",
        },
        "frozen_mark_model": {
            "source": "A1 mark model unchanged across all timing candidates",
            "development_mark_nll_nats": mark_nll,
            "development_mark_nll_nats_per_bundle": mark_nll / len(development),
            "candidate_mark_likelihoods_identical_by_construction": True,
        },
        "timing_candidate_support": support_keys,
        "rollout_eligible_candidates": [name for name, score in joint_scores.items()
                                         if score["finite"] and all(
                                             models[name].gap_probability(row.context, row.gap_seconds) > 0
                                             for row in development)
                                         and (name != "B2-W" or all(
                                             row["converged"] for row in fit["b2_weibull_optimizer_by_context"].values()))],
        "decision": "NO_CANDIDATE_SELECTED_HISTORICAL_DEVELOPMENT_COMPARISON_ONLY",
    }
    return result


def _candidate_trace(model: Any, seed: int) -> tuple[list[Any], int]:
    context = Context("faceoff", True, 0, 0)
    rng = random.Random(seed)
    current = 0
    trace = []
    terminal_gap = 0
    while current < PERIOD_SECONDS:
        gap = model.sample_gap(context, rng)
        arrival = current + gap
        if arrival >= PERIOD_SECONDS:
            terminal_gap = gap
            break
        mark = model.sample_mark(context, rng)
        trace.append((arrival, mark))
        context = kernel.update_context(context, mark, arrival)
        current = arrival
        if len(trace) > PERIOD_SECONDS:
            raise AssertionError("positive gaps generated more events than seconds")
    kernel.validate_trace(trace, horizon=PERIOD_SECONDS)
    return trace, terminal_gap


def _cluster_bootstrap_crps(score_rows: Mapping[str, Sequence[float]], *,
                            replicates: int = BOOTSTRAP_REPLICATES,
                            seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    games = sorted(score_rows)
    if not games:
        raise ValueError("CRPS interval requires game rows")
    rng = random.Random(seed)
    values = []
    for _ in range(replicates):
        sampled = [games[rng.randrange(len(games))] for _ in games]
        flattened = [value for game in sampled for value in score_rows[game]]
        values.append(statistics.mean(flattened))
    values.sort()
    return {"replicates": len(values), "seed": seed,
            "mean": statistics.mean(values),
            "ci95_low": values[int(.025 * (len(values) - 1))],
            "ci95_high": values[int(.975 * (len(values) - 1))]}


def autonomous_evaluation(cache_periods: Sequence[Any], historical: Mapping[str, Any],
                          spells: Sequence[RiskSpell]) -> dict[str, Any]:
    models, fit, _, _, _, _ = _fit_population(cache_periods, spells)
    eligible = set(historical.get("rollout_eligible_candidates", []))
    if not eligible:
        raise ValueError("historical stage found no candidate with complete support; autonomous run refused")
    selected = {name: model for name, model in models.items()
                if name in {"A0", "A1"} or name in eligible}
    periods = [period for period in cache_periods if period.season == 2021]
    max_bundle_size = min(model.max_bundle_size for model in selected.values())
    metrics = ("bundle_count", "shot_attempts", "sog", "goals",
               *(f"family:{family}" for family in FAMILIES))
    observed: dict[str, dict[tuple[str, int], float]] = {m: {} for m in metrics}
    forecasts: dict[str, dict[str, dict[tuple[str, int], list[float]]]] = {
        name: {m: {} for m in metrics} for name in selected}
    generated_gaps: dict[str, list[int]] = {name: [] for name in selected}
    first_generated_gaps: dict[str, list[int]] = {name: [] for name in selected}
    first_arrival_censored: collections.Counter[str] = collections.Counter()
    terminal_gaps: dict[str, list[int]] = {name: [] for name in selected}
    model_runtime_seconds: collections.Counter[str] = collections.Counter()
    trace_count = 0
    reproducibility: dict[str, Any] | None = None

    for period in periods:
        key_period = (period.game_id, period.period)
        target = run_experiment._period_target(period, max_bundle_size)
        if target is not None:
            values, _, _ = target
            for metric, value in values.items():
                observed[metric][key_period] = value
        for replicate in range(10):
            seed = common_random_seed(period.game_id, period.period, replicate)
            for name, model in selected.items():
                model_started = time.perf_counter()
                trace, terminal = _candidate_trace(model, seed)
                model_runtime_seconds[name] += time.perf_counter() - model_started
                if name in {"A0", "A1"}:
                    frozen_trace = sample_trace(model, seed)
                    if trace != frozen_trace:
                        raise ValueError(f"{name} candidate trace differs from frozen sampler")
                trace_count += 1
                if terminal <= 0:
                    raise ValueError(f"{name} trace lacks its terminal right-censor proposal")
                terminal_gaps[name].append(terminal)
                if trace:
                    first_generated_gaps[name].append(trace[0][0])
                else:
                    first_arrival_censored[name] += 1
                generated_gaps[name].extend(
                    next_second - previous_second
                    for previous_second, next_second in zip(
                        [0, *(second for second, _ in trace[:-1])],
                        [second for second, _ in trace])
                )
                counts = trace_counts(trace)
                for metric in metrics:
                    forecasts[name][metric].setdefault(key_period, []).append(
                        float(counts.get(metric, 0)))
                if reproducibility is None:
                    repeated, _ = _candidate_trace(model, seed)
                    reproducibility = {"candidate": name, "game_id": period.game_id,
                                       "period": period.period, "replicate": replicate,
                                       "byte_identical": repeated == trace}
                    if not reproducibility["byte_identical"]:
                        raise ValueError("fixed-seed trace is not reproducible")

    metric_results: dict[str, Any] = {}
    for metric in metrics:
        candidate_results = {}
        game_crps: dict[str, dict[str, list[float]]] = {
            name: collections.defaultdict(list) for name in selected
        }
        for name in selected:
            per_period_means = []
            per_period_draws = []
            observed_values = []
            coverage = []
            raw_counts = []
            for period_key, target_value in observed[metric].items():
                draws = forecasts[name][metric][period_key]
                if len(draws) != 10:
                    raise ValueError(f"incomplete common-random draw block for {name}/{metric}/{period_key}")
                per_period_draws.append(draws)
                per_period_means.append(statistics.mean(draws))
                observed_values.append(target_value)
                raw_counts.extend(draws)
                game_crps[name][period_key[0]].append(crps(draws, target_value))
                low, high = _quantile(draws, .10), _quantile(draws, .90)
                coverage.append(float(low <= target_value <= high))
            score_rows = game_crps[name]
            candidate_results[name] = {
                "periods_scored": len(observed_values),
                "observed_mean": statistics.mean(observed_values),
                "generated_mean": statistics.mean(raw_counts),
                "observed_period_variance": statistics.pvariance(observed_values),
                "mean_within_period_trace_variance": statistics.mean(
                    statistics.pvariance(draws) for draws in per_period_draws),
                "mean_forecast_period_mean_variance": statistics.pvariance(per_period_means),
                "central_80pct_interval_coverage": statistics.mean(coverage),
                "crps": statistics.mean(value for rows in score_rows.values() for value in rows),
                "crps_game_clustered_interval": _cluster_bootstrap_crps(score_rows),
                "generated_count_quantiles": {
                    "p50": _quantile(raw_counts, .50), "p90": _quantile(raw_counts, .90),
                    "p95": _quantile(raw_counts, .95), "p99": _quantile(raw_counts, .99),
                },
            }
        reference = candidate_results["A0"]
        for name, result in candidate_results.items():
            if name == "A0":
                continue
            delta_rows = {}
            for game in sorted(set(game_crps[name]) & set(game_crps["A0"])):
                delta_rows[game] = [b - a for a, b in zip(game_crps["A0"][game], game_crps[name][game])]
            result["crps_delta_vs_a0"] = statistics.mean(
                value for rows in delta_rows.values() for value in rows)
            result["crps_delta_vs_a0_game_clustered_interval"] = _cluster_bootstrap_crps(delta_rows)
        metric_results[metric] = {"candidates": candidate_results}

    terminal_summaries = {}
    for name in selected:
        gaps = generated_gaps[name]
        terminals = terminal_gaps[name]
        terminal_summaries[name] = {
            "emitted_gap_quantiles": {f"p{int(q*100)}": _quantile(gaps, q)
                                      for q in (.50, .90, .95, .99)},
            "terminal_censored_proposal_count": len(terminals),
            "terminal_proposal_quantiles": {f"p{int(q*100)}": _quantile(terminals, q)
                                            for q in (.50, .90, .95, .99)},
            "first_generated_gap_quantiles": {
                f"p{int(q*100)}": _quantile(first_generated_gaps[name], q)
                for q in (.50, .90, .95, .99)},
            "first_arrival_right_censored_traces": first_arrival_censored[name],
            "trace_generation_runtime_seconds": model_runtime_seconds[name],
        }
    return {
        "stage": "autonomous_rollout",
        "models_run": list(selected),
        "development_periods": len(periods),
        "replicates_per_period": 10,
        "trace_count": trace_count,
        "frozen_mark_model": "A1 unchanged for all timing candidates",
        "training_fit_diagnostics": {
            "b2_selected_contexts": fit["b2_selected_contexts"],
            "b2_training_event_spells": fit["b2_training_event_spells"],
            "b2_training_censored_spells": fit["b2_training_censored_spells"],
        },
        "metrics": metric_results,
        "gap_and_terminal_proposal_summaries": terminal_summaries,
        "trace_reproducibility": reproducibility,
        "decision": "DEVELOPMENT_ONLY_NO_MODEL_SELECTED",
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sha256_file(path)


def _write_report(path: Path, historical: Mapping[str, Any],
                  rollout: Mapping[str, Any] | None = None) -> None:
    def ci_cell(row: Mapping[str, Any] | None) -> str:
        if row is None:
            return "reference"
        if row.get("status") != "ok":
            return str(row.get("status", "unavailable"))
        return (f"{row['candidate_minus_reference_mean']:+.5f} "
                f"[{row['ci95_low']:+.5f}, {row['ci95_high']:+.5f}]")

    lines = [
        "# NHL A1 Gap Estimator Comparison",
        "",
        "**Date:** 2026-10-28  ",
        "**Branch:** `research/nhl-a1-gap-estimator-comparison-2026-10-28`  ",
        f"**Historical result:** `{historical.get('result_sha256', 'not yet finalized')}`  ",
        f"**Risk-spell cache SHA-256:** `{historical['risk_spell_cache_sha256']}`",
        "",
        "## Scope and data boundary",
        "",
        "A0 and A1 remain frozen controls. B1 replaces A1's uniform timing pseudocount with the pooled training timing distribution at the same 600-count prior strength. B2-E and B2-W fit discrete event-time distributions using event and right-censored spells. All event marks use the unchanged A1 mark model. The 2021 season is exposed development data, not an independent test. No scoring, production forecast, or gate changed.",
        "",
        "## Where A1's timing prior goes",
        "",
        f"A1 uses 0.5 pseudocount at each of 1,200 gap seconds, or 600 total prior counts per selected context. Across 2021 pre-gap contexts, the measured prior mass share was **{historical['pseudocount_allocation']['a1_prior_mass_weighted_by_observed_context']:.3%}**. Its uniform prior's mean duration is **{historical['pseudocount_allocation']['a1_prior_mean_gap_seconds']:.2f}s**; the context-weighted raw empirical mean is **{historical['pseudocount_allocation']['a1_context_mixture_empirical_mean_seconds']:.2f}s**, and A1's smoothed mean is **{historical['pseudocount_allocation']['a1_context_mixture_smoothed_mean_seconds']:.2f}s**. The full 1-second PMF and survival arrays are in the JSON.",
        "",
        "| Duration bin | Observed 2021 gaps | A1 raw context PMF | A1 smoothed PMF | Uniform-prior contribution | A0 pooled PMF | B1 pooled-shrink PMF |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    allocation = historical["pseudocount_allocation"]
    observed_bins = allocation["distribution_by_duration_bin"]["observed_development_counts"]
    for low, high in DURATION_BINS:
        label = f"{low}-{high}s"
        lines.append(
            f"| {label} | {observed_bins[label]:,} | "
            f"{allocation['distribution_by_duration_bin']['a1_raw_context_empirical'][label]:.4f} | "
            f"{allocation['distribution_by_duration_bin']['a1_smoothed_context'][label]:.4f} | "
            f"{allocation['prior_probability_by_duration_bin'][label]:.4f} | "
            f"{allocation['distribution_by_duration_bin']['a0_pooled'][label]:.4f} | "
            f"{allocation['distribution_by_duration_bin']['b1_pooled_shrinkage'][label]:.4f} |"
        )
    lines.extend(["", "## Historical-state replay", "",
                  "| Estimator | All-gap NLL / 5v5 min | Δ vs A0 (95% game-cluster CI) | Δ vs A1 (95% game-cluster CI) | p50 | p90 | p95 | p99 | Unsupported raw gaps |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    all_replay = historical["historical_state_replay"]["all_retained_transitions"]
    for name, metrics in all_replay["models"].items():
        quantiles = metrics["predicted_gap_quantiles"]
        support = metrics["support"]
        unsupported = support.get("heldout_event_gaps_without_raw_selected_key_support", "n/a")
        paired = all_replay["paired_game_clustered_event_gap_nll_delta"]
        delta_a0 = paired["A0"].get(name)
        delta_a1 = paired["A1"].get(name)
        lines.append(
            f"| {name} | {metrics['event_gap_nll_nats_per_5v5_minute']:.5f} | "
            f"{ci_cell(delta_a0)} | {ci_cell(delta_a1)} | "
            f"{quantiles['p50_seconds']} | {quantiles['p90_seconds']} | "
            f"{quantiles['p95_seconds']} | {quantiles['p99_seconds']} | {unsupported} |"
        )
    lines.extend(["", "Event-gap NLL contrasts are game-clustered; confidence intervals and first-versus-later results are in the JSON.",
                  "", "### Censoring and survival likelihood", "",
                  "The source extractor reconciles event-observed risk spells plus same-second boundary-tied event censors exactly to the frozen transition cache. Ineligible event bundles, 5v5 exits, ambiguous state, period end, and eligible-event boundary ties are separate right-censor reasons. A censor is not encoded as a long event gap. Whole-second censor ties are shown under both censor-first and event-first Kaplan–Meier conventions.",
                  "", "| Estimator | Censored spells | Joint event+censor NLL / at-risk min | Δ vs A0 (95% game-cluster CI) | Δ vs A1 (95% game-cluster CI) | Support failures |",
                  "|---|---:|---:|---:|---:|---:|"])
    joint = historical["joint_event_and_censor_log_likelihood"]
    censor_n = historical["source_censor_and_exposure_summary"]["right_censored_spells_by_season"].get("2021", 0)
    for name, row in joint["models"].items():
        ci_a0 = joint["paired_game_clustered_ci"]["A0"].get(name)
        ci_a1 = joint["paired_game_clustered_ci"]["A1"].get(name)
        lines.append(
            f"| {name} | {censor_n:,} | {row['joint_nll_nats_per_risk_minute'] if row['finite'] else 'infinite'} | "
            f"{ci_cell(ci_a0)} | {ci_cell(ci_a1)} | {row['support_failures']} |"
        )
    lines.extend(["", "### First event and later events", "",
                  "A period-entry/re-entry observation is reported separately and is not pooled with post-event gaps. Within the frozen transition sample, the first retained transition per period and later transitions are scored separately. Full predicted/observed quantiles, survival calibration, and censoring splits are preserved in the JSON.",
                  "", "## Autonomous rollout", ""])
    if rollout is None:
        lines.append("Not yet run. The historical-state stage must complete and validate support before this stage starts.")
    else:
        lines.extend([
            f"The rollout used {rollout['development_periods']:,} periods × {rollout['replicates_per_period']} common seeds, for {rollout['trace_count']:,} traces. Candidate and control marks remain A1's frozen mark model.",
            "",
            "| Metric | Estimator | Generated mean | Observed mean | CRPS | CRPS delta vs A0 (95% game-cluster CI) | Generated p50/p90/p95/p99 |",
            "|---|---|---:|---:|---:|---:|---|"])
        for metric, block in rollout["metrics"].items():
            for name, row in block["candidates"].items():
                quantiles = row["generated_count_quantiles"]
                ci = row.get("crps_delta_vs_a0_game_clustered_interval")
                delta = (f"{row['crps_delta_vs_a0']:+.4f} "
                         f"[{ci['ci95_low']:+.4f}, {ci['ci95_high']:+.4f}]"
                         if ci else "reference")
                lines.append(
                    f"| {metric} | {name} | {row['generated_mean']:.3f} | {row['observed_mean']:.3f} | "
                    f"{row['crps']:.4f} | {delta} | "
                    f"{quantiles['p50']}/{quantiles['p90']}/{quantiles['p95']}/{quantiles['p99']} |"
                )
        lines.extend(["", "Generated emitted-gap and terminal-censor proposal quantiles, mark-family counts, SOG, attempts, goals, trace reproducibility, and runtimes are in the rollout JSON."])
    lines.extend([
        "",
        "## Decision and limitations",
        "",
        "This is a mechanism comparison on exposed 2021 development data. It does not select or adopt a timing model. B1's complete-gap fit does not use censored spells in its PMF, while B2-E/W use the reconstructed right-censored risk set; censoring reason is retained because penalty/state exits may be informative rather than independent. No puck tracking, new source, or production data was needed for this timing investigation.",
        "",
        "A0/A1 original artifacts remain unchanged. All candidate paths keep the shot/mark sampler fixed. The autonomous rollout is not an independent validation of the NHL game model.",
        "",
        "## Reproduction",
        "",
        "```bash",
        "python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage audit --game-limit 1",
        "python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage historical",
        "python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage rollout",
        "python3 -m unittest discover -s research/nhl/autonomous-5v5/tests -p 'test_gap_estimator_comparison.py'",
        "```",
        "",
        "- Preregistration: [protocol](NHL-A1-GAP-ESTIMATOR-COMPARISON-PREREG-2026-10-28.md).",
        "- Machine-readable historical results: [`nhl-a1-gap-estimator-comparison-historical-2026-10-28.json`](../../research/nhl/autonomous-5v5/results/nhl-a1-gap-estimator-comparison-historical-2026-10-28.json).",
        "- Machine-readable rollout results: [`nhl-a1-gap-estimator-comparison-rollout-2026-10-28.json`](../../research/nhl/autonomous-5v5/results/nhl-a1-gap-estimator-comparison-rollout-2026-10-28.json).",
        "- Implementation/tests: [`gap_estimator_comparison.py`](../../research/nhl/autonomous-5v5/gap_estimator_comparison.py), [`test_gap_estimator_comparison.py`](../../research/nhl/autonomous-5v5/tests/test_gap_estimator_comparison.py).",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    payload, cache_periods = verify_frozen_inputs(args.cache, args.data_root)
    spells, summary, entries = reconstruct_risk_spells(
        cache_periods, args.data_root, game_limit=args.game_limit)
    result = {
        "stage": "single_game_source_audit",
        "game_limit": args.game_limit,
        "games_processed_by_start_season": summary["games_processed_by_start_season"],
        "periods_processed": summary["periods_processed"],
        "risk_spells": len(spells),
        "source_summary": {key: value for key, value in summary.items()
                           if key != "period_summaries"},
        "segment_entry_rows": len(entries),
        "sequence_cache_population": payload["population"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def run_historical(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    payload, cache_periods = verify_frozen_inputs(args.cache, args.data_root)
    frozen_hashes = {
        "parent_result_sha256": PARENT_RESULT_SHA256,
        "sequence_cache_sha256": SEQUENCE_CACHE_SHA256,
        "kernel_sha256": KERNEL_SHA256,
        "data_sha256": DATA_SHA256,
        "payload_source_hashes": payload["source_hashes"],
        "preregistration_commits": [
            PREREG_COMMIT, PREREG_INPUT_PIN_COMMIT,
            PREREG_CENSOR_CONVENTION_COMMIT, PREREG_BOUNDARY_TIE_COMMIT,
        ],
    }
    spells, source_summary, entries = reconstruct_risk_spells(cache_periods, args.data_root)
    risk_cache_hash = _write_risk_cache(args.risk_cache, spells, source_summary, entries, frozen_hashes)
    result = historical_evaluation(cache_periods, spells, source_summary, entries,
                                   frozen_hashes, risk_cache_hash)
    result["runtime_seconds"] = time.perf_counter() - started
    result_hash = _write_json(args.historical_output, result)
    print(json.dumps({
        "stage": "historical_state_replay",
        "output": str(args.historical_output),
        "risk_cache": str(args.risk_cache),
        "risk_cache_sha256": risk_cache_hash,
        "result_sha256": result_hash,
        "transitions_2021": result["development_transition_count"],
        "censored_spells_2021": result["source_censor_and_exposure_summary"]["right_censored_spells_by_season"].get("2021", 0),
        "rollout_eligible_candidates": result["rollout_eligible_candidates"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True), flush=True)
    return result


def run_rollout(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    payload, cache_periods = verify_frozen_inputs(args.cache, args.data_root)
    historical = _read_json(args.historical_output)
    if historical.get("stage") != "historical_state_replay":
        raise ValueError("rollout requires a completed historical-state result")
    frozen_hashes = {
        "parent_result_sha256": PARENT_RESULT_SHA256,
        "sequence_cache_sha256": SEQUENCE_CACHE_SHA256,
        "kernel_sha256": KERNEL_SHA256,
        "data_sha256": DATA_SHA256,
        "payload_source_hashes": payload["source_hashes"],
        "preregistration_commits": [
            PREREG_COMMIT, PREREG_INPUT_PIN_COMMIT,
            PREREG_CENSOR_CONVENTION_COMMIT, PREREG_BOUNDARY_TIE_COMMIT,
        ],
    }
    spells, _, _ = _read_risk_cache(
        args.risk_cache, historical["risk_spell_cache_sha256"], frozen_hashes)
    rollout = autonomous_evaluation(cache_periods, historical, spells)
    rollout["preregistration_commits"] = [
        PREREG_COMMIT, PREREG_INPUT_PIN_COMMIT,
        PREREG_CENSOR_CONVENTION_COMMIT, PREREG_BOUNDARY_TIE_COMMIT,
    ]
    rollout["historical_result_sha256"] = sha256_file(args.historical_output)
    rollout["risk_spell_cache_sha256"] = historical["risk_spell_cache_sha256"]
    rollout["sequence_cache_sha256"] = SEQUENCE_CACHE_SHA256
    rollout["runtime_seconds"] = time.perf_counter() - started
    rollout_hash = _write_json(args.rollout_output, rollout)
    historical["result_sha256"] = sha256_file(args.historical_output)
    rollout["result_sha256"] = rollout_hash
    _write_report(args.report, historical, rollout)
    print(json.dumps({
        "stage": "autonomous_rollout",
        "output": str(args.rollout_output),
        "report": str(args.report),
        "result_sha256": rollout_hash,
        "models_run": rollout["models_run"],
        "trace_count": rollout["trace_count"],
        "runtime_seconds": rollout["runtime_seconds"],
    }, sort_keys=True), flush=True)
    return rollout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("audit", "historical", "rollout"), required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--risk-cache", type=Path, default=DEFAULT_RISK_CACHE)
    parser.add_argument("--historical-output", type=Path, default=DEFAULT_HISTORICAL)
    parser.add_argument("--rollout-output", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--game-limit", type=int, default=None)
    args = parser.parse_args(argv)
    if args.stage == "audit":
        if args.game_limit is None:
            parser.error("--stage audit requires --game-limit")
        run_audit(args)
    elif args.stage == "historical":
        if args.game_limit is not None:
            parser.error("--stage historical requires the full frozen population")
        run_historical(args)
    else:
        if args.game_limit is not None:
            parser.error("--stage rollout uses the full frozen population")
        run_rollout(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


