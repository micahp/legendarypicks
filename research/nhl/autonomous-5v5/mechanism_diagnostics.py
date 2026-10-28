#!/usr/bin/env python3
"""Reproduce grouped A0/A1 diagnostics and source-linked top-error traces."""

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
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import data
from kernel import (FAMILIES, PERIOD_SECONDS, RenewalModel, common_random_seed,
                    crps, sample_trace, trace_counts, update_context, validate_trace)

EXPECTED_CACHE = "9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2"
EXPECTED_RESULT = "6116b755505fbfeca9dabd512b3a8db328202f78d4cf0345ed8c457763da3326"
RESULT_PATH = HERE / "results/nhl-autonomous-5v5-arrival-development-2026-10-27.json"
DEFAULT_OUT = HERE / "results/nhl-autonomous-mechanism-diagnostics-2026-10-27.json"
N_DRAWS = 10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ctx_json(ctx: Any) -> dict[str, Any]:
    return {"previous_family": ctx.previous_family,
            "possession_known": ctx.possession_known,
            "score_diff": ctx.score_diff,
            "score_state": ctx.score_state,
            "clock_bucket": ctx.clock_bucket}


def mark_json(mark: Any) -> list[dict[str, str]]:
    return [{"family": token.family, "owner": token.owner} for token in mark]


def _component_losses(model: RenewalModel, row: Any) -> tuple[float, dict[str, float], float]:
    key = model.selected_key(row.context)
    size_loss = -math.log(model._size_probability(key, len(row.mark)))
    family_loss: collections.Counter[str] = collections.Counter()
    owner_loss: collections.Counter[str] = collections.Counter()
    prefix: list[str] = []
    for position, token in enumerate(row.mark):
        prefix_key = tuple(prefix)
        families = model._family_counts(key, position, prefix_key)
        p_family = model._probability(families[token.family], sum(families.values()), len(FAMILIES))
        owners = model._owner_counts(key, position, prefix_key, token.family)
        domain = data.OWNER_DOMAINS[token.family]
        p_owner = model._probability(owners[token.owner], sum(owners.values()), len(domain))
        family_loss[token.family] += -math.log(p_family)
        owner_loss[token.family] += -math.log(p_owner)
        prefix.append(token.family)
    return size_loss, dict(family_loss), sum(owner_loss.values())


def _predicted_first_family(model: RenewalModel, ctx: Any) -> dict[str, float]:
    key = model.selected_key(ctx)
    counts = model._family_counts(key, 0, ())
    support = sum(counts.values())
    return {family: model._probability(counts[family], support, len(FAMILIES))
            for family in FAMILIES}


def mark_probability_factors(model: RenewalModel, ctx: Any, mark: Any) -> dict[str, Any]:
    key = model.selected_key(ctx)
    stats = model.stats[key]
    size_support = sum(stats.sizes.values())
    factors = {"selected_context_key": list(key),
               "training_support": stats.n,
               "bundle_size_probability": model._size_probability(key, len(mark)),
               "tokens": []}
    prefix: list[str] = []
    for position, token in enumerate(mark):
        prefix_key = tuple(prefix)
        family_counts = model._family_counts(key, position, prefix_key)
        family_support = sum(family_counts.values())
        p_family = model._probability(family_counts[token.family], family_support, len(FAMILIES))
        owner_counts = model._owner_counts(key, position, prefix_key, token.family)
        owner_support = sum(owner_counts.values())
        domain = data.OWNER_DOMAINS[token.family]
        p_owner = model._probability(owner_counts[token.owner], owner_support, len(domain))
        factors["tokens"].append({"position": position, "prefix": list(prefix),
                                  "family": token.family, "family_probability": p_family,
                                  "family_count": family_counts[token.family],
                                  "family_support": family_support, "owner": token.owner,
                                  "owner_probability": p_owner,
                                  "owner_count": owner_counts[token.owner],
                                  "owner_support": owner_support})
        prefix.append(token.family)
    factors["bundle_size_support"] = size_support
    return factors


