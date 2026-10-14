#!/usr/bin/env python3
"""Step 1 of the tennis prediction brief: a point model, P(server wins a point).

For a server X against a returner Y on a surface:
  - X's serve rate and Y's return rate are each shrunk toward the surface baseline b, with prior
    strength k (in points): serve = (won + k*b) / (points + k); return = (won + k*(1-b)) / (points + k).
  - The point probability combines them on the odds scale, relative to the baseline:
        odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b)
  - Form: each player's serve and return counts are exponentially weighted toward recent matches, with a
    half-life in years (0 = cumulative).
  - Rest: each side's days since its last match fall in a bucket. The bucket coefficients are added to the
    server's logit, and the returner's coefficients enter with the opposite sign. They are fitted on
    validation by logistic regression, and the intercept also absorbs any level shift.
    Caveat: the data has no match dates. tourney_date is the event start, shared by all of a player's matches
    in that event, so "rest" here is the days between event starts. The 0 to 3 day bucket is empty by construction
    (14 of 17,611 consecutive event-start gaps, ATP 2018 to 2022). Read the rest result as an event-gap effect,
    not as rest.

Evaluation is walk-forward. Each match is predicted from matches dated before its date only, and its
result is added afterwards. The player half-life and k come from the validation window. The rest coefficients
are fitted on validation, and the test window is scored once.

Tour filters are in TOUR_FILTER. WTA follows the main-tour rule approved on 2026-10-14.

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

# Tour-level filter per tour, as SQL over tennis_<tour>_matches.
# ATP: the four tour levels. WTA (approved 2026-10-14): Grand Slams, season-ending, Premier and International,
# historical Tier I to V, and the generic W code before 2010. From 2010, W is decided event by event, by tourney_id,
# from the WTA's own pages and Wikipedia (checked 2026-10-14). Excluded: C and CC (ITF and low-tier circuits),
# numeric ITF prize-money codes, D (team competitions), O (Olympics), E (exhibition), J (juniors), and the +H codes.
WTA_W_MAIN_TOUR_IDS_FROM_2010 = (
    "2015-W-WT-SIN-01A-2015",  # WTA Finals 2015: main tour (no serve stats, so it adds no matches to the model)
    "2021-2033",  # Charleston 2 (MUSC Health Women's Open), 12-18 Apr: WTA 250
    "2021-2035",  # Belgrade, 17 May: Serbia Open, WTA 250
    "2021-406",  # Strasbourg, 24 May: WTA 250 (Wikipedia; one wtatennis URL says 500; main tour either way)
    "2021-2017",  # Bad Homburg, 21 June: WTA 250
    "2021-710",  # Eastbourne, 21 June: WTA 500
    "2021-703",  # San Jose, 2 Aug: WTA 500
    "2021-2040",  # Cleveland, 23 Aug: WTA 250
    "2021-2047",  # Chicago 1 (Chicago Women's Open), 23 Aug: WTA 250 (wtatennis chicago-250)
    # Excluded, WTA 125: "2021-2041" Parma (wtatennis parma-125) and "2024-2052" Buenos Aires 125.
)
_WTA_W_IDS = ", ".join(f"'{tid}'" for tid in WTA_W_MAIN_TOUR_IDS_FROM_2010)
TOUR_FILTER = {
    "atp": "tourney_level IN ('G', 'M', 'A', 'F')",
    "wta": (
        "(tourney_level IN ('G', 'F', 'P', 'PM', 'I', 'T1', 'T2', 'T3', 'T4', 'T5') "
        f"OR (tourney_level = 'W' AND (tourney_date < 20100101 OR tourney_id IN ({_WTA_W_IDS}))))"
    ),
}
K_GRID = (100, 250, 500, 1000, 2000, 4000)
PLAYER_HALF_LIVES = (0.0, 0.5, 1.0, 2.0)  # years; 0 = cumulative player counts
EPS = 1e-6
COLD_START_BASELINE = 0.64  # used only before a surface has any history

# Rest buckets: 0 = up to 3 days, 1 = 4 to 7, 2 = 8 to 14 (reference), 3 = 15 or more, 4 = no earlier match.
REST_REFERENCE = 2
REST_NO_MATCH = 4
REST_FEATURES = (0, 1, 3, 4)  # buckets with their own coefficient, in the order of REST_NAMES
REST_NAMES = ("rest_0_3_days", "rest_4_7_days", "rest_15_plus_days", "rest_no_earlier_match")
N_REST = 1 + 2 * len(REST_FEATURES)  # intercept, server bucket coefficients, returner bucket coefficients


def _ordinal(yyyymmdd: int) -> int:
    return _date(yyyymmdd // 10000, (yyyymmdd // 100) % 100, yyyymmdd % 100).toordinal()


def odds(p: float) -> float:
    return p / (1.0 - p)


def point_prob(serve: float, return_opp: float, baseline: float) -> float:
    """P(server wins the point) from the server's serve rate and the returner's return rate."""
    o = odds(serve) * odds(1.0 - return_opp) / odds(baseline)
    return min(max(o / (1.0 + o), EPS), 1.0 - EPS)


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def load_matches(conn: sqlite3.Connection, tour: str, start: int, end: int, by_level: bool = False) -> list[tuple]:
    """Tour-level matches in [start, end]. With by_level, the surface field becomes 'surface|level', so every
    baseline and shrinkage target is per surface and tournament level. Everything downstream is unchanged."""
    surface_field = "surface || '|' || tourney_level" if by_level else "surface"
    sql = (
        f"SELECT tourney_date, {surface_field} AS surface, winner_id, loser_id, w_svpt, w_1stWon, w_2ndWon, "
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


def rest_bucket(day: int | None, last_day: int | None) -> int:
    if day is None or last_day is None:
        return REST_NO_MATCH
    gap = day - last_day
    if gap <= 3:
        return 0
    if gap <= 7:
        return 1
    if gap <= 14:
        return REST_REFERENCE
    return 3


class OnlineStats:
    """Player counts, surface baseline and rest, as they stand before a given date.

    Surface baseline: cumulative, or over the last `baseline_years` years, or exponentially weighted with
    `half_life_years`. Player counts: cumulative, or exponentially weighted with `player_half_life` years.
    Player weighting is applied lazily, so a count is decayed only when it is read or written.
    """

    def __init__(self, baseline_years: int, half_life_years: float | None = None, player_half_life: float | None = None):
        self.baseline_years = baseline_years
        self.half_life_years = half_life_years
        self.player_half_life = player_half_life
        self.player: dict[tuple, list] = {}  # (player, surface) -> [serve_won, serve_pts, return_won, return_pts, day]
        self.last_day: dict[Any, int] = {}
        self.cum_won = defaultdict(int)
        self.cum_pts = defaultdict(int)
        self.win_won = defaultdict(int)
        self.win_pts = defaultdict(int)
        self.window: deque = deque()
        self.ew_won = defaultdict(float)  # exponentially weighted, as of ew_day
        self.ew_pts = defaultdict(float)
        self.ew_day: int | None = None
        self.today: int | None = None

    def expire(self, date: int) -> None:
        day = _ordinal(date)
        self.today = day
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

    def _counts(self, player: Any, surface: str) -> tuple[float, float, float, float]:
        entry = self.player.get((player, surface))
        if entry is None:
            return (0.0, 0.0, 0.0, 0.0)
        factor = 1.0
        if self.player_half_life and self.today is not None and self.today > entry[4]:
            factor = 0.5 ** ((self.today - entry[4]) / (self.player_half_life * 365.25))
        return (entry[0] * factor, entry[1] * factor, entry[2] * factor, entry[3] * factor)

    def serve(self, player: Any, surface: str, k: float) -> float:
        b = self.baseline(surface)
        won, pts, _, _ = self._counts(player, surface)
        return (won + k * b) / (pts + k)

    def returns(self, player: Any, surface: str, k: float) -> float:
        b = self.baseline(surface)
        _, _, won, pts = self._counts(player, surface)
        return (won + k * (1.0 - b)) / (pts + k)

    def rest(self, player: Any) -> int:
        return rest_bucket(self.today, self.last_day.get(player))

    def effective_points(self, player: Any, surface: str) -> tuple[float, float]:
        """Serve and return points behind the estimate, after any player-level decay."""
        _, serve_pts, _, return_pts = self._counts(player, surface)
        return serve_pts, return_pts

    def add(self, row: tuple) -> None:
        date, surface, winner, loser, wsv, w1, w2, lsv, l1, l2 = row
        self.expire(date)  # a no-op when the caller has already expired this date
        ww, lw = w1 + w2, l1 + l2
        won, pts = ww + lw, wsv + lsv
        self.cum_won[surface] += won
        self.cum_pts[surface] += pts
        if self.half_life_years:
            self.ew_won[surface] += won
            self.ew_pts[surface] += pts
        if self.baseline_years:
            self.win_won[surface] += won
            self.win_pts[surface] += pts
            self.window.append((date, surface, won, pts))
        for player, delta in (
            (winner, (ww, wsv, lsv - lw, lsv)),
            (loser, (lw, lsv, wsv - ww, wsv)),
        ):
            current = self._counts(player, surface)
            self.player[(player, surface)] = [
                current[0] + delta[0], current[1] + delta[1], current[2] + delta[2], current[3] + delta[3], self.today,
            ]
            self.last_day[player] = self.today


def _accumulate(acc: dict, key: tuple, served: int, won: int, p: float) -> None:
    p = min(max(p, EPS), 1.0 - EPS)
    a = acc.setdefault(key, [0.0, 0, 0, 0.0])  # log loss sum, points, points won, predicted points won
    a[0] += -(won * math.log(p) + (served - won) * math.log(1.0 - p))
    a[1] += served
    a[2] += won
    a[3] += p * served


def _window_of(date: int, validate_start: int, test_start: int, test_end: int) -> str | None:
    if validate_start <= date < test_start:
        return "validation"
    if test_start <= date <= test_end:
        return "test"
    return None


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


def walk_forward(rows: list[tuple], validate_start: int, test_start: int, test_end: int, baseline_years: int,
                 half_life_years: float | None = None, player_half_life: float | None = None) -> dict:
    """Predict each match from matches dated earlier, for every k in K_GRID, then add the match."""
    state = OnlineStats(baseline_years, half_life_years, player_half_life)
    acc: dict = {}
    for date, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        state.expire(date)
        window = _window_of(date, validate_start, test_start, test_end)
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


def walk_detail(rows: list[tuple], validate_start: int, test_start: int, test_end: int, baseline_years: int,
                half_life_years: float | None, player_half_life: float | None, k: float) -> list[tuple]:
    """Per-side records (window, p, served, won, server_rest, returner_rest) for one (player half-life, k) choice.
    p is the combined form model, before any rest term. Rest buckets are read before the group's matches are added."""
    state = OnlineStats(baseline_years, half_life_years, player_half_life)
    records: list[tuple] = []
    for date, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        state.expire(date)
        window = _window_of(date, validate_start, test_start, test_end)
        if window:
            for row in group:
                surface, winner, loser = row[1], row[2], row[3]
                wsv, w1, w2, lsv, l1, l2 = row[4:10]
                rest_w, rest_l = state.rest(winner), state.rest(loser)
                for server, returner, served, won, rs, rr in (
                    (winner, loser, wsv, w1 + w2, rest_w, rest_l),
                    (loser, winner, lsv, l1 + l2, rest_l, rest_w),
                ):
                    b = state.baseline(surface)
                    p = point_prob(state.serve(server, surface, k), state.returns(returner, surface, k), b)
                    records.append((window, p, served, won, rs, rr))
        for row in group:
            state.add(row)
    return records


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


