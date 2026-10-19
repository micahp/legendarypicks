#!/usr/bin/env python3
"""WTA test of M2: the registered verdict, and the declared per-tour K sensitivity.

Protocol: research/tennis/rolling/2026-10-19/PROTOCOL-wta-m2.md, committed before this script was run.
The registered numbers are read from a1_per_tour.json, so the verdict cannot drift from the A1 record. The K = 32
replay is checked against those numbers before any sensitivity result is used. The sensitivity is diagnostic only.
Read-only on the database.
  python3 -I research/tennis/rolling/2026-10-19/wta_m2_check.py --db <dev DB, read-only>
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
TOURS = ("atp", "wta")
K_GRID = (16.0, 24.0, 32.0, 40.0, 48.0)
REGISTERED_K = 32.0
TUNE = (2015, 2019)
EVAL = (2020, 2026)
TOUR_NAME = {"atp": "ATP", "wta": "WTA"}


def brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (np.clip(p, 1e-9, 1 - 1e-9) - y) ** 2


def in_window(years: np.ndarray, window: tuple[int, int]) -> np.ndarray:
    return (years >= window[0]) & (years <= window[1])


def replays(db: str, tour: str) -> dict[float, dict[str, Any]]:
    out = {k: a1.winner_forecasts(db, tour, k=k) for k in K_GRID}
    base = out[REGISTERED_K]
    for k, f in out.items():
        same = all(np.array_equal(f[key], base[key]) for key in ("y", "year", "event", "cluster"))
        if not same:
            raise SystemExit(f"{tour}: rows differ between K values, so the paired comparison is invalid (K={k})")
    return out


def tune(out: dict[float, dict[str, Any]], model: str) -> tuple[float, dict[str, float]]:
    base = out[REGISTERED_K]
    mask = in_window(base["year"], TUNE)
    scores = {k: float(brier(out[k][f"p_{model}"][mask], base["y"][mask]).mean()) for k in K_GRID}
    best = min(K_GRID, key=lambda k: (scores[k], k))  # ties go to the smaller K
    return best, {str(k): v for k, v in scores.items()}


def paired_eval(out: dict[float, dict[str, Any]], tour: str, k_m1: float, k_m2: float, label: str) -> dict[str, Any]:
    base = out[REGISTERED_K]
    mask = in_window(base["year"], EVAL)
    y = base["y"][mask]
    b1 = brier(out[k_m1]["p_M1"][mask], y)
    b2 = brier(out[k_m2]["p_M2_2000"][mask], y)
    diff = b2 - b1
    mean, lo, hi, n = ro.paired_intervals({"d": diff}, base["cluster"][mask], f"{label}-{tour}")["d"]
    years = base["year"][mask]
    per_year = {int(yr): float(diff[years == yr].mean()) for yr in range(EVAL[0], EVAL[1] + 1) if (years == yr).any()}
    return {"k_M1": k_m1, "k_M2": k_m2, "matches": int(n), "brier_M1": float(b1.mean()),
            "brier_M2_2000": float(b2.mean()), "delta_M2_minus_M1": mean, "ci95": [lo, hi],
            "per_year": per_year, "years_negative": sum(1 for v in per_year.values() if v < 0),
            "years_evaluated": len(per_year)}


def registered(a1_json: dict[str, Any], tour: str) -> dict[str, Any]:
    t = a1_json["tours"][tour]
    p = t["paired_vs_M1"]["pooled"]
    return {"matches": t["population"]["matches"], "brier_M1": t["brier_pooled"]["M1"],
            "brier_M2_2000": t["brier_pooled"]["M2_2000"],
            "delta_M2_minus_M1": p["M2_2000"]["diff"], "ci95": p["M2_2000"]["ci95"],
            "years_negative": t["paired_vs_M1"]["years_negative"]["M2_2000"],
            "deployed_delta_M2_live_minus_M1": p["M2_live"]["diff"],
            "deployed_ci95": p["M2_live"]["ci95"]}


def verdict(tour: str, ci: list[float]) -> str:
    if ci[1] < 0:
        return f"{TOUR_NAME[tour]}: interval below zero, M2 beats M1"
    return f"{TOUR_NAME[tour]}: interval contains zero"


def tables(result: dict[str, Any]) -> str:
    lines = ["#### Registered test (shared configuration, the verdict)\n",
             "| Tour | Matches | M1 Brier | M2 on 2000 history Brier | M2 minus M1 | Match-clustered 95% | Years negative | Verdict |",
             "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |"]
    for tour in TOURS:
        r = result["registered"][tour]
        lines.append(f"| {TOUR_NAME[tour]} | {r['matches']:,} | {r['brier_M1']:.5f} | {r['brier_M2_2000']:.5f} | "
                     f"{r['delta_M2_minus_M1']:+.5f} | [{r['ci95'][0]:+.5f}, {r['ci95'][1]:+.5f}] | "
                     f"{r['years_negative']} of 12 | {result['verdict'][tour]} |")
    lines += ["", "Deployed M2 (2020 history) minus M1, for reference: "
              + "; ".join(f"{TOUR_NAME[t]} {result['registered'][t]['deployed_delta_M2_live_minus_M1']:+.5f} "
                          f"[{result['registered'][t]['deployed_ci95'][0]:+.5f}, "
                          f"{result['registered'][t]['deployed_ci95'][1]:+.5f}]" for t in TOURS) + "\n",
              "#### Diagnostic: per-tour K sensitivity (K tuned 2015 to 2019, evaluated 2020 to 2026)\n",
              "| Tour | K for M1 | K for M2 | M1 Brier 2020 to 2026 | M2 Brier 2020 to 2026 | M2 minus M1 | Match-clustered 95% | Years negative (of 7) | M2 minus M1 at K 32, 2020 to 2026 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |"]
    for tour in TOURS:
        s = result["sensitivity"][tour]
        r32 = result["registered_k32_2020_2026"][tour]
        lines.append(f"| {TOUR_NAME[tour]} | {s['k_M1']:g} | {s['k_M2']:g} | {s['brier_M1']:.5f} | {s['brier_M2_2000']:.5f} | "
                     f"{s['delta_M2_minus_M1']:+.5f} | [{s['ci95'][0]:+.5f}, {s['ci95'][1]:+.5f}] | "
                     f"{s['years_negative']} | {r32['delta_M2_minus_M1']:+.5f} [{r32['ci95'][0]:+.5f}, {r32['ci95'][1]:+.5f}] |")
    lines += ["", "#### Tuning scores (mean Brier, 2015 to 2019)\n",
              "| Tour | Model | " + " | ".join(f"K {k:g}" for k in K_GRID) + " | Chosen K |",
              "| --- | --- | " + " | ".join("---:" for _ in K_GRID) + " | ---: |"]
    for tour in TOURS:
        for model, label in (("M1", "M1"), ("M2_2000", "M2 on 2000 history")):
            tu = result["tuning"][tour][model]
            cells = " | ".join(f"{tu['scores'][str(k)]:.5f}" for k in K_GRID)
            lines.append(f"| {TOUR_NAME[tour]} | {label} | {cells} | {tu['k_star']:g} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    a1_json = json.loads((HERE / "a1_per_tour.json").read_text())
    result: dict[str, Any] = {"protocol": "PROTOCOL-wta-m2.md", "k_grid": list(K_GRID), "tune_window": TUNE,
                              "eval_window": EVAL, "registered": {}, "verdict": {}, "tuning": {}, "sensitivity": {},
                              "registered_k32_2020_2026": {}}
    for tour in TOURS:
        out = replays(args.db, tour)
        base = out[REGISTERED_K]
        reg = registered(a1_json, tour)
        result["registered"][tour] = reg
        # The K = 32 replay must reproduce the A1 record before anything is compared with it.
        mean_m1 = float(brier(base["p_M1"], base["y"]).mean())
        mean_m2 = float(brier(base["p_M2_2000"], base["y"]).mean())
        if abs(mean_m1 - reg["brier_M1"]) > 1e-12 or abs(mean_m2 - reg["brier_M2_2000"]) > 1e-12:
            raise SystemExit(f"{tour}: K = 32 replay does not reproduce a1_per_tour.json")
        result["verdict"][tour] = verdict(tour, reg["ci95"])
        k_m1, scores_m1 = tune(out, "M1")
        k_m2, scores_m2 = tune(out, "M2_2000")
        result["tuning"][tour] = {"M1": {"k_star": k_m1, "scores": scores_m1},
                                  "M2_2000": {"k_star": k_m2, "scores": scores_m2}}
        result["sensitivity"][tour] = paired_eval(out, tour, k_m1, k_m2, "wta-k-sens")
        result["registered_k32_2020_2026"][tour] = paired_eval(out, tour, REGISTERED_K, REGISTERED_K, "wta-k32")
        print(tour, "K* M1", k_m1, "K* M2", k_m2, "eval delta", round(result["sensitivity"][tour]["delta_M2_minus_M1"], 6),
              result["sensitivity"][tour]["ci95"], "K32 delta", round(result["registered_k32_2020_2026"][tour]["delta_M2_minus_M1"], 6))
    wta_clear = result["registered"]["wta"]["ci95"][1] < 0
    atp_clear = result["registered"]["atp"]["ci95"][1] < 0
    result["overall"] = ("M2 validated on both tours" if wta_clear and atp_clear
                         else "M2 is ATP-only: recommendation is per-tour model selection" if atp_clear
                         else "M2 not validated on ATP under this check")
    (HERE / "wta_m2_check.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (HERE / "WTA-M2-TABLES.md").write_text(tables(result))
    for tour in TOURS:
        print(TOUR_NAME[tour], "registered", result["registered"][tour]["delta_M2_minus_M1"],
              result["registered"][tour]["ci95"], "->", result["verdict"][tour])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
