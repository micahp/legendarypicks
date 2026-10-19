#!/usr/bin/env python3
"""Rolling-origin records, per-year and pooled summaries, and incumbent selection for the tennis targets.

Implements research/tennis/rolling/2026-10-18/PROTOCOL.md. Development data: 2015 to 2026 has been used by earlier
replays, so no year here is an untouched holdout. This gives CP2 evidence only.

Targets: match winner (M1, M2 variants, constant), total games (direct histograms and the simulator), aces and double
faults (C0 prior-year rate, and the replay's Poisson and Gamma-Poisson P0 and P1). Every model is scored on the same
rows within a target.

  python3 -I research/tennis/rolling/2026-10-18/rolling_origin.py --db <dev DB, read-only> \
      --out-dir research/tennis/rolling/2026-10-18
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
import zlib
from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_daily_projections as tdp  # noqa: E402  (live logit helpers, used verbatim)
import tennis_point_model as tpm  # noqa: E402
import tennis_props_rate_backtest as rb  # noqa: E402
import tennis_total_games_backtest as tgb  # noqa: E402

EVAL_START, EVAL_END = 20150101, 20261231
YEARS = tuple(range(2015, 2027))
ELO_START, ELO_K = 1500.0, 32.0
WINNER_HISTORY_START = 20000101  # backend/tennis_match_backtest.py: M1 history
LIVE_HISTORY_START = 20200101  # backend/tennis_daily_projections.py: HISTORY_START, deployed M2
INCOMPLETE = ("RET", "W/O", "DEF", "ABD")
REPS = 1000
SIDE_SEED = 20261018
SURVIVAL_YEARS = 9  # PROTOCOL: negative in at least 9 of 12 years
TOURS = ("atp", "wta")
TOUR_CODE = {"atp": 0, "wta": 1}

WINNER_MODELS = ("M1", "M2_2000", "M2_live", "B0")
WINNER_REF = "M1"
GAMES_MODELS = ("direct_format", "direct_surface", "direct_surface_competitive", "simulator")
GAMES_REF = "direct_format"
COUNT_MODELS = ("C0", "p0_poisson", "p0_gamma_poisson", "p1_poisson", "p1_gamma_poisson")
COUNT_REF = "C0"
# PROTOCOL simplicity order, used only when the top candidate fails the runner-up test.
SIMPLICITY = {
    "winner": ("B0", "M1", "M2_2000", "M2_live"),
    "games": ("direct_format", "direct_surface", "direct_surface_competitive", "simulator"),
    "counts": ("C0", "p0_poisson", "p0_gamma_poisson", "p1_poisson", "p1_gamma_poisson"),
}


def complete(score: str | None) -> bool:
    return score is not None and not any(token in score for token in INCOMPLETE)


def event_code(tour: str, tournament_id: Any) -> int:
    """Stable integer for a tournament instance (tour and event id), used as the sensitivity cluster."""
    return zlib.crc32(f"{tour}:{tournament_id}".encode())


def elo_p(rating_a: float, rating_b: float) -> float:
    """Probability that A wins under the Elo scale used by M1 and the live code."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def blend_p(global_r: dict, surface_r: dict, a: str, b: str, surface: str) -> float:
    """50/50 logit average of global and surface Elo, as backend/tennis_daily_projections.py line 242."""
    scale = math.log(10.0) / 400.0
    p_global = tdp._logistic((global_r[a] - global_r[b]) * scale)
    p_surface = tdp._logistic((surface_r[(a, surface)] - surface_r[(b, surface)]) * scale)
    return tdp._logistic(0.5 * (tdp._logit(p_global) + tdp._logit(p_surface)))


def brier_log(p_a: float, y: float) -> tuple[float, float]:
    p = min(max(p_a, 1e-9), 1.0 - 1e-9)
    return (p - y) ** 2, -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


class Columns:
    """Column-oriented record store, to keep the 2015 to 2026 count rows small in memory."""

    def __init__(self) -> None:
        self.data: dict[str, list] = defaultdict(list)

    def append(self, **values: Any) -> None:
        for key, value in values.items():
            self.data[key].append(value)

    def arrays(self) -> dict[str, np.ndarray]:
        return {key: np.asarray(values) for key, values in self.data.items()}


# ----------------------------------------------------------------------------- winner

