#!/usr/bin/env python3
"""Historical nearest-neighbor ranking for archived SLC game seeds.

This module is deliberately independent of the simulator. Inputs are immutable, normalized
historical game rows and archived seed rows; replay is a separate validation stage.
"""
from __future__ import annotations

import csv
import json
import math
import multiprocessing
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    import numpy as _np
except ImportError:  # NumPy is an optional acceleration; the stdlib path stays available.
    _np = None

NUMERICAL_BACKEND = {"name": "numpy", "version": _np.__version__} if _np is not None else {
    "name": "python-stdlib", "version": None,
}


DEFAULT_WEIGHTS = {
    "drives": 0.30,
    "decisions": 0.25,
    "workloads": 0.25,
    "game": 0.20,
}
FAILED_STATUSES = {"blocked", "error", "failed", "incomplete", "invalid"}
_WORKER_CONTEXT: tuple | None = None


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def robust_scales(rows: Iterable[dict], group: str) -> dict[str, tuple[float, float]]:
    """Return median and robust scale (IQR/1.349, then MAD, then 1) per feature."""
    gathered: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        values = row.get("features", {}).get(group, {})
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            number = _finite(value)
            if number is not None:
                gathered[name].append(number)
    scales = {}
    for name, values in gathered.items():
        ordered = sorted(values)
        center = _median(ordered)
        q1 = _quantile(ordered, 0.25)
        q3 = _quantile(ordered, 0.75)
        scale = (q3 - q1) / 1.349
        if scale <= 1e-12:
            scale = 1.4826 * _median([abs(value - center) for value in ordered])
        if scale <= 1e-12:
            scale = 1.0
        scales[name] = (center, scale)
    return scales


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _distance(left: dict, right: dict, scales: dict[str, tuple[float, float]], group: str) -> float | None:
    lvalues = left.get("features", {}).get(group, {})
    rvalues = right.get("features", {}).get(group, {})
    terms = []
    for name, (center, scale) in scales.items():
        a = _finite(lvalues.get(name)) if isinstance(lvalues, dict) else None
        b = _finite(rvalues.get(name)) if isinstance(rvalues, dict) else None
        if a is None or b is None:
            continue
        # Clipping keeps a single heavy-tailed football outcome from dominating a group.
        z = max(-8.0, min(8.0, (a - b) / scale))
        terms.append(z * z)
    return math.sqrt(sum(terms) / len(terms)) if terms else None


def historical_neighbors(candidate: dict, historical: Iterable[dict], group: str,
                         *, season_exclude: int | None = None, k: int = 20) -> list[tuple[dict, float]]:
    """Find deterministic nearest historical games, optionally holding out a full season."""
    reference = [row for row in historical
                 if (season_exclude is None or row.get("season") != season_exclude)
                 and row.get("game_id") != candidate.get("game_id")]
    scales = robust_scales(reference, group)
    distances = []
    for row in reference:
        distance = _distance(candidate, row, scales, group)
        if distance is not None:
            distances.append((row, distance))
    return sorted(distances, key=lambda item: (item[1], str(item[0].get("game_id", ""))))[:max(1, k)]


def _mean_neighbor_distance(candidate: dict, reference: list[dict], group: str, k: int) -> float | None:
    if not reference:
        return None
    neighbors = historical_neighbors(candidate, reference, group, k=k)
    if not neighbors:
        return None
    return sum(distance for _row, distance in neighbors) / len(neighbors)


