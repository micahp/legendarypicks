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
from datetime import date as _date
from itertools import groupby
from typing import Any, Iterable

# Tour-level filter per tour, as SQL over tennis_<tour>_matches. ATP: the four tour levels.
# WTA (approved 2026-10-14): Grand Slams, season-ending, Premier and International, historical Tier I to V,
# and the generic W code only before 2010. From 2010, W also covers WTA 125 events (e.g. "Buenos Aires 125"),
# so those rows wait for review. Excluded: C and CC (ITF and low-tier circuits), numeric ITF prize-money
# codes, D (team competitions), O (Olympics), E (exhibition), J (juniors), and the +H codes.
TOUR_FILTER = {
    "atp": "tourney_level IN ('G', 'M', 'A', 'F')",
    "wta": (
        "(tourney_level IN ('G', 'F', 'P', 'PM', 'I', 'T1', 'T2', 'T3', 'T4', 'T5') "
        "OR (tourney_level = 'W' AND tourney_date < 20100101))"
    ),
}
K_GRID = (100, 250, 500, 1000, 2000, 4000)
EPS = 1e-6
COLD_START_BASELINE = 0.64  # used only before a surface has any history


def _ordinal(yyyymmdd: int) -> int:
    return _date(yyyymmdd // 10000, (yyyymmdd // 100) % 100, yyyymmdd % 100).toordinal()


def odds(p: float) -> float:
    return p / (1.0 - p)


def point_prob(serve: float, return_opp: float, baseline: float) -> float:
    """P(server wins the point) from the server's serve rate and the returner's return rate."""
    o = odds(serve) * odds(1.0 - return_opp) / odds(baseline)
    return min(max(o / (1.0 + o), EPS), 1.0 - EPS)


def load_matches(conn: sqlite3.Connection, tour: str, start: int, end: int) -> list[tuple]:
    sql = (
        f"SELECT tourney_date, surface, winner_id, loser_id, w_svpt, w_1stWon, w_2ndWon, "
        f"l_svpt, l_1stWon, l_2ndWon FROM tennis_{tour}_matches "
        f"WHERE {TOUR_FILTER[tour]} AND tourney_date BETWEEN ? AND ? "
        f"AND surface IS NOT NULL AND winner_id IS NOT NULL AND loser_id IS NOT NULL "
        f"AND w_svpt > 0 AND l_svpt > 0 AND w_1stWon IS NOT NULL AND w_2ndWon IS NOT NULL "
        f"AND l_1stWon IS NOT NULL AND l_2ndWon IS NOT NULL ORDER BY tourney_date"
    )
    return list(conn.execute(sql, (start, end)))


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

    def __init__(self, baseline_years: int, half_life_years: float | None = None):
        self.baseline_years = baseline_years
        self.half_life_years = half_life_years
        self.player = defaultdict(lambda: [0, 0, 0, 0])
        self.cum_won = defaultdict(int)
        self.cum_pts = defaultdict(int)
        self.win_won = defaultdict(int)
        self.win_pts = defaultdict(int)
        self.window: deque = deque()
        self.ew_won = defaultdict(float)  # exponentially weighted, as of ew_day
        self.ew_pts = defaultdict(float)
        self.ew_day: int | None = None

    def expire(self, date: int) -> None:
        day = _ordinal(date)
        if self.half_life_years:
            if self.ew_day is not None and day > self.ew_day:
                factor = 0.5 ** ((day - self.ew_day) / (self.half_life_years * 365.25))
                for surface in list(self.ew_won):
                    self.ew_won[surface] *= factor
                    self.ew_pts[surface] *= factor
            self.ew_day = day
        if self.baseline_years:
            lower = date - 10000 * self.baseline_years
            while self.window and self.window[0][0] < lower:
                _, surface, won, pts = self.window.popleft()
                self.win_won[surface] -= won
                self.win_pts[surface] -= pts

    def baseline(self, surface: str) -> float:
        if self.half_life_years and self.ew_pts[surface] > 0:
            return self.ew_won[surface] / self.ew_pts[surface]
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
        if self.half_life_years:
            self.ew_won[surface] += won
            self.ew_pts[surface] += pts
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


def walk_forward(rows: list[tuple], validate_start: int, test_start: int, test_end: int, baseline_years: int, half_life_years: float | None = None) -> dict:
    """Predict each match from matches dated earlier, for every k in K_GRID, then add the match."""
    state = OnlineStats(baseline_years, half_life_years)
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


def walk_records(rows: list[tuple], validate_start: int, test_start: int, test_end: int, baseline_years: int,
                 half_life_years: float | None, k: float) -> list[tuple]:
    """Per-side records (window, p, served, won) for the combined model, for one (half-life, k) setting."""
    state = OnlineStats(baseline_years, half_life_years)
    records: list[tuple] = []
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
                    p = point_prob(state.serve(server, surface, k), state.returns(returner, surface, k), b)
                    records.append((window, p, served, won))
        for row in group:
            state.add(row)
    return records


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def shift_metrics(records: list[tuple], delta: float) -> dict[str, float]:
    """Log loss, mean predicted and observed rate after adding delta to every logit."""
    loss, served_total, won_total, predicted = 0.0, 0, 0, 0.0
    for _, p, served, won in records:
        q = min(max(_sigmoid(_logit(p) + delta), EPS), 1.0 - EPS)
        loss += -(won * math.log(q) + (served - won) * math.log(1.0 - q))
        served_total += served
        won_total += won
        predicted += q * served
    return {
        "points": served_total,
        "log_loss_per_point": loss / served_total,
        "observed_rate": won_total / served_total,
        "predicted_rate": predicted / served_total,
    }


def fit_shift(records: list[tuple]) -> float:
    """The logit shift that makes the predicted rate equal the observed rate on these records (bisection)."""
    target = sum(won for _, _, _, won in records) / sum(served for _, _, served, _ in records)
    lo, hi = -0.5, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if shift_metrics(records, mid)["predicted_rate"] < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run(db: str, tour: str, from_date: int, validate_start: int, test_start: int, test_end: int,
        half_lives: tuple[float, ...] = (0.0,), baseline_years: int = 0) -> dict[str, Any]:
    """Choose (half-life, k) on the validation window, then score the test window once with that choice.

    A half-life of 0 means a cumulative baseline (no time weighting).
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = load_matches(conn, tour, from_date, test_end)
    finally:
        conn.close()
    results: dict[float, dict[str, Any]] = {}
    for h in half_lives:
        acc = walk_forward(rows, validate_start, test_start, test_end, baseline_years, h or None)
        grid = {k: summarise(acc, "validation", "combined", k)["log_loss_per_point"] for k in K_GRID}
        best_k = min(grid, key=grid.get)
        results[h] = {"acc": acc, "validation_by_k": grid, "best_k": best_k}
    best_h = min(results, key=lambda h: results[h]["validation_by_k"][results[h]["best_k"]])
    chosen = results[best_h]
    acc, k = chosen["acc"], chosen["best_k"]
    counts = {
        "validation": sum(1 for r in rows if validate_start <= r[0] < test_start),
        "test": sum(1 for r in rows if test_start <= r[0] <= test_end),
    }
    records = walk_records(rows, validate_start, test_start, test_end, 0, best_h or None, k)
    val_records = [r for r in records if r[0] == "validation"]
    test_records = [r for r in records if r[0] == "test"]
    delta = fit_shift(val_records)
    report: dict[str, Any] = {
        "tour": tour,
        "evaluation": "walk-forward",
        "matches": counts,
        "chosen": {"half_life_years": best_h, "k": k},
        "calibration": {
            "validation_logit_shift": delta,
            "validation_uncalibrated": shift_metrics(val_records, 0.0),
            "test_uncalibrated": shift_metrics(test_records, 0.0),
            "test_calibrated": shift_metrics(test_records, delta),
        },
        "validation_log_loss_by_half_life": {
            str(h): results[h]["validation_by_k"][results[h]["best_k"]] for h in half_lives
        },
        "validation_best_k_by_half_life": {str(h): results[h]["best_k"] for h in half_lives},
        "test": {
            "baseline": summarise(acc, "test", "baseline", None),
            "serve_only": summarise(acc, "test", "serve_only", k),
            "combined": summarise(acc, "test", "combined", k),
        },
        "test_combined_by_half_life": {
            str(h): summarise(results[h]["acc"], "test", "combined", results[h]["best_k"]) for h in half_lives
        },
        "test_by_surface": {},
    }
    surfaces = sorted({s for (w, s, _, _) in acc if w == "test"})
    for surface in surfaces:
        report["test_by_surface"][surface] = {
            "baseline": summarise(acc, "test", "baseline", None, surface),
            "combined": summarise(acc, "test", "combined", k, surface),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", default="atp", choices=sorted(TOUR_FILTER))
    parser.add_argument("--from-date", type=int, default=20000101)
    parser.add_argument("--validate-start", type=int, required=True)
    parser.add_argument("--test-start", type=int, required=True)
    parser.add_argument("--test-end", type=int, default=20261231)
    parser.add_argument("--half-lives", default="0,0.5,1,2,4", help="comma-separated half-lives in years; 0 = cumulative baseline")
    args = parser.parse_args(argv)
    half_lives = tuple(float(x) for x in args.half_lives.split(","))
    report = run(args.db, args.tour, args.from_date, args.validate_start, args.test_start, args.test_end, half_lives)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
