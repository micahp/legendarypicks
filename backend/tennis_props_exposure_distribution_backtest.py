#!/usr/bin/env python3
"""Walk-forward CRPS comparison for simulated vs empirical service-point distributions.

Research-only while the match-data licence remains unresolved. Example:
  python3 backend/tennis_props_exposure_distribution_backtest.py --db backend/data/picks.dev.db \
    --tour atp --simulations 50 --out /tmp/atp-exposure-dist.json --records /tmp/atp-exposure-dist.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from itertools import groupby
from typing import Any

import tennis_match_sim as sim
import tennis_point_model as tpm

SEED = 20261016
PLAYER_HALF_LIFE_YEARS = 2.0
EXPOSURE_PRIOR_MATCHES = 8.0
TEST_START = 20150101
TEST_END = 20261231
INCOMPLETE_TOKENS = ("RET", "W/O", "DEF", "ABD")
STANDARD_FORMAT = {"bestOf": 3}
BRACKET_FORMAT = {"bestOf": 3, "finalSet": "match_tiebreak", "finalSetTiebreakPoints": 10}


def is_complete(score: str | None) -> bool:
    return score is not None and not any(token in score.upper() for token in INCOMPLETE_TOKENS)


def load_matches(db: str, tour: str, end: int) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return list(conn.execute(
            f"SELECT tourney_date,surface,winner_id,loser_id,best_of,score,"
            f"w_svpt,w_1stWon,w_2ndWon,l_svpt,l_1stWon,l_2ndWon "
            f"FROM tennis_{tour}_matches WHERE {tpm.TOUR_FILTER[tour]} "
            "AND tourney_date>=20000101 AND tourney_date<=? AND surface IS NOT NULL "
            "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date",
            (end,),
        ))
    finally:
        conn.close()


def valid_stats(row: tuple) -> bool:
    wsv, w1, w2, lsv, l1, l2 = row[6:12]
    return (None not in (wsv, w1, w2, lsv, l1, l2)
            and wsv > 0 and lsv > 0 and w1 + w2 <= wsv and l1 + l2 <= lsv)


class EmpiricalExposure:
    """Decayed empirical player/surface count distribution with surface-prior shrinkage."""

    def __init__(self) -> None:
        self.players: dict[tuple[Any, str], tuple[Counter, int]] = {}
        self.surfaces: dict[str, tuple[Counter, int]] = {}

    @staticmethod
    def _decay(days: int) -> float:
        return 0.5 ** (max(0, days) / (PLAYER_HALF_LIFE_YEARS * 365.25))

    @classmethod
    def _at_day(cls, entry: tuple[Counter, int] | None, day: int) -> Counter:
        if entry is None:
            return Counter()
        counts, last_day = entry
        factor = cls._decay(day - last_day)
        return Counter({value: weight * factor for value, weight in counts.items() if weight * factor > 1e-12})

    def distribution(self, player: Any, surface: str, day: int) -> Counter:
        player_counts = self._at_day(self.players.get((player, surface)), day)
        surface_counts = self._at_day(self.surfaces.get(surface), day)
        if not surface_counts:
            pooled = Counter()
            for key, entry in self.surfaces.items():
                pooled.update(self._at_day(entry, day))
            surface_counts = pooled
        if not surface_counts:
            return Counter({80: 1.0})
        n_player = sum(player_counts.values())
        shrink = n_player / (n_player + EXPOSURE_PRIOR_MATCHES)
        n_surface = sum(surface_counts.values())
        forecast = Counter()
        for value, weight in surface_counts.items():
            forecast[value] += (1.0 - shrink) * weight / n_surface
        if n_player:
            for value, weight in player_counts.items():
                forecast[value] += shrink * weight / n_player
        return forecast

    def add(self, player: Any, surface: str, service_points: int, day: int) -> None:
        for store, key in ((self.players, (player, surface)), (self.surfaces, surface)):
            previous = self._at_day(store.get(key), day)
            previous[service_points] += 1.0
            store[key] = (previous, day)


def crps_pmf(pmf: Counter, observed: int) -> float:
    total = sum(pmf.values())
    if total <= 0:
        return math.nan
    first = sum(weight / total * abs(value - observed) for value, weight in pmf.items())
    pair = 0.0
    cumulative_p = cumulative_x = 0.0
    for value, weight in sorted(pmf.items()):
        probability = weight / total
        pair += probability * (value * cumulative_p - cumulative_x)
        cumulative_p += probability
        cumulative_x += probability * value
    return first - pair


def crps_sample(draws: list[int], observed: int) -> float:
    """Unbiased empirical CRPS estimator using the U-statistic pair term."""
    ordered = sorted(draws)
    n = len(ordered)
    if not n:
        return math.nan
    first = sum(abs(value - observed) for value in ordered) / n
    pair = (sum((2 * i - n - 1) * value for i, value in enumerate(ordered, 1)) / (n * (n - 1))
            if n > 1 else 0.0)
    return first - pair


def quantile_sorted(ordered: list[int], level: float) -> int:
    return ordered[min(len(ordered) - 1, max(0, math.ceil(level * len(ordered)) - 1))]


def quantile_pmf(pmf: Counter, level: float) -> int:
    total = sum(pmf.values())
    cumulative = 0.0
    for value, weight in sorted(pmf.items()):
        cumulative += weight / total
        if cumulative >= level:
            return int(value)
    return int(max(pmf))


def run(db: str, tour: str, simulations: int, start: int = TEST_START,
        end: int = TEST_END, seed: int = SEED) -> list[dict[str, Any]]:
    rows = load_matches(db, tour, end)
    point_state = tpm.OnlineStats(baseline_years=0, half_life_years=None,
                                  player_half_life=PLAYER_HALF_LIFE_YEARS)
    direct = EmpiricalExposure()
    orientation_rng = random.Random(SEED)
    simulation_rng = random.Random(seed)
    records: list[dict[str, Any]] = []

    for date, day_rows in groupby(rows, key=lambda row: row[0]):
        day_rows = list(day_rows)
        point_state.expire(date)
        day = tpm._ordinal(date)
        for row in day_rows:
            _, surface, winner, loser, best_of, score = row[:6]
            if not (start <= date <= end and best_of == 3 and is_complete(score) and valid_stats(row)):
                continue
            a_is_winner = orientation_rng.random() < 0.5
            player_a, player_b = (winner, loser) if a_is_winner else (loser, winner)
            actual_a, actual_b = (row[6], row[9]) if a_is_winner else (row[9], row[6])
            baseline = point_state.baseline(surface)
            serve_a = tpm.point_prob(point_state.serve(player_a, surface, 250.0),
                                     point_state.returns(player_b, surface, 250.0), baseline)
            serve_b = tpm.point_prob(point_state.serve(player_b, surface, 250.0),
                                     point_state.returns(player_a, surface, 250.0), baseline)
            rules = BRACKET_FORMAT if "[" in score else STANDARD_FORMAT

            direct_a = direct.distribution(player_a, surface, day)
            direct_b = direct.distribution(player_b, surface, day)
            sim_a: list[int] = []
            sim_b: list[int] = []
            for _ in range(simulations):
                first_server = "A" if simulation_rng.getrandbits(1) else "B"
                result = sim.simulate_match(simulation_rng, serve_a, serve_b, rules, first_server)
                sim_a.append(result["service_points_a"])
                sim_b.append(result["service_points_b"])

            row_record: dict[str, Any] = {
                "tour": tour, "date": date, "year": date // 10000, "surface": surface,
                "sim_crps": (crps_sample(sim_a, actual_a) + crps_sample(sim_b, actual_b)) / 2.0,
                "direct_crps": (crps_pmf(direct_a, actual_a) + crps_pmf(direct_b, actual_b)) / 2.0,
            }
            sorted_sim_a, sorted_sim_b = sorted(sim_a), sorted(sim_b)
            for level, label in ((0.50, "50"), (0.80, "80"), (0.90, "90")):
                sim_hits = sum(
                    quantile_sorted(draws, (1.0 - level) / 2.0) <= actual <=
                    quantile_sorted(draws, 1.0 - (1.0 - level) / 2.0)
                    for draws, actual in ((sorted_sim_a, actual_a), (sorted_sim_b, actual_b))
                )
                direct_hits = sum(
                    quantile_pmf(pmf, (1.0 - level) / 2.0) <= actual <=
                    quantile_pmf(pmf, 1.0 - (1.0 - level) / 2.0)
                    for pmf, actual in ((direct_a, actual_a), (direct_b, actual_b))
                )
                row_record[f"sim_cover_{label}"] = sim_hits / 2.0
                row_record[f"direct_cover_{label}"] = direct_hits / 2.0
            records.append(row_record)

        # Same event-start date remains fully prior-only for both models.
        for row in day_rows:
            _, surface, winner, loser, best_of, score = row[:6]
            if best_of != 3 or not is_complete(score) or not valid_stats(row):
                continue
            wsv, w1, w2, lsv, l1, l2 = row[6:12]
            point_state.add((date, surface, winner, loser, wsv, w1, w2, lsv, l1, l2))
            direct.add(winner, surface, wsv, day)
            direct.add(loser, surface, lsv, day)
    return records


def _paired_crps(records: list[dict[str, Any]]) -> dict[str, float]:
    differences = [row["sim_crps"] - row["direct_crps"] for row in records]
    if not differences:
        return {"sim_minus_direct_crps": math.nan, "ci95_low": math.nan, "ci95_high": math.nan}
    n = len(differences)
    mean = sum(differences) / n
    if n < 2:
        return {"sim_minus_direct_crps": mean, "ci95_low": math.nan, "ci95_high": math.nan}
    variance = sum((value - mean) ** 2 for value in differences) / (n - 1)
    half_width = 1.959963984540054 * math.sqrt(variance / n)
    return {"sim_minus_direct_crps": mean, "ci95_low": mean - half_width, "ci95_high": mean + half_width}


def summarize(records: list[dict[str, Any]], simulations: int, seed: int) -> dict[str, Any]:
    def summarize_group(group: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(group)
        return {
            "matches": n,
            "sim_crps": sum(row["sim_crps"] for row in group) / n if n else math.nan,
            "direct_crps": sum(row["direct_crps"] for row in group) / n if n else math.nan,
            "paired_difference": _paired_crps(group),
            "coverage": {
                model: {level: sum(row[f"{model}_cover_{level}"] for row in group) / n if n else math.nan
                        for level in ("50", "80", "90")}
                for model in ("sim", "direct")
            },
        }

    return {
        "tour": records[0]["tour"] if records else None,
        "simulations_per_match": simulations,
        "simulation_seed": seed,
        "test_start": min((row["date"] for row in records), default=None),
        "test_end": max((row["date"] for row in records), default=None),
        "note": "Full empirical count distributions scored by CRPS; paired normal-theory intervals are preliminary.",
        "overall": summarize_group(records),
        "by_year": {str(year): summarize_group([row for row in records if row["year"] == year])
                    for year in sorted({row["year"] for row in records})},
        "by_surface": {surface: summarize_group([row for row in records if row["surface"] == surface])
                       for surface in sorted({row["surface"] for row in records})},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", required=True, choices=sorted(tpm.TOUR_FILTER))
    parser.add_argument("--start", type=int, default=TEST_START)
    parser.add_argument("--end", type=int, default=TEST_END)
    parser.add_argument("--simulations", type=int, default=50)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args()
    if args.simulations < 2:
        parser.error("--simulations must be at least 2")
    records = run(args.db, args.tour, args.simulations, args.start, args.end, args.seed)
    with open(args.records, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]) if records else [])
        if records:
            writer.writeheader()
            writer.writerows(records)
    summary = summarize(records, args.simulations, args.seed)
    with open(args.out, "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary["overall"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