def contextual_distance(candidate: dict, historical: list[dict], group: str,
                        scales: dict[str, tuple[float, float]], k: int = 20) -> float | None:
    """Blend league, same-team and exact-pair neighbors with small-cohort shrinkage."""
    all_rows = [row for row in historical if row.get("game_id") != candidate.get("game_id")]
    distances = []
    for row in all_rows:
        value = _distance(candidate, row, scales, group)
        if value is not None:
            distances.append((row, value))
    distances.sort(key=lambda item: (item[1], str(item[0].get("game_id", ""))))
    base_values = [distance for _row, distance in distances[:max(1, k)]]
    if not base_values:
        return None
    components = [(sum(base_values) / len(base_values), 1.0)]
    teams = set(candidate.get("teams") or [])
    if teams:
        same_team = [(row, distance) for row, distance in distances
                     if teams.intersection(row.get("teams") or [])]
        if same_team:
            count = len(same_team)
            weight = min(0.5, count / (count + 40.0))
            team_values = [distance for _row, distance in same_team[:max(1, k)]]
            components.append((sum(team_values) / len(team_values), weight))
        exact_pair = [(row, distance) for row, distance in distances
                      if set(row.get("teams") or []) == teams]
        if len(exact_pair) >= 3:
            count = len(exact_pair)
            weight = min(0.25, count / (count + 20.0))
            pair_values = [distance for _row, distance in exact_pair[:max(1, k)]]
            components.append((sum(pair_values) / len(pair_values), weight))
    return sum(value * weight for value, weight in components) / sum(weight for _value, weight in components)


def hard_gate(row: dict) -> dict[str, Any]:
    """Separate statistical scoreability from full-game renderability."""
    reasons = []
    status = str(row.get("status") or row.get("outcome_status") or "success").lower()
    if status in FAILED_STATUSES:
        reasons.append(f"run_status_{status}")
    if row.get("valid_full_game") is False:
        reasons.append("invalid_full_game")
    reconciliation = row.get("reconciliation")
    if isinstance(reconciliation, dict) and reconciliation.get("matches") is False:
        reasons.append("boxscore_reconciliation_failed")
    if row.get("essential_participants_available") is False:
        reasons.append("essential_participant_unavailable")
    if row.get("unsupported_sequence"):
        reasons.append("unsupported_sequence")
    scoreable = not any(reason.startswith(("run_status_", "invalid_full_game", "boxscore_reconciliation_failed",
                                           "essential_participant_unavailable", "unsupported_sequence"))
                        for reason in reasons)
    render_reasons = list(reasons)
    if row.get("score_only_overtime"):
        render_reasons.append("score_only_overtime")
    if row.get("complete_sequence") is False:
        render_reasons.append("incomplete_play_sequence")
    if row.get("contract_compatible") is False:
        render_reasons.append("gridiron_contract_incompatible")
    return {
        "scoreable": scoreable,
        "renderable": scoreable and not render_reasons,
        "reasons": sorted(set(reasons)),
        "render_reasons": sorted(set(render_reasons)),
    }


def _cross_validated_distances(historical: list[dict], group: str, k: int) -> tuple[list[float], dict[str, dict[str, float]]]:
    seasons = sorted({row.get("season") for row in historical if row.get("season") is not None})
    distances = []
    by_season: dict[str, list[float]] = defaultdict(list)
    for season in seasons:
        train = [row for row in historical if row.get("season") != season]
        test = [row for row in historical if row.get("season") == season]
        if len(train) < 2:
            continue
        scales = robust_scales(train, group)
        for row in test:
            distance = contextual_distance(row, train, group, scales, k)
            if distance is not None:
                distances.append(distance)
                by_season[str(season)].append(distance)
    summary = {
        season: {
            "n": len(values),
            "median_distance": _median(values),
            "p90_distance": _quantile(sorted(values), 0.90),
        }
        for season, values in sorted(by_season.items())
    }
    return distances, summary


def _cross_validated_worker(args: tuple[list[dict], str, int]) -> tuple[list[float], dict[str, dict[str, float]]]:
    return _cross_validated_distances(*args)


def _typicality(distance: float | None, calibration: list[float]) -> float:
    if distance is None or not calibration:
        return 0.0
    # Smaller nearest-neighbor distance is more typical. Mid-rank ties avoid arbitrary extremes.
    below = sum(value < distance for value in calibration)
    equal = sum(value == distance for value in calibration)
    percentile = (below + 0.5 * equal) / len(calibration)
    return max(0.0, min(100.0, (1.0 - percentile) * 100.0))


