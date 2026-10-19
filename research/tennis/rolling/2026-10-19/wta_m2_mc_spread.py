#!/usr/bin/env python3
"""Monte Carlo spread of the bootstrap endpoints for the WTA M2 check.

The statistic is unchanged: the match-clustered paired difference M2 minus M1, from the same replay and the same
ro.paired_intervals bootstrap (1,000 resamples). Only the bootstrap block label varies. The registered label
reproduces the A1 record exactly, which checks this script against a1_per_tour.json. The spread shows how far the
95% endpoints move with the seed, so a bound near zero is read at its real precision.
Read-only on the database.
  python3 -I research/tennis/rolling/2026-10-19/wta_m2_mc_spread.py --db <dev DB, read-only>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import a1_per_tour as a1  # noqa: E402

ro = a1.ro
EXTRA_LABELS = ("mc-1", "mc-2", "mc-3", "mc-4")


def spread(diff: np.ndarray, cluster: np.ndarray, registered_label: str) -> dict[str, Any]:
    rows = {}
    for label in (registered_label, *EXTRA_LABELS):
        mean, lo, hi, _ = ro.paired_intervals({"d": diff}, cluster, label)["d"]
        rows[label] = {"mean": mean, "ci95": [lo, hi]}
    uppers = [v["ci95"][1] for v in rows.values()]
    lowers = [v["ci95"][0] for v in rows.values()]
    return {"labels": rows, "upper_min": min(uppers), "upper_max": max(uppers),
            "lower_min": min(lowers), "lower_max": max(lowers)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    a1_json = json.loads((HERE / "a1_per_tour.json").read_text())
    check = json.loads((HERE / "wta_m2_check.json").read_text())
    result: dict[str, Any] = {"statistic": "match-clustered paired difference, M2 on 2000 history minus M1, 1,000 resamples",
                              "tours": {}}
    for tour in ("atp", "wta"):
        f32 = a1.winner_forecasts(args.db, tour, k=32.0)
        b1, b2 = (np.clip(f32["p_M1"], 1e-9, 1 - 1e-9) - f32["y"]) ** 2, (np.clip(f32["p_M2_2000"], 1e-9, 1 - 1e-9) - f32["y"]) ** 2
        diff = b2 - b1
        # The registered 2015 to 2026 interval, with the A1 block label, must reproduce a1_per_tour.json.
        registered = spread(diff, f32["cluster"], f"a1-{tour}-match")
        rec = a1_json["tours"][tour]["paired_vs_M1"]["pooled"]["M2_2000"]["ci95"]
        reg_ci = registered["labels"][f"a1-{tour}-match"]["ci95"]
        if max(abs(reg_ci[0] - rec[0]), abs(reg_ci[1] - rec[1])) > 1e-12:
            raise SystemExit(f"{tour}: registered interval does not reproduce a1_per_tour.json: {reg_ci} vs {rec}")
        # The diagnostic sensitivity: the tuned K pair, 2020 to 2026, with its declared block key.
        k_m1 = check["tuning"][tour]["M1"]["k_star"]
        k_m2 = check["tuning"][tour]["M2_2000"]["k_star"]
        f1 = a1.winner_forecasts(args.db, tour, k=k_m1) if k_m1 != 32.0 else f32
        f2 = a1.winner_forecasts(args.db, tour, k=k_m2) if k_m2 != 32.0 else f32
        if not (np.array_equal(f1["y"], f32["y"]) and np.array_equal(f2["y"], f32["y"])):
            raise SystemExit(f"{tour}: rows differ across K values")
        sens_diff = ((np.clip(f2["p_M2_2000"], 1e-9, 1 - 1e-9) - f2["y"]) ** 2
                     - (np.clip(f1["p_M1"], 1e-9, 1 - 1e-9) - f1["y"]) ** 2)
        mask = (f32["year"] >= 2020) & (f32["year"] <= 2026)
        sensitivity = spread(sens_diff[mask], f32["cluster"][mask], f"wta-k-sens-{tour}")
        result["tours"][tour] = {"registered_2015_2026": registered, "sensitivity_2020_2026": sensitivity,
                                 "k_m1": k_m1, "k_m2": k_m2}
        print(tour, "registered upper range", round(registered["upper_min"], 6), round(registered["upper_max"], 6),
              "| sensitivity upper range", round(sensitivity["upper_min"], 6), round(sensitivity["upper_max"], 6))
    (HERE / "wta_m2_mc_spread.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