def score_decomposition(models: dict[str, RenewalModel], dev_periods: list[Any],
                        max_bundle_size: int) -> dict[str, Any]:
    metrics: dict[str, dict[str, float]] = {}
    grouped: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    first_family: dict[str, dict[str, dict[str, Any]]] = {}
    all_exposure = 0
    all_counts = 0

    def add(group: str, label: str, candidate: str, loss: float, exposure: int = 0) -> None:
        target = grouped.setdefault(group, {}).setdefault(label, {}).setdefault(
            candidate, {"loss_nats": 0.0, "exposure_seconds": 0.0, "observations": 0.0})
        target["loss_nats"] += loss
        target["exposure_seconds"] += exposure
        target["observations"] += 1

    for period in dev_periods:
        for row in period.transitions:
            if len(row.mark) > max_bundle_size:
                continue
            all_exposure += row.gap_seconds
            all_counts += 1
            gap_bin = next(label for upper, label in (
                (5, "1-5s"), (10, "6-10s"), (20, "11-20s"), (30, "21-30s"),
                (60, "31-60s"), (120, "61-120s"), (300, "121-300s"),
                (600, "301-600s"), (PERIOD_SECONDS, "601-1200s"))
                if row.gap_seconds <= upper)
            for candidate, model in models.items():
                gap_loss = -model.gap_log_probability(row.context, row.gap_seconds)
                size_loss, families, owners_total = _component_losses(model, row)
                mark_loss = -model.mark_log_probability(row.context, row.mark)
                if abs((size_loss + sum(families.values()) + owners_total) - mark_loss) > 1e-8:
                    raise AssertionError("mark likelihood component sum does not reconcile")
                metric = metrics.setdefault(candidate, {
                    "gap_nll_nats": 0.0, "bundle_size_nll_nats": 0.0,
                    "family_nll_nats": 0.0, "owner_nll_nats": 0.0,
                    "mark_nll_nats": 0.0, "total_nll_nats": 0.0})
                owner_loss = max(0.0, mark_loss - size_loss - sum(families.values()))
                metric["gap_nll_nats"] += gap_loss
                metric["bundle_size_nll_nats"] += size_loss
                metric["family_nll_nats"] += sum(families.values())
                metric["owner_nll_nats"] += owner_loss
                metric["mark_nll_nats"] += mark_loss
                metric["total_nll_nats"] += gap_loss + mark_loss
                add("gap_by_interval", gap_bin, candidate, gap_loss, row.gap_seconds)
                add("gap_by_previous_family", row.context.previous_family,
                    candidate, gap_loss, row.gap_seconds)
                add("gap_by_score_state", row.context.score_state,
                    candidate, gap_loss, row.gap_seconds)
                add("gap_by_clock_bucket", str(row.context.clock_bucket),
                    candidate, gap_loss, row.gap_seconds)
                add("bundle_size_component", str(len(row.mark)), candidate, size_loss)
                for family, loss in families.items():
                    add("mark_family_component", family, candidate, loss)
                add("mark_owner_component", "all", candidate, owner_loss)

                counts = first_family.setdefault(candidate, {}).setdefault(
                    row.context.previous_family,
                    {"observed": collections.Counter(), "predicted": collections.Counter(),
                     "transitions": 0})
                counts["observed"][row.mark[0].family] += 1
                for family, probability in _predicted_first_family(model, row.context).items():
                    counts["predicted"][family] += probability
                counts["transitions"] += 1

    for candidate, row in metrics.items():
        row["nll_nats_per_5v5_minute"] = row["total_nll_nats"] / (all_exposure / 60.0)
        row["eligible_transitions"] = all_counts

    grouped_out: dict[str, Any] = {}
    for group, labels in grouped.items():
        grouped_out[group] = {}
        for label, candidates in labels.items():
            grouped_out[group][label] = {}
            for candidate, values in candidates.items():
                exposure = values["exposure_seconds"]
                values["nll_nats_per_minute"] = (
                    values["loss_nats"] / (exposure / 60.0) if exposure else None)
                grouped_out[group][label][candidate] = values

    transitions_out: dict[str, Any] = {}
    for candidate, previous_rows in first_family.items():
        transitions_out[candidate] = {}
        for previous, values in previous_rows.items():
            n = values["transitions"]
            transitions_out[candidate][previous] = {
                "transitions": n,
                "observed_next_bundle_first_family_rate": {
                    family: values["observed"].get(family, 0) / n for family in FAMILIES},
                "mean_model_probability_next_bundle_first_family": {
                    family: values["predicted"].get(family, 0.0) / n for family in FAMILIES},
            }

    return {"exposure_seconds": all_exposure,
            "eligible_transition_gaps": all_counts,
            "nll_components": metrics,
            "grouped_nll": grouped_out,
            "next_bundle_first_family_by_previous_family": transitions_out}