def fit_reference_model(historical: list[dict], *, weights: dict[str, float] | None = None,
                        k: int = 20, workers: int = 1) -> dict:
    weights = dict(weights or DEFAULT_WEIGHTS)
    calibration = {}
    validation = {}
    scales = {}
    groups = list(weights)
    workers = max(1, min(int(workers), len(groups), os.cpu_count() or 1))
    if workers > 1:
        context = multiprocessing.get_context("fork")
        args = [(historical, group, k) for group in groups]
        with context.Pool(processes=workers) as pool:
            calibrated = pool.map(_cross_validated_worker, args)
        for group, (distances, validation_by_season) in zip(groups, calibrated):
            calibration[group] = distances
            validation[group] = validation_by_season
            scales[group] = robust_scales(historical, group)
    else:
        for group in groups:
            calibration[group], validation[group] = _cross_validated_distances(historical, group, k)
            scales[group] = robust_scales(historical, group)
    return {"weights": weights, "k": k, "calibration": calibration,
            "validation": validation, "scales": scales}


def _rank_one(source: dict, historical: list[dict], weights: dict[str, float], k: int,
              calibration: dict, scales: dict) -> dict:
    row = dict(source)
    component_scores = {}
    distances = {}
    contributions = {}
    for group, weight in weights.items():
        distance = contextual_distance(row, historical, group, scales[group], k)
        score = _typicality(distance, calibration[group])
        distances[group] = distance
        component_scores[group] = round(score, 6)
        contributions[group] = round(score * weight, 6)
    gate = hard_gate(row)
    row.update({
        "realism_score": round(sum(contributions.values()), 6),
        "component_scores": component_scores,
        "score_contributions": contributions,
        "group_distances": distances,
        "gate": gate,
        "replay_status": row.get("replay_status", "not_tested"),
    })
    return row


def _init_rank_worker(historical: list[dict], weights: dict[str, float], k: int,
                      calibration: dict, scales: dict) -> None:
    global _WORKER_CONTEXT
    _WORKER_CONTEXT = (historical, weights, k, calibration, scales)


def _rank_worker(source: dict) -> dict:
    if _WORKER_CONTEXT is None:
        raise RuntimeError("ranking worker was not initialized")
    historical, weights, k, calibration, scales = _WORKER_CONTEXT
    return _rank_one(source, historical, weights, k, calibration, scales)


