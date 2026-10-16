#!/usr/bin/env python3
"""Walk-forward test of exact simulator service-point means against direct exposure baselines.

Research-only while the source-data licence remains unresolved. Example:
  python3 backend/tennis_props_exposure_backtest.py --db backend/data/picks.dev.db --tour atp \
    --out /tmp/atp-exposure.json --records /tmp/atp-exposure.csv
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


class DirectExposure:
    """Two-year decayed player/surface mean shrunk to the tour/surface mean."""

    def __init__(self) -> None:
        self.player: dict[tuple[Any, str], list[float]] = {}
        self.surface: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    @staticmethod
    def _decay(days: int) -> float:
        return 0.5 ** (days / (PLAYER_HALF_LIFE_YEARS * 365.25))

    def _player_counts(self, player_id: Any, surface: str, day: int) -> tuple[float, float]:
        entry = self.player.get((player_id, surface))
        if entry is None:
            return 0.0, 0.0
        factor = self._decay(max(0, day - int(entry[2])))
        return entry[0] * factor, entry[1] * factor

    def _surface_counts(self, surface: str, day: int) -> tuple[float, float]:
        entry = self.surface[surface]
        if not entry[2]:
            return 0.0, 0.0
        factor = self._decay(max(0, day - int(entry[2])))
        return entry[0] * factor, entry[1] * factor

    def estimate(self, player_id: Any, surface: str, day: int) -> float:
        total, matches = self._surface_counts(surface, day)
        if matches > 0:
            prior = total / matches
        else:
            by_surface = [self._surface_counts(key, day) for key in self.surface]
            totals = [entry[0] for entry in by_surface if entry[1] > 0]
            counts = [entry[1] for entry in by_surface if entry[1] > 0]
            prior = sum(totals) / sum(counts) if counts else 80.0
        player_total, player_matches = self._player_counts(player_id, surface, day)
        return (player_total + EXPOSURE_PRIOR_MATCHES * prior) / (player_matches + EXPOSURE_PRIOR_MATCHES)

    def add(self, player_id: Any, surface: str, service_points: int, day: int) -> None:
        entry = self.player.get((player_id, surface))
        if entry is None:
            entry = [0.0, 0.0, float(day)]
            self.player[(player_id, surface)] = entry
        factor = self._decay(max(0, day - int(entry[2])))
        entry[0] = entry[0] * factor + service_points
        entry[1] = entry[1] * factor + 1.0
        entry[2] = float(day)

        surface_entry = self.surface[surface]
        factor = self._decay(max(0, day - int(surface_entry[2]))) if surface_entry[2] else 1.0
        surface_entry[0] = surface_entry[0] * factor + service_points
        surface_entry[1] = surface_entry[1] * factor + 1.0
        surface_entry[2] = float(day)


def forecast_simulator(serve_a: float, serve_b: float, rules: dict[str, Any]) -> tuple[float, float]:
    mixed = sim.match_distribution(serve_a, serve_b, rules, None)
    return mixed["expected_service_points_a"], mixed["expected_service_points_b"]


def _valid_stats(row: tuple) -> bool:
    wsv, w1, w2, lsv, l1, l2 = row[6:12]
    return (None not in (wsv, w1, w2, lsv, l1, l2)
            and wsv > 0 and lsv > 0 and w1 + w2 <= wsv and l1 + l2 <= lsv)


def run(db: str, tour: str, start: int = TEST_START, end: int = TEST_END) -> list[dict[str, Any]]:
    rows = load_matches(db, tour, end)
    point_state = tpm.OnlineStats(baseline_years=0, half_life_years=None,
                                  player_half_life=PLAYER_HALF_LIFE_YEARS)
    direct = DirectExposure()
    rng = random.Random(SEED)
    records: list[dict[str, Any]] = []

    for date, day_rows in groupby(rows, key=lambda r: r[0]):
        day_rows = list(day_rows)
        point_state.expire(date)
        day = tpm._ordinal(date)
        for row in day_rows:
            _, surface, winner, loser, best_of, score = row[:6]
            if not (start <= date <= end and best_of == 3 and is_complete(score) and _valid_stats(row)):
                continue
            a_is_winner = rng.random() < 0.5
            player_a, player_b = (winner, loser) if a_is_winner else (loser, winner)
            actual_a, actual_b = (row[6], row[9]) if a_is_winner else (row[9], row[6])
            baseline = point_state.baseline(surface)
            serve_a = tpm.point_prob(point_state.serve(player_a, surface, 250.0),
                                     point_state.returns(player_b, surface, 250.0), baseline)
            serve_b = tpm.point_prob(point_state.serve(player_b, surface, 250.0),
                                     point_state.returns(player_a, surface, 250.0), baseline)
            rules = BRACKET_FORMAT if "[" in score else STANDARD_FORMAT
            sim_a, sim_b = forecast_simulator(serve_a, serve_b, rules)
            direct_a = direct.estimate(player_a, surface, day)
            direct_b = direct.estimate(player_b, surface, day)
            surface_total, surface_matches = direct._surface_counts(surface, day)
            surface_mean = surface_total / surface_matches if surface_matches else direct_a
            records.append({
                "tour": tour, "date": date, "year": date // 10000, "surface": surface,
                "actual_a": actual_a, "actual_b": actual_b,
                "sim_a": sim_a, "sim_b": sim_b,
                "player_rolling_a": direct_a, "player_rolling_b": direct_b,
                "surface_mean_a": surface_mean,
                "surface_mean_b": surface_mean,
                "serve_prob_a": serve_a, "serve_prob_b": serve_b,
                "history_matches_a": direct._player_counts(player_a, surface, day)[1],
                "history_matches_b": direct._player_counts(player_b, surface, day)[1],
            })

        # Update after all same-date forecasts, so no match in an event-start date informs another.
        for row in day_rows:
            _, surface, winner, loser, best_of, score = row[:6]
            if best_of != 3 or not is_complete(score) or not _valid_stats(row):
                continue
            wsv, w1, w2, lsv, l1, l2 = row[6:12]
            point_state.add((date, surface, winner, loser, wsv, w1, w2, lsv, l1, l2))
            direct.add(winner, surface, wsv, day)
            direct.add(loser, surface, lsv, day)
    return records


def _errors(records: list[dict[str, Any]], model: str) -> dict[str, float | int]:
    errors = [r[f"{model}_{side}"] - r[f"actual_{side}"] for r in records for side in ("a", "b")]
    if not errors:
        return {"matches": 0}
    return {
        "matches": len(records), "player_match_targets": len(errors),
        "mae": sum(abs(e) for e in errors) / len(errors),
        "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)),
        "bias_predicted_minus_actual": sum(errors) / len(errors),
    }


def _paired_mae_difference(records: list[dict[str, Any]], baseline: str) -> dict[str, float]:
    """Paired normal-theory interval over match-level MAE differences; negative favors the simulator."""
    differences = [
        (abs(r["sim_a"] - r["actual_a"]) + abs(r["sim_b"] - r["actual_b"])
         - abs(r[f"{baseline}_a"] - r["actual_a"]) - abs(r[f"{baseline}_b"] - r["actual_b"])) / 2.0
        for r in records
    ]
    if not differences:
        return {"mean_sim_minus_baseline_mae": math.nan, "ci95_low": math.nan, "ci95_high": math.nan}
    n = len(differences)
    mean = sum(differences) / n
    if n < 2:
        return {"mean_sim_minus_baseline_mae": mean, "ci95_low": math.nan, "ci95_high": math.nan}
    variance = sum((value - mean) ** 2 for value in differences) / (n - 1)
    half_width = 1.959963984540054 * math.sqrt(variance / n)
    return {"mean_sim_minus_baseline_mae": mean, "ci95_low": mean - half_width, "ci95_high": mean + half_width}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tour": records[0]["tour"] if records else None,
        "test_start": min((r["date"] for r in records), default=None),
        "test_end": max((r["date"] for r in records), default=None),
        "n_matches": len(records),
        "models": {name: _errors(records, name) for name in ("sim", "player_rolling", "surface_mean")},
        "paired_mae_difference": {
            "sim_minus_player_rolling": _paired_mae_difference(records, "player_rolling"),
            "sim_minus_surface_mean": _paired_mae_difference(records, "surface_mean"),
        },
        "by_year": {}, "by_surface": {},
        "note": "Expected-volume scores only; this is not the distributional Gate A decision.",
    }
    for key in sorted({r["year"] for r in records}):
        result["by_year"][str(key)] = {
            name: _errors([r for r in records if r["year"] == key], name)
            for name in ("sim", "player_rolling", "surface_mean")
        }
        year_records = [r for r in records if r["year"] == key]
        result["by_year"][str(key)]["paired_mae_difference"] = {
            "sim_minus_player_rolling": _paired_mae_difference(year_records, "player_rolling"),
        }
    for key in sorted({r["surface"] for r in records}):
        result["by_surface"][key] = {
            name: _errors([r for r in records if r["surface"] == key], name)
            for name in ("sim", "player_rolling", "surface_mean")
        }
        surface_records = [r for r in records if r["surface"] == key]
        result["by_surface"][key]["paired_mae_difference"] = {
            "sim_minus_player_rolling": _paired_mae_difference(surface_records, "player_rolling"),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", required=True, choices=sorted(tpm.TOUR_FILTER))
    parser.add_argument("--start", type=int, default=TEST_START)
    parser.add_argument("--end", type=int, default=TEST_END)
    parser.add_argument("--out", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args()
    records = run(args.db, args.tour, args.start, args.end)
    with open(args.records, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]) if records else [])
        if records:
            writer.writeheader()
            writer.writerows(records)
    summary = summarize(records)
    with open(args.out, "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary["models"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