def observed_target(period: Any, max_bundle_size: int) -> tuple[float, int, list[Any]] | None:
    rows = [row for row in period.transitions if len(row.mark) <= max_bundle_size]
    exposure = sum(row.gap_seconds for row in rows)
    if not exposure:
        return None
    return len(rows) * PERIOD_SECONDS / exposure, exposure, rows


class LoggedRandom(random.Random):
    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.uniforms: list[float] = []

    def random(self) -> float:
        value = super().random()
        self.uniforms.append(value)
        return value


def traced_sample(model: RenewalModel, seed: int) -> dict[str, Any]:
    rng = LoggedRandom(seed)
    ctx = data.Context("faceoff", True, 0, 0)
    now = 0
    steps: list[dict[str, Any]] = []
    trace: list[tuple[int, tuple[Any, ...]]] = []
    terminal = None
    while now < PERIOD_SECONDS:
        before = ctx
        key = model.selected_key(before)
        support = model.stats[key].n
        start = len(rng.uniforms)
        gap = model.sample_gap(before, rng)
        gap_u = rng.uniforms[start]
        arrival = now + gap
        if arrival >= PERIOD_SECONDS:
            terminal = {"gap_seconds": gap, "gap_probability": model.gap_probability(before, gap),
                        "gap_uniform": gap_u, "selected_context_key": list(key),
                        "context_support": support}
            break
        mark = model.sample_mark(before, rng)
        after = update_context(before, mark, arrival)
        steps.append({"relative_second": arrival, "gap_seconds": gap,
                      "context_before": ctx_json(before), "context_after": ctx_json(after),
                      "selected_context_key": list(key), "context_support": support,
                      "gap_probability": model.gap_probability(before, gap),
                      "gap_uniform": gap_u, "mark": mark_json(mark),
                      "mark_log_probability": model.mark_log_probability(before, mark),
                      "mark_probability_factors": mark_probability_factors(model, before, mark),
                      "mark_uniforms": rng.uniforms[start + 1:]})
        trace.append((arrival, mark))
        ctx, now = after, arrival
    validate_trace(trace, horizon=PERIOD_SECONDS)
    if sample_trace(model, seed) != trace:
        raise AssertionError("trace logger changed the frozen sampler output")
    return {"steps": steps, "terminal_gap": terminal, "parity": True}


def _actual_period(data_root: Path, behavior: Any, pbp_manifest: dict[str, Any],
                   shift_manifest: dict[str, Any], game_id: str, period_no: int,
                   season: int, max_bundle: int, expected: list[Any]) -> list[dict[str, Any]]:
    pbp, shifts = behavior._load_game_source(data_root, pbp_manifest, shift_manifest, game_id)
    local = {"event_records": data._extract_event_records(pbp, shifts, game_id, behavior)}
    ambiguous_events = {
        int(row["time"]) for row in local["event_records"]
        if row.get("period_type") == "REG" and int(row.get("period") or 0) == period_no
        and row.get("type") not in data.BOUNDARY_TYPES
        and not (row.get("event_state_attribution") or {}).get("eligible_for_conditional_fit")
    }
    bundles, _ = data._make_bundles(local, pbp, game_id, season, period_no, ambiguous_events)
    home = str((pbp.get("homeTeam") or {}).get("id") or "")
    away = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home: "home", away: "away"}
    roster = {str(p.get("playerId")): (str(p.get("teamId") or ""),
                                        str(p.get("positionCode") or "?"))
              for p in pbp.get("rosterSpots") or [] if p.get("playerId") is not None}
    states, _, _ = data._state_by_second(shifts, game_id, period_no, team_sides, roster)
    pairs = []
    for previous, current in zip(bundles, bundles[1:]):
        if not previous.eligible or not current.eligible or len(current.mark) > max_bundle:
            continue
        between = states[previous.second:current.second]
        if any(state != "5v5" for state in between):
            continue
        pairs.append((previous, current))
    if len(pairs) != len(expected):
        raise ValueError(f"{game_id} P{period_no}: raw/cache transition count mismatch")
    output = []
    for i, ((previous, current), cached) in enumerate(zip(pairs, expected)):
        gap = current.second - previous.second
        if gap != cached.gap_seconds or previous.context_after != cached.context or current.mark != cached.mark:
            raise ValueError(f"{game_id} P{period_no} transition {i}: source/cache mismatch")
        source_events = [{"event_id": row.get("event_id"), "sort_order": row.get("sort_order"),
                          "type": row.get("type"), "owner": row.get("side")}
                         for row in local["event_records"]
                         if row.get("period_type") == "REG"
                         and int(row.get("period") or 0) == period_no
                         and int(row.get("time") or -1) == current.second]
        output.append({"sequence_index": i, "clock_seconds_elapsed": current.second,
                       "gap_seconds": gap, "context": ctx_json(cached.context),
                       "mark": mark_json(cached.mark), "source_events": source_events})
    for i, item in enumerate(output):
        if i + 1 < len(expected):
            item["context_after"] = ctx_json(expected[i + 1].context)
        else:
            item["context_after"] = ctx_json(update_context(
                expected[i].context, expected[i].mark, item["clock_seconds_elapsed"]))
    return output


