#!/usr/bin/env python3
"""Select the direct incumbent for aces, double faults and total games, per tour (Track B, tennis).

Frozen candidates only. Counts: C0 (reference), then P0 and P1 Poisson and Gamma-Poisson, from the replay in
backend/tennis_props_rate_backtest.py. Total games: direct format (reference), direct surface, direct surface plus
competitiveness, and the point simulator, from backend/tennis_total_games_backtest.py. Both replays run unchanged.
Read-only hooks on their scoring and forecast functions capture each forecast's full distribution.

Every forecast is prior-only: a match is forecast from matches dated before its event-start date. Matches dated
before WINDOW_START only build state (fit data) and are not scored. Retirements, walkovers, defaults and
abandonments are excluded from scoring and from state, as in both replays. The rules and verdicts are in RESULTS.md.

  python3 -I research/tennis/counts-2026-10-20/run_counts_eval.py --db <path to picks.dev.db> [--tour atp]

Writes summary.json, TABLES.md and predictions/*.csv.gz next to this file. Opens the database read-only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import time
import zlib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_props_rate_backtest as rb  # noqa: E402
import tennis_total_games_backtest as tgb  # noqa: E402

HERE = Path(__file__).resolve().parent
TOURS = ("atp", "wta")
COUNT_TARGETS = ("aces", "double_faults")
YEARS = (2023, 2024, 2025, 2026)
WINDOW_START = 20230101
COUNT_START = 20140101  # the rolling replay's start: C0 needs the prior calendar year
GAMES_HISTORY_START = 20000101  # rolling-origin protocol: total-games histograms start in 2000
REPS = 1000
BOOT_SEED = 20261020
PIT_SEED = 20261020
COUNT_MODELS = ("C0", "p0_poisson", "p0_gamma_poisson", "p1_poisson", "p1_gamma_poisson")
COUNT_REF = "C0"
GAMES_MODELS = ("direct_format", "direct_surface", "direct_surface_competitive", "simulator")
GAMES_REF = "direct_format"
NOMINAL = {"50": 0.50, "80": 0.80, "90": 0.90}
# Declared tolerances. Fixed before the run; see RESULTS.md.
MIN_ROWS = 5000
MIN_MATCHES = 2000
MIN_SIGN_YEARS = 3
KS_MAX = 0.02
TAIL_BAND = (0.04, 0.06)
COVER_SLACK = 0.02
P95_MAX = 0.06
P99_MAX = 0.015
THRESH_GAP_MAX = 0.02
TRIM_MASS = 1e-12


def event_code(tour: str, event: Any) -> int:
    return zlib.crc32(f"{tour}:{event}".encode())


def book_lines(fit_mean: float) -> tuple[float, float, float]:
    """Three half-integer lines centred on the half-integer at or below the fit-period mean."""
    centre = math.floor(fit_mean) + 0.5
    return (centre - 1.0, centre, centre + 1.0)


def over_threshold(line: float) -> int:
    """First integer count that is over the line (P(Y > line) = P(Y >= threshold))."""
    return int(math.floor(line)) + 1


def distribution_metrics(pmf: np.ndarray, support_start: int, observed: int, uniform: float,
                         thresholds: list[int]) -> dict[str, Any]:
    cdf = np.cumsum(pmf)
    index = observed - support_start
    below = float(cdf[index - 1]) if index > 0 else 0.0
    tails = []
    for threshold in thresholds:
        j = threshold - support_start
        tails.append(1.0 if j <= 0 else float(max(0.0, 1.0 - cdf[min(j - 1, len(cdf) - 1)])))
    return {
        "pit": below + uniform * (float(cdf[index]) - below),
        "q95": support_start + int(np.searchsorted(cdf, 0.95)),
        "q99": support_start + int(np.searchsorted(cdf, 0.99)),
        "tail": tails,
        "mean": float(np.dot(pmf, np.arange(support_start, support_start + len(pmf)))),
    }


def pit_summary(pit: np.ndarray) -> dict[str, Any]:
    n = len(pit)
    ordered = np.sort(pit)
    ranks = np.arange(1, n + 1)
    ks = max(float(np.max(ranks / n - ordered)), float(np.max(ordered - (ranks - 1) / n)))
    deciles = np.histogram(pit, bins=10, range=(0.0, 1.0))[0] / n
    return {
        "mean": float(pit.mean()),
        "decile_shares": [round(float(x), 4) for x in deciles],
        "ks": round(ks, 4),
        "share_below_0.05": round(float(np.mean(pit < 0.05)), 4),
        "share_above_0.95": round(float(np.mean(pit > 0.95)), 4),
    }


def cluster_ci(diff: np.ndarray, clusters: np.ndarray) -> dict[str, Any]:
    """Cluster bootstrap of the mean paired difference. The same draws are used for every comparison in a cell."""
    codes, inverse = np.unique(clusters, return_inverse=True)
    k = codes.size
    sums = np.bincount(inverse, weights=diff, minlength=k)
    counts = np.bincount(inverse, minlength=k).astype(float)
    rng = np.random.default_rng(BOOT_SEED)
    estimates = np.empty(REPS)
    for start in range(0, REPS, 100):
        draws = rng.integers(0, k, size=(min(100, REPS - start), k))
        estimates[start:start + draws.shape[0]] = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    low, high = np.percentile(estimates, [2.5, 97.5])
    return {"diff": round(float(diff.mean()), 6), "ci95": [round(float(low), 6), round(float(high), 6)],
            "clusters": int(k)}


# ----------------------------------------------------------------------------- counts

def run_counts(db: str, tour: str) -> dict[str, Any]:
    """One replay pass per tour. Returns scored window rows (both targets) and fit-period means."""
    captured: list[list[float]] = []
    blocks: deque[dict[str, list[float]]] = deque()
    orig_score, orig_forecast = rb.score_pmf, rb.forecast_target

    def score_hook(pmf, observed):
        captured.append(list(pmf))
        return orig_score(pmf, observed)

    def forecast_hook(*args, **kwargs):
        captured.clear()
        out, scores = orig_forecast(*args, **kwargs)
        if len(captured) != len(rb.MODEL_NAMES):
            raise RuntimeError(f"expected {len(rb.MODEL_NAMES)} score calls per forecast, got {len(captured)}")
        blocks.append(dict(zip(rb.MODEL_NAMES, captured)))
        return out, scores

    prior_sum: dict[tuple, float] = defaultdict(float)
    prior_n: dict[tuple, int] = defaultdict(int)
    fit_sum: dict[str, float] = defaultdict(float)
    fit_n: dict[str, int] = defaultdict(int)
    pending: dict[str, tuple[int, str, Any]] = {}
    match_counter: dict[str, int] = defaultdict(int)
    rows: dict[str, list[dict[str, Any]]] = {target: [] for target in COUNT_TARGETS}
    uniform_rng = np.random.default_rng(PIT_SEED)
    leak_flags: dict[str, int] = defaultdict(int)
    n_rows = 0

    rb.score_pmf, rb.forecast_target = score_hook, forecast_hook
    try:
        for row in rb.run(db, tour, start=COUNT_START, end=rb.TEST_END):
            block = blocks.popleft()
            target, year, date, actual = row["target"], row["year"], row["date"], row["actual"]
            surface = row["surface"]
            n_rows += 1
            key_surface, key_tour = (year - 1, target, surface), (year - 1, target)
            pmfs = {}
            if year >= 2015:  # C0 needs a prior calendar year; the rolling pipeline starts it in 2015
                if prior_n.get(key_surface):
                    mean = prior_sum[key_surface] / prior_n[key_surface]
                else:
                    mean = prior_sum[key_tour] / prior_n[key_tour]
                mean = max(mean, 0.05)
                pmfs["C0"] = rb.poisson_pmf(mean, actual)
            pmfs.update({model: block[model] for model in rb.MODEL_NAMES})
            if year < 2023:
                fit_sum[target] += actual
                fit_n[target] += 1
            else:
                for name, pmf in pmfs.items():  # leakage check on scored rows only
                    arr = np.asarray(pmf, dtype=float)
                    pmf_mean = float(np.dot(arr, np.arange(arr.size)))
                    pmf_sd = math.sqrt(max(0.0, float(np.dot(arr, (np.arange(arr.size) - pmf_mean) ** 2))))
                    if actual > pmf_mean + 12.0 * pmf_sd + 30.0:
                        leak_flags[name] += 1
                uniform = float(uniform_rng.uniform())
                if target in pending:
                    match_id, first_date, first_event = pending.pop(target)
                    if (first_date, first_event) != (date, row["event_id"]):
                        raise RuntimeError("count rows are not paired by match")
                else:
                    match_counter[target] += 1
                    match_id = match_counter[target]
                    pending[target] = (match_id, date, row["event_id"])
                rows[target].append({
                    "tour": tour, "target": target, "date": date, "year": year,
                    "event": event_code(tour, row["event_id"]), "event_id": row["event_id"],
                    "match": event_code(tour, f"{row['event_id']}|{date}|{target}|{match_id}"),
                    "player_id": row["player_id"], "surface": surface, "band": row["history_band"],
                    "observed": actual, "support_start": 0, "uniform": uniform,
                    "pmfs": {name: np.asarray(pmf, dtype=float) for name, pmf in pmfs.items()},
                })
            prior_sum[(year, target, surface)] += actual
            prior_n[(year, target, surface)] += 1
            prior_sum[(year, target)] += actual
            prior_n[(year, target)] += 1
    finally:
        rb.score_pmf, rb.forecast_target = orig_score, orig_forecast
    if blocks or pending:
        raise RuntimeError("unconsumed forecast blocks or unpaired rows after the replay")
    return {
        "rows": rows,
        "fit_mean": {target: fit_sum[target] / fit_n[target] for target in COUNT_TARGETS},
        "fit_rows": {target: fit_n[target] for target in COUNT_TARGETS},
        "replay_rows_seen": n_rows,
        "cap_driven_rows": dict(leak_flags),
    }


# ----------------------------------------------------------------------------- total games

def games_fit_mean(db: str, tour: str) -> tuple[float, int]:
    total = count = 0
    for row in tgb.load_matches(db, tour, WINDOW_START - 1):
        date, _, name, level, _, _, _, best_of, score = row[:9]
        if date < GAMES_HISTORY_START or best_of != 3 or not tgb.is_complete(score):
            continue
        tagged = tgb.score_format(score, level, name, date)
        if tagged is None:
            continue
        games = tgb.total_games_from_score(score, tagged[0])
        if games is not None:
            total += games
            count += 1
    return total / count, count


def run_games(db: str, tour: str) -> dict[str, Any]:
    captured: list[list[float]] = []
    orig_scores = tgb.pmf_scores
    orig_history = tgb.HISTORY_START

    def scores_hook(pmf, support, observed):
        captured.append(list(pmf))
        return orig_scores(pmf, support, observed)

    tgb.HISTORY_START = GAMES_HISTORY_START
    tgb.pmf_scores = scores_hook
    try:
        records, _ = tgb.run(db, tour, start=WINDOW_START, end=tgb.TEST_END)
    finally:
        tgb.pmf_scores = orig_scores
        tgb.HISTORY_START = orig_history
    if len(captured) != len(tgb.MODEL_NAMES) * len(records):
        raise RuntimeError("total-games hook and replay disagree on the number of scored distributions")
    uniform_rng = np.random.default_rng(PIT_SEED)
    rows = []
    for index, record in enumerate(records):
        support = tgb.support_for(record["format"])
        base = len(tgb.MODEL_NAMES) * index
        pmfs = {model: np.asarray(captured[base + j], dtype=float) for j, model in enumerate(tgb.MODEL_NAMES)}
        rows.append({
            "tour": tour, "target": "games", "date": record["date"], "year": record["year"],
            "event": event_code(tour, record["event_id"]), "event_id": record["event_id"],
            "match": event_code(tour, f"{record['event_id']}|{record['date']}|games|{index}"),
            "player_id": "", "surface": record["surface"], "format": record["format"],
            "band": record["history_band"], "observed": record["actual_games"],
            "support_start": support[0], "uniform": float(uniform_rng.uniform()), "pmfs": pmfs,
        })
    return {"rows": rows, "records": len(records)}


# ----------------------------------------------------------------------------- cell evaluation

def arrays_for(rows: list[dict[str, Any]], model: str, kind: str, lines: tuple[float, ...]) -> dict[str, Any]:
    thresholds = [over_threshold(line) for line in lines]
    out: dict[str, list] = defaultdict(list)
    for row in rows:
        pmf = row["pmfs"][model]
        observed = row["observed"]
        support_start = row["support_start"]
        if kind == "games":
            support = tuple(range(support_start, support_start + pmf.size))
            scores = tgb.pmf_scores(pmf.tolist(), support, observed)
            crps, log_score = scores["crps"], scores["log_score"]
            covers = {level: scores[f"cover_{level}"] for level in NOMINAL}
        else:
            scores = rb.score_pmf(pmf.tolist(), observed)
            crps, log_score = scores["crps"], scores["log_score"]
            covers = {level: scores[f"cover_{level}"] for level in NOMINAL}
        metrics = distribution_metrics(pmf, support_start, observed, row["uniform"], thresholds)
        out["crps"].append(crps)
        out["log"].append(log_score)
        for level in NOMINAL:
            out[f"cover_{level}"].append(covers[level])
        out["pit"].append(metrics["pit"])
        out["exceed_p95"].append(float(observed > metrics["q95"]))
        out["exceed_p99"].append(float(observed > metrics["q99"]))
        out["mean"].append(metrics["mean"])
        out["observed"].append(observed)
        for j, threshold in enumerate(thresholds):
            out[f"tail_{j}"].append(metrics["tail"][j])
            out[f"brier_{j}"].append((metrics["tail"][j] - float(observed >= threshold)) ** 2)
            out[f"obs_{j}"].append(float(observed >= threshold))
    return {key: np.asarray(values, dtype=float) for key, values in out.items()}


def summarise_model(arr: dict[str, Any], rows: list[dict[str, Any]], lines: tuple[float, ...]) -> dict[str, Any]:
    years = np.asarray([row["year"] for row in rows])
    events = np.asarray([row["event"] for row in rows])
    summary: dict[str, Any] = {
        "n": int(arr["crps"].size),
        "events": int(np.unique(events).size),
        "crps": round(float(arr["crps"].mean()), 6),
        "log_score": round(float(arr["log"].mean()), 6),
        "mean_predicted": round(float(arr["mean"].mean()), 4),
        "mean_observed": round(float(arr["observed"].mean()), 4),
        "coverage": {level: round(float(arr[f"cover_{level}"].mean()), 4) for level in NOMINAL},
        "pit": pit_summary(arr["pit"]),
        "tail_exceed": {"p95": round(float(arr["exceed_p95"].mean()), 4),
                        "p99": round(float(arr["exceed_p99"].mean()), 4)},
        "threshold": [],
        "crps_by_year": {str(y): round(float(arr["crps"][years == y].mean()), 6) for y in YEARS
                         if np.any(years == y)},
    }
    for j, line in enumerate(lines):
        predicted = float(arr[f"tail_{j}"].mean())
        observed = float(arr[f"obs_{j}"].mean())
        summary["threshold"].append({
            "line": line, "threshold": over_threshold(line), "predicted": round(predicted, 4),
            "observed": round(observed, 4), "gap": round(observed - predicted, 4),
            "brier": round(float(arr[f"brier_{j}"].mean()), 6),
        })
    return summary


def calibration(model_summary: dict[str, Any]) -> dict[str, Any]:
    pit = model_summary["pit"]
    checks = {
        "pit_ks": pit["ks"] <= KS_MAX,
        "pit_tail_low": TAIL_BAND[0] <= pit["share_below_0.05"] <= TAIL_BAND[1],
        "pit_tail_high": TAIL_BAND[0] <= pit["share_above_0.95"] <= TAIL_BAND[1],
        "coverage": all(model_summary["coverage"][level] >= NOMINAL[level] - COVER_SLACK for level in NOMINAL),
        "tail_p95": model_summary["tail_exceed"]["p95"] <= P95_MAX,
        "tail_p99": model_summary["tail_exceed"]["p99"] <= P99_MAX,
        "thresholds": all(abs(t["gap"]) <= THRESH_GAP_MAX for t in model_summary["threshold"]),
    }
    checks["all_pass"] = all(checks.values())
    return checks


def paired(arr_a: dict[str, Any], arr_b: dict[str, Any], rows: list[dict[str, Any]], years_arr: np.ndarray,
           lines_count: int) -> dict[str, Any]:
    clusters = np.asarray([row["event"] for row in rows])
    match_clusters = np.asarray([row["match"] for row in rows])
    out: dict[str, Any] = {}
    for key, label in (("crps", "crps"), ("log", "log_score")):
        diff = arr_a[key] - arr_b[key]
        out[label] = {
            "event_cluster": cluster_ci(diff, clusters),
            "match_cluster": cluster_ci(diff, match_clusters),
            "negative_years": int(sum(1 for y in YEARS if np.any(years_arr == y)
                                      and diff[years_arr == y].mean() < 0)),
            "years": int(sum(1 for y in YEARS if np.any(years_arr == y))),
        }
    out["threshold_brier"] = []
    for j in range(lines_count):
        diff = arr_a[f"brier_{j}"] - arr_b[f"brier_{j}"]
        out["threshold_brier"].append(cluster_ci(diff, clusters))
    return out


def decide(cell: dict[str, Any], models: tuple[str, ...], ref: str) -> dict[str, Any]:
    crps = {m: cell["models"][m]["crps"] for m in models}
    if cell["n_rows"] < MIN_ROWS or cell["n_matches"] < MIN_MATCHES or any(
            cell["rows_by_year"].get(str(y), 0) == 0 for y in YEARS):
        return {"verdict": "INSUFFICIENT_DATA", "winner": None, "runner_up": None, "calibrated": None,
                "clear_over_reference": []}
    clear = [m for m in models if m != ref and cell["vs_ref"][m]["crps"]["event_cluster"]["ci95"][1] < 0
             and cell["vs_ref"][m]["crps"]["negative_years"] >= MIN_SIGN_YEARS]
    if not clear:
        return {"verdict": "NOT_ADOPTED", "winner": None, "runner_up": None, "calibrated": None,
                "clear_over_reference": []}
    top = min(clear, key=lambda m: crps[m])
    runner = min((m for m in models if m != top), key=lambda m: crps[m])
    head_to_head = cell["head_to_head"][f"{top}-{runner}"]["crps"]
    beats_runner = (head_to_head["event_cluster"]["ci95"][1] < 0
                    and head_to_head["negative_years"] >= MIN_SIGN_YEARS)
    calibrated = cell["calibration"][top]["all_pass"]
    verdict = "ADOPT_CANDIDATE" if beats_runner and calibrated else "INCONCLUSIVE"
    return {"verdict": verdict, "winner": top, "runner_up": runner, "calibrated": calibrated,
            "clear_over_reference": clear, "beats_runner_up": beats_runner}


def evaluate_cell(rows: list[dict[str, Any]], kind: str, models: tuple[str, ...], ref: str,
                  lines: tuple[float, ...]) -> dict[str, Any]:
    arrays = {model: arrays_for(rows, model, kind, lines) for model in models}
    years_arr = np.asarray([row["year"] for row in rows])
    n_matches = len({row["match"] for row in rows})
    cell: dict[str, Any] = {
        "n_rows": len(rows), "n_matches": n_matches, "lines": list(lines),
        "rows_by_year": {str(y): int(np.sum(years_arr == y)) for y in YEARS},
        "bands": {b: int(sum(1 for row in rows if row["band"] == b)) for b in sorted({r["band"] for r in rows})},
        "surfaces": {s: int(sum(1 for row in rows if row["surface"] == s))
                     for s in sorted({r["surface"] for r in rows})},
        "models": {}, "calibration": {}, "vs_ref": {}, "head_to_head": {},
    }
    for model in models:
        cell["models"][model] = summarise_model(arrays[model], rows, lines)
        cell["calibration"][model] = calibration(cell["models"][model])
    for model in models:
        if model != ref:
            cell["vs_ref"][model] = paired(arrays[model], arrays[ref], rows, years_arr, len(lines))
    cell["pooled_order"] = sorted(models, key=lambda m: cell["models"][m]["crps"])
    for top in models:
        for runner in models:
            if top != runner:
                cell["head_to_head"][f"{top}-{runner}"] = paired(arrays[top], arrays[runner], rows, years_arr,
                                                                 len(lines))
    cell["decision"] = decide(cell, models, ref)
    cell["prediction_model"] = cell["pooled_order"][0]
    return cell


def write_predictions(rows: list[dict[str, Any]], model: str, path: Path, kind: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["tour", "target", "model", "date", "year", "event_id", "player_id", "surface", "format",
              "history_band", "observed", "support_start", "mean", "pmf"]
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            pmf = row["pmfs"][model]
            keep = np.nonzero(pmf > TRIM_MASS)[0]
            first, last = int(keep[0]), int(keep[-1])
            trimmed = pmf[first:last + 1]
            start = row["support_start"] + first
            writer.writerow([
                row["tour"], row["target"], model, row["date"], row["year"], row["event_id"], row["player_id"],
                row["surface"], row.get("format", ""), row["band"], row["observed"], start,
                f"{float(np.dot(pmf, np.arange(row['support_start'], row['support_start'] + pmf.size))):.9g}",
                ";".join(f"{value:.9g}" for value in trimmed),
            ])
    return len(rows)


# ----------------------------------------------------------------------------- anchors

def anchors(tour: str, count_cells: dict[str, Any], games_cell: dict[str, Any]) -> dict[str, Any]:
    """Reproduction checks against committed outputs. Any mismatch stops the run."""
    rolling = json.loads((ROOT / "research/tennis/rolling/2026-10-18/rolling_summary.json").read_text())
    checks: dict[str, Any] = {}
    for target, cell in count_cells.items():
        block = rolling["counts_aces" if target == "aces" else "counts_double_faults"]["models"]
        for year in YEARS:
            published = block[f"{tour}_{year}"]["mean"]
            for model in COUNT_MODELS:
                got = cell["models"][model]["crps_by_year"][str(year)]
                if abs(got - published[model]) > 1e-6:
                    raise RuntimeError(f"{tour} {target} {model} {year}: CRPS {got} vs rolling {published[model]}")
        checks[f"counts_{target}_per_year_vs_rolling"] = "match"
    published_games = rolling["games"]["models"]
    for year in YEARS:
        for model in GAMES_MODELS:
            got = games_cell["models"][model]["crps_by_year"][str(year)]
            expected = published_games[f"{tour}_{year}"]["mean"][model]
            if abs(got - expected) > 1e-6:
                raise RuntimeError(f"{tour} games {model} {year}: CRPS {got} vs rolling {expected}")
    checks["games_per_year_vs_rolling"] = "match"
    pooled = json.loads((ROOT / f"research/tennis/total-games/2026-10-16/{tour}.json").read_text())
    simulator_pooled = pooled["scores"]["models"]["simulator"]["crps"]
    got = games_cell["models"]["simulator"]["crps"]
    if round(got, 4) != round(simulator_pooled, 4):
        raise RuntimeError(f"{tour} simulator pooled CRPS {got} vs 2026-10-16 JSON {simulator_pooled}")
    checks["simulator_pooled_vs_2026-10-16_json"] = {"got": round(got, 4), "published": simulator_pooled}
    return checks


# ----------------------------------------------------------------------------- rendering

def render_tables(summary: dict[str, Any]) -> str:
    lines_out = ["# Generated tables", "",
                 "Produced by `run_counts_eval.py` from `summary.json`. Differences are candidate minus reference.",
                 "CI is the 95% cluster bootstrap (tournament clusters; match clusters in the JSON as sensitivity).", ""]
    for tour in TOURS:
        for target, cell in summary["tours"][tour]["cells"].items():
            ref = COUNT_REF if target in COUNT_TARGETS else GAMES_REF
            models = COUNT_MODELS if target in COUNT_TARGETS else GAMES_MODELS
            lines_out.append(f"## {tour.upper()} {target}")
            lines_out.append("")
            lines_out.append(f"n = {cell['n_rows']} {'player-match targets' if target in COUNT_TARGETS else 'matches'}"
                             f" ({cell['n_matches']} matches); years {cell['rows_by_year']}; lines {cell['lines']}.")
            lines_out.append("")
            lines_out.append("| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | "
                             "PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |")
            lines_out.append("|---|---:|---|---:|---|---|---:|---|---|---|")
            for model in models:
                m = cell["models"][model]
                if model == ref:
                    d_crps = d_log = "(ref)"
                else:
                    c = cell["vs_ref"][model]["crps"]["event_cluster"]
                    l = cell["vs_ref"][model]["log_score"]["event_cluster"]
                    d_crps = f"{c['diff']:+.5f} [{c['ci95'][0]:+.5f}, {c['ci95'][1]:+.5f}]"
                    d_log = f"{l['diff']:+.5f} [{l['ci95'][0]:+.5f}, {l['ci95'][1]:+.5f}]"
                cov = "/".join(f"{m['coverage'][k] * 100:.1f}" for k in ("50", "80", "90"))
                lines_out.append(
                    f"| {model} | {m['crps']:.5f} | {d_crps} | {m['log_score']:.5f} | {d_log} | {cov} | "
                    f"{m['pit']['ks']:.4f} | {m['pit']['share_below_0.05'] * 100:.1f} / "
                    f"{m['pit']['share_above_0.95'] * 100:.1f} | {m['tail_exceed']['p95'] * 100:.1f} / "
                    f"{m['tail_exceed']['p99'] * 100:.2f} | {'yes' if cell['calibration'][model]['all_pass'] else 'no'} |"
                )
            lines_out.append("")
            lines_out.append("Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):")
            lines_out.append("")
            header = "| model | " + " | ".join(f"over {t['line']}" for t in cell["models"][models[0]]["threshold"])
            lines_out.append(header + " |")
            lines_out.append("|---|" + "---|" * len(cell["models"][models[0]]["threshold"]))
            for model in models:
                cells_text = []
                for t in cell["models"][model]["threshold"]:
                    cells_text.append(f"{t['predicted'] * 100:.1f} vs {t['observed'] * 100:.1f}, B {t['brier']:.4f}")
                lines_out.append(f"| {model} | " + " | ".join(cells_text) + " |")
            lines_out.append("")
            lines_out.append("CRPS by year: " + "; ".join(
                f"{model} " + ", ".join(f"{y} {v:.4f}" for y, v in cell["models"][model]["crps_by_year"].items())
                for model in models))
            lines_out.append("")
            d = cell["decision"]
            lines_out.append(f"**Decision:** {d['verdict']}; winner (clear over reference, lowest CRPS) "
                             f"{d['winner']}; runner-up {d['runner_up']}; calibrated {d['calibrated']}; "
                             f"lowest pooled CRPS overall {cell['prediction_model']}.")
            lines_out.append("")
    return "\n".join(lines_out) + "\n"


# ----------------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--tour", action="append", choices=TOURS)
    args = parser.parse_args()
    tours = args.tour or list(TOURS)
    summary: dict[str, Any] = {
        "window": {"start": WINDOW_START, "end": "last scoreable date", "fit_start": GAMES_HISTORY_START,
                   "count_replay_start": COUNT_START, "years": list(YEARS)},
        "tolerances": {"min_rows": MIN_ROWS, "min_matches": MIN_MATCHES, "min_sign_years": MIN_SIGN_YEARS,
                       "ks_max": KS_MAX, "tail_band": list(TAIL_BAND), "cover_slack": COVER_SLACK,
                       "p95_max": P95_MAX, "p99_max": P99_MAX, "threshold_gap_max": THRESH_GAP_MAX},
        "tours": {},
    }
    predictions_dir = HERE / "predictions"
    for tour in tours:
        started = time.time()
        counts = run_counts(args.db, tour)
        print(f"{tour}: count replay {counts['replay_rows_seen']} rows in {time.time() - started:.0f}s", flush=True)
        cells: dict[str, Any] = {}
        count_cells: dict[str, Any] = {}
        for target in COUNT_TARGETS:
            rows = counts["rows"][target]
            lines = book_lines(counts["fit_mean"][target])
            cell = evaluate_cell(rows, "counts", COUNT_MODELS, COUNT_REF, lines)
            cell["fit_mean"] = round(counts["fit_mean"][target], 4)
            cell["fit_rows"] = counts["fit_rows"][target]
            cells[target] = cell
            count_cells[target] = cell
            print(f"{tour} {target}: n={cell['n_rows']} verdict={cell['decision']['verdict']}", flush=True)
        started = time.time()
        games = run_games(args.db, tour)
        fit_mean, fit_matches = games_fit_mean(args.db, tour)
        games_lines = book_lines(fit_mean)
        game_cell = evaluate_cell(games["rows"], "games", GAMES_MODELS, GAMES_REF, games_lines)
        game_cell["fit_mean"] = round(fit_mean, 4)
        game_cell["fit_matches"] = fit_matches
        cells["games"] = game_cell
        print(f"{tour} games: n={game_cell['n_rows']} verdict={game_cell['decision']['verdict']} "
              f"in {time.time() - started:.0f}s", flush=True)
        for target, cell in cells.items():
            rows = counts["rows"][target] if target in COUNT_TARGETS else games["rows"]
            model = cell["prediction_model"]
            write_predictions(rows, model, predictions_dir / f"{tour}_{target}_{model}.csv.gz",
                              "games" if target == "games" else "counts")
            cell["prediction_file"] = f"predictions/{tour}_{target}_{model}.csv.gz"
        summary["tours"][tour] = {
            "cells": cells,
            "count_replay": {"rows_seen": counts["replay_rows_seen"], "cap_driven_rows": counts["cap_driven_rows"]},
            "games_records": games["records"],
            "anchors": anchors(tour, count_cells, game_cell),
        }
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (HERE / "TABLES.md").write_text(render_tables(summary))
    print("wrote summary.json, TABLES.md, predictions/", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
