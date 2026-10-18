#!/usr/bin/env python3
"""Calibration of the direct Gamma-Poisson P0 and P1 count forecasts on identical player-match rows.

Track B, Gate B follow-up: finish calibration before any direct incumbent is selected. The replay in
backend/tennis_props_rate_backtest.py is run unchanged. Two read-only hooks record, for each forecast
distribution of the two Gamma-Poisson models, the CDF at the observed count and the upper-tail probabilities at
the replay's own thresholds. Headline CRPS and log score come from the replay's own score_pmf output.

Randomized PIT: U = F(y-1) + V * (F(y) - F(y-1)), with V ~ Uniform(0, 1) from a fixed seed. For a calibrated
forecast, U is Uniform(0, 1).

  python3 -I research/tennis/props/2026-10-18/gp_calibration.py --db <dev DB, opened read-only> \
      --tour atp --out <json>

Paired differences are P1 minus P0 on the same rows. Negative CRPS or log-score differences favour P1.
Intervals resample tournament events (event_id) with replacement, 1,000 times.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_props_rate_backtest as rb  # noqa: E402

FAMILIES = ("p0_gamma_poisson", "p1_gamma_poisson")
THRESHOLDS = (1, 2, 4, 6, 8, 10)
SEED = 20261018
REPS = 1000

_captured: list[tuple[int, float, float, dict[int, float]]] = []
_blocks: deque[dict[str, tuple[int, float, float, dict[int, float]]]] = deque()


def _score_hook(pmf, observed):
    below = sum(pmf[:observed])
    tails = {k: 1.0 - sum(pmf[:k]) for k in THRESHOLDS}  # P(Y >= k)
    _captured.append((observed, below, below + pmf[observed], tails))
    return _orig_score(pmf, observed)


def _forecast_hook(*args, **kwargs):
    _captured.clear()
    out, scores = _orig_forecast(*args, **kwargs)
    if len(_captured) != len(rb.MODEL_NAMES):
        raise RuntimeError(f"expected {len(rb.MODEL_NAMES)} score calls per forecast, got {len(_captured)}")
    _blocks.append(dict(zip(rb.MODEL_NAMES, list(_captured))))
    return out, scores


_orig_score = rb.score_pmf
_orig_forecast = rb.forecast_target


def collect(db: str, tour: str) -> dict[str, np.ndarray]:
    rb.score_pmf = _score_hook
    rb.forecast_target = _forecast_hook
    rng = np.random.default_rng(SEED)
    cols: dict[str, list] = defaultdict(list)
    for row in rb.run(db, tour):
        block = _blocks.popleft()
        actual = row["actual"]
        cols["target"].append(row["target"])
        cols["year"].append(row["year"])
        cols["event"].append(row["event_id"])
        cols["surface"].append(row["surface"])
        cols["band"].append(row["history_band"])
        cols["actual"].append(actual)
        cols["p1_mean"].append(row["p1_gamma_poisson_mean"])
        for fam in FAMILIES:
            observed, below, at, tails = block[fam]
            if observed != actual:
                raise RuntimeError("hook and replay disagree on the observed count")
            cols[f"{fam}_crps"].append(row[f"{fam}_crps"])
            cols[f"{fam}_log"].append(row[f"{fam}_log_score"])
            for level in ("50", "80", "90"):
                cols[f"{fam}_c{level}"].append(row[f"{fam}_cover_{level}"])
            cols[f"{fam}_pit"].append(below + rng.uniform() * (at - below))
            for k in THRESHOLDS:
                cols[f"{fam}_tail{k}"].append(tails[k])
    if _blocks:
        raise RuntimeError("unconsumed forecast blocks after the replay")
    rb.score_pmf = _orig_score
    rb.forecast_target = _orig_forecast
    return {name: np.asarray(values) for name, values in cols.items()}


def pit_summary(pit: np.ndarray) -> dict:
    n = len(pit)
    ordered = np.sort(pit)
    ranks = np.arange(1, n + 1)
    ks = max(float(np.max(ranks / n - ordered)), float(np.max(ordered - (ranks - 1) / n)))
    bins = np.histogram(pit, bins=10, range=(0.0, 1.0))[0] / n
    return {
        "mean_pit": float(pit.mean()),
        "decile_shares": [round(float(x), 4) for x in bins],
        "ks_distance": round(ks, 4),
        "share_below_0.05": round(float(np.mean(pit < 0.05)), 4),
        "share_above_0.95": round(float(np.mean(pit > 0.95)), 4),
    }


def cluster_interval(values: np.ndarray, events: np.ndarray, seed: list[int]) -> dict:
    _, inverse = np.unique(events, return_inverse=True)
    k = inverse.max() + 1
    sums = np.bincount(inverse, weights=values, minlength=k)
    counts = np.bincount(inverse, minlength=k).astype(float)
    draws = np.random.default_rng(seed).integers(0, k, size=(REPS, k))
    estimates = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    estimates.sort()
    return {
        "mean": round(float(values.mean()), 5),
        "ci95": [round(float(estimates[int(0.025 * (REPS - 1))]), 5),
                 round(float(estimates[int(0.975 * (REPS - 1))]), 5)],
        "events": int(k),
    }


def family_slice(cols: dict[str, np.ndarray], mask: np.ndarray, target: str, fam: str) -> dict:
    out = {"n": int(mask.sum()), "events": int(len(np.unique(cols["event"][mask])))}
    out["crps"] = round(float(cols[f"{fam}_crps"][mask].mean()), 5)
    out["log_score"] = round(float(cols[f"{fam}_log"][mask].mean()), 5)
    for level in ("50", "80", "90"):
        out[f"coverage_{level}"] = round(float(cols[f"{fam}_c{level}"][mask].mean()), 4)
    out["pit"] = pit_summary(cols[f"{fam}_pit"][mask])
    reliability = {}
    actual = cols["actual"][mask]
    for k in rb.TARGET_THRESHOLDS[target]:
        predicted = cols[f"{fam}_tail{k}"][mask]
        observed = (actual >= k).astype(float)
        reliability[f">={k}"] = {
            "predicted": round(float(predicted.mean()), 4),
            "observed": round(float(observed.mean()), 4),
            "gap_observed_minus_predicted": round(float(observed.mean() - predicted.mean()), 4),
        }
    out["threshold_reliability"] = reliability
    return out


def slices(cols: dict[str, np.ndarray], target: str) -> tuple[dict[str, np.ndarray], list[float]]:
    target_mask = cols["target"] == target
    year = cols["year"]
    result = {"all": target_mask, "window_2019_2026": target_mask & (year >= 2019)}
    for y in sorted(set(year.tolist())):
        result[f"year_{y}"] = target_mask & (year == y)
    for surface in sorted(set(cols["surface"].tolist())):
        result[f"surface_{surface}"] = target_mask & (cols["surface"] == surface)
    for band in ("cold_lt10", "mid_10_40", "deep_ge40"):
        result[f"history_{band}"] = target_mask & (cols["band"] == band)
    # Forecast-size quartiles use the predicted P1 mean only. Banding on the observed count would select on the
    # outcome and make PIT, coverage and paired scores within a band meaningless as calibration checks.
    mean = cols["p1_mean"]
    edges = [float(x) for x in np.quantile(mean[target_mask], [0.25, 0.5, 0.75])]
    bounds = [-np.inf] + edges + [np.inf]
    for i in range(4):
        result[f"forecast_mean_q{i + 1}"] = target_mask & (mean > bounds[i]) & (mean <= bounds[i + 1])
    return result, edges


def summarise(cols: dict[str, np.ndarray]) -> dict:
    report: dict = {}
    for target in ("aces", "double_faults"):
        per_target: dict = {}
        masks, edges = slices(cols, target)
        per_target["_forecast_mean_quartile_edges_p1"] = [round(x, 4) for x in edges]
        for name, mask in masks.items():
            if mask.sum() == 0:
                continue
            entry = {fam: family_slice(cols, mask, target, fam) for fam in FAMILIES}
            events = cols["event"][mask]
            d_crps = cols["p1_gamma_poisson_crps"][mask] - cols["p0_gamma_poisson_crps"][mask]
            d_log = cols["p1_gamma_poisson_log"][mask] - cols["p0_gamma_poisson_log"][mask]
            # Seeds depend on the slice name, so each interval does not move when slices are added or reordered.
            seed = [SEED + 1, zlib.crc32(f"{target}/{name}".encode())]
            entry["p1_minus_p0"] = {
                "crps": cluster_interval(d_crps, events, seed),
                "log_score": cluster_interval(d_log, events, [seed[0], seed[1] + 1]),
            }
            per_target[name] = entry
        report[target] = per_target
    return report


def headline_check(cols: dict[str, np.ndarray]) -> dict:
    check = {}
    for target in ("aces", "double_faults"):
        mask = cols["target"] == target
        check[target] = {
            fam: {"n": int(mask.sum()),
                  "crps": round(float(cols[f"{fam}_crps"][mask].mean()), 4),
                  "log_score": round(float(cols[f"{fam}_log"][mask].mean()), 4)}
            for fam in FAMILIES
        }
    return check


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", required=True, choices=sorted(rb.tpm.TOUR_FILTER))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    cols = collect(args.db, args.tour)
    result = {
        "tour": args.tour,
        "rows": int(len(cols["target"])),
        "replay_totals": headline_check(cols),
        "slices": summarise(cols),
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.tour}: {result['rows']} player-match target rows written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