def first_divergence(observed: list[dict[str, Any]], generated: list[dict[str, Any]],
                     cached: list[Any], model: RenewalModel) -> dict[str, Any] | None:
    for i in range(max(len(observed), len(generated))):
        obs = observed[i] if i < len(observed) else None
        sim = generated[i] if i < len(generated) else None
        if obs is not None and sim is not None and obs["gap_seconds"] == sim["gap_seconds"] and obs["mark"] == sim["mark"]:
            continue
        result = {"sequence_index": i,
                  "kind": "generated_missing" if sim is None else "observed_missing" if obs is None else
                          "gap_and_mark" if obs["gap_seconds"] != sim["gap_seconds"] and obs["mark"] != sim["mark"] else
                          "gap" if obs["gap_seconds"] != sim["gap_seconds"] else "mark",
                  "observed": obs, "generated": sim,
                  "alignment_note": "Index comparison only; after this first divergence, states differ. "
                                    "The simulation starts from its fixed synthetic Context(faceoff, known, 0-0, bucket 0)."}
        if obs is not None:
            row = cached[i]
            key = model.selected_key(row.context)
            result["observed_probability"] = {
                "context": ctx_json(row.context), "selected_key": list(key),
                "training_support": model.stats[key].n,
                "gap_probability": model.gap_probability(row.context, row.gap_seconds),
                "mark_log_probability": model.mark_log_probability(row.context, row.mark),
                "mark_probability_factors": mark_probability_factors(model, row.context, row.mark)}
        if sim is not None:
            result["generated_probability"] = {
                "context": sim["context_before"], "selected_key": sim["selected_context_key"],
                "training_support": sim["context_support"],
                "gap_probability": sim["gap_probability"], "gap_uniform": sim["gap_uniform"],
                "mark_log_probability": sim["mark_log_probability"],
                "mark_probability_factors": sim["mark_probability_factors"],
                "mark_uniforms": sim["mark_uniforms"]}
        return result
    return None


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    cache_hash = sha256(args.cache)
    if cache_hash != EXPECTED_CACHE:
        raise ValueError(f"cache hash mismatch: {cache_hash}")
    result_hash = sha256(RESULT_PATH)
    if result_hash != EXPECTED_RESULT:
        raise ValueError(f"frozen result hash mismatch: {result_hash}")
    payload = data.load_cache(args.cache)
    source_hashes = payload["source_hashes"]
    all_periods = data.period_records(payload)
    train_periods = [p for p in all_periods if p.season in (2019, 2020)]
    dev_periods = [p for p in all_periods if p.season == 2021]
    training = [t for p in train_periods for t in p.transitions]
    if len(training) != 329667 or len(dev_periods) != 3876:
        raise ValueError("frozen population changed")
    models = {name: RenewalModel(name) for name in ("A0", "A1")}
    for model in models.values():
        model.fit(training)
    del payload, all_periods, train_periods, training
    gc.collect()

    max_bundle = models["A0"].max_bundle_size
    if models["A1"].max_bundle_size != max_bundle:
        raise ValueError("A0/A1 training marks differ")
    decomposition = score_decomposition(models, dev_periods, max_bundle)
    frozen = json.loads(RESULT_PATH.read_text())
    for name in ("A0", "A1"):
        expected = frozen["development_nll"][name]
        actual = decomposition["nll_components"][name]
        for key in ("gap_nll_nats", "mark_nll_nats", "total_nll_nats"):
            if abs(actual[key] - expected[key]) > 1e-5:
                raise AssertionError(f"{name} {key} differs from frozen result")

    ranked = []
    a1 = models["A1"]
    for period in dev_periods:
        target = observed_target(period, max_bundle)
        if target is None:
            continue
        observed, exposure, rows = target
        counts, seeds = [], []
        for replicate in range(N_DRAWS):
            seed = common_random_seed(period.game_id, period.period, replicate)
            seeds.append(seed)
            counts.append(len(sample_trace(a1, seed)))
        score = crps(counts, observed)
        ranked.append({"game_id": period.game_id, "period": period.period,
                       "observed_bundle_count_20m_equivalent": observed,
                       "observed_bundle_count": len(rows), "exposure_seconds": exposure,
                       "a1_trace_counts": counts, "a1_crps": score,
                       "worst_absolute_error_replicate": max(
                           range(N_DRAWS), key=lambda i: abs(counts[i] - observed)),
                       "replicate_seeds": seeds})
        if len(ranked) and len(ranked) % 500 == 0:
            print(f"ranked {len(ranked)} periods", flush=True)
    if len(ranked) != 3843:
        raise ValueError(f"scored period count changed: {len(ranked)}")
    mean_crps = sum(row["a1_crps"] for row in ranked) / len(ranked)
    frozen_crps = frozen["simulation_comparison"]["metrics"]["bundle_count"]["candidates"]["A1"]["crps"]
    if abs(mean_crps - frozen_crps) > 1e-9:
        raise AssertionError(f"A1 CRPS does not reproduce frozen result: {mean_crps} != {frozen_crps}")
    ranked.sort(key=lambda row: row["a1_crps"], reverse=True)
    top = ranked[:10]

    behavior = data._load_behavior_module()
    pbp_manifest, shift_manifest = data._verified_manifests(args.data_root, behavior)
    dev_lookup = {(p.game_id, p.period): p for p in dev_periods}
    cases = []
    for rank, item in enumerate(top, 1):
        period = dev_lookup[(item["game_id"], item["period"])]
        _, _, cached_rows = observed_target(period, max_bundle)
        replicate = item["worst_absolute_error_replicate"]
        seed = item["replicate_seeds"][replicate]
        generated = traced_sample(a1, seed)
        observed = _actual_period(args.data_root, behavior, pbp_manifest, shift_manifest,
                                  item["game_id"], item["period"], 2021, max_bundle, cached_rows)
        div = first_divergence(observed, generated["steps"], cached_rows, a1)
        a0_trace = sample_trace(models["A0"], seed)
        cases.append({**{k: item[k] for k in ("game_id", "period", "observed_bundle_count",
                                               "observed_bundle_count_20m_equivalent", "exposure_seconds",
                                               "a1_crps", "a1_trace_counts")},
                      "rank": rank, "replicate": replicate, "seed": seed,
                      "a1_generated_bundles": len(generated["steps"]),
                      "a0_generated_bundles_same_seed": len(a0_trace),
                      "a1_sampler_parity": generated["parity"],
                      "first_divergence": div,
                      "observed_first_20_transitions": observed[:20],
                      "a1_trace_steps": generated["steps"],
                      "a1_terminal_gap": generated["terminal_gap"]})

    return {"schema": "nhl-autonomous-mechanism-diagnostics-v1",
            "scope": "read-only diagnostic; no parameter changes or candidate selection",
            "arrival_model": "categorical probability mass function over integer-second gaps 1..1200; not a continuous-time hazard",
            "sequence_cache_sha256": cache_hash,
            "frozen_result_sha256": result_hash,
            "source_hashes": source_hashes,
            "scoring_code_sha256": sha256(HERE / "kernel.py"),
            "extractor_code_sha256": sha256(HERE / "data.py"),
            "diagnostic_code_sha256": sha256(Path(__file__).resolve()),
            "training_transition_gaps": 329667,
            "development_periods": 3843,
            "a1_bundle_crps_mean_reproduced": mean_crps,
            "nll_and_crps_reconciled_to_frozen_result": True,
            "nll_decomposition": decomposition,
            "top_a1_bundle_crps_periods": top,
            "top_error_traces": cases,
            "elapsed_seconds": time.perf_counter() - started}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=data.DEFAULT_CACHE)
    parser.add_argument("--data-root", type=Path, default=data.DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": sha256(args.output),
                      "elapsed_seconds": result["elapsed_seconds"],
                      "periods": result["development_periods"],
                      "top_traces": len(result["top_error_traces"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
