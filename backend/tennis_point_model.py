#!/usr/bin/env python3
"""Step 1 of the tennis prediction brief: a point model, P(server wins a point).

For a server X against a returner Y on a surface:
  - X's serve rate and Y's return rate are each shrunk toward the surface baseline b, with prior
    strength k (in points): serve = (won + k*b) / (points + k); return = (won + k*(1-b)) / (points + k).
  - The point probability combines them on the odds scale, relative to the baseline:
        odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b)
  - Two players at baseline (serve = b, return = 1-b) give P = b. A server with a better serve gives a
    higher P; a returner with a better return gives a lower P.

Evaluation is chronological and static. Statistics for a window come only from matches dated before
that window. k is chosen on the validation window; the test window is scored once, with the chosen k.
Only ATP tour-level matches are used here. WTA waits on the tour-level decision (D4).

  python3 tennis_point_model.py --db <db> --tour atp --validate-start 20220101 --test-start 20230101
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from typing import Any, Iterable

TOUR_LEVELS = {"atp": ("G", "M", "A", "F")}
K_GRID = (100, 250, 500, 1000, 2000, 4000)
EPS = 1e-6


def odds(p: float) -> float:
    return p / (1.0 - p)


def point_prob(serve: float, return_opp: float, baseline: float) -> float:
    """P(server wins the point) from the server's serve rate and the returner's return rate."""
    o = odds(serve) * odds(1.0 - return_opp) / odds(baseline)
    return min(max(o / (1.0 + o), EPS), 1.0 - EPS)


def load_matches(conn: sqlite3.Connection, tour: str, start: int, end: int) -> list[tuple]:
    levels = TOUR_LEVELS[tour]
    marks = ",".join("?" for _ in levels)
    sql = (
        f"SELECT tourney_date, surface, winner_id, loser_id, w_svpt, w_1stWon, w_2ndWon, "
        f"l_svpt, l_1stWon, l_2ndWon FROM tennis_{tour}_matches "
        f"WHERE tourney_level IN ({marks}) AND tourney_date BETWEEN ? AND ? "
        f"AND surface IS NOT NULL AND winner_id IS NOT NULL AND loser_id IS NOT NULL "
        f"AND w_svpt > 0 AND l_svpt > 0 AND w_1stWon IS NOT NULL AND w_2ndWon IS NOT NULL "
        f"AND l_1stWon IS NOT NULL AND l_2ndWon IS NOT NULL ORDER BY tourney_date"
    )
    return list(conn.execute(sql, (*levels, start, end)))


class Stats:
    """Surface baselines and per-player, per-surface serve and return counts from a set of matches."""

    def __init__(self, rows: Iterable[tuple]):
        self.surface_won = defaultdict(int)
        self.surface_pts = defaultdict(int)
        self.player = defaultdict(lambda: [0, 0, 0, 0])  # serve_won, serve_pts, return_won, return_pts
        for _, surface, winner, loser, wsv, w1, w2, lsv, l1, l2 in rows:
            ww, lw = w1 + w2, l1 + l2
            self.surface_won[surface] += ww + lw
            self.surface_pts[surface] += wsv + lsv
            pw = self.player[(winner, surface)]
            pw[0] += ww
            pw[1] += wsv
            pw[2] += lsv - lw
            pw[3] += lsv
            pl = self.player[(loser, surface)]
            pl[0] += lw
            pl[1] += lsv
            pl[2] += wsv - ww
            pl[3] += wsv

    def baseline(self, surface: str) -> float:
        return self.surface_won[surface] / self.surface_pts[surface]

    def serve(self, player: Any, surface: str, k: float) -> float:
        b = self.baseline(surface)
        won, pts, _, _ = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * b) / (pts + k)

    def returns(self, player: Any, surface: str, k: float) -> float:
        b = self.baseline(surface)
        _, _, won, pts = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * (1.0 - b)) / (pts + k)


def score(rows: list[tuple], stats: Stats, k: float | None, mode: str) -> dict[str, float]:
    """Per-point log loss and mean predicted vs observed rate, over both servers in every match.

    mode: 'baseline' (surface rate only), 'serve_only' (server's shrunk serve rate only), or 'combined'.
    """
    loss = 0.0
    points = 0
    won_total = 0
    predicted_total = 0.0
    for _, surface, winner, loser, wsv, w1, w2, lsv, l1, l2 in rows:
        for server, returner, served, won in (
            (winner, loser, wsv, w1 + w2),
            (loser, winner, lsv, l1 + l2),
        ):
            b = stats.baseline(surface)
            if mode == "baseline":
                p = b
            elif mode == "serve_only":
                p = stats.serve(server, surface, k)
            else:
                p = point_prob(stats.serve(server, surface, k), stats.returns(returner, surface, k), b)
            p = min(max(p, EPS), 1.0 - EPS)
            loss += -(won * math.log(p) + (served - won) * math.log(1.0 - p))
            points += served
            won_total += won
            predicted_total += p * served
    return {
        "points": points,
        "log_loss_per_point": loss / points,
        "observed_rate": won_total / points,
        "predicted_rate": predicted_total / points,
    }


def choose_k(validation_rows: list[tuple], train_stats: Stats) -> tuple[float, dict[int, float]]:
    results = {}
    for k in K_GRID:
        results[k] = score(validation_rows, train_stats, k, "combined")["log_loss_per_point"]
    best = min(results, key=results.get)
    return best, results


def run(db: str, tour: str, from_date: int, validate_start: int, test_start: int, test_end: int) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        history = load_matches(conn, tour, from_date, test_start - 1)
        validation = [row for row in history if row[0] >= validate_start]
        before_validation = [row for row in history if row[0] < validate_start]
        train_stats = Stats(before_validation)
        k, grid = choose_k(validation, train_stats)

        test = load_matches(conn, tour, test_start, test_end)
        test_stats = Stats(history)
        report: dict[str, Any] = {
            "tour": tour,
            "matches": {"train": len(before_validation), "validation": len(validation), "test": len(test)},
            "chosen_k": k,
            "validation_log_loss_by_k": grid,
            "test": {mode: score(test, test_stats, k, mode) for mode in ("baseline", "serve_only", "combined")},
            "test_by_surface": {},
        }
        for surface in sorted({row[1] for row in test}):
            rows = [row for row in test if row[1] == surface]
            report["test_by_surface"][surface] = {
                mode: score(rows, test_stats, k, mode) for mode in ("baseline", "combined")
            }
        return report
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", default="atp", choices=sorted(TOUR_LEVELS))
    parser.add_argument("--from-date", type=int, default=20000101)
    parser.add_argument("--validate-start", type=int, required=True)
    parser.add_argument("--test-start", type=int, required=True)
    parser.add_argument("--test-end", type=int, default=20261231)
    args = parser.parse_args(argv)
    report = run(args.db, args.tour, args.from_date, args.validate_start, args.test_start, args.test_end)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
