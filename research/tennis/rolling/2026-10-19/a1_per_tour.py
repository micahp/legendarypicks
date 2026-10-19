#!/usr/bin/env python3
"""A1: rolling-origin M1 versus M2 on identical matches, scored separately for ATP and WTA.

The replay is the one in research/tennis/rolling/2026-10-18/rolling_origin.py, rebuilt here so that the
forecasts themselves (not only the Brier values) are available for calibration. The rebuilt Brier and log
loss arrays are checked against that module's own records before anything is reported. The paired
intervals reuse that module's bootstrap. What is new here: per-tour selection under the pre-declared rule,
calibration (slope, intercept, reliability), and the post-warm-up windows.

Read-only on the database. Development data (2015 to 2026 has been inspected), so this gives CP2 evidence only.
  python3 -I research/tennis/rolling/2026-10-19/a1_per_tour.py --db <dev DB, read-only> \
      --out research/tennis/rolling/2026-10-19/a1_per_tour.json
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
sys.path.insert(0, str(ROOT / "research" / "tennis" / "rolling" / "2026-10-18"))
import rolling_origin as ro  # noqa: E402

TOURS = ("atp", "wta")
MODELS = ("M1", "M2_2000", "M2_live", "B0")
CANDIDATES = ("M2_2000", "M2_live", "B0")
REF = "M1"
SIMPLICITY = ("B0", "M1", "M2_2000", "M2_live")  # PROTOCOL: winner simplicity order
YEARS = tuple(range(2015, 2027))
WINDOWS = {"2020_2026": (2020, 2026), "2023_2026": (2023, 2026)}
ANCHORS = {"atp": (0.22802, 11777), "wta": (0.21596, 13066)}  # M1 Brier, 2023 to 2026, from the 10-14 backtest
SURVIVAL = ro.SURVIVAL_YEARS


def winner_forecasts(db: str, tour: str, k: float = ro.ELO_K) -> dict[str, Any]:
    """Same rows, order, side draws and updates as ro.winner_records, but keeping each forecast probability.

    `k` is the Elo K. The default is the registered value, so the A1 numbers do not depend on it.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT tourney_date, tourney_id, surface, winner_id, loser_id, best_of, score FROM tennis_{tour}_matches "
            f"WHERE {ro.tpm.TOUR_FILTER[tour]} AND tourney_date >= ? AND tourney_date <= ? "
            "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
            (ro.WINNER_HISTORY_START, ro.EVAL_END),
        ).fetchall()
    finally:
        conn.close()
    full_g: dict = defaultdict(lambda: ro.ELO_START)
    full_s: dict = defaultdict(lambda: ro.ELO_START)
    live_g: dict = defaultdict(lambda: ro.ELO_START)
    live_s: dict = defaultdict(lambda: ro.ELO_START)
    side_rng = random.Random(ro.SIDE_SEED)
    out: dict[str, list] = {"year": [], "event": [], "y": [], **{f"p_{m}": [] for m in MODELS}}
    for date, group_iter in groupby(rows, key=itemgetter(0)):
        group = list(group_iter)
        if ro.EVAL_START <= date <= ro.EVAL_END:
            for _, tourney_id, surface, winner, loser, best_of, score in group:
                if surface is None or best_of != 3 or not ro.complete(score):
                    continue
                a_wins = side_rng.random() < 0.5
                a, b = (winner, loser) if a_wins else (loser, winner)
                out["year"].append(date // 10000)
                out["event"].append(ro.event_code(tour, tourney_id))
                out["y"].append(1.0 if a_wins else 0.0)
                out["p_M1"].append(ro.elo_p(full_g[a], full_g[b]))
                out["p_M2_2000"].append(ro.blend_p(full_g, full_s, a, b, surface))
                out["p_M2_live"].append(ro.blend_p(live_g, live_s, a, b, surface))
                out["p_B0"].append(0.5)
        # Same update rule as ro.winner_records: every row of the event-start date updates after that date.
        full_updates, full_surface_updates, live_updates, live_surface_updates = [], [], [], []
        for _, _, surface, winner, loser, _, _ in group:
            if surface is not None:
                full_updates.append((winner, loser, k * (1.0 - ro.elo_p(full_g[winner], full_g[loser]))))
                full_surface_updates.append((winner, loser, surface, k * (
                    1.0 - ro.elo_p(full_s[(winner, surface)], full_s[(loser, surface)]))))
            if date >= ro.LIVE_HISTORY_START:
                live_updates.append((winner, loser, k * (1.0 - ro.elo_p(live_g[winner], live_g[loser]))))
                if surface:
                    live_surface_updates.append((winner, loser, surface, k * (
                        1.0 - ro.elo_p(live_s[(winner, surface)], live_s[(loser, surface)]))))
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
    arrays = {k: np.asarray(v, dtype=float if k.startswith("p_") or k == "y" else np.int64) for k, v in out.items()}
    arrays["cluster"] = np.arange(len(arrays["y"]))  # one match per cluster for the winner target
    return arrays


def check_against_module(db: str, tour: str, f: dict[str, Any]) -> dict[str, float]:
    """The rebuilt rows must reproduce the committed 10-18 records exactly, row for row."""
    cols = ro.Columns()
    ro.winner_records(db, tour, cols)
    ref = cols.arrays()
    if len(ref["year"]) != len(f["y"]) or not np.array_equal(ref["event"], f["event"]):
        raise SystemExit(f"{tour}: rebuilt rows differ from ro.winner_records (count or order)")
    worst = {}
    for m in MODELS:
        p = np.clip(f[f"p_{m}"], 1e-9, 1 - 1e-9)
        brier = (p - f["y"]) ** 2
        log_loss = -(f["y"] * np.log(p) + (1 - f["y"]) * np.log(1 - p))
        worst[m] = float(max(np.max(np.abs(brier - ref[f"{m}__p"])), np.max(np.abs(log_loss - ref[f"{m}__s"]))))
        if worst[m] > 1e-9:
            raise SystemExit(f"{tour} {m}: rebuilt scores differ from ro.winner_records by {worst[m]}")
    return worst


def fit_logit(z: np.ndarray, y: np.ndarray, start: np.ndarray | None = None) -> np.ndarray:
    """Newton fit of y on [1, z]. Returns (intercept, slope); slope 1 and intercept 0 is perfect calibration."""
    x = np.column_stack([np.ones_like(z), z])
    beta = np.array([0.0, 1.0]) if start is None else start.copy()
    for _ in range(50):
        mu = 1.0 / (1.0 + np.exp(-(x @ beta)))
        grad = x.T @ (y - mu)
        hess = (x * (mu * (1.0 - mu))[:, None]).T @ x
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def calibration(p: np.ndarray, y: np.ndarray, label: str) -> dict[str, Any]:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    z = np.log(p / (1 - p))
    beta = fit_logit(z, y)
    rng = np.random.default_rng([ro.SIDE_SEED, zlib.crc32(label.encode())])
    n = len(y)
    boot = np.empty((ro.REPS, 2))
    for r in range(ro.REPS):  # one row is one match cluster, so row resampling is the match-clustered bootstrap
        idx = rng.integers(0, n, size=n)
        boot[r] = fit_logit(z[idx], y[idx], start=beta)
    bins = np.clip((p * 10).astype(int), 0, 9)
    reliability = []
    ece = 0.0
    for b in range(10):
        mask = bins == b
        if not mask.any():
            continue
        mean_p, observed = float(p[mask].mean()), float(y[mask].mean())
        ece += mask.sum() / n * abs(mean_p - observed)
        reliability.append({"bin": b / 10, "n": int(mask.sum()), "mean_p": mean_p, "observed": observed})
    return {
        "intercept": float(beta[0]), "intercept_ci95": [float(v) for v in np.quantile(boot[:, 0], [0.025, 0.975])],
        "slope": float(beta[1]), "slope_ci95": [float(v) for v in np.quantile(boot[:, 1], [0.025, 0.975])],
        "ece_10bin": float(ece), "mean_p": float(p.mean()), "observed": float(y.mean()), "reliability": reliability,
    }


def paired_block(diffs: dict[str, np.ndarray], f: dict[str, Any], mask: np.ndarray, label: str) -> dict[str, Any]:
    """Pooled paired difference with match-clustered and tournament-clustered 95% intervals, plus per-year means."""
    sub = {m: d[mask] for m, d in diffs.items()}
    match = ro.paired_intervals(sub, f["cluster"][mask], f"{label}-match")
    tourn = ro.paired_intervals(sub, f["event"][mask], f"{label}-tournament")
    per_year = {}
    for yr in YEARS:
        ym = mask & (f["year"] == yr)
        if ym.any():
            per_year[yr] = {m: float(diffs[m][ym].mean()) for m in diffs}
    years_negative = {m: sum(1 for yr in per_year if per_year[yr][m] < 0) for m in diffs}
    return {
        "pooled": {m: {"diff": v[0], "ci95": [v[1], v[2]], "matches": v[3]} for m, v in match.items()},
        "tournament_ci95": {m: [v[1], v[2]] for m, v in tourn.items()},
        "per_year": per_year, "years_negative": years_negative, "years_evaluated": len(per_year),
    }


def select_incumbent(block: dict[str, Any], f: dict[str, Any], brier: dict[str, np.ndarray]) -> dict[str, Any]:
    """PROTOCOL selection rule, applied to one tour. Thresholds unchanged: 95% interval below zero, 9 of 12 years."""
    pooled_score = {m: float(brier[m].mean()) for m in MODELS}
    clear = [m for m in CANDIDATES if block["pooled"][m]["ci95"][1] < 0 and block["years_negative"][m] >= SURVIVAL]
    if not clear:
        return {"clear_over_reference": [], "incumbent": REF, "runner_up": None,
                "reason": "no candidate clearly beats M1 on this tour; reference retained (rule 4)"}
    top = min(clear, key=lambda m: pooled_score[m])
    runner = next(m for m in sorted(MODELS, key=lambda m: pooled_score[m]) if m != top)
    margin = ro.paired_intervals({"d": brier[top] - brier[runner]}, f["cluster"], f"a1-margin-{top}-{runner}")["d"]
    margin_years = {}
    for yr in YEARS:
        ym = f["year"] == yr
        if ym.any():
            margin_years[yr] = float((brier[top] - brier[runner])[ym].mean())
    margin_negative = sum(1 for v in margin_years.values() if v < 0)
    if margin[2] < 0 and margin_negative >= SURVIVAL:
        incumbent = top
        reason = "top candidate clearly beats the runner-up (rule 3)"
    else:
        incumbent = min((top, runner), key=SIMPLICITY.index)
        reason = "top candidate does not clearly beat the runner-up; the simpler model is the incumbent (rule 3)"
    return {"clear_over_reference": clear, "top": top, "runner_up": runner, "incumbent": incumbent,
            "margin_top_minus_runner_up": {"diff": margin[0], "ci95": [margin[1], margin[2]],
                                           "years_negative": margin_negative},
            "reason": reason}


def analyse_tour(db: str, tour: str) -> dict[str, Any]:
    f = winner_forecasts(db, tour)
    worst = check_against_module(db, tour, f)
    y = f["y"]
    brier = {m: (np.clip(f[f"p_{m}"], 1e-9, 1 - 1e-9) - y) ** 2 for m in MODELS}
    log_loss = {m: -(y * np.log(np.clip(f[f"p_{m}"], 1e-9, 1 - 1e-9))
                     + (1 - y) * np.log(1 - np.clip(f[f"p_{m}"], 1e-9, 1 - 1e-9))) for m in MODELS}
    diffs = {m: brier[m] - brier[REF] for m in CANDIDATES}
    everything = np.ones(len(y), dtype=bool)
    block = paired_block(diffs, f, everything, f"a1-{tour}")
    year_means = {m: {yr: float(brier[m][f["year"] == yr].mean()) for yr in YEARS if (f["year"] == yr).any()}
                  for m in MODELS}
    population = {"matches": int(len(y)),
                  "per_year": {yr: int((f["year"] == yr).sum()) for yr in YEARS if (f["year"] == yr).any()}}
    windows = {}
    for name, (lo, hi) in WINDOWS.items():
        mask = (f["year"] >= lo) & (f["year"] <= hi)
        windows[name] = {"matches": int(mask.sum()),
                         "M1_brier": float(brier[REF][mask].mean()),
                         **paired_block(diffs, f, mask, f"a1-{tour}-{name}")}
    # M2_live is the 0.5 floor for 2015 to 2019 (no 2020-start history), so the post-warm-up windows are the fair read.
    cal = {}
    for name, (lo, hi) in {"2015_2026": (2015, 2026), **WINDOWS}.items():
        mask = (f["year"] >= lo) & (f["year"] <= hi)
        cal[name] = {m: calibration(f[f"p_{m}"][mask], y[mask], f"a1-{tour}-cal-{name}-{m}")
                     for m in ("M1", "M2_2000", "M2_live")}
    anchor_value, anchor_n = ANCHORS[tour]
    m23 = (f["year"] >= 2023) & (f["year"] <= 2026)
    anchor = {"M1_brier_2023_2026": float(round(brier[REF][m23].mean(), 5)), "n": int(m23.sum()),
              "published": anchor_value, "published_n": anchor_n}
    if anchor["M1_brier_2023_2026"] != anchor_value or anchor["n"] != anchor_n:
        raise SystemExit(f"{tour}: anchor failed {anchor}")
    return {
        "population": population,
        "anchor": anchor,
        "crosscheck_max_abs_diff_vs_module": worst,
        "brier_pooled": {m: float(brier[m].mean()) for m in MODELS},
        "log_loss_pooled": {m: float(log_loss[m].mean()) for m in MODELS},
        "brier_per_year": year_means,
        "paired_vs_M1": block,
        "windows": windows,
        "calibration": cal,
        "selection": select_incumbent(block, f, brier),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result: dict[str, Any] = {"target": "winner", "db": Path(args.db).name, "rule": "PROTOCOL 2026-10-18, per tour",
                              "reps": ro.REPS, "seed": ro.SIDE_SEED, "tours": {}}
    for tour in TOURS:
        result["tours"][tour] = analyse_tour(args.db, tour)
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    for tour in TOURS:
        t = result["tours"][tour]
        print(tour, "matches", t["population"]["matches"], "anchor", t["anchor"]["M1_brier_2023_2026"], t["anchor"]["n"])
        print(" pooled brier", {m: round(v, 5) for m, v in t["brier_pooled"].items()})
        print(" M2_2000-M1", t["paired_vs_M1"]["pooled"]["M2_2000"], t["paired_vs_M1"]["years_negative"]["M2_2000"])
        print(" M2_live-M1", t["paired_vs_M1"]["pooled"]["M2_live"], t["paired_vs_M1"]["years_negative"]["M2_live"])
        print(" selection", t["selection"]["incumbent"], "|", t["selection"]["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
