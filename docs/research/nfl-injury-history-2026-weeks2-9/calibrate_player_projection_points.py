#!/usr/bin/env python3
"""Research-only forward calibration of frozen Spec B v2 player point estimates.

Input is the already deduplicated player-game-market file. Never uses target
week outcomes to fit a target week map and never rewrites a frozen model.
Only rows with a historical stat-log participant were included upstream.
"""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATEGIES = ("raw", "add_mean", "add_median", "mult_mean")
PRIOR_N = 100
LOWER_SCALE, UPPER_SCALE = 0.75, 1.40


def load_rows(path):
    rows = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as f:
        for item in csv.DictReader(f):
            key = (int(item["week"]), item["game_id"], item["stable_player_id"], item["market"])
            if key in seen:
                raise ValueError("duplicate player/game/market: " + repr(key))
            seen.add(key)
            value = float(item["projection_mean"])
            actual = float(item["actual"])
            if not math.isfinite(value) or not math.isfinite(actual):
                raise ValueError("nonfinite point or actual: " + repr(key))
            rows.append({
                "week": key[0], "game_id": key[1], "player_id": key[2],
                "market": key[3], "projection": value, "actual": actual,
            })
    if not rows:
        raise ValueError("empty projections input")
    return rows


def fit(prior):
    """Market-only maps; all training rows precede the served target week."""
    n = len(prior)
    if not n:
        return {"n": 0, "shrinkage": 0, "mean_offset": 0, "median_offset": 0,
                "mean_scale": 1}
    residuals = [r["actual"] - r["projection"] for r in prior]
    frac = n / (n + PRIOR_N)
    predicted_total = sum(r["projection"] for r in prior)
    observed_total = sum(r["actual"] for r in prior)
    ratio = observed_total / max(1e-9, predicted_total)
    ratio = max(LOWER_SCALE, min(UPPER_SCALE, ratio))
    return {"n": n, "shrinkage": frac,
            "mean_offset": frac * statistics.mean(residuals),
            "median_offset": frac * statistics.median(residuals),
            "mean_scale": 1 + frac * (ratio - 1)}


def predict(value, params, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("unsupported strategy: " + strategy)
    p = float(value)
    if strategy == "add_mean":
        p += params["mean_offset"]
    elif strategy == "add_median":
        p += params["median_offset"]
    elif strategy == "mult_mean":
        p *= params["mean_scale"]
    return max(0.0, p)


def confidence_interval_improvement(diffs):
    """Normal approximation to player-game-clustered 95% CI for MAE gain."""
    n = len(diffs)
    mean = statistics.mean(d for _, d in diffs)
    grouped = defaultdict(list)
    for game_id, gain in diffs:
        grouped[game_id].append(gain)
    g = len(grouped)
    if g < 2:
        return [None, None], g
    variance = g / (g - 1) * sum(
        (sum(vals) - len(vals) * mean) ** 2 for vals in grouped.values()
    ) / (n * n)
    margin = 1.96 * math.sqrt(max(0.0, variance))
    return [mean - margin, mean + margin], g


def evaluate(rows):
    by_market = defaultdict(list)
    for row in rows:
        by_market[row["market"]].append(row)
    output = {
        "status": "research_only; not deployed or validated on new forward games",
        "input_scope": "distinct 2026 Weeks 2-9 player-game-market rows; stat-log participants only",
        "prior_pseudo_observations": PRIOR_N,
        "methods": {
            "raw": "original frozen prediction",
            "add_mean": "max(0, raw + n/(n+100) * mean(actual - raw) on earlier weeks)",
            "add_median": "max(0, raw + n/(n+100) * median(actual - raw) on earlier weeks)",
            "mult_mean": "max(0, raw * (1 + n/(n+100) * (clamp(sum(actual)/sum(raw),0.75,1.40) - 1)))",
        },
        "evaluation_weeks": list(range(3, 10)),
        "market_results": {},
    }
    prediction_rows = []
    for market, data in sorted(by_market.items()):
        latest = fit(data)
        tested = defaultdict(list)
        differences = defaultdict(list)
        for week in sorted({r["week"] for r in data}):
            past = [r for r in data if r["week"] < week]
            par = fit(past)
            for row in (r for r in data if r["week"] == week):
                candidates = {st: predict(row["projection"], par, st) for st in STRATEGIES}
                rec = {
                    "week": week, "game_id": row["game_id"], "player_id": row["player_id"],
                    "market": market, "fit_rows_before_week": par["n"],
                    "raw": row["projection"], "actual": row["actual"],
                    **{st: candidates[st] for st in STRATEGIES if st != "raw"},
                }
                prediction_rows.append(rec)
                if week < 3:
                    continue
                raw_abs = abs(row["projection"] - row["actual"])
                for st in STRATEGIES:
                    err = candidates[st] - row["actual"]
                    tested[st].append((row["game_id"], err))
                    if st != "raw":
                        differences[st].append((row["game_id"], raw_abs - abs(err)))
        results = {}
        for st in STRATEGIES:
            subset = tested[st]
            results[st] = {
                "n": len(subset),
                "mae": statistics.mean(abs(err) for _, err in subset),
                "rmse": math.sqrt(statistics.mean(err * err for _, err in subset)),
                "mean_bias": statistics.mean(err for _, err in subset),
            }
            if st != "raw":
                ci, g = confidence_interval_improvement(differences[st])
                results[st]["mae_gain_vs_raw"] = statistics.mean(v for _, v in differences[st])
                results[st]["mae_gain_95pct_cluster_ci"] = ci
                results[st]["cluster_count"] = g
        output["market_results"][market] = {
            "all_weeks_rows": len(data), "forward": results,
            "fit_through_week_9_candidate_for_later_weeks": latest,
        }
    return output, sorted(prediction_rows, key=lambda r: (
        r["week"], r["game_id"], r["player_id"], r["market"]
    ))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", type=Path, default=HERE / "player-game-market-projections.csv")
    ap.add_argument("--json", type=Path, default=HERE / "point-projection-calibration-study.json")
    ap.add_argument("--csv", type=Path, default=HERE / "forward-point-calibration.csv")
    args = ap.parse_args()
    result, rows = evaluate(load_rows(args.input))
    args.json.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with args.csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({
        "status": result["status"],
        "rows": len(rows), "markets": len(result["market_results"]),
        "json": str(args.json), "csv": str(args.csv),
    }, indent=2))


if __name__ == "__main__":
    main()