def winner_records(db: str, tour: str, cols: Columns) -> None:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT tourney_date, tourney_id, surface, winner_id, loser_id, best_of, score FROM tennis_{tour}_matches "
            f"WHERE {tpm.TOUR_FILTER[tour]} AND tourney_date >= ? AND tourney_date <= ? "
            "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
            (WINNER_HISTORY_START, EVAL_END),
        ).fetchall()
    finally:
        conn.close()
    full_g: dict = defaultdict(lambda: ELO_START)
    full_s: dict = defaultdict(lambda: ELO_START)
    live_g: dict = defaultdict(lambda: ELO_START)
    live_s: dict = defaultdict(lambda: ELO_START)
    side_rng = random.Random(SIDE_SEED)
    cluster = TOUR_CODE[tour] * 10_000_000
    for date, group_iter in groupby(rows, key=itemgetter(0)):
        group = list(group_iter)
        if EVAL_START <= date <= EVAL_END:
            for _, tourney_id, surface, winner, loser, best_of, score in group:
                if surface is None or best_of != 3 or not complete(score):
                    continue
                a_wins = side_rng.random() < 0.5
                a, b = (winner, loser) if a_wins else (loser, winner)
                y = 1.0 if a_wins else 0.0
                forecasts = {
                    "M1": elo_p(full_g[a], full_g[b]),
                    "M2_2000": blend_p(full_g, full_s, a, b, surface),
                    "M2_live": blend_p(live_g, live_s, a, b, surface),
                    "B0": 0.5,
                }
                scored = {m: brier_log(p, y) for m, p in forecasts.items()}
                cluster += 1
                values: dict[str, Any] = {"year": date // 10000, "tour": TOUR_CODE[tour], "cluster": cluster,
                                          "event": event_code(tour, tourney_id)}
                for model, (brier, log_loss) in scored.items():
                    values[f"{model}__p"] = brier
                    values[f"{model}__s"] = log_loss
                cols.append(**values)
        # Ratings update after the whole event-start date; M1 and M2_2000 use surface-not-null rows from 2000,
        # the deployed M2 uses every row from 2020, as in the live projection code.
        full_updates, full_surface_updates = [], []
        live_updates, live_surface_updates = [], []
        for _, _, surface, winner, loser, _, _ in group:
            if surface is not None:
                full_updates.append((winner, loser, ELO_K * (1.0 - elo_p(full_g[winner], full_g[loser]))))
                full_surface_updates.append((winner, loser, surface, ELO_K * (
                    1.0 - elo_p(full_s[(winner, surface)], full_s[(loser, surface)]))))
            if date >= LIVE_HISTORY_START:
                live_updates.append((winner, loser, ELO_K * (1.0 - elo_p(live_g[winner], live_g[loser]))))
                if surface:
                    live_surface_updates.append((winner, loser, surface, ELO_K * (
                        1.0 - elo_p(live_s[(winner, surface)], live_s[(loser, surface)]))))
        for winner, loser, delta in full_updates:
            full_g[winner] += delta
            full_g[loser] -= delta
        for winner, loser, surface, delta in full_surface_updates:
            full_s[(winner, surface)] += delta
            full_s[(loser, surface)] -= delta
        for winner, loser, delta in live_updates:
            live_g[winner] += delta
            live_g[loser] -= delta
        for winner, loser, surface, delta in live_surface_updates:
            live_s[(winner, surface)] += delta
            live_s[(loser, surface)] -= delta


# ----------------------------------------------------------------------------- total games

def games_records(db: str, tour: str, cols: Columns) -> None:
    tgb.HISTORY_START = WINNER_HISTORY_START  # PROTOCOL: histograms start in 2000, not 2022
    records, _ = tgb.run(db, tour, start=EVAL_START, end=EVAL_END)
    cluster = TOUR_CODE[tour] * 10_000_000
    for record in records:
        cluster += 1
        values: dict[str, Any] = {"year": record["year"], "tour": TOUR_CODE[tour], "cluster": cluster,
                                  "event": event_code(tour, record["event_id"])}
        for model in GAMES_MODELS:
            values[f"{model}__p"] = record[f"{model}_crps"]
            values[f"{model}__s"] = record[f"{model}_log_score"]
            values[f"{model}__m"] = abs(record[f"{model}_mean"] - record["actual_games"])
        cols.append(**values)


# ----------------------------------------------------------------------------- aces and double faults

