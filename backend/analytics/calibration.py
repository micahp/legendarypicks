"""Calibration compute (design §3): reliability buckets + Brier score.

Input: list of (p_fair, hit) pairs for settled, de-vig-able props.
"""
import math
from typing import List, Tuple


def brier(pairs: List[Tuple[float, int]]) -> float:
    """mean((p_fair - hit)^2). 0.25 = coin-flip baseline; lower is better."""
    if not pairs:
        return 0.0
    return sum((p - h) ** 2 for p, h in pairs) / len(pairs)


def reliability_buckets(pairs: List[Tuple[float, int]], min_props: int = 10, width: float = 0.05) -> List[dict]:
    """Bucket props by p_fair (default 0.05-wide) -> predicted vs realized."""
    buckets: dict = {}
    for p, h in pairs:
        # clamp to [0, 1), floor to bucket
        idx = min(int(p / width), int(1 / width) - 1)
        buckets.setdefault(idx, []).append((p, h))
    out = []
    for idx in sorted(buckets):
        rows = buckets[idx]
        n = len(rows)
        mean_pred = sum(p for p, _ in rows) / n
        mean_real = sum(h for _, h in rows) / n
        lo = idx * width
        out.append({
            "bucket": f"{lo:.2f}-{lo + width:.2f}",
            "n": n,
            "mean_predicted": round(mean_pred, 4),
            "mean_realized": round(mean_real, 4),
            "error": round(mean_pred - mean_real, 4),
            "confidence": "ok" if n >= min_props else "low",
        })
    return out


def brier_decomposition(pairs: List[Tuple[float, int]], width: float = 0.05) -> dict:
    """Murphy decomposition: Brier = reliability - resolution + uncertainty."""
    n = len(pairs)
    if n == 0:
        return {"reliability": 0.0, "resolution": 0.0, "uncertainty": 0.0}
    base = sum(h for _, h in pairs) / n  # overall hit rate
    uncertainty = base * (1 - base)
    buckets: dict = {}
    for p, h in pairs:
        idx = min(int(p / width), int(1 / width) - 1)
        buckets.setdefault(idx, []).append((p, h))
    reliability = 0.0
    resolution = 0.0
    for rows in buckets.values():
        nk = len(rows)
        mean_pred = sum(p for p, _ in rows) / nk
        mean_real = sum(h for _, h in rows) / nk
        reliability += nk * (mean_pred - mean_real) ** 2
        resolution += nk * (mean_real - base) ** 2
    return {
        "reliability": round(reliability / n, 4),
        "resolution": round(resolution / n, 4),
        "uncertainty": round(uncertainty, 4),
    }