def rest_features(rs: int, rr: int) -> list[float]:
    """Intercept, then the server's bucket indicators, then the returner's (with the opposite sign)."""
    x = [1.0]
    x += [1.0 if rs == b else 0.0 for b in REST_FEATURES]
    x += [-1.0 if rr == b else 0.0 for b in REST_FEATURES]
    return x


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def fit_rest(records: list[tuple], iterations: int = 30) -> list[float]:
    """Logistic coefficients for the rest buckets, by Newton's method on the records, with the logit of the
    form probability as an offset. The intercept also absorbs any level shift."""
    theta = [0.0] * N_REST
    for _ in range(iterations):
        grad = [0.0] * N_REST
        hess = [[0.0] * N_REST for _ in range(N_REST)]
        for _, p, served, won, rs, rr in records:
            x = rest_features(rs, rr)
            nz = [i for i in range(N_REST) if x[i]]
            q = _sigmoid(_logit(p) + sum(theta[i] * x[i] for i in nz))
            for i in nz:
                grad[i] += (won - served * q) * x[i]
                for j in nz:
                    hess[i][j] += served * q * (1.0 - q) * x[i] * x[j]
        for i in range(N_REST):
            hess[i][i] += 1e-9
        step = _solve(hess, grad)
        theta = [t + s for t, s in zip(theta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return theta


def shift_metrics(records: list[tuple], delta: float, theta: list[float] | None = None) -> dict[str, float]:
    """Log loss, mean predicted and observed rate. Adds delta to every logit, or the rest term if theta is given."""
    loss, served_total, won_total, predicted = 0.0, 0, 0, 0.0
    for _, p, served, won, rs, rr in records:
        if theta is None:
            z = _logit(p) + delta
        else:
            z = _logit(p) + sum(t * xi for t, xi in zip(theta, rest_features(rs, rr)))
        q = min(max(_sigmoid(z), EPS), 1.0 - EPS)
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
    target = sum(won for _, _, _, won, _, _ in records) / sum(served for _, _, served, _, _, _ in records)
    lo, hi = -0.5, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if shift_metrics(records, mid)["predicted_rate"] < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run(db: str, tour: str, from_date: int, validate_start: int, test_start: int, test_end: int,
        player_half_lives: tuple[float, ...] = PLAYER_HALF_LIVES, by_level: bool = False) -> dict[str, Any]:
    """Choose (player half-life, k) on validation, fit the form calibration and the rest coefficients on
    validation, then score the test window once."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = load_matches(conn, tour, from_date, test_end, by_level)
    finally:
        conn.close()

    by_half_life: dict[float, dict[str, Any]] = {}
    for h in player_half_lives:
        acc = walk_forward(rows, validate_start, test_start, test_end, 0, None, h or None)
        grid = {k: summarise(acc, "validation", "combined", k)["log_loss_per_point"] for k in K_GRID}
        best_k = min(grid, key=grid.get)
        by_half_life[h] = {"acc": acc, "validation_by_k": grid, "best_k": best_k}
    best_h = min(by_half_life, key=lambda h: by_half_life[h]["validation_by_k"][by_half_life[h]["best_k"]])
    k = by_half_life[best_h]["best_k"]
    acc = by_half_life[best_h]["acc"]

    records = walk_detail(rows, validate_start, test_start, test_end, 0, None, best_h or None, k)
    val_records = [r for r in records if r[0] == "validation"]
    test_records = [r for r in records if r[0] == "test"]
    delta = fit_shift(val_records)
    theta = fit_rest(val_records)

    counts = {
        "validation": sum(1 for r in rows if validate_start <= r[0] < test_start),
        "test": sum(1 for r in rows if test_start <= r[0] <= test_end),
    }
    names = ["intercept"] + [f"server_{n}" for n in REST_NAMES] + [f"returner_{n}" for n in REST_NAMES]
    report: dict[str, Any] = {
        "tour": tour,
        "by_level": by_level,
        "evaluation": "walk-forward",
        "matches": counts,
        "chosen": {"player_half_life_years": best_h, "k": k},
        "validation_log_loss_by_player_half_life": {
            str(h): by_half_life[h]["validation_by_k"][by_half_life[h]["best_k"]] for h in player_half_lives
        },
        "validation_best_k_by_player_half_life": {str(h): by_half_life[h]["best_k"] for h in player_half_lives},
        "test_baseline": summarise(acc, "test", "baseline", None),
        "test_serve_only": summarise(acc, "test", "serve_only", k),
        "test_combined": summarise(acc, "test", "combined", k),
        "test_combined_by_player_half_life": {
            str(h): summarise(by_half_life[h]["acc"], "test", "combined", by_half_life[h]["best_k"]) for h in player_half_lives
        },
        "form_calibration": {
            "validation_logit_shift": delta,
            "test_uncalibrated": shift_metrics(test_records, 0.0),
            "test_calibrated": shift_metrics(test_records, delta),
        },
        "rest": {
            "coefficients": dict(zip(names, theta)),
            "validation_in_sample": shift_metrics(val_records, 0.0, theta),
            "test": shift_metrics(test_records, 0.0, theta),
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
    parser.add_argument("--player-half-lives", default="0,0.5,1,2", help="comma-separated player half-lives in years; 0 = cumulative")
    parser.add_argument("--by-level", action="store_true", help="key the baseline and shrinkage by surface and tournament level")
    args = parser.parse_args(argv)
    half_lives = tuple(float(x) for x in args.player_half_lives.split(","))
    report = run(args.db, args.tour, args.from_date, args.validate_start, args.test_start, args.test_end, half_lives,
                 by_level=args.by_level)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
