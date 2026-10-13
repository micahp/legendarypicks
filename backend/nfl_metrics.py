"""nfl_metrics.py -- scoring functions for the NFL backtest (SPEC A, 6.1 and the A3 questions).

Pure functions, no database. Conventions, fixed here so every report uses the same ones:
- Probabilities are P(home wins). Outcomes are 1 (home won) or 0 (away won). Ties are excluded
  by the caller and counted separately; these functions never see a tie.
- `spread_line` is the home team's expected margin: positive means the home team is favored.
  The home team covers when actual_margin > spread_line; equal is a push.
- Moneylines are American odds. The market probability is de-vigged by proportional
  normalization of the two implied probabilities. This is a stated choice, not the only one.
"""
from __future__ import annotations

import math
import random

EPS = 1e-12
CALIBRATION_MIN_N = 20


def brier(probs, outcomes):
    n = len(probs)
    if n == 0 or n != len(outcomes):
        raise ValueError("probs and outcomes must be the same non-zero length")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / n


def log_loss(probs, outcomes):
    n = len(probs)
    if n == 0 or n != len(outcomes):
        raise ValueError("probs and outcomes must be the same non-zero length")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(max(p, EPS), 1.0 - EPS)
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / n


def mae(pred, actual):
    n = len(pred)
    if n == 0 or n != len(actual):
        raise ValueError("pred and actual must be the same non-zero length")
    return sum(abs(p - a) for p, a in zip(pred, actual)) / n


def american_to_prob(odds):
    """Implied probability of one American moneyline, before removing the vig."""
    if odds is None:
        raise ValueError("odds is None")
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds < 0:
        return -odds / (-odds + 100.0)
    return 100.0 / (odds + 100.0)


def devig_home_prob(home_ml, away_ml):
    """Fair P(home wins) from a two-sided moneyline, proportional de-vig."""
    ph = american_to_prob(home_ml)
    pa = american_to_prob(away_ml)
    return ph / (ph + pa)


def calibration_bins(probs, outcomes, width=0.1):
    """Rows of (lo, hi, n, wins, win_rate, flagged). flagged = n < CALIBRATION_MIN_N.

    A probability of exactly 1.0 falls in the last bin. Empty bins are returned with n = 0.
    """
    if width <= 0 or width > 1:
        raise ValueError("width must be in (0, 1]")
    k = int(round(1.0 / width))
    bins = [[0, 0] for _ in range(k)]
    for p, y in zip(probs, outcomes):
        idx = min(int(p / width), k - 1)
        bins[idx][0] += 1
        bins[idx][1] += y
    rows = []
    for i, (n, wins) in enumerate(bins):
        lo, hi = i * width, (i + 1) * width
        rate = wins / n if n else None
        rows.append((round(lo, 10), round(hi, 10), n, wins, rate, n < CALIBRATION_MIN_N))
    return rows


def ats_result(actual_margin, spread_line):
    """'cover', 'miss' or 'push' for the home side against its spread."""
    diff = actual_margin - spread_line
    if abs(diff) < 1e-9:
        return "push"
    return "cover" if diff > 0 else "miss"


def ats_record(actual_margins, spread_lines):
    """Counts and cover rate, pushes excluded from the rate and reported separately."""
    if len(actual_margins) != len(spread_lines):
        raise ValueError("length mismatch")
    counts = {"cover": 0, "miss": 0, "push": 0}
    for m, s in zip(actual_margins, spread_lines):
        counts[ats_result(m, s)] += 1
    decided = counts["cover"] + counts["miss"]
    counts["cover_rate"] = counts["cover"] / decided if decided else None
    return counts


def bootstrap_mean_diff_ci(loss_a, loss_b, reps=10000, seed=20261009, alpha=0.05):
    """Paired bootstrap 95% interval for mean(loss_a - loss_b), resampling games.

    Returns (point_estimate, lo, hi). An interval that excludes zero is the evidence; the
    point estimate alone is not.
    """
    n = len(loss_a)
    if n == 0 or n != len(loss_b):
        raise ValueError("loss lists must be the same non-zero length")
    diffs = [a - b for a, b in zip(loss_a, loss_b)]
    point = sum(diffs) / n
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * reps)]
    hi = means[min(reps - 1, int((1 - alpha / 2) * reps))]
    return point, lo, hi
