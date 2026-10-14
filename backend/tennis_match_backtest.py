#!/usr/bin/env python3
"""Step 3: match-level backtest of the point model through the simulator, against Elo.

The rules are frozen in docs/TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md. This script implements them and does
nothing else: it walks the matches in date order, predicts each test match from earlier dates only, and then
scores simulator and Elo on the same matches.

  python3 backend/tennis_match_backtest.py --db <dev DB, read-only> --tour atp --out summary.json --records rows.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from itertools import groupby
from typing import Any

import tennis_match_sim as sim
import tennis_point_model as tpm

FORM_PLAYER_HALF_LIFE = 2.0  # years; chosen on the 2022 validation window in step 1, for both tours
FORM_K = 250.0  # points; chosen on the same window
SEED = 20261014
ELO_START = 1500.0
ELO_K = 32.0
TEST_START, TEST_END = 20230101, 20261231
INCOMPLETE_TOKENS = ("RET", "W/O", "DEF", "ABD")
STANDARD_FORMAT = {"bestOf": 3}  # 7-point tiebreaks at 6-6 in every set, including the final set
BRACKET_FORMAT = {"bestOf": 3, "finalSet": "match_tiebreak", "finalSetTiebreakPoints": 10}
BOOTSTRAP_RESAMPLES = 1000
MIN_BIN = 200
EPS = 1e-9


def load_matches(conn: sqlite3.Connection, tour: str, start: int, end: int) -> list[tuple]:
    """Every main-tour match in [start, end], with or without serve statistics, in date order."""
    sql = (
        f"SELECT tourney_date, surface, winner_id, loser_id, best_of, score, "
        f"w_svpt, w_1stWon, w_2ndWon, l_svpt, l_1stWon, l_2ndWon "
        f"FROM tennis_{tour}_matches WHERE {tpm.TOUR_FILTER[tour]} AND tourney_date BETWEEN ? AND ? "
        f"AND surface IS NOT NULL AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date"
    )
    return list(conn.execute(sql, (start, end)))


def has_serve_stats(row: tuple) -> bool:
    wsv, w1, w2, lsv, l1, l2 = row[6:12]
    return None not in (wsv, w1, w2, lsv, l1, l2) and wsv > 0 and lsv > 0


def is_complete(score: str | None) -> bool:
    return score is not None and not any(tok in score for tok in INCOMPLETE_TOKENS)


def log_loss(p: float, y: int) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def depth_bucket(points: float) -> str:
    if points < 300:
        return "thin"
    if points < 1500:
        return "middling"
    return "deep"


def run(db: str, tour: str, start: int = TEST_START, end: int = TEST_END) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Walk every match in date order. Returns one record per primary test match, plus coverage counts."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = load_matches(conn, tour, 20000101, end)
    finally:
        conn.close()
    rng = random.Random(SEED)
    state = tpm.OnlineStats(baseline_years=0, half_life_years=None, player_half_life=FORM_PLAYER_HALF_LIFE)
    elo: dict[Any, float] = defaultdict(lambda: ELO_START)
    records: list[dict[str, Any]] = []
    counts = defaultdict(int)
    for date, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        state.expire(date)
        in_window = start <= date <= end
        for row in group:
            _, surface, winner, loser, best_of, score = row[:6]
            if not in_window:
                continue
            a_is_winner = rng.random() < 0.5  # one draw per test-window match, in order, whether or not it is scored
            counts["test_matches"] += 1
            if best_of != 3:
                counts["excluded_not_best_of_3"] += 1
                continue
            if not is_complete(score):
                counts["excluded_incomplete_score"] += 1
                continue
            a, b = (winner, loser) if a_is_winner else (loser, winner)
            baseline = state.baseline(surface)
            serve_a = tpm.point_prob(state.serve(a, surface, FORM_K), state.returns(b, surface, FORM_K), baseline)
            serve_b = tpm.point_prob(state.serve(b, surface, FORM_K), state.returns(a, surface, FORM_K), baseline)
            rules = BRACKET_FORMAT if "[" in score else STANDARD_FORMAT
            p_sim = 0.5 * (
                sim.match_distribution(serve_a, serve_b, rules, "A")["p_a"]
                + sim.match_distribution(serve_a, serve_b, rules, "B")["p_a"]
            )
            p_elo = 1.0 / (1.0 + 10 ** ((elo[b] - elo[a]) / 400.0))
            sa, ra = state.effective_points(a, surface)
            sb, rb = state.effective_points(b, surface)
            records.append({
                "tour": tour,
                "date": date,
                "year": date // 10000,
                "surface": surface,
                "bracket_format": "[" in score,
                "has_serve_stats": has_serve_stats(row),
                "depth_points": min(sa, ra, sb, rb),
                "p_sim": p_sim,
                "p_elo": p_elo,
                "y": int(a_is_winner),
            })
            counts["scored"] += 1
            counts["scored_with_serve_stats"] += has_serve_stats(row)
        # Elo deltas use the ratings from before the date group, so same-day matches do not inform each other.
        deltas = []
        for row in group:
            winner, loser = row[2], row[3]
            expected = 1.0 / (1.0 + 10 ** ((elo[loser] - elo[winner]) / 400.0))
            deltas.append((winner, loser, ELO_K * (1.0 - expected)))
        for winner, loser, d in deltas:
            elo[winner] += d
            elo[loser] -= d
        for row in group:
            if has_serve_stats(row):
                state.add((row[0], row[1], row[2], row[3], row[6], row[7], row[8], row[9], row[10], row[11]))
    return records, dict(counts)


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(recs)
    if n == 0:
        return {"n": 0}
    ll_sim = [log_loss(r["p_sim"], r["y"]) for r in recs]
    ll_elo = [log_loss(r["p_elo"], r["y"]) for r in recs]
    bins: list[dict[str, float]] = []
    for i in range(10):
        members = [r for r in recs if min(int(r["p_sim"] * 10), 9) == i]
        bins.append({
            "lo": i / 10,
            "hi": (i + 1) / 10,
            "n": len(members),
            "mean_predicted": sum(r["p_sim"] for r in members) / len(members) if members else math.nan,
            "observed": sum(r["y"] for r in members) / len(members) if members else math.nan,
        })
    return {
        "n": n,
        "log_loss_sim": sum(ll_sim) / n,
        "log_loss_elo": sum(ll_elo) / n,
        "brier_sim": sum(brier(r["p_sim"], r["y"]) for r in recs) / n,
        "brier_elo": sum(brier(r["p_elo"], r["y"]) for r in recs) / n,
        "mean_predicted_sim": sum(r["p_sim"] for r in recs) / n,
        "mean_observed": sum(r["y"] for r in recs) / n,
        "calibration_bins": bins,
        "max_bin_gap_bins_n_at_least_200": max(
            (abs(b["observed"] - b["mean_predicted"]) for b in bins if b["n"] >= MIN_BIN and not math.isnan(b["observed"])),
            default=math.nan,
        ),
    }


def paired_interval(recs: list[dict[str, Any]], seed: int = SEED) -> dict[str, float]:
    """Mean of (simulator minus Elo) log loss, with a 95% paired bootstrap interval over matches."""
    diffs = [log_loss(r["p_sim"], r["y"]) - log_loss(r["p_elo"], r["y"]) for r in recs]
    n = len(diffs)
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES))
    return {
        "mean_difference": sum(diffs) / n,
        "ci_low": means[int(0.025 * BOOTSTRAP_RESAMPLES)],
        "ci_high": means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1],
    }


def decide(recs: list[dict[str, Any]], overall: dict[str, Any], interval: dict[str, float]) -> dict[str, Any]:
    years = sorted({r["year"] for r in recs})
    wins_by_year = {}
    for y in years:
        yr = [r for r in recs if r["year"] == y]
        sim_mean = sum(log_loss(r["p_sim"], r["y"]) for r in yr) / len(yr)
        elo_mean = sum(log_loss(r["p_elo"], r["y"]) for r in yr) / len(yr)
        wins_by_year[y] = sim_mean < elo_mean
    p1 = overall["log_loss_sim"] < overall["log_loss_elo"] and interval["ci_high"] < 0
    p2 = (
        overall["max_bin_gap_bins_n_at_least_200"] <= 0.03
        and abs(overall["mean_predicted_sim"] - overall["mean_observed"]) <= 0.01
    )
    p3 = sum(wins_by_year.values()) >= 3
    return {"P1_predictive_value": p1, "P2_calibration": p2, "P3_stability_years_won": sum(wins_by_year.values()),
            "P3_years": len(years), "P3_stability": p3, "years_sim_better": wins_by_year}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", required=True, choices=sorted(tpm.TOUR_FILTER))
    parser.add_argument("--out", required=True)
    parser.add_argument("--records", required=True)
    args = parser.parse_args(argv)
    print(f"walking {args.tour} matches", file=sys.stderr, flush=True)
    recs, counts = run(args.db, args.tour)
    print(f"scored {len(recs)} matches", file=sys.stderr, flush=True)
    with open(args.records, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)
    overall = summarise(recs)
    interval = paired_interval(recs)
    report = {
        "tour": args.tour,
        "protocol": "docs/TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md",
        "counts": counts,
        "overall": overall,
        "paired_difference_sim_minus_elo": interval,
        "by_year": {str(y): summarise([r for r in recs if r["year"] == y]) for y in sorted({r["year"] for r in recs})},
        "by_surface": {s: summarise([r for r in recs if r["surface"] == s]) for s in sorted({r["surface"] for r in recs})},
        "by_depth": {d: summarise([r for r in recs if depth_bucket(r["depth_points"]) == d])
                     for d in ("thin", "middling", "deep")},
        "by_serve_stats_in_match": {
            "with": summarise([r for r in recs if r["has_serve_stats"]]),
            "without": summarise([r for r in recs if not r["has_serve_stats"]]),
        },
        "by_bracket_format": {
            "bracketed_match_tiebreak": summarise([r for r in recs if r["bracket_format"]]),
            "standard": summarise([r for r in recs if not r["bracket_format"]]),
        },
        "decisions": decide(recs, overall, interval),
    }
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=float)
    print(json.dumps({k: report[k] for k in ("tour", "counts", "decisions")}, indent=2, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