def _vectorized_context_distances(candidates: list[dict], historical: list[dict], group: str,
                                 scales: dict[str, tuple[float, float]], k: int) -> list[float | None]:
    """Compute the same clipped robust NN distances with chunked NumPy operations."""
    if _np is None:
        raise RuntimeError("NumPy is unavailable")
    names = list(scales)
    if not names:
        return [None] * len(candidates)
    centers = _np.asarray([scales[name][0] for name in names], dtype=_np.float64)
    divisors = _np.asarray([scales[name][1] for name in names], dtype=_np.float64)

    def matrix(rows: list[dict]):
        values = _np.full((len(rows), len(names)), _np.nan, dtype=_np.float64)
        for row_index, row in enumerate(rows):
            source = row.get("features", {}).get(group, {})
            for feature_index, name in enumerate(names):
                number = _finite(source.get(name)) if isinstance(source, dict) else None
                if number is not None:
                    values[row_index, feature_index] = number
        return values

    left = matrix(candidates)
    right = matrix(historical)
    right_valid = _np.isfinite(right)
    distances = _np.full((len(candidates), len(historical)), _np.nan, dtype=_np.float64)
    chunk_size = 64
    for start in range(0, len(candidates), chunk_size):
        stop = min(start + chunk_size, len(candidates))
        current = left[start:stop]
        valid = _np.isfinite(current)[:, None, :] & right_valid[None, :, :]
        delta = (current[:, None, :] - right[None, :, :]) / divisors
        _np.nan_to_num(delta, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        _np.clip(delta, -8.0, 8.0, out=delta)
        delta[~valid] = 0.0
        counts = valid.sum(axis=2)
        squared = _np.square(delta).sum(axis=2)
        block = _np.full(counts.shape, _np.nan, dtype=_np.float64)
        _np.divide(squared, counts, out=block, where=counts > 0)
        _np.sqrt(block, out=block)
        distances[start:stop] = block

    historical_teams = [set(row.get("teams") or []) for row in historical]
    candidate_groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(candidates):
        candidate_groups[tuple(sorted(set(row.get("teams") or [])))].append(index)

    def nearest_mean(values):
        valid = _np.isfinite(values)
        counts = valid.sum(axis=1)
        take = min(max(1, k), values.shape[1])
        safe = _np.where(valid, values, _np.inf)
        nearest = _np.partition(safe, take - 1, axis=1)[:, :take]
        sums = _np.where(_np.isfinite(nearest), nearest, 0.0).sum(axis=1)
        denominators = _np.minimum(counts, k)
        means = _np.full(len(values), _np.nan, dtype=_np.float64)
        _np.divide(sums, denominators, out=means, where=denominators > 0)
        return means

    result = _np.full(len(candidates), _np.nan, dtype=_np.float64)
    for team_key, indices in candidate_groups.items():
        team_set = set(team_key)
        values = distances[indices]
        base = nearest_mean(values)
        numerator = _np.where(_np.isfinite(base), base, 0.0)
        denominator = _np.isfinite(base).astype(_np.float64)
        same_team = _np.asarray([bool(team_set.intersection(teams)) for teams in historical_teams])
        if bool(same_team.any()):
            same_counts = _np.isfinite(values[:, same_team]).sum(axis=1)
            same_weights = _np.minimum(0.5, same_counts / (same_counts + 40.0))
            same_mean = nearest_mean(values[:, same_team])
            usable = _np.isfinite(same_mean) & (same_counts > 0)
            numerator += _np.where(usable, same_mean * same_weights, 0.0)
            denominator += _np.where(usable, same_weights, 0.0)
        exact_pair = _np.asarray([teams == team_set for teams in historical_teams])
        if bool(exact_pair.any()):
            exact_counts = _np.isfinite(values[:, exact_pair]).sum(axis=1)
            exact_weights = _np.where(exact_counts >= 3,
                                      _np.minimum(0.25, exact_counts / (exact_counts + 20.0)), 0.0)
            pair_mean = nearest_mean(values[:, exact_pair])
            usable = _np.isfinite(pair_mean) & (exact_counts >= 3)
            numerator += _np.where(usable, pair_mean * exact_weights, 0.0)
            denominator += _np.where(usable, exact_weights, 0.0)
        computed = _np.full(len(indices), _np.nan, dtype=_np.float64)
        _np.divide(numerator, denominator, out=computed, where=denominator > 0)
        result[indices] = computed
    return [None if not _np.isfinite(value) else float(value) for value in result]


def _rank_candidates_vectorized(candidates: list[dict], historical: list[dict], weights: dict[str, float],
                                k: int, calibration: dict, scales: dict) -> list[dict]:
    group_distances = {
        group: _vectorized_context_distances(candidates, historical, group, scales[group], k)
        for group in weights
    }
    group_scores = {}
    for group in weights:
        values = _np.asarray([_np.inf if value is None else value for value in group_distances[group]])
        reference = _np.sort(_np.asarray(calibration[group], dtype=_np.float64))
        if len(reference):
            below = _np.searchsorted(reference, values, side="left")
            above = _np.searchsorted(reference, values, side="right")
            percentile = (below + 0.5 * (above - below)) / len(reference)
            scores = _np.clip((1.0 - percentile) * 100.0, 0.0, 100.0)
        else:
            scores = _np.zeros(len(candidates), dtype=_np.float64)
        group_scores[group] = scores

    ranked = []
    for index, source in enumerate(candidates):
        row = dict(source)
        component_scores = {group: round(float(group_scores[group][index]), 6) for group in weights}
        contributions = {group: round(component_scores[group] * weights[group], 6) for group in weights}
        distances = {group: group_distances[group][index] for group in weights}
        row.update({
            "realism_score": round(sum(contributions.values()), 6),
            "component_scores": component_scores,
            "score_contributions": contributions,
            "group_distances": distances,
            "gate": hard_gate(row),
            "replay_status": row.get("replay_status", "not_tested"),
        })
        ranked.append(row)
    return sorted(ranked, key=lambda row: (-row["realism_score"], int(row.get("seed", 0))))


def rank_candidates(candidates: Iterable[dict], historical: list[dict], *,
                    weights: dict[str, float] | None = None, k: int = 20,
                    reference_model: dict | None = None, workers: int = 1,
                    use_numpy: bool | None = None) -> list[dict]:
    """Score all candidates against season-held-out historical NN distances."""
    weights = dict(weights or DEFAULT_WEIGHTS)
    if set(weights) != set(DEFAULT_WEIGHTS) or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("weights must define drives, decisions, workloads, game and sum to one")
    model = reference_model or fit_reference_model(historical, weights=weights, k=k)
    if model.get("weights") != weights:
        raise ValueError("reference model weights do not match ranking weights")
    calibration, scales = model["calibration"], model["scales"]

    candidates = list(candidates)
    if use_numpy is not False and _np is not None:
        return _rank_candidates_vectorized(candidates, historical, weights, k, calibration, scales)
    workers = max(1, min(int(workers), len(candidates) or 1, os.cpu_count() or 1))
    if workers > 1 and len(candidates) >= workers * 4:
        # Fork shares the immutable historical reference efficiently on Linux; each worker
        # scores independent seeds and ordered map results preserve deterministic tie breaks.
        context = multiprocessing.get_context("fork")
        chunksize = max(1, len(candidates) // (workers * 8))
        with context.Pool(
            processes=workers,
            initializer=_init_rank_worker,
            initargs=(historical, weights, k, calibration, scales),
        ) as pool:
            ranked = pool.map(_rank_worker, candidates, chunksize=chunksize)
    else:
        ranked = [_rank_one(source, historical, weights, k, calibration, scales)
                  for source in candidates]
    return sorted(ranked, key=lambda row: (-row["realism_score"], int(row.get("seed", 0))))


def replay_equivalence(original: dict, replay: dict) -> list[str]:
    """Return paths for mismatches in scores, boxes, drives, and period outcomes."""
    fields = ("score", "teams", "players", "drives", "quarters", "status", "valid_full_game")
    mismatches = []
    for name in fields:
        if name in original or name in replay:
            if original.get(name) != replay.get(name):
                mismatches.append(name)
    return mismatches


def _story(row: dict) -> dict:
    return row.get("story") if isinstance(row.get("story"), dict) else {}


def _eligible_for_marketing(row: dict) -> bool:
    gate = row.get("gate") or hard_gate(row)
    replay_ok = row.get("replay_status") in {"passed", "equivalent"}
    return bool(gate.get("renderable") and replay_ok)


def _interest(row: dict) -> int:
    story = _story(row)
    supplied = _finite(story.get("visual_interest_score"))
    if supplied is not None:
        return max(0, min(100, round(supplied)))
    margin = _finite(story.get("margin"))
    game_features = row.get("features", {}).get("game", {})
    q4_points = _finite(game_features.get("q4_points_total_proxy")) or 0.0
    turnovers = _finite(game_features.get("turnovers_total")) or 0.0
    score = 20.0
    if margin is not None:
        score += max(0.0, 20.0 - 2.0 * margin)
    score += 25.0 if story.get("comeback") else 0.0
    score += 10.0 if story.get("defensive_score") else 0.0
    score += 20.0 if story.get("plausible_star") else 0.0
    score += min(10.0, max(0.0, turnovers * 2.5))
    score += min(15.0, max(0.0, (q4_points - 7.0) * 1.5))
    return max(0, min(100, round(score)))


def select_marketing_scenarios(ranked: Iterable[dict], limit: int = 15) -> list[dict]:
    """Choose distinct story roles only after realism and full replay gates pass."""
    candidates = [row for row in ranked if _eligible_for_marketing(row)]
    candidates.sort(key=lambda row: (-float(row.get("realism_score", 0)), int(row.get("seed", 0))))
    categories = [
        ("most_representative", lambda _row: True),
        ("close_finish", lambda row: abs(_finite(_story(row).get("margin")) or 99) <= 8),
        ("comeback", lambda row: bool(_story(row).get("comeback"))),
        ("defensive_game", lambda row: bool(_story(row).get("defensive_score"))),
        ("star_showcase", lambda row: bool(_story(row).get("plausible_star"))),
    ]
    selected = []
    used = set()
    for label, predicate in categories:
        match = next((row for row in candidates if int(row.get("seed", -1)) not in used and predicate(row)), None)
        if match is None:
            continue
        used.add(int(match["seed"]))
        selected.append({**match, "selection": label, "visual_interest_score": _interest(match)})
    target = max(len(selected), limit)
    for row in candidates:
        if len(selected) >= target:
            break
        seed = int(row.get("seed", -1))
        if seed not in used:
            used.add(seed)
            selected.append({**row, "selection": "additional_realistic_scenario",
                             "visual_interest_score": _interest(row)})
    return selected[:limit]


def write_outputs(ranked: list[dict], out_dir: Path, *, top_n: int = 150, marketing_n: int = 15) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ["seed", "realism_score", "replay_status", "status", "scoreable", "renderable",
              "hard_gate_reasons", "render_gate_reasons", "score_drives", "score_decisions",
              "score_workloads", "score_game", "distance_drives", "distance_decisions",
              "distance_workloads", "distance_game", "team_points", "opponent_points", "margin",
              "total_points", "turnovers", "comeback", "plausible_star"]
    with (out_dir / "seed-realism-rankings.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(ranked, key=lambda item: int(item.get("seed", 0))):
            gate = row.get("gate") or hard_gate(row)
            components = row.get("score_contributions", {})
            distances = row.get("group_distances", {})
            story = _story(row)
            points = row.get("points") or {}
            writer.writerow({
                "seed": row.get("seed"), "realism_score": row.get("realism_score"),
                "replay_status": row.get("replay_status"), "status": row.get("status"),
                "scoreable": gate.get("scoreable"), "renderable": gate.get("renderable"),
                "hard_gate_reasons": ";".join(gate.get("reasons", [])),
                "render_gate_reasons": ";".join(gate.get("render_reasons", [])),
                "score_drives": components.get("drives"), "score_decisions": components.get("decisions"),
                "score_workloads": components.get("workloads"), "score_game": components.get("game"),
                "distance_drives": distances.get("drives"), "distance_decisions": distances.get("decisions"),
                "distance_workloads": distances.get("workloads"), "distance_game": distances.get("game"),
                "team_points": points.get("team"), "opponent_points": points.get("opponent"),
                "margin": story.get("margin"), "total_points": story.get("total_points"),
                "turnovers": (row.get("features", {}).get("game", {}) or {}).get("turnovers"),
                "comeback": story.get("comeback"), "plausible_star": story.get("plausible_star"),
            })
    replay_has_run = any(row.get("replay_status") != "not_tested" for row in ranked)
    if replay_has_run:
        eligible = [row for row in ranked
                    if (row.get("gate") or hard_gate(row)).get("renderable")
                    and row.get("replay_status") in {"passed", "equivalent"}]
    else:
        eligible = [row for row in ranked if (row.get("gate") or hard_gate(row)).get("scoreable")]
    top = sorted(eligible, key=lambda row: (-row.get("realism_score", 0), int(row.get("seed", 0))))[:top_n]
    (out_dir / "top-seeds.json").write_text(json.dumps(top, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    marketing = select_marketing_scenarios(ranked, limit=marketing_n)
    marketing_document = {"schema": "lp.nfl.slc-marketing-seeds.v1", "seeds": marketing}
    (out_dir / "marketing-seeds.json").write_text(
        json.dumps(marketing_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

