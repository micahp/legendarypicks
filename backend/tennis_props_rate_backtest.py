#!/usr/bin/env python3
"""Chronological P0/P1 ace and double-fault count-distribution backtest.

Research-only while the source-data licence remains unresolved. Example:
  PYTHONPATH=backend python3 backend/tennis_props_rate_backtest.py \
    --db backend/data/picks.dev.db --tour atp --out /tmp/atp-p0-p1.json \
    --records /tmp/atp-p0-p1.csv

P0 forecasts counts per match; P1 forecasts a direct service-point exposure and
an event rate per service point (aces) or second-serve opportunity (DFs). Each
model is scored on the same eligible match-side observations.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
from collections import defaultdict
from itertools import groupby
from typing import Any, Iterator

import tennis_point_model as tpm

HALF_LIFE_DAYS = 2.0 * 365.25
P0_PRIOR_MATCHES = 8.0
P1_ACE_PRIOR_POINTS = 500.0
P1_DF_PRIOR_SECOND_SERVES = 250.0
FIRST_IN_PRIOR_POINTS = 200.0
EXPOSURE_PRIOR_MATCHES = 8.0
TEST_START = 20150101
TEST_END = 20261231
INCOMPLETE_TOKENS = ("RET", "W/O", "DEF", "ABD")
TARGET_THRESHOLDS = {"aces": (4, 6, 8, 10), "double_faults": (1, 2, 4, 6)}
INTERVALS = ((0.50, "50"), (0.80, "80"), (0.90, "90"))
MODEL_NAMES = ("p0_poisson", "p0_gamma_poisson", "p1_poisson", "p1_gamma_poisson")


def is_complete(score: str | None) -> bool:
    return score is not None and not any(token in score.upper() for token in INCOMPLETE_TOKENS)


def load_matches(db: str, tour: str, end: int) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(conn.execute(
            f"SELECT tourney_date,tourney_id,surface,winner_id,loser_id,best_of,score,"
            f"w_ace,w_df,w_svpt,w_1stIn,l_ace,l_df,l_svpt,l_1stIn "
            f"FROM tennis_{tour}_matches WHERE {tpm.TOUR_FILTER[tour]} "
            "AND tourney_date>=20000101 AND tourney_date<=? AND surface IS NOT NULL "
            "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date",
            (end,),
        ))
    finally:
        conn.close()


def decay(days: int) -> float:
    return 0.5 ** (max(0, days) / HALF_LIFE_DAYS)


class WeightedTotals:
    """Lazily decayed success/exposure totals, by player and tour-wide."""

    def __init__(self) -> None:
        self.player: dict[Any, list[float]] = {}
        self.total = [0.0, 0.0, 0.0]

    @staticmethod
    def _at(entry: list[float] | None, day: int) -> tuple[float, float]:
        if entry is None:
            return 0.0, 0.0
        factor = decay(day - int(entry[2]))
        return entry[0] * factor, entry[1] * factor

    def get(self, player: Any, day: int) -> tuple[float, float]:
        return self._at(self.player.get(player), day)

    def global_at(self, day: int) -> tuple[float, float]:
        return self._at(self.total, day)

    def add(self, player: Any, successes: float, exposure: float, day: int) -> None:
        entry = self.player.get(player)
        if entry is None:
            entry = [0.0, 0.0, float(day)]
            self.player[player] = entry
        factor = decay(day - int(entry[2]))
        entry[0] = entry[0] * factor + successes
        entry[1] = entry[1] * factor + exposure
        entry[2] = float(day)
        factor = decay(day - int(self.total[2])) if self.total[2] else 1.0
        self.total[0] = self.total[0] * factor + successes
        self.total[1] = self.total[1] * factor + exposure
        self.total[2] = float(day)


class DirectServiceExposure:
    """Gate-A direct player/surface service-point mean with surface shrinkage."""

    def __init__(self) -> None:
        self.player: dict[tuple[Any, str], list[float]] = {}
        self.surface: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])

    def _at(self, entry: list[float] | None, day: int) -> tuple[float, float, float]:
        if entry is None or not entry[3]:
            return 0.0, 0.0, 0.0
        factor = decay(day - int(entry[3]))
        return entry[0] * factor, entry[1] * factor, entry[2] * factor

    def mean(self, player: Any, surface: str, day: int) -> float:
        return self.moments(player, surface, day)[0]

    def moments(self, player: Any, surface: str, day: int) -> tuple[float, float]:
        surface_total, surface_matches, surface_sq = self._at(self.surface.get(surface), day)
        if surface_matches:
            prior_mean = surface_total / surface_matches
            prior_second = surface_sq / surface_matches
        else:
            totals = [self._at(entry, day) for entry in self.surface.values()]
            totals = [item for item in totals if item[1] > 0]
            n = sum(item[1] for item in totals)
            prior_mean = sum(item[0] for item in totals) / n if n else 80.0
            prior_second = sum(item[2] for item in totals) / n if n else 80.0**2 + 20.0**2
        player_total, player_matches, player_sq = self._at(self.player.get((player, surface)), day)
        shrink = player_matches / (player_matches + EXPOSURE_PRIOR_MATCHES)
        player_mean = player_total / player_matches if player_matches else prior_mean
        player_second = player_sq / player_matches if player_matches else prior_second
        mean = (1.0 - shrink) * prior_mean + shrink * player_mean
        second = (1.0 - shrink) * prior_second + shrink * player_second
        return mean, max(0.0, second - mean * mean)

    def add(self, player: Any, surface: str, service_points: int, day: int) -> None:
        entry = self.player.get((player, surface))
        if entry is None:
            entry = [0.0, 0.0, 0.0, float(day)]
            self.player[(player, surface)] = entry
        factor = decay(day - int(entry[3]))
        entry[0] = entry[0] * factor + service_points
        entry[1] = entry[1] * factor + 1.0
        entry[2] = entry[2] * factor + service_points * service_points
        entry[3] = float(day)
        surface_entry = self.surface[surface]
        factor = decay(day - int(surface_entry[3])) if surface_entry[3] else 1.0
        surface_entry[0] = surface_entry[0] * factor + service_points
        surface_entry[1] = surface_entry[1] * factor + 1.0
        surface_entry[2] = surface_entry[2] * factor + service_points * service_points
        surface_entry[3] = float(day)


def poisson_pmf(mean: float, observed: int) -> list[float]:
    mean = max(1e-12, mean)
    cap = max(observed, int(math.ceil(mean + 12.0 * math.sqrt(mean + 1.0) + 30)))
    values = [math.exp(-mean)]
    for k in range(cap):
        values.append(values[-1] * mean / (k + 1))
    total = sum(values)
    return [p / total for p in values]


def gamma_poisson_pmf(shape: float, rate: float, exposure: float, observed: int) -> list[float]:
    """Poisson future counts integrated over a Gamma(shape, rate) event rate."""
    shape = max(1e-9, shape)
    rate = max(1e-9, rate)
    exposure = max(1e-12, exposure)
    mean = shape * exposure / rate
    variance = mean + mean * mean / shape
    cap = max(observed, int(math.ceil(mean + 12.0 * math.sqrt(variance + 1.0) + 30)))
    p0 = math.exp(shape * math.log(rate / (rate + exposure)))
    ratio = exposure / (rate + exposure)
    values = [p0]
    for k in range(cap):
        values.append(values[-1] * (k + shape) * ratio / (k + 1))
    total = sum(values)
    return [p / total for p in values]


def moment_matched_gamma_poisson_pmf(mean: float, extra_mean_variance: float,
                                    observed: int) -> list[float]:
    """Approximate joint exposure/rate uncertainty with a Gamma-Poisson count law."""
    mean = max(1e-12, mean)
    if extra_mean_variance <= 1e-12:
        return poisson_pmf(mean, observed)
    shape = mean * mean / extra_mean_variance
    return gamma_poisson_pmf(shape, shape / mean, 1.0, observed)


def score_pmf(pmf: list[float], observed: int) -> dict[str, float]:
    n = len(pmf)
    if observed >= n:
        # The support cap includes the observed value; this is an invariant guard.
        raise ValueError(f"Observed count {observed} outside predictive support {n}")
    cdf = 0.0
    first = pair = 0.0
    cdf_x = 0.0
    for value, probability in enumerate(pmf):
        first += probability * abs(value - observed)
        pair += probability * (value * cdf - cdf_x)
        cdf += probability
        cdf_x += probability * value
    quantiles: dict[str, int] = {}
    cumulative = 0.0
    needed = {label: (1.0 - level) / 2.0 for level, label in INTERVALS}
    needed.update({f"{label}_upper": 1.0 - tail for label, tail in list(needed.items())})
    for value, probability in enumerate(pmf):
        cumulative += probability
        for key, level in needed.items():
            if key not in quantiles and cumulative >= level:
                quantiles[key] = value
    result: dict[str, float] = {
        "crps": first - pair,
        "log_score": -math.log(max(1e-300, pmf[observed])),
    }
    for level, label in INTERVALS:
        result[f"cover_{label}"] = float(quantiles[label] <= observed <= quantiles[f"{label}_upper"])
    for threshold in range(1, n):
        if threshold in TARGET_THRESHOLDS["aces"] or threshold in TARGET_THRESHOLDS["double_faults"]:
            probability = sum(pmf[threshold:])
            result[f"brier_ge_{threshold}"] = (probability - float(observed >= threshold)) ** 2
            result[f"event_ge_{threshold}"] = float(observed >= threshold)
    return result


def rate_mean(state: WeightedTotals, player: Any, day: int, prior_exposure: float) -> tuple[float, float, float]:
    player_success, player_exposure = state.get(player, day)
    global_success, global_exposure = state.global_at(day)
    prior_rate = global_success / global_exposure if global_exposure > 0 else 0.05
    alpha = prior_rate * prior_exposure + player_success
    beta = prior_exposure + player_exposure
    return alpha / beta, alpha, beta


def p0_parameters(state: WeightedTotals, player: Any, day: int) -> tuple[float, float, float]:
    player_count, player_matches = state.get(player, day)
    global_count, global_matches = state.global_at(day)
    prior_rate = global_count / global_matches if global_matches > 0 else 5.0
    alpha = P0_PRIOR_MATCHES * prior_rate + player_count
    beta = P0_PRIOR_MATCHES + player_matches
    return alpha / beta, alpha, beta


def valid_count(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and value >= 0 and int(value) == value


def forecast_target(target: str, player: Any, surface: str, day: int, actual: int,
                    p0: WeightedTotals, p1: WeightedTotals,
                    exposure: DirectServiceExposure, first_in: WeightedTotals) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    p0_mean, p0_shape, p0_rate = p0_parameters(p0, player, day)
    direct_sp_mean, direct_sp_variance = exposure.moments(player, surface, day)
    first_rate, first_alpha, first_beta = rate_mean(first_in, player, day, FIRST_IN_PRIOR_POINTS)
    if target == "aces":
        target_exposure = direct_sp_mean
        target_exposure_variance = direct_sp_variance
        prior_opportunities = P1_ACE_PRIOR_POINTS
    else:
        second_serve_rate = max(0.0, 1.0 - first_rate)
        first_rate_variance = (first_alpha * (first_beta - first_alpha)
                               / (first_beta * first_beta * (first_beta + 1.0)))
        second_moment_sp = direct_sp_variance + direct_sp_mean * direct_sp_mean
        target_exposure = direct_sp_mean * second_serve_rate
        target_exposure_variance = (
            direct_sp_mean * second_serve_rate * first_rate
            + direct_sp_variance * second_serve_rate * second_serve_rate
            + max(0.0, second_moment_sp - direct_sp_mean) * first_rate_variance
        )
        prior_opportunities = P1_DF_PRIOR_SECOND_SERVES
    p1_rate_mean, p1_shape, p1_rate = rate_mean(p1, player, day, prior_opportunities)
    p1_mean = p1_rate_mean * target_exposure
    p1_rate_variance = p1_shape / (p1_rate * p1_rate)
    extra_mean_variance = (
        target_exposure_variance * p1_rate_mean * p1_rate_mean
        + (target_exposure_variance + target_exposure * target_exposure) * p1_rate_variance
    )

    distributions = {
        "p0_poisson": poisson_pmf(p0_mean, actual),
        "p0_gamma_poisson": gamma_poisson_pmf(p0_shape, p0_rate, 1.0, actual),
        "p1_poisson": poisson_pmf(p1_mean, actual),
        "p1_gamma_poisson": moment_matched_gamma_poisson_pmf(p1_mean, extra_mean_variance, actual),
    }
    out: dict[str, Any] = {
        "target": target, "actual": actual, "surface": surface,
        "p0_history_matches": p0.get(player, day)[1],
        "p1_history_opportunities": p1.get(player, day)[1],
        "predicted_service_points": direct_sp_mean,
        "predicted_service_points_variance": direct_sp_variance,
        "predicted_target_exposure": target_exposure,
        "predicted_target_exposure_variance": target_exposure_variance,
    }
    scores = {model: score_pmf(pmf, actual) for model, pmf in distributions.items()}
    for model, pmf in distributions.items():
        out[f"{model}_mean"] = sum(k * p for k, p in enumerate(pmf))
    return out, scores


def _row_players(row: tuple, flip: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    # SQL fields after score: winner ace/DF/svpt/1stIn, then loser counterparts.
    winner = {"id": row[3], "aces": row[7], "double_faults": row[8], "svpt": row[9], "first_in": row[10]}
    loser = {"id": row[4], "aces": row[11], "double_faults": row[12], "svpt": row[13], "first_in": row[14]}
    return (loser, winner) if flip else (winner, loser)


def run(db: str, tour: str, start: int = TEST_START, end: int = TEST_END) -> Iterator[dict[str, Any]]:
    rows = load_matches(db, tour, end)
    p0 = {target: WeightedTotals() for target in ("aces", "double_faults")}
    p1 = {target: WeightedTotals() for target in ("aces", "double_faults")}
    exposure = DirectServiceExposure()
    first_in = WeightedTotals()
    orientation = random.Random(20261016)
    for date, grouped in groupby(rows, key=lambda row: row[0]):
        day_rows = list(grouped)
        day = tpm._ordinal(date)
        for row in day_rows:
            _, event_id, surface, _, _, best_of, score = row[:7]
            if not (start <= date <= end and best_of == 3 and is_complete(score)):
                continue
            a, b = _row_players(row, orientation.random() < 0.5)
            target_specs = (
                ("aces", lambda x: valid_count(x["aces"]) and valid_count(x["svpt"]) and x["svpt"] > 0
                 and x["aces"] <= x["svpt"]),
                ("double_faults", lambda x: valid_count(x["double_faults"]) and valid_count(x["svpt"])
                 and valid_count(x["first_in"]) and x["svpt"] > 0 and 0 <= x["first_in"] <= x["svpt"]
                 and x["double_faults"] <= x["svpt"] - x["first_in"]),
            )
            for target, valid in target_specs:
                if not (valid(a) and valid(b)):
                    continue
                target_rows = []
                target_scores = []
                for player in (a, b):
                    row_out, scores = forecast_target(target, player["id"], surface, day,
                                                      int(player[target]), p0[target], p1[target], exposure, first_in)
                    row_out.update({
                        "tour": tour, "date": date, "year": date // 10000,
                        "event_id": event_id, "player_id": player["id"],
                    })
                    target_rows.append(row_out)
                    target_scores.append(scores)
                # Store one row per player target with all forecast scores and calibration outcomes.
                for row_out, scores in zip(target_rows, target_scores):
                    for model in MODEL_NAMES:
                        for metric, value in scores[model].items():
                            row_out[f"{model}_{metric}"] = value
                    hist = row_out["p0_history_matches"]
                    row_out["history_band"] = "cold_lt10" if hist < 10 else ("mid_10_40" if hist < 40 else "deep_ge40")
                    yield row_out

        # Update only after the full event-start date has been forecast.
        for row in day_rows:
            _, _, surface, _, _, best_of, score = row[:7]
            if best_of != 3 or not is_complete(score):
                continue
            winner, loser = _row_players(row, False)
            for player in (winner, loser):
                if valid_count(player["aces"]):
                    p0["aces"].add(player["id"], player["aces"], 1.0, day)
                if valid_count(player["double_faults"]):
                    p0["double_faults"].add(player["id"], player["double_faults"], 1.0, day)
                svpt = player["svpt"]
                first = player["first_in"]
                if not valid_count(svpt) or svpt <= 0:
                    continue
                exposure.add(player["id"], surface, int(svpt), day)
                if valid_count(first) and 0 <= first <= svpt:
                    first_in.add(player["id"], first, svpt, day)
                    if valid_count(player["aces"]) and player["aces"] <= svpt:
                        p1["aces"].add(player["id"], player["aces"], svpt, day)
                    second_serve_opportunities = svpt - first
                    if (valid_count(player["double_faults"])
                            and player["double_faults"] <= second_serve_opportunities
                            and second_serve_opportunities > 0):
                        p1["double_faults"].add(player["id"], player["double_faults"],
                                                  second_serve_opportunities, day)
def _empty_accumulator(target: str) -> dict[str, Any]:
    return {
        "target": target, "n": 0, "actual_sum": 0.0,
        "models": {model: {
            "prediction_sum": 0.0, "abs_error_sum": 0.0, "sq_error_sum": 0.0,
            "bias_sum": 0.0, "crps_sum": 0.0, "log_sum": 0.0,
            "covers": {label: 0.0 for _, label in INTERVALS},
            "brier": {threshold: 0.0 for threshold in TARGET_THRESHOLDS[target]},
        } for model in MODEL_NAMES},
    }


def _add_accumulator(acc: dict[str, Any], row: dict[str, str]) -> None:
    actual = int(row["actual"])
    acc["n"] += 1
    acc["actual_sum"] += actual
    target = row["target"]
    for model in MODEL_NAMES:
        prediction = float(row[f"{model}_mean"])
        error = prediction - actual
        model_acc = acc["models"][model]
        model_acc["prediction_sum"] += prediction
        model_acc["abs_error_sum"] += abs(error)
        model_acc["sq_error_sum"] += error * error
        model_acc["bias_sum"] += error
        model_acc["crps_sum"] += float(row[f"{model}_crps"])
        model_acc["log_sum"] += float(row[f"{model}_log_score"])
        for _, label in INTERVALS:
            model_acc["covers"][label] += float(row[f"{model}_cover_{label}"])
        for threshold in TARGET_THRESHOLDS[target]:
            model_acc["brier"][threshold] += float(row[f"{model}_brier_ge_{threshold}"])


def _finish_accumulator(acc: dict[str, Any]) -> dict[str, Any]:
    n = acc["n"]
    result: dict[str, Any] = {"player_match_targets": n,
                              "observed_mean": acc["actual_sum"] / n if n else math.nan,
                              "models": {}}
    for model, values in acc["models"].items():
        result["models"][model] = {
            "mean_prediction": values["prediction_sum"] / n if n else math.nan,
            "mae": values["abs_error_sum"] / n if n else math.nan,
            "rmse": math.sqrt(values["sq_error_sum"] / n) if n else math.nan,
            "bias_predicted_minus_actual": values["bias_sum"] / n if n else math.nan,
            "crps": values["crps_sum"] / n if n else math.nan,
            "log_score": values["log_sum"] / n if n else math.nan,
            "coverage": {key: value / n if n else math.nan for key, value in values["covers"].items()},
            "exceedance_brier": {str(key): value / n if n else math.nan
                                  for key, value in values["brier"].items()},
        }
    return result


def _cluster_interval(clusters: dict[str, list[float]], seed: int, reps: int = 1000) -> dict[str, float]:
    keys = list(clusters)
    if not keys:
        return {"difference_a_minus_b": math.nan, "ci95_low": math.nan, "ci95_high": math.nan}
    cluster_sums = [sum(clusters[key]) for key in keys]
    cluster_counts = [len(clusters[key]) for key in keys]
    total = sum(cluster_sums)
    count = sum(cluster_counts)
    observed = total / count
    rng = random.Random(seed)
    estimates = []
    for _ in range(reps):
        sample = [rng.randrange(len(keys)) for _ in keys]
        numerator = sum(cluster_sums[index] for index in sample)
        denominator = sum(cluster_counts[index] for index in sample)
        estimates.append(numerator / denominator)
    estimates.sort()
    return {"difference_a_minus_b": observed,
            "ci95_low": estimates[int(0.025 * (reps - 1))],
            "ci95_high": estimates[int(0.975 * (reps - 1))],
            "bootstrap_clusters": len(keys), "bootstrap_replicates": reps}


def summarize_csv(path: str, tour: str, start: int, end: int) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    pairs = {
        "p1_poisson_minus_p0_poisson": ("p1_poisson", "p0_poisson", 20261016),
        "p1_gamma_poisson_minus_p0_gamma_poisson": ("p1_gamma_poisson", "p0_gamma_poisson", 20261017),
        "p1_gamma_poisson_minus_p1_poisson": ("p1_gamma_poisson", "p1_poisson", 20261018),
        "p0_gamma_poisson_minus_p0_poisson": ("p0_gamma_poisson", "p0_poisson", 20261019),
    }
    paired_clusters: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(dict))
    paired_brier_clusters: dict[str, dict[str, dict[int, dict[str, list[float]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    min_date: int | None = None
    max_date: int | None = None
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            target = row["target"]
            date, year, surface, history = int(row["date"]), int(row["year"]), row["surface"], row["history_band"]
            min_date = date if min_date is None else min(min_date, date)
            max_date = date if max_date is None else max(max_date, date)
            keys = [("overall", "all"), ("year", str(year)), ("surface", surface), ("history", history)]
            for group_type, group_value in keys:
                group_key = (target, group_type, group_value)
                acc = groups.setdefault(group_key, _empty_accumulator(target))
                _add_accumulator(acc, row)
            event_id = str(row["event_id"] or date)
            for pair_name, (model_a, model_b, _) in pairs.items():
                cell = paired_clusters[target][pair_name].setdefault(event_id, [])
                cell.append(float(row[f"{model_a}_crps"]) - float(row[f"{model_b}_crps"]))
                for threshold in TARGET_THRESHOLDS[target]:
                    brier_cell = paired_brier_clusters[target][pair_name][threshold].setdefault(event_id, [])
                    brier_cell.append(
                        float(row[f"{model_a}_brier_ge_{threshold}"])
                        - float(row[f"{model_b}_brier_ge_{threshold}"])
                    )

    by_target: dict[str, Any] = {}
    for target in ("aces", "double_faults"):
        overall = groups.get((target, "overall", "all"), _empty_accumulator(target))
        by_target[target] = {
            "overall": _finish_accumulator(overall),
            "by_year": {value: _finish_accumulator(acc) for (t, typ, value), acc in sorted(groups.items())
                        if t == target and typ == "year"},
            "by_surface": {value: _finish_accumulator(acc) for (t, typ, value), acc in sorted(groups.items())
                           if t == target and typ == "surface"},
            "by_p0_history": {value: _finish_accumulator(acc) for (t, typ, value), acc in sorted(groups.items())
                              if t == target and typ == "history"},
            "paired_crps_difference": {
                pair_name: _cluster_interval(paired_clusters[target].get(pair_name, {}), seed)
                for pair_name, (_, _, seed) in pairs.items()
            },
            "paired_exceedance_brier_difference": {
                pair_name: {
                    str(threshold): _cluster_interval(
                        paired_brier_clusters[target].get(pair_name, {}).get(threshold, {}), seed + threshold
                    )
                    for threshold in TARGET_THRESHOLDS[target]
                }
                for pair_name, (_, _, seed) in pairs.items()
            },
        }
    return {
        "tour": tour, "evaluation_start": min_date, "evaluation_end": max_date,
        "requested_start": start, "requested_end": end,
        "method": "Prior-only chronological walk-forward; same event-start date held out as a block; completed main-tour best-of-three matches only.",
        "decay_half_life_years": 2.0,
        "p0_prior_pseudomatches": P0_PRIOR_MATCHES,
        "p1_ace_prior_service_points": P1_ACE_PRIOR_POINTS,
        "p1_df_prior_second_serves": P1_DF_PRIOR_SECOND_SERVES,
        "first_serve_in_prior_service_points": FIRST_IN_PRIOR_POINTS,
        "p1_exposure_forecast": "Direct 2-year-decayed player/surface service-point mean and variance, shrunk toward the tour/surface mean using eight pseudo-matches; DF second-serve exposure derives from the smoothed first-serve-in rate.",
        "p1_gamma_poisson_note": "Moment-matched negative-binomial count distribution includes direct exposure variance, posterior event-rate variance, and the interaction term; it assumes rate and opportunity are independent.",
        "score_notes": "CRPS and negative log score are proper count-distribution scores. Intervals are central equal-tail. Cluster-bootstrap CRPS differences resample tournament IDs; they quantify paired historical variation but do not make this an untouched prospective evaluation.",
        "player_match_target_records": sum(groups.get((target, "overall", "all"), _empty_accumulator(target))["n"]
                                         for target in ("aces", "double_faults")),
        "targets": by_target,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", required=True, choices=sorted(tpm.TOUR_FILTER))
    parser.add_argument("--start", type=int, default=TEST_START)
    parser.add_argument("--end", type=int, default=TEST_END)
    parser.add_argument("--out", required=True)
    parser.add_argument("--records", required=True)
    parser.add_argument("--summarize-existing", action="store_true",
                        help="build the summary from --records without rerunning the database replay")
    args = parser.parse_args()
    if not args.summarize_existing:
        records = iter(run(args.db, args.tour, args.start, args.end))
        first = next(records, None)
        with open(args.records, "w", newline="") as handle:
            if first is not None:
                writer = csv.DictWriter(handle, fieldnames=list(first))
                writer.writeheader()
                writer.writerow(first)
                writer.writerows(records)
    summary = summarize_csv(args.records, args.tour, args.start, args.end)
    with open(args.out, "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps({target: data["overall"] for target, data in summary["targets"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
