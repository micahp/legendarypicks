#!/usr/bin/env python3
"""Step 1 of the tennis prediction brief: a point model, P(server wins a point).

For a server X against a returner Y on a surface:
  - X's serve rate and Y's return rate are each shrunk toward the surface baseline b, with prior
    strength k (in points): serve = (won + k*b) / (points + k); return = (won + k*(1-b)) / (points + k).
  - The point probability combines them on the odds scale, relative to the baseline:
        odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b)
  - Two players at baseline (serve = b, return = 1-b) give P = b. A better serve raises P; a better
    return lowers it.

Evaluation is walk-forward. Each match is predicted from matches dated before its date only, and its
result is added afterwards. Player counts are cumulative. The surface baseline is cumulative, or covers
the last `baseline_years` years. k is chosen on the validation window, and the test window is scored
with that k. Only ATP tour-level matches are used here. WTA waits on the tour-level decision (D4).

  python3 tennis_point_model.py --db <db> --tour atp --validate-start 20220101 --test-start 20230101
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict, deque
from itertools import groupby
from typing import Any, Iterable

TOUR_LEVELS = {"atp": ("G", "M", "A", "F")}
K_GRID = (100, 250, 500, 1000, 2000, 4000)
EPS = 1e-6
COLD_START_BASELINE = 0.64  # used only before a surface has any history


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


def _add_player_counts(player: dict, row: tuple) -> None:
    _, surface, winner, loser, wsv, w1, w2, lsv, l1, l2 = row
    ww, lw = w1 + w2, l1 + l2
    pw = player[(winner, surface)]
    pw[0] += ww
    pw[1] += wsv
    pw[2] += lsv - lw
    pw[3] += lsv
    pl = player[(loser, surface)]
    pl[0] += lw
    pl[1] += lsv
    pl[2] += wsv - ww
    pl[3] += wsv


class Stats:
    """Static counts from a set of matches. Used by the unit tests and for a single-window score."""

    def __init__(self, rows: Iterable[tuple]):
        self.surface_won = defaultdict(int)
        self.surface_pts = defaultdict(int)
        self.player = defaultdict(lambda: [0, 0, 0, 0])  # serve_won, serve_pts, return_won, return_pts
        for row in rows:
            _, surface, _, _, wsv, w1, w2, lsv, l1, l2 = row
            self.surface_won[surface] += (w1 + w2) + (l1 + l2)
            self.surface_pts[surface] += wsv + lsv
            _add_player_counts(self.player, row)

    def baseline(self, surface: str) -> float:
        if self.surface_pts[surface] == 0:
            return COLD_START_BASELINE
        return self.surface_won[surface] / self.surface_pts[surface]

    def serve(self, player: Any, surface: str, k: float) -> float:
        won, pts, _, _ = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * self.baseline(surface)) / (pts + k)

    def returns(self, player: Any, surface: str, k: float) -> float:
        _, _, won, pts = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * (1.0 - self.baseline(surface))) / (pts + k)


class OnlineStats:
    """Player counts and surface baseline as they stand before a given date."""

    def __init__(self, baseline_years: int):
        self.baseline_years = baseline_years
        self.player = defaultdict(lambda: [0, 0, 0, 0])
        self.cum_won = defaultdict(int)
        self.cum_pts = defaultdict(int)
        self.win_won = defaultdict(int)
        self.win_pts = defaultdict(int)
        self.window: deque = deque()

    def expire(self, date: int) -> None:
        if not self.baseline_years:
            return
        lower = date - 10000 * self.baseline_years
        while self.window and self.window[0][0] < lower:
            _, surface, won, pts = self.window.popleft()
            self.win_won[surface] -= won
            self.win_pts[surface] -= pts

    def baseline(self, surface: str) -> float:
        if self.baseline_years and self.win_pts[surface] > 0:
            return self.win_won[surface] / self.win_pts[surface]
        if self.cum_pts[surface] > 0:
            return self.cum_won[surface] / self.cum_pts[surface]
        return COLD_START_BASELINE

    def serve(self, player: Any, surface: str, k: float) -> float:
        won, pts, _, _ = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * self.baseline(surface)) / (pts + k)

    def returns(self, player: Any, surface: str, k: float) -> float:
        _, _, won, pts = self.player.get((player, surface), (0, 0, 0, 0))
        return (won + k * (1.0 - self.baseline(surface))) / (pts + k)

    def add(self, row: tuple) -> None:
        date, surface, _, _, wsv, w1, w2, lsv, l1, l2 = row
        won, pts = (w1 + w2) + (l1 + l2), wsv + lsv
        self.cum_won[surface] += won
        self.cum_pts[surface] += pts
        if self.baseline_years:
            self.win_won[surface] += won
            self.win_pts[surface] += pts
            self.window.append((date, surface, won, pts))
        _add_player_counts(self.player, row)


def _accumulate(acc: dict, key: tuple, served: int, won: int, p: float) -> None:
    p = min(max(p, EPS), 1.0 - EPS)
    a = acc.setdefault(key, [0.0, 0, 0, 0.0])  # log loss sum, points, points won, predicted points won
    a[0] += -(won * math.log(p) + (served - won) * math.log(1.0 - p))
    a[1] += served
    a[2] += won
    a[3] += p * served


def score(rows: list[tuple], stats: Stats, k: float | None, mode: str) -> dict[str, float]:
    """Static per-point log loss over one set of matches, for a fixed set of counts (used by the unit tests)."""
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


def walk_forward(rows: list[tuple], validate_start: int, test_start: int, test_end: int, baseline_years: int) -> dict:
    """Predict each match from matches dated earlier, for every k in K_GRID, then add the match."""
    state = OnlineStats(baseline_years)
    acc: dict = {}
    for date, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        state.expire(date)
        if validate_start <= date < test_start:
            window = "validation"
        elif test_start <= date <= test_end:
            window = "test"
        else:
            window = None
        if window:
            for row in group:
                surface, winner, loser = row[1], row[2], row[3]
                wsv, w1, w2, lsv, l1, l2 = row[4:10]
                for server, returner, served, won in (
                    (winner, loser, wsv, w1 + w2),
                    (loser, winner, lsv, l1 + l2),
                ):
                    b = state.baseline(surface)
                    _accumulate(acc, (window, surface, "baseline", None), served, won, b)
                    for k in K_GRID:
                        s = state.serve(server, surface, k)
                        r = state.returns(returner, surface, k)
                        _accumulate(acc, (window, surface, "serve_only", k), served, won, s)
                        _accumulate(acc, (window, surface, "combined", k), served, won, point_prob(s, r, b))
        for row in group:
            state.add(row)
    return acc


def summarise(acc: dict, window: str, mode: str, k: int | None, surface: str | None = None) -> dict[str, float]:
    loss, points, won, predicted = 0.0, 0, 0, 0.0
    for (w, s, m, kk), (lo, pt, wo, pr) in acc.items():
        if w != window or m != mode or kk != k or (surface is not None and s != surface):
            continue
        loss += lo
        points += pt
        won += wo
        predicted += pr
    return {
        "points": points,
        "log_loss_per_point": loss / points,
        "observed_rate": won / points,
        "predicted_rate": predicted / points,
    }


def run(db: str, tour: str, from_date: int, validate_start: int, test_start: int, test_end: int, baseline_years: int = 0) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = load_matches(conn, tour, from_date, test_end)
    finally:
        conn.close()
    acc = walk_forward(rows, validate_start, test_start, test_end, baseline_years)
    grid = {k: summarise(acc, "validation", "combined", k)["log_loss_per_point"] for k in K_GRID}
    best = min(grid, key=grid.get)
    counts = {
        "validation": sum(1 for r in rows if validate_start <= r[0] < test_start),
        "test": sum(1 for r in rows if test_start <= r[0] <= test_end),
    }
    report: dict[str, Any] = {
        "tour": tour,
        "baseline_years": baseline_years,
        "evaluation": "walk-forward",
        "matches": counts,
        "chosen_k": best,
        "validation_log_loss_by_k": grid,
        "test": {
            "baseline": summarise(acc, "test", "baseline", None),
            "serve_only": summarise(acc, "test", "serve_only", best),
            "combined": summarise(acc, "test", "combined", best),
        },
        "test_by_surface": {},
    }
    surfaces = sorted({s for (w, s, _, _) in acc if w == "test"})
    for surface in surfaces:
        report["test_by_surface"][surface] = {
            "baseline": summarise(acc, "test", "baseline", None, surface),
            "combined": summarise(acc, "test", "combined", best, surface),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", default="atp", choices=sorted(TOUR_LEVELS))
    parser.add_argument("--from-date", type=int, default=20000101)
    parser.add_argument("--validate-start", type=int, required=True)
    parser.add_argument("--test-start", type=int, required=True)
    parser.add_argument("--test-end", type=int, default=20261231)
    parser.add_argument("--baseline-years", type=int, default=0, help="years of matches behind the surface baseline; 0 = all history")
    args = parser.parse_args(argv)
    report = run(args.db, args.tour, args.from_date, args.validate_start, args.test_start, args.test_end, args.baseline_years)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
