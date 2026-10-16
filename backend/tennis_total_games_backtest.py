#!/usr/bin/env python3
"""Chronological total-games distribution comparison for ATP/WTA main-tour BO3 matches.

Compares the current point model + exact scoring simulator against three direct,
prior-only total-games histograms: format only, format + surface, and format +
surface + pre-match Elo competitiveness. The historical histogram starts in 2022
to align with the Grand Slam 10-point final-set tiebreak standard.

Example:
  PYTHONPATH=backend python3 backend/tennis_total_games_backtest.py \
    --db backend/data/picks.dev.db --tour atp --out /tmp/atp-games.json \
    --records /tmp/atp-games.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sqlite3
from collections import defaultdict
from itertools import groupby
from typing import Any

import tennis_match_sim as sim
import tennis_point_model as tpm

PLAYER_HALF_LIFE_YEARS = 2.0
FORM_K = 250.0
ELO_START = 1500.0
ELO_K = 32.0
TEST_START = 20230101
TEST_END = 20261231
HISTORY_START = 20220101
HISTOGRAM_HALF_LIFE_YEARS = 5.0
GLOBAL_PRIOR_MASS = 10.0
SURFACE_PRIOR_MATCHES = 30.0
COMPETITIVENESS_PRIOR_MATCHES = 30.0
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261016
INCOMPLETE_TOKENS = ("RET", "W/O", "DEF", "ABD")
OVER_LINES = (18.5, 20.5, 22.5, 24.5, 26.5)
SLAM_NAMES = {"australian open", "roland garros", "wimbledon", "us open"}
STANDARD_RULES: dict[str, Any] = {"bestOf": 3, "tiebreakAt": 6, "tiebreakPoints": 7,
                                  "finalSet": "tiebreak", "finalSetTiebreakAt": 6,
                                  "finalSetTiebreakPoints": 7}
SLAM_10_RULES: dict[str, Any] = {**STANDARD_RULES, "finalSetTiebreakPoints": 10}
MATCH_TIEBREAK_RULES: dict[str, Any] = {"bestOf": 3, "finalSet": "match_tiebreak",
                                        "finalSetTiebreakPoints": 10}
MODEL_NAMES = ("simulator", "direct_format", "direct_surface", "direct_surface_competitive")


def is_complete(score: str | None) -> bool:
    return score is not None and not any(token in score.upper() for token in INCOMPLETE_TOKENS)


def score_format(score: str, tourney_level: str | None, tourney_name: str | None,
                 date: int) -> tuple[str, dict[str, Any]] | None:
    if "[" in score or "]" in score:
        return "match_tiebreak_10", MATCH_TIEBREAK_RULES
    if tourney_level == "G":
        if (tourney_name or "").strip().lower() not in SLAM_NAMES or date < 20220101:
            return None
        return "grand_slam_final_tiebreak_10", SLAM_10_RULES
    return "standard_tiebreak_7", STANDARD_RULES


def total_games_from_score(score: str, format_key: str) -> int | None:
    """Sum played set games; a match tiebreak in square brackets is not a game."""
    if not is_complete(score):
        return None
    regular_score = re.sub(r"\[[^\]]*\]", " ", score)
    sets = re.findall(r"(?<!\d)(\d+)-(\d+)(?:\(\d+\))?", regular_score)
    expected_sets = (2,) if format_key == "match_tiebreak_10" else (2, 3)
    if len(sets) not in expected_sets:
        return None
    game_pairs = [(int(a), int(b)) for a, b in sets]
    for a, b in game_pairs:
        if max(a, b) > 7 or max(a, b) < 6 or abs(a - b) < 1:
            return None
        if max(a, b) == 7 and min(a, b) not in (5, 6):
            return None
        if max(a, b) == 6 and min(a, b) > 4:
            return None
    count = sum(a + b for a, b in game_pairs)
    if format_key == "match_tiebreak_10":
        return count if 12 <= count <= 26 else None
    return count if 12 <= count <= 39 else None


def load_matches(db: str, tour: str, end: int) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(conn.execute(
            f"SELECT tourney_date,tourney_id,tourney_name,tourney_level,surface,winner_id,loser_id,best_of,score,"
            f"w_svpt,w_1stWon,w_2ndWon,l_svpt,l_1stWon,l_2ndWon FROM tennis_{tour}_matches "
            f"WHERE {tpm.TOUR_FILTER[tour]} AND tourney_date>=20000101 AND tourney_date<=? "
            "AND surface IS NOT NULL AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date",
            (end,),
        ))
    finally:
        conn.close()


def valid_serve_stats(row: tuple) -> bool:
    values = row[9:15]
    if any(value is None or not isinstance(value, (int, float)) for value in values):
        return False
    wsv, w1, w2, lsv, l1, l2 = values
    return wsv > 0 and lsv > 0 and 0 <= w1 + w2 <= wsv and 0 <= l1 + l2 <= lsv


def competition_bucket(elo_gap: float) -> str:
    if elo_gap < 50:
        return "under_50"
    if elo_gap < 150:
        return "50_to_149"
    if elo_gap < 300:
        return "150_to_299"
    return "300_plus"


def history_bucket(points: float) -> str:
    if points < 300:
        return "thin_under_300"
    if points < 1500:
        return "middling_300_to_1499"
    return "deep_1500_plus"


class DecayedHistogram:
    def __init__(self) -> None:
        self.counts: dict[int, float] = defaultdict(float)
        self.weight = 0.0
        self.last_day: int | None = None

    def _decay_to(self, day: int) -> None:
        if self.last_day is not None and day > self.last_day:
            factor = 0.5 ** ((day - self.last_day) / (HISTOGRAM_HALF_LIFE_YEARS * 365.25))
            for value in list(self.counts):
                self.counts[value] *= factor
            self.weight *= factor
        self.last_day = day

    def add(self, value: int, day: int) -> None:
        self._decay_to(day)
        self.counts[value] += 1.0
        self.weight += 1.0

    def pmf(self, day: int, support: tuple[int, ...], parent: list[float] | None,
            prior_mass: float) -> list[float]:
        self._decay_to(day)
        if parent is None:
            parent = [1.0 / len(support)] * len(support)
        denominator = self.weight + prior_mass
        if denominator <= 0:
            return parent[:]
        return [
            (self.counts.get(value, 0.0) + prior_mass * parent[index]) / denominator
            for index, value in enumerate(support)
        ]


class DirectGames:
    """Prior-only hierarchical empirical distributions, with exponential time decay."""

    def __init__(self) -> None:
        self.by_format: dict[str, DecayedHistogram] = defaultdict(DecayedHistogram)
        self.by_surface: dict[tuple[str, str], DecayedHistogram] = defaultdict(DecayedHistogram)
        self.by_comp: dict[tuple[str, str, str], DecayedHistogram] = defaultdict(DecayedHistogram)

    def add(self, format_key: str, surface: str, comp: str, games: int, day: int) -> None:
        self.by_format[format_key].add(games, day)
        self.by_surface[(format_key, surface)].add(games, day)
        self.by_comp[(format_key, surface, comp)].add(games, day)

    def forecasts(self, format_key: str, surface: str, comp: str, day: int,
                  support: tuple[int, ...]) -> dict[str, list[float]]:
        root = self.by_format[format_key].pmf(day, support, None, GLOBAL_PRIOR_MASS)
        surface_pmf = self.by_surface[(format_key, surface)].pmf(
            day, support, root, SURFACE_PRIOR_MATCHES
        )
        comp_pmf = self.by_comp[(format_key, surface, comp)].pmf(
            day, support, surface_pmf, COMPETITIVENESS_PRIOR_MATCHES
        )
        return {
            "direct_format": root,
            "direct_surface": surface_pmf,
            "direct_surface_competitive": comp_pmf,
        }


def pmf_scores(pmf: list[float], support: tuple[int, ...], observed: int) -> dict[str, Any]:
    total = sum(pmf)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("invalid predictive distribution")
    probs = [max(0.0, p / total) for p in pmf]
    if observed not in support:
        raise ValueError(f"actual total {observed} outside support {support[0]}..{support[-1]}")
    first = pair_half = cdf = expected = 0.0
    quantiles: dict[float, int] = {}
    levels = (0.50, 0.80, 0.90)
    needed = {level: ((1.0 - level) / 2.0, 1.0 - (1.0 - level) / 2.0) for level in levels}
    lows: dict[float, int] = {}
    highs: dict[float, int] = {}
    for value, probability in zip(support, probs):
        first += probability * abs(value - observed)
        pair_half += probability * (value * cdf - expected)
        cdf += probability
        expected += probability * value
    cdf = 0.0
    for value, probability in zip(support, probs):
        cdf += probability
        for level, (low_q, high_q) in needed.items():
            if level not in lows and cdf >= low_q:
                lows[level] = value
            if level not in highs and cdf >= high_q:
                highs[level] = value
    scores: dict[str, Any] = {
        "crps": first - pair_half,
        "log_score": -math.log(max(1e-300, probs[support.index(observed)])),
        "mean": sum(value * probability for value, probability in zip(support, probs)),
        "cover_50": float(lows[0.50] <= observed <= highs[0.50]),
        "cover_80": float(lows[0.80] <= observed <= highs[0.80]),
        "cover_90": float(lows[0.90] <= observed <= highs[0.90]),
        "width_80": highs[0.80] - lows[0.80],
    }
    scores["variance"] = sum(
        probability * (value - scores["mean"]) ** 2
        for value, probability in zip(support, probs)
    )
    for line in OVER_LINES:
        threshold = math.floor(line) + 1
        probability_over = sum(p for value, p in zip(support, probs) if value >= threshold)
        event = float(observed >= threshold)
        key = str(line)
        scores[f"over_{key}_prob"] = probability_over
        scores[f"over_{key}_brier"] = (probability_over - event) ** 2
        scores[f"over_{key}_event"] = event
    return scores


def simulator_distribution(serve_a: float, serve_b: float, rules: dict[str, Any],
                           support: tuple[int, ...]) -> tuple[list[float], float, dict[str, float]]:
    result = sim.match_distribution(serve_a, serve_b, rules, first_server=None)
    resolved = result["p_a"] + result["p_b"]
    unresolved = result["unresolved"]
    if resolved <= 0 or unresolved > 1e-8:
        raise ValueError(f"simulator unresolved/empty distribution: unresolved={unresolved}, mass={resolved}")
    probabilities = [result["total_games"].get(value, 0.0) / resolved for value in support]
    structure = {
        "expected_sets": sum(sets * mass for sets, mass in result["sets_played"].items()) / resolved,
        "p_deciding_set": result["sets_played"].get(3, 0.0) / resolved,
        "p_any_tiebreak": result["p_tiebreak_any"] / resolved,
        "expected_set_games": sum((winner_games + loser_games) * mass
                                   for (_, _, winner_games, loser_games), mass
                                   in result["set_scores"].items()) / resolved,
        "expected_tiebreak_sets": sum(mass for (_, _, winner_games, loser_games), mass
                                       in result["set_scores"].items()
                                       if winner_games == 7 and loser_games == 6) / resolved,
    }
    return probabilities, unresolved, structure


def observed_structure(score: str) -> dict[str, float]:
    regular_score = re.sub(r"\[[^\]]*\]", " ", score)
    sets = [(int(a), int(b)) for a, b in re.findall(
        r"(?<!\d)(\d+)-(\d+)(?:\(\d+\))?", regular_score
    )]
    if not sets:
        raise ValueError(f"unable to parse set scores: {score!r}")
    return {
        "sets": float(len(sets)),
        "deciding_set": float(len(sets) == 3),
        "any_tiebreak": float(any(max(a, b) == 7 and min(a, b) == 6 for a, b in sets)),
        "set_games": float(sum(a + b for a, b in sets)),
        "tiebreak_sets": float(sum(max(a, b) == 7 and min(a, b) == 6 for a, b in sets)),
    }


def support_for(format_key: str) -> tuple[int, ...]:
    return tuple(range(12, 27)) if format_key == "match_tiebreak_10" else tuple(range(12, 40))


def run(db: str, tour: str, start: int = TEST_START, end: int = TEST_END) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = load_matches(db, tour, end)
    point_state = tpm.OnlineStats(baseline_years=0, half_life_years=None,
                                  player_half_life=PLAYER_HALF_LIFE_YEARS)
    elo: dict[Any, float] = defaultdict(lambda: ELO_START)
    direct = DirectGames()
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for date, grouped in groupby(rows, key=lambda row: row[0]):
        day_rows = list(grouped)
        day = tpm._ordinal(date)
        point_state.expire(date)
        test_date = start <= date <= end
        for row in day_rows:
            _, event_id, event_name, level, surface, winner, loser, best_of, score = row[:9]
            if best_of != 3:
                counts["excluded_not_best_of_three"] += int(test_date)
                continue
            if not is_complete(score):
                counts["excluded_incomplete_or_walkover"] += int(test_date)
                continue
            tagged_format = score_format(score, level, event_name, date)
            if tagged_format is None:
                counts["excluded_unverified_format"] += int(test_date)
                continue
            format_key, rules = tagged_format
            actual_games = total_games_from_score(score, format_key)
            if actual_games is None:
                counts["excluded_unparseable_score"] += int(test_date)
                continue
            if date >= HISTORY_START and test_date:
                comp = competition_bucket(abs(elo[winner] - elo[loser]))
                if test_date:
                    # Match side orientation is canonicalized by ID, not by the eventual winner.
                    a, b = sorted((winner, loser), key=str)
                    baseline = point_state.baseline(surface)
                    serve_a = tpm.point_prob(point_state.serve(a, surface, FORM_K),
                                             point_state.returns(b, surface, FORM_K), baseline)
                    serve_b = tpm.point_prob(point_state.serve(b, surface, FORM_K),
                                             point_state.returns(a, surface, FORM_K), baseline)
                    sim_pmf, unresolved, sim_structure = simulator_distribution(
                        serve_a, serve_b, rules, support_for(format_key)
                    )
                    direct_pmfs = direct.forecasts(format_key, surface, comp, day,
                                                   support_for(format_key))
                    low_a, high_a = point_state.effective_points(a, surface)
                    low_b, high_b = point_state.effective_points(b, surface)
                    scored = {"simulator": sim_pmf, **direct_pmfs}
                    observed = observed_structure(score)
                    row_out: dict[str, Any] = {
                        "tour": tour, "date": date, "year": date // 10000,
                        "event_id": event_id, "event_name": event_name, "surface": surface,
                        "format": format_key, "actual_games": actual_games,
                        "elo_gap": abs(elo[winner] - elo[loser]), "competitiveness": comp,
                        "history_points": min(low_a, high_a, low_b, high_b),
                        "history_band": history_bucket(min(low_a, high_a, low_b, high_b)),
                        "simulator_unresolved_mass": unresolved,
                        "actual_sets": observed["sets"],
                        "actual_deciding_set": observed["deciding_set"],
                        "actual_any_tiebreak": observed["any_tiebreak"],
                        "actual_set_games": observed["set_games"],
                        "actual_tiebreak_sets": observed["tiebreak_sets"],
                        "simulator_expected_sets": sim_structure["expected_sets"],
                        "simulator_p_deciding_set": sim_structure["p_deciding_set"],
                        "simulator_p_any_tiebreak": sim_structure["p_any_tiebreak"],
                        "simulator_expected_set_games": sim_structure["expected_set_games"],
                        "simulator_expected_tiebreak_sets": sim_structure["expected_tiebreak_sets"],
                    }
                    for model, pmf in scored.items():
                        for metric, value in pmf_scores(pmf, support_for(format_key), actual_games).items():
                            row_out[f"{model}_{metric}"] = value
                    records.append(row_out)
                    counts["scored"] += 1
            elif test_date:
                counts["excluded_no_direct_history"] += 1

        # The target rows on an event-start date never enter same-day priors.
        for row in day_rows:
            _, event_id, event_name, level, surface, winner, loser, best_of, score = row[:9]
            if date >= HISTORY_START and best_of == 3 and is_complete(score):
                tagged_format = score_format(score, level, event_name, date)
                if tagged_format is not None:
                    format_key, _ = tagged_format
                    actual_games = total_games_from_score(score, format_key)
                    if actual_games is not None:
                        comp = competition_bucket(abs(elo[winner] - elo[loser]))
                        direct.add(format_key, surface, comp, actual_games, day)
            if valid_serve_stats(row):
                point_state.add((row[0], surface, winner, loser, *row[9:15]))

        # Competitiveness ratings also update only after the date block; incomplete results do not count.
        rating_updates = []
        for row in day_rows:
            date0, _, event_name, level, surface, winner, loser, best_of, score = row[:9]
            if is_complete(score):
                expected = 1.0 / (1.0 + 10 ** ((elo[loser] - elo[winner]) / 400.0))
                rating_updates.append((winner, loser, ELO_K * (1.0 - expected)))
        for winner, loser, delta in rating_updates:
            elo[winner] += delta
            elo[loser] -= delta

    return records, dict(counts)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"matches": len(rows), "models": {}}
    for model in MODEL_NAMES:
        result["models"][model] = {
            "crps": _mean([r[f"{model}_crps"] for r in rows]),
            "log_score": _mean([r[f"{model}_log_score"] for r in rows]),
            "mean_absolute_error": _mean([abs(r[f"{model}_mean"] - r["actual_games"]) for r in rows]),
            "bias": _mean([r[f"{model}_mean"] - r["actual_games"] for r in rows]),
            "coverage": {level: _mean([r[f"{model}_cover_{level}"] for r in rows])
                         for level in ("50", "80", "90")},
            "mean_80_interval_width": _mean([r[f"{model}_width_80"] for r in rows]),
            "over_lines": {
                str(line): {
                    "brier": _mean([r[f"{model}_over_{line}_brier"] for r in rows]),
                    "mean_probability": _mean([r[f"{model}_over_{line}_prob"] for r in rows]),
                    "observed_frequency": _mean([r[f"{model}_over_{line}_event"] for r in rows]),
                }
                for line in OVER_LINES
            },
        }
    return result


def _structure_sums(rows: list[dict[str, Any]]) -> dict[str, float]:
    sums = {key: 0.0 for key in (
        "n", "actual_games", "actual_games_sq", "simulator_mean", "simulator_second_moment",
        "actual_sets", "actual_deciding", "actual_any_tiebreak", "actual_set_games",
        "actual_tiebreak_sets", "simulator_expected_sets", "simulator_p_deciding_set",
        "simulator_p_any_tiebreak", "simulator_expected_set_games",
        "simulator_expected_tiebreak_sets",
    )}
    for row in rows:
        sums["n"] += 1
        actual = row["actual_games"]
        mean = row["simulator_mean"]
        sums["actual_games"] += actual
        sums["actual_games_sq"] += actual * actual
        sums["simulator_mean"] += mean
        sums["simulator_second_moment"] += row["simulator_variance"] + mean * mean
        for key in sums:
            if key not in {"n", "actual_games", "actual_games_sq", "simulator_mean", "simulator_second_moment"}:
                row_key = "actual_deciding_set" if key == "actual_deciding" else key
                sums[key] += row[row_key]
    return sums


def _structure_differences(sums: dict[str, float]) -> dict[str, float]:
    n = sums["n"]
    if n <= 0:
        return {}
    obs_sets = sums["actual_sets"]
    sim_sets = sums["simulator_expected_sets"]
    obs_set_games = sums["actual_set_games"]
    sim_set_games = sums["simulator_expected_set_games"]
    obs_mean = sums["actual_games"] / n
    sim_mean = sums["simulator_mean"] / n
    obs_games_per_set = obs_set_games / obs_sets
    sim_games_per_set = sim_set_games / sim_sets
    observed_variance = max(0.0, sums["actual_games_sq"] / n - obs_mean * obs_mean)
    predictive_variance = max(
        0.0, sums["simulator_second_moment"] / n - sim_mean * sim_mean
    )
    sets_per_match_gap = sim_sets / n - obs_sets / n
    set_length_gap = sim_games_per_set - obs_games_per_set
    return {
        "total_games_bias": sim_mean - obs_mean,
        "sets_per_match_gap": sets_per_match_gap,
        "games_per_set_gap": set_length_gap,
        "deciding_set_probability_gap": (
            sums["simulator_p_deciding_set"] - sums["actual_deciding"]
        ) / n,
        "any_tiebreak_probability_gap": (
            sums["simulator_p_any_tiebreak"] - sums["actual_any_tiebreak"]
        ) / n,
        "tiebreak_set_rate_gap": (
            sums["simulator_expected_tiebreak_sets"] / sim_sets
            - sums["actual_tiebreak_sets"] / obs_sets
        ),
        "total_variance_gap": predictive_variance - observed_variance,
    }


def _bootstrap_structure(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_event[str(row["event_id"])].append(row)
    keys = list(by_event)
    if not keys:
        return {}
    event_sums = [_structure_sums(by_event[key]) for key in keys]
    fields = tuple(event_sums[0])
    rng = random.Random(BOOTSTRAP_SEED)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(BOOTSTRAP_RESAMPLES):
        combined = {field: 0.0 for field in fields}
        for _ in keys:
            sampled = event_sums[rng.randrange(len(keys))]
            for field in fields:
                combined[field] += sampled[field]
        for metric, value in _structure_differences(combined).items():
            samples[metric].append(value)
    intervals = {}
    for metric, values in samples.items():
        values.sort()
        intervals[metric] = {
            "low": values[int(0.025 * len(values))],
            "high": values[int(0.975 * len(values)) - 1],
        }
    return intervals


def summarize_structure(rows: list[dict[str, Any]], bootstrap: bool = False) -> dict[str, Any]:
    sums = _structure_sums(rows)
    n = sums["n"]
    if not n:
        return {"matches": 0}
    actual_sets = sums["actual_sets"]
    predicted_sets = sums["simulator_expected_sets"]
    actual_set_games = sums["actual_set_games"]
    predicted_set_games = sums["simulator_expected_set_games"]
    actual_mean = sums["actual_games"] / n
    predicted_mean = sums["simulator_mean"] / n
    # Decompose total-games error using observed set length as the reference.
    observed_games_per_set = actual_set_games / actual_sets
    predicted_games_per_set = predicted_set_games / predicted_sets
    set_count_contribution = (predicted_sets - actual_sets) / n * observed_games_per_set
    set_length_contribution = predicted_sets / n * (predicted_games_per_set - observed_games_per_set)
    result: dict[str, Any] = {
        "matches": int(n),
        "observed": {
            "total_games_per_match": actual_mean,
            "sets_per_match": actual_sets / n,
            "games_per_set": observed_games_per_set,
            "deciding_set_frequency": sums["actual_deciding"] / n,
            "any_tiebreak_match_frequency": sums["actual_any_tiebreak"] / n,
            "tiebreak_sets_per_match": sums["actual_tiebreak_sets"] / n,
            "tiebreak_share_of_sets": sums["actual_tiebreak_sets"] / actual_sets,
        },
        "simulator": {
            "expected_total_games_per_match": predicted_mean,
            "expected_sets_per_match": predicted_sets / n,
            "expected_games_per_set": predicted_games_per_set,
            "deciding_set_probability": sums["simulator_p_deciding_set"] / n,
            "any_tiebreak_match_probability": sums["simulator_p_any_tiebreak"] / n,
            "expected_tiebreak_sets_per_match": sums["simulator_expected_tiebreak_sets"] / n,
            "tiebreak_share_of_sets": sums["simulator_expected_tiebreak_sets"] / predicted_sets,
        },
        "total_games_bias_decomposition": {
            "observed_reference_set_count_contribution": set_count_contribution,
            "simulated_set_length_contribution": set_length_contribution,
            "sum": set_count_contribution + set_length_contribution,
            "observed_simulator_bias": predicted_mean - actual_mean,
        },
        "gaps_simulator_minus_observed": _structure_differences(sums),
    }
    if bootstrap:
        result["event_cluster_bootstrap_95_ci"] = _bootstrap_structure(rows)
    return result


def summarize_predictive_variance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actual = [row["actual_games"] for row in rows]
    actual_mean = _mean(actual) or 0.0
    observed_variance = _mean([(value - actual_mean) ** 2 for value in actual]) or 0.0
    result = {"observed_total_games_variance": observed_variance, "models": {}}
    for model in MODEL_NAMES:
        means = [row[f"{model}_mean"] for row in rows]
        average_mean = _mean(means) or 0.0
        average_conditional_variance = _mean([row[f"{model}_variance"] for row in rows]) or 0.0
        between_match_variance = _mean([(value - average_mean) ** 2 for value in means]) or 0.0
        result["models"][model] = {
            "mean_conditional_forecast_variance": average_conditional_variance,
            "between_match_forecast_mean_variance": between_match_variance,
            "mixture_predictive_variance": average_conditional_variance + between_match_variance,
            "variance_gap_vs_observed": average_conditional_variance + between_match_variance - observed_variance,
        }
    return result


def paired_cluster_bootstrap(rows: list[dict[str, Any]], challenger: str, baseline: str,
                             metric: str = "crps") -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["event_id"])].append(
            row[f"{challenger}_{metric}"] - row[f"{baseline}_{metric}"]
        )
    keys = list(grouped)
    if not keys:
        return {"mean_difference": math.nan, "ci95_low": math.nan, "ci95_high": math.nan,
                "clusters": 0, "resamples": BOOTSTRAP_RESAMPLES}
    cluster_sums = [sum(grouped[key]) for key in keys]
    cluster_counts = [len(grouped[key]) for key in keys]
    n = sum(cluster_counts)
    observed = sum(cluster_sums) / n
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [rng.randrange(len(keys)) for _ in keys]
        denominator = sum(cluster_counts[i] for i in sample)
        estimates.append(sum(cluster_sums[i] for i in sample) / denominator)
    estimates.sort()
    return {"mean_difference": observed,
            "ci95_low": estimates[int(0.025 * BOOTSTRAP_RESAMPLES)],
            "ci95_high": estimates[int(0.975 * BOOTSTRAP_RESAMPLES) - 1],
            "clusters": len(keys), "resamples": BOOTSTRAP_RESAMPLES}


def summarize(records: list[dict[str, Any]], tour: str, counts: dict[str, int],
              start: int, end: int) -> dict[str, Any]:
    by_year = {str(year): summarize_group([r for r in records if r["year"] == year])
               for year in sorted({r["year"] for r in records})}
    by_surface = {surface: summarize_group([r for r in records if r["surface"] == surface])
                  for surface in sorted({r["surface"] for r in records})}
    by_comp = {bucket: summarize_group([r for r in records if r["competitiveness"] == bucket])
               for bucket in ("under_50", "50_to_149", "150_to_299", "300_plus")}
    by_history = {bucket: summarize_group([r for r in records if r["history_band"] == bucket])
                  for bucket in ("thin_under_300", "middling_300_to_1499", "deep_1500_plus")}
    return {
        "tour": tour,
        "evaluation_start": min((r["date"] for r in records), default=None),
        "evaluation_end": max((r["date"] for r in records), default=None),
        "requested_start": start, "requested_end": end,
        "training_history_start": HISTORY_START,
        "counts": counts,
        "method": "Prior-only date-block walk-forward; exact point-model scoring simulator versus hierarchically shrunk, five-year-decayed empirical total-games distributions.",
        "format_rules": {
            "standard_tiebreak_7": "Best-of-three, 7-point tiebreak at 6-6 in all sets.",
            "grand_slam_final_tiebreak_10": "For 2022 onward Grand Slam BO3 rows, 7-point tiebreaks before the deciding set and 10-point deciding-set tiebreak at 6-6.",
            "match_tiebreak_10": "Bracketed deciding match tiebreak; it adds no games to the total-games target.",
        },
        "scores": summarize_group(records),
        "simulator_structure": summarize_structure(records, bootstrap=True),
        "simulator_structure_by_year": {
            str(year): summarize_structure([r for r in records if r["year"] == year])
            for year in sorted({r["year"] for r in records})
        },
        "predictive_variance_diagnostic": summarize_predictive_variance(records),
        "paired_event_bootstrap_crps_simulator_minus_direct_surface_competitive": paired_cluster_bootstrap(
            records, "simulator", "direct_surface_competitive", "crps"),
        "paired_event_bootstrap_log_score_simulator_minus_direct_surface_competitive": paired_cluster_bootstrap(
            records, "simulator", "direct_surface_competitive", "log_score"),
        "by_year": by_year, "by_surface": by_surface,
        "by_pre_match_competitiveness": by_comp, "by_min_player_point_history": by_history,
        "diagnostic_thresholds_are_not_sportsbook_lines": list(OVER_LINES),
        "evidence_status": "Development backtest. The 2023-2026 winner sample has been inspected; this is a different target, but total-games outcomes must not be called untouched confirmation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", choices=sorted(tpm.TOUR_FILTER), required=True)
    parser.add_argument("--start", type=int, default=TEST_START)
    parser.add_argument("--end", type=int, default=TEST_END)
    parser.add_argument("--out", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args()
    records, counts = run(args.db, args.tour, args.start, args.end)
    if not records:
        raise SystemExit("no eligible total-games forecasts in requested window")
    with open(args.records, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    report = summarize(records, args.tour, counts, args.start, args.end)
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({"tour": args.tour, "counts": counts,
                      "overall": report["scores"],
                      "paired_crps": report["paired_event_bootstrap_crps_simulator_minus_direct_surface_competitive"]},
                     indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