def counts_records(db: str, tour: str, cols_by_target: dict[str, Columns]) -> None:
    """Stream the replay (rows are never all held in memory). Rows arrive in pairs: both players of one
    match for one target, so a pair shares one cluster. Every record carries every column."""
    prior_sum: dict[tuple, float] = defaultdict(float)
    prior_n: dict[tuple, int] = defaultdict(int)
    pending: dict[str, dict] = {}
    cluster = TOUR_CODE[tour] * 10_000_000
    for row in rb.run(db, tour, start=2014 * 10000 + 101, end=EVAL_END):
        target = row["target"]
        year = row["year"]
        surface = row["surface"]
        actual = row["actual"]
        if year >= EVAL_START // 10000:
            # C0: prior calendar-year tour and surface mean per player-match, falling back to the tour mean.
            key_surface = (year - 1, target, surface)
            key_tour = (year - 1, target)
            if prior_n.get(key_surface):
                mean = prior_sum[key_surface] / prior_n[key_surface]
            else:
                mean = prior_sum[key_tour] / prior_n[key_tour]
            mean = max(mean, 0.05)
            c0 = rb.score_pmf(rb.poisson_pmf(mean, actual), actual)
            record: dict[str, Any] = {"year": year, "tour": TOUR_CODE[tour], "C0__p": c0["crps"], "C0__s": c0["log_score"],
                                      "event": event_code(tour, row["event_id"])}
            for model in COUNT_MODELS[1:]:
                record[f"{model}__p"] = row[f"{model}_crps"]
                record[f"{model}__s"] = row[f"{model}_log_score"]
            if target in pending:
                first = pending.pop(target)
                if (first["event"], first["date"]) != (row["event_id"], row["date"]):
                    raise RuntimeError("count rows are not paired by match")
                cluster += 1
                for done in (first["record"], record):
                    done["cluster"] = cluster
                    cols_by_target[target].append(**done)
            else:
                pending[target] = {"event": row["event_id"], "date": row["date"], "record": record}
        prior_sum[(year, target, surface)] += actual
        prior_n[(year, target, surface)] += 1
        prior_sum[(year, target)] += actual
        prior_n[(year, target)] += 1
    if pending:
        raise RuntimeError("unpaired count rows at the end of the replay")


# ----------------------------------------------------------------------------- statistics

