#!/usr/bin/env python3
"""Post-hoc diagnostics for the rolling-origin result. NOT used for selection.

Written after rolling_origin.py had produced its selection, to explain two things the pre-registered table shows:

1. Why the deployed M2 (Elo history from 2020-01-01) differs from M2 on 2000 history. The two differ in two ways,
   the start date and whether rows without a surface update the global rating. Both 2x2 cells are computed, so the
   start effect and the population effect can be separated.
2. Whether each selected incumbent's margin holds tour by tour (the protocol's tour check).

It reads the per-row arrays saved by rolling_origin.py and recomputes the winner variants from the database.

  python3 -I research/tennis/rolling/2026-10-18/diagnostics.py --db <dev DB, read-only> \
      --records-dir <records dir from rolling_origin.py> --out research/tennis/rolling/2026-10-18/diagnostics.json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rolling_origin as ro  # noqa: E402

VARIANTS = {
    "M2_2000_surface_rows": (20000101, False),  # protocol M2_2000: history from 2000, rows without surface skipped
    "M2_2020_surface_rows": (20200101, False),  # start effect alone
    "M2_2000_all_rows": (20000101, True),  # population effect alone
    "M2_2020_all_rows": (20200101, True),  # deployed M2: history from 2020, all rows update global rating
}


def winner_variants(db: str, tour: str) -> dict[str, dict[str, np.ndarray]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT tourney_date, surface, winner_id, loser_id, best_of, score FROM tennis_{tour}_matches "
            f"WHERE {ro.tpm.TOUR_FILTER[tour]} AND tourney_date >= 20000101 AND tourney_date <= ? "
            "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date, match_num",
            (ro.EVAL_END,),
        ).fetchall()
    finally:
        conn.close()
    states = {name: (defaultdict(lambda: ro.ELO_START), defaultdict(lambda: ro.ELO_START))
              for name in VARIANTS}
    out: dict[str, dict[str, list]] = {name: {"year": [], "cluster": [], "brier": []} for name in VARIANTS}
    side_rng = random.Random(ro.SIDE_SEED)
    cluster = ro.TOUR_CODE[tour] * 10_000_000
    for date, group_iter in groupby(rows, key=itemgetter(0)):
        group = list(group_iter)
        if ro.EVAL_START <= date <= ro.EVAL_END:
            for _, surface, winner, loser, best_of, score in group:
                if surface is None or best_of != 3 or not ro.complete(score):
                    continue
                a_wins = side_rng.random() < 0.5
                a, b = (winner, loser) if a_wins else (loser, winner)
                y = 1.0 if a_wins else 0.0
                cluster += 1
                for name, (start, _) in VARIANTS.items():
                    if date < start:
                        p = 0.5
                    else:
                        global_r, surface_r = states[name]
                        p = ro.blend_p(global_r, surface_r, a, b, surface)
                    out[name]["year"].append(date // 10000)
                    out[name]["cluster"].append(cluster)
                    out[name]["brier"].append(ro.brier_log(p, y)[0])
        for name, (start, all_rows) in VARIANTS.items():
            global_r, surface_r = states[name]
            global_updates, surface_updates = [], []
            for _, surface, winner, loser, _, _ in group:
                if surface is None and not all_rows:
                    continue
                if date < start:
                    continue
                global_updates.append((winner, loser, ro.ELO_K * (1.0 - ro.elo_p(global_r[winner], global_r[loser]))))
                if surface:
                    surface_updates.append((winner, loser, surface, ro.ELO_K * (
                        1.0 - ro.elo_p(surface_r[(winner, surface)], surface_r[(loser, surface)]))))
            for winner, loser, delta in global_updates:
                global_r[winner] += delta
                global_r[loser] -= delta
            for winner, loser, surface, delta in surface_updates:
                surface_r[(winner, surface)] += delta
                surface_r[(loser, surface)] -= delta
    return {name: {k: np.asarray(v) for k, v in cols.items()} for name, cols in out.items()}


def cluster_interval(diff: np.ndarray, clusters: np.ndarray, label: str) -> dict:
    result = ro.paired_intervals({"d": diff}, clusters, label)["d"]
    return {"diff": result[0], "ci95": [result[1], result[2]], "clusters": result[3]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True)
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    records = Path(args.records_dir)
    report: dict = {"note": "post-hoc diagnostics; not used for selection"}

    # 1. Winner: 2x2 of start date and population, against M1, pooled and per year, plus the deployed model after warm-up.
    winner = {tour: winner_variants(args.db, tour) for tour in ro.TOURS}
    stacked = {name: {k: np.concatenate([winner[t][name][k] for t in ro.TOURS]) for k in ("year", "cluster", "brier")}
               for name in VARIANTS}
    m1 = np.load(records / "winner.npz")
    report["winner_check"] = {
        name: {"pooled_brier": float(stacked[name]["brier"].mean())} for name in VARIANTS
    }
    report["winner_check"]["M1_from_records"] = float(m1["M1__p"].mean())
    report["winner_check"]["M2_2000_matches_records"] = bool(np.allclose(
        np.sort(stacked["M2_2000_surface_rows"]["brier"]), np.sort(m1["M2_2000__p"]), atol=1e-12))
    report["winner_check"]["M2_2020_all_rows_matches_records"] = bool(np.allclose(
        np.sort(stacked["M2_2020_all_rows"]["brier"]), np.sort(m1["M2_live__p"]), atol=1e-12))
    m1_brier = m1["M1__p"]
    report["winner_vs_M1"] = {}
    for name in VARIANTS:
        diff = stacked[name]["brier"] - m1_brier
        report["winner_vs_M1"][name] = {
            "pooled": cluster_interval(diff, m1["cluster"], f"diag/{name}/M1"),
            "2023_2026": cluster_interval(diff[m1["year"] >= 2023], m1["cluster"][m1["year"] >= 2023],
                                          f"diag/{name}/M1/2023"),
        }
    # Start effect (2020 vs 2000, same population) and population effect (all rows vs surface rows, same start).
    start_effect = stacked["M2_2020_surface_rows"]["brier"] - stacked["M2_2000_surface_rows"]["brier"]
    population_effect = stacked["M2_2020_all_rows"]["brier"] - stacked["M2_2020_surface_rows"]["brier"]
    report["winner_effects"] = {
        "start_2020_minus_2000_pooled": cluster_interval(start_effect, m1["cluster"], "diag/start"),
        "start_2020_minus_2000_2023_2026": cluster_interval(
            start_effect[stacked["M2_2000_surface_rows"]["year"] >= 2023],
            m1["cluster"][m1["year"] >= 2023], "diag/start/2023"),
        "all_rows_minus_surface_rows_pooled_2020_start": cluster_interval(
            population_effect, m1["cluster"], "diag/population"),
    }
    report["winner_per_year_brier"] = {
        name: {int(y): float(stacked[name]["brier"][stacked[name]["year"] == y].mean()) for y in ro.YEARS}
        for name in VARIANTS
    }

    # 2. Tour check for the selected incumbents (pooled over years, per tour).
    tour_check = {}
    for name, label_a, label_b in (
        ("winner", "M2_2000", "M1"),
        ("games", "direct_surface_competitive", "direct_surface"),
        ("counts_aces", "p1_gamma_poisson", "p0_gamma_poisson"),
        ("counts_double_faults", "p1_gamma_poisson", "p0_gamma_poisson"),
    ):
        arr = np.load(records / f"{name}.npz")
        tour_check[name] = {"candidate": label_a, "runner_or_reference": label_b}
        for tour, code in (("atp", 0), ("wta", 1)):
            mask = arr["tour"] == code
            diff = arr[f"{label_a}__p"][mask] - arr[f"{label_b}__p"][mask]
            tour_check[name][tour] = cluster_interval(diff, arr["cluster"][mask], f"tour/{name}/{tour}")
    report["tour_check"] = tour_check

    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True, default=float) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