def paired_intervals(diffs: dict[str, np.ndarray], clusters: np.ndarray, seed_label: str) -> dict[str, tuple]:
    """Match-clustered bootstrap of the mean difference, with the same resamples for every model."""
    codes, inverse = np.unique(clusters, return_inverse=True)
    k = len(codes)
    counts = np.bincount(inverse, minlength=k).astype(np.float64)
    sums = {m: np.bincount(inverse, weights=d, minlength=k) for m, d in diffs.items()}
    estimates = {m: np.empty(REPS) for m in diffs}
    rng = np.random.default_rng([SIDE_SEED, zlib.crc32(seed_label.encode())])
    chunk = max(1, min(REPS, 2_000_000 // max(k, 1)))
    start = 0
    while start < REPS:
        size = min(chunk, REPS - start)
        idx = rng.integers(0, k, size=(size, k))
        draw_counts = counts[idx].sum(axis=1)
        for m in diffs:
            estimates[m][start:start + size] = sums[m][idx].sum(axis=1) / draw_counts
        start += size
    out = {}
    for m, d in diffs.items():
        lo, hi = np.quantile(estimates[m], [0.025, 0.975])
        out[m] = (float(d.mean()), float(lo), float(hi), int(k))
    return out


def slice_mask(arrays: dict[str, np.ndarray], tour: str | None, year: int | None) -> np.ndarray:
    mask = np.ones(len(arrays["year"]), dtype=bool)
    if tour is not None:
        mask &= arrays["tour"] == TOUR_CODE[tour]
    if year is not None:
        mask &= arrays["year"] == year
    return mask


def summarise_target(name: str, arrays: dict[str, np.ndarray], models: tuple[str, ...], reference: str,
                     metric: str) -> dict[str, Any]:
    """metric is 'p' (primary) or 's' (secondary). Returns means, paired differences and interval per slice."""
    result: dict[str, Any] = {"target": name, "reference": reference, "metric": metric, "models": {}, "paired": {}}
    primary = {m: arrays[f"{m}__p"] for m in models}
    value = {m: arrays[f"{m}__{metric}"] for m in models}
    # Per-year pooled (both tours) and pooled slices, then per tour.
    slices = {"both_pooled": (None, None)}
    for tour in TOURS:
        slices[f"{tour}_pooled"] = (tour, None)
    for year in YEARS:
        slices[f"both_{year}"] = (None, year)
    for tour in TOURS:
        for year in YEARS:
            slices[f"{tour}_{year}"] = (tour, year)
    for slice_name, (tour, year) in slices.items():
        mask = slice_mask(arrays, tour, year)
        means = {m: float(value[m][mask].mean()) if mask.any() else None for m in models}
        result["models"].setdefault(slice_name, {"n_rows": int(mask.sum()), "clusters": int(len(np.unique(arrays["cluster"][mask]))), "mean": means})
    # Paired differences against the reference, one bootstrap per slice shared by every model.
    for slice_name, (tour, year) in slices.items():
        mask = slice_mask(arrays, tour, year)
        if not mask.any():
            continue
        clusters = arrays["cluster"][mask]
        diffs = {m: (value[m][mask] - value[reference][mask]) for m in models if m != reference}
        intervals = paired_intervals(diffs, clusters, f"{name}/{reference}/{slice_name}")
        result["paired"].setdefault(slice_name, {})
        for m, (diff, lo, hi, k) in intervals.items():
            result["paired"][slice_name][m] = {"diff": diff, "ci95": [lo, hi], "clusters": k}
    # Sensitivity only (PROTOCOL): tournament-clustered intervals for the pooled slices.
    result["paired_tournament"] = {}
    for slice_name, (tour, year) in slices.items():
        if year is not None:  # the pooled slices only: both tours, ATP, WTA
            continue
        mask = slice_mask(arrays, tour, year)
        diffs = {m: (value[m][mask] - value[reference][mask]) for m in models if m != reference}
        intervals = paired_intervals(diffs, arrays["event"][mask], f"{name}/{reference}/{slice_name}/tournament")
        result["paired_tournament"][slice_name] = {
            m: {"diff": diff, "ci95": [lo, hi], "clusters": k} for m, (diff, lo, hi, k) in intervals.items()}
    # Years on which each model is better than the reference (pooled over both tours).
    for m in models:
        if m == reference:
            continue
        negative = [y for y in YEARS if result["paired"][f"both_{y}"][m]["diff"] < 0]
        result["paired"].setdefault("years_negative", {})[m] = len(negative)
    return result


def clear_win(summary: dict[str, Any], model: str, need: int = SURVIVAL_YEARS) -> bool:
    pooled = summary["paired"]["both_pooled"][model]
    interval_below_zero = pooled["ci95"][1] < 0
    return interval_below_zero and summary["paired"]["years_negative"][model] >= need


def select_incumbent(name: str, arrays: dict[str, np.ndarray], models: tuple[str, ...], reference: str,
                     summary: dict[str, Any]) -> dict[str, Any]:
    """PROTOCOL rules 1 to 4. Returns the decision and the margins that justify it."""
    pooled_mean = {m: summary["models"]["both_pooled"]["mean"][m] for m in models}
    candidates = [m for m in models if m != reference]
    clear = [m for m in candidates if clear_win(summary, m)]
    decision: dict[str, Any] = {"clear_over_reference": clear, "reference": reference}
    if not clear:
        decision.update({"incumbent": reference, "reason": "no candidate clearly beats the reference"})
        return decision
    top = min(clear, key=lambda m: pooled_mean[m])
    runner = sorted(models, key=lambda m: pooled_mean[m])
    runner = next(m for m in runner if m != top)
    mask = slice_mask(arrays, None, None)
    diff = arrays[f"{top}__p"][mask] - arrays[f"{runner}__p"][mask]
    margin = paired_intervals({"top_minus_runner": diff}, arrays["cluster"][mask], f"{name}/{top}/{runner}")
    margin_diff, lo, hi, k = margin["top_minus_runner"]
    tournament = paired_intervals({"d": diff}, arrays["event"][mask], f"{name}/{top}/{runner}/tournament")["d"]
    years_neg = 0
    for year in YEARS:
        year_mask = slice_mask(arrays, None, year)
        year_diff = arrays[f"{top}__p"][year_mask] - arrays[f"{runner}__p"][year_mask]
        if year_diff.mean() < 0:
            years_neg += 1
    survives = hi < 0 and years_neg >= SURVIVAL_YEARS
    if survives:
        incumbent = top
        reason = "top candidate beats the runner-up clearly and in at least 9 of 12 years"
    else:
        order = SIMPLICITY[name]
        incumbent = min((top, runner), key=order.index)
        reason = "margin over runner-up not clear or not sign-stable; the simpler of the top two is kept"
    decision.update({
        "top": top, "runner_up": runner, "incumbent": incumbent, "reason": reason,
        "margin_top_minus_runner_up": {"diff": margin_diff, "ci95": [lo, hi], "clusters": k,
                                        "years_negative": years_neg,
                                        "tournament_ci95": [tournament[1], tournament[2]],
                                        "tournament_clusters": tournament[3]},
    })
    return decision


def verification(name: str, arrays: dict[str, np.ndarray], summaries: dict[str, Any]) -> dict[str, Any]:
    """Anchors from the published numbers. Any mismatch raises, so a drifted run cannot be written."""
    checks: dict[str, Any] = {}
    if name == "winner":
        for tour, expected in (("atp", 0.22802), ("wta", 0.21596)):
            mask = slice_mask(arrays, tour, None) & (arrays["year"] >= 2023)
            got = float(arrays["M1__p"][mask].mean())
            checks[f"M1_brier_2023_2026_{tour}"] = {"got": round(got, 5), "published": expected}
            if round(got, 5) != expected:
                raise RuntimeError(f"M1 2023 to 2026 {tour} Brier {got:.5f} does not match {expected}")
    if name == "games":
        for tour, expected in (("atp", 3.5327), ("wta", 3.5572)):
            mask = slice_mask(arrays, tour, None) & (arrays["year"] >= 2023)
            got = float(arrays["simulator__p"][mask].mean())
            checks[f"simulator_crps_2023_2026_{tour}"] = {"got": round(got, 4), "published": expected}
            if round(got, 4) != expected:
                raise RuntimeError(f"simulator 2023 to 2026 {tour} CRPS {got:.4f} does not match {expected}")
    if name.startswith("counts_"):
        published = {
            ("atp", "aces"): ("p0_gamma_poisson", 2.0505, "p1_gamma_poisson", 1.9934),
            ("wta", "aces"): ("p0_gamma_poisson", 1.2221, "p1_gamma_poisson", 1.2005),
            ("atp", "double_faults"): ("p0_gamma_poisson", 1.1047, "p1_gamma_poisson", 1.0955),
            ("wta", "double_faults"): ("p0_gamma_poisson", 1.3444, "p1_gamma_poisson", 1.3308),
        }
        target = name.split("_", 1)[1]
        for tour in TOURS:
            if (tour, target) not in published:
                continue
            p0, p0_expected, p1, p1_expected = published[(tour, target)]
            mask = slice_mask(arrays, tour, None)
            for model, expected in ((p0, p0_expected), (p1, p1_expected)):
                got = float(arrays[f"{model}__p"][mask].mean())
                checks[f"{model}_crps_{target}_{tour}"] = {"got": round(got, 4), "published": expected}
                if round(got, 4) != expected:
                    raise RuntimeError(f"{model} {target} {tour} CRPS {got:.4f} does not match {expected}")
    return checks


def build(db: str, out_dir: Path, records_dir: Path | None) -> dict[str, Any]:
    targets: dict[str, dict[str, Any]] = {}
    winner, games = Columns(), Columns()
    counts = {"aces": Columns(), "double_faults": Columns()}
    for tour in TOURS:
        winner_records(db, tour, winner)
        games_records(db, tour, games)
        counts_records(db, tour, counts)
    specs = {
        "winner": (winner, WINNER_MODELS, WINNER_REF, "p"),
        "games": (games, GAMES_MODELS, GAMES_REF, "p"),
        "counts_aces": (counts["aces"], COUNT_MODELS, COUNT_REF, "p"),
        "counts_double_faults": (counts["double_faults"], COUNT_MODELS, COUNT_REF, "p"),
    }
    for name, (cols, models, reference, metric) in specs.items():
        arrays = cols.arrays()
        if records_dir is not None:
            records_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(records_dir / f"{name}.npz", **arrays)
        summary = summarise_target(name, arrays, models, reference, metric)
        summary["secondary"] = {m: float(arrays[f"{m}__s"].mean()) for m in models}
        if f"{models[0]}__m" in arrays:
            summary["secondary_mae"] = {m: float(arrays[f"{m}__m"].mean()) for m in models}
        summary["verification"] = verification(name, arrays, {})
        summary["selection"] = select_incumbent(name, arrays, models, reference, summary)
        summary["rows"] = int(len(arrays["year"]))
        targets[name] = summary
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "rolling_summary.json"
    out_path.write_text(json.dumps(targets, indent=2, sort_keys=True) + "\n")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--records-dir", default=None,
                        help="optional directory for compressed per-row arrays (kept outside the repository)")
    args = parser.parse_args()
    targets = build(args.db, Path(args.out_dir), Path(args.records_dir) if args.records_dir else None)
    for name, summary in targets.items():
        print(name, "rows", summary["rows"], "selected", summary["selection"]["incumbent"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
