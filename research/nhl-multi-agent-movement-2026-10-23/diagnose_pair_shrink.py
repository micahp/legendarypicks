#!/usr/bin/env python3
"""Run the preregistered, descriptive JC-DIAG3 pair-geometry shrink analysis."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from collections import defaultdict
from itertools import combinations
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "research/nhl-multi-agent-movement-2026-10-23/results"
DATA = Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23")
PREREG = ROOT / "docs/research/NHL-JC-DIAG3-PREREG-2026-10-23.md"
PREREG_COMMIT = "6de9fb88b031606ff2191aecf83cc970378c39ba"
PREREG_SHA256 = "96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de"
BASE_COMMIT = "2cdbe1f3859e5fcf4060c2a698d0e421658e26ca"
DIAG1_RESULTS = RESULTS / "jc-attribution-jcdiag-2026-10-23-v1.json"
DIAG2_RESULTS = RESULTS / "jc-diag2-pair-persistence-2026-10-23-v1.json"
DIAG2_PREREG = ROOT / "docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md"
PATHS = {
    "jc_results": RESULTS / "joint-coherence-jc-2026-10-23-v1.json",
    "fold_models": RESULTS / "fold_models-bc91d1610de5.json",
    "movement_comparison": RESULTS / "movement_comparison-bc91d1610de5.json",
    "scenario_archive": RESULTS / "scenario_archive-bc91d1610de5.json.gz",
    "rollout_starts": DATA / "rollout_starts.json.gz",
    "jc_diag_results": DIAG1_RESULTS,
    "jc_diag2_preregistration": DIAG2_PREREG,
    "jc_diag2_results": DIAG2_RESULTS,
}
EXPECTED_HASHES = {
    "jc_results": "0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c",
    "fold_models": "194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a",
    "movement_comparison": "1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8",
    "scenario_archive": "a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce",
    "rollout_starts": "07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de",
    "jc_diag_results": "f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c",
    "jc_diag2_preregistration": "2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234",
    "jc_diag2_results": "54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed",
}
MODELS = ("M0", "M1", "M2")
CANDIDATES = ("M1", "M2")
TEAMS = ("Home", "Away")
GROUPS = ("Home", "Away", "EqualTeam")
HORIZONS = (15, 45)
MIN_PAIRS = 3
BOOTSTRAPS = 10_000
SEED = 20261024
EXPECTED_P3_EDGES = [
    0.02013880768063752, 0.03778431147562884, 0.057149271788077625,
    0.0772826427731225, 0.10184994154651683, 0.12700537055808211,
    0.16006325254241388, 0.2074288029626061, 0.2889645922798206,
]
EXPECTED_P4_EDGES = [17.038243596734116, 25.896550730297974, 36.18400154397977]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def finite_xy(value: object) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in value))


def get_path(value: dict, *path):
    for key in path:
        value = value[key]
    return value


def near(actual: float, expected: float, tolerance: float = 5e-9) -> bool:
    return math.isfinite(float(actual)) and abs(float(actual) - expected) <= tolerance


def source_hash_gate() -> tuple[dict, list[dict]]:
    actual, checks = {}, []
    for name, path in PATHS.items():
        if not path.is_file():
            actual[name] = None
            checks.append({"name": name, "path": str(path), "expected": EXPECTED_HASHES[name],
                           "actual": None, "passed": False, "reason": "missing_source"})
            continue
        value = sha256_file(path)
        actual[name] = value
        checks.append({"name": name, "path": str(path), "expected": EXPECTED_HASHES[name],
                       "actual": value, "passed": value == EXPECTED_HASHES[name]})
    prereg_actual = sha256_file(PREREG) if PREREG.is_file() else None
    checks.append({"name": "jc_diag3_preregistration", "path": str(PREREG),
                   "expected": PREREG_SHA256, "actual": prereg_actual,
                   "passed": prereg_actual == PREREG_SHA256})
    return actual, checks


def raw_frame_support(jc: dict, archive: dict, starts_manifest: dict) -> dict:
    starts = starts_manifest["starts"]
    games = list(jc["population"]["games"])
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in archive["scenarios"].values()}
    start_ids = [f"{row['game']}|{row['period']}|{row['cutoff_seq']}" for row in starts]
    if len(start_ids) != 200 or len(set(start_ids)) != 200:
        raise RuntimeError(f"expected 200 unique frozen starts, got {len(start_ids)}")
    if set(start_ids) - scenario_by_id.keys():
        raise RuntimeError("rollout-start manifest references missing scenarios")
    jc_rows = {(r["scenario_id"], int(r["horizon_ordinal_increment"])): r
               for r in jc["scenario_measurements"]}
    if len(jc_rows) != len(jc["scenario_measurements"]):
        raise RuntimeError("duplicate frozen JC scenario/horizon rows")

    totals = {team: 0 for team in TEAMS}
    p3_totals = {team: 0 for team in TEAMS}
    p4_totals = {team: 0 for team in TEAMS}
    scored_ids, per_start, grid_checks = [], {}, []
    for start, sid in zip(starts, start_ids):
        scenario = scenario_by_id[sid]
        initial_rows = scenario["initial_state"]["players"]
        initial = {p["id"]: p for p in initial_rows}
        if len(initial) != len(initial_rows):
            raise RuntimeError(f"duplicate initial-state track ID in {sid}")
        team_by_id = {pid: p["team"] for pid, p in initial.items()}
        if any(team not in TEAMS for team in team_by_id.values()):
            raise RuntimeError(f"unknown team in initial state for {sid}")
        if any(not finite_xy([p.get("x"), p.get("y")]) for p in initial.values()):
            raise RuntimeError(f"nonfinite initial position in {sid}")
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        counts_by_h = {}
        common_ids_by_h = {}
        eligible45 = None
        for h in (1, 15, 30, 45):
            frame = frames[h]
            observed = (frame.get("observed") or {}).get("players") or {}
            models = {m: frame.get("models", {}).get(m, {}).get("players", {}) for m in MODELS}
            common = [pid for pid in initial if finite_xy(observed.get(pid)) and
                      all(finite_xy(models[m].get(pid)) for m in MODELS)]
            common_ids_by_h[h] = {team: {pid for pid in common if team_by_id[pid] == team} for team in TEAMS}
            counts = {team: sum(team_by_id[pid] == team for pid in common) for team in TEAMS}
            pairs = {team: counts[team] * (counts[team] - 1) // 2 for team in TEAMS}
            eligible = all(counts[t] >= 2 for t in TEAMS)
            jc_row = jc_rows.get((sid, h))
            if jc_row is None:
                raise RuntimeError(f"missing JC row for {sid} +{h}")
            published_eligible = bool(jc_row["eligible"])
            pub_counts = jc_row["counts"]
            expected_pub = {
                "common_skaters": len(common),
                "common_home_skaters": counts["Home"],
                "common_away_skaters": counts["Away"],
                "home_within_team_pairs": pairs["Home"],
                "away_within_team_pairs": pairs["Away"],
            }
            passed = eligible == published_eligible and all(int(pub_counts[k]) == v for k, v in expected_pub.items())
            grid_checks.append({"start_id": sid, "horizon": h, "passed": passed,
                                "raw_eligible": eligible, "jc_eligible": published_eligible,
                                "raw_counts": expected_pub,
                                "jc_counts": {k: int(pub_counts[k]) for k in expected_pub}})
            if not passed:
                raise RuntimeError(f"raw-frame/JC support mismatch at {sid} +{h}: {expected_pub} vs {pub_counts}")
            counts_by_h[str(h)] = {"skaters_by_team": counts, "pairs_by_team": pairs,
                                   "jc_eligible": eligible}
            if h == 45:
                eligible45 = eligible
                if eligible:
                    scored_ids.append(sid)
                    for team in TEAMS:
                        totals[team] += pairs[team]
                        p3_ids = set.intersection(*(common_ids_by_h[h][team] for h in (1, 15, 45)))
                        p3_totals[team] += len(p3_ids) * (len(p3_ids) - 1) // 2
                        n45 = len(common_ids_by_h[45][team])
                        p4_totals[team] += n45 * (n45 - 1) // 2
        per_start[sid] = {"game": scenario["game"], "eligible_plus45": eligible45,
                          "by_horizon": counts_by_h}

    plus45_ok = len(scored_ids) == 172 and totals == {"Home": 1064, "Away": 1100} and sum(totals.values()) == 2164
    p3_ok = sum(p3_totals.values()) == 2164
    p4_ok = sum(p4_totals.values()) == 2164
    return {
        "game_count": len(games), "rollout_start_count": len(starts),
        "plus45_scored_start_count": len(scored_ids), "plus45_pair_counts_by_team": totals,
        "plus45_pair_count_total": sum(totals.values()), "raw_denominator_assertion_passed": plus45_ok,
        "p3_common_1_15_45_pair_counts_by_team": p3_totals,
        "p3_common_1_15_45_pair_count_total": sum(p3_totals.values()),
        "p4_cutoff_plus45_pair_counts_by_team": p4_totals,
        "p4_cutoff_plus45_pair_count_total": sum(p4_totals.values()),
        "p3_fixed_bin_support_assertion_passed": p3_ok,
        "p4_fixed_bin_support_assertion_passed": p4_ok,
        "per_start_raw_frame_counts": per_start, "jc_grid_reconciliation": grid_checks,
        "scored_start_ids": scored_ids,
    }


def run_provenance_gate(output_path: Path) -> tuple[dict | None, dict | None, dict | None, dict]:
    hashes, hash_checks = source_hash_gate()
    gate = {"expected_source_hashes": EXPECTED_HASHES, "actual_source_hashes": hashes,
            "source_hash_checks": hash_checks, "assertions": [], "all_assertions_passed": False}
    if not all(item["passed"] for item in hash_checks):
        gate["failure"] = "frozen source or preregistration hash mismatch; Q1-Q4 not run"
        write_failure(output_path, gate)
        return None, None, None, gate

    try:
        jc = read_json(PATHS["jc_results"])
        diag1 = read_json(DIAG1_RESULTS)
        diag2 = read_json(DIAG2_RESULTS)
        archive = read_gzip_json(PATHS["scenario_archive"])
        starts = read_gzip_json(PATHS["rollout_starts"])
        actual_support = raw_frame_support(jc, archive, starts)
    except Exception as exc:
        gate["failure"] = f"provenance artifact or raw-frame assertion failed: {type(exc).__name__}: {exc}"
        write_failure(output_path, gate)
        print("PROVENANCE FAILURE", gate["failure"])
        return None, None, None, gate

    scalar_specs = [
        ("plus45_M1_signed_pair_error_ft", -3.990319961147472,
         ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds", "45",
          "within_team_pair_distribution", "M1", "metrics", "signed_mean"), 5e-9),
        ("plus45_M2_signed_pair_error_ft", -4.018689087597857,
         ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds", "45",
          "within_team_pair_distribution", "M2", "metrics", "signed_mean"), 5e-9),
        ("plus45_M1_individual_radial_gain_ft", 1.1295843676250077,
         ("Q5_plus45_individual_group_dissociation", "candidates", "M1", "individual_radial_gain_ft"), 5e-9),
        ("plus15_M1_Home_signed_pair_bias_ft", -0.819339742276739,
         ("Q1_pair_type_and_team_decomposition", "horizons_ordinal_increments_not_seconds", "15",
          "by_team", "Home", "model_estimates", "M1", "signed_pair_bias_ft"), 5e-5),
    ]
    for name, expected, path, tolerance in scalar_specs:
        value = get_path(diag1, *path)
        if isinstance(value, dict):
            value = value.get("estimate", value.get("equal_game_mean_available_games"))
        actual = float(value)
        gate["assertions"].append({"name": name, "expected": expected, "actual": actual,
                                   "tolerance_abs": tolerance,
                                   "passed": near(actual, expected, tolerance)})

    ci_specs = [
        ("plus45_M1_signed_pair_error_95ci", [-4.745503058078117, -3.277490265327321],
         ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds", "45",
          "within_team_pair_distribution", "M1", "metrics", "signed_mean", "bootstrap_95_percentile_interval")),
        ("plus45_M2_signed_pair_error_95ci", [-4.7651974061864095, -3.325853562183953],
         ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds", "45",
          "within_team_pair_distribution", "M2", "metrics", "signed_mean", "bootstrap_95_percentile_interval")),
    ]
    for name, expected, path in ci_specs:
        actual = [float(x) for x in get_path(diag1, *path)]
        gate["assertions"].append({"name": name, "expected": expected, "actual": actual,
                                   "tolerance_abs": 5e-9,
                                   "passed": len(actual) == 2 and all(near(actual[i], expected[i]) for i in range(2))})

    gate["assertions"].append({
        "name": "plus45_pair_denominators_recomputed_from_raw_frames",
        "expected": {"Home": 1064, "Away": 1100, "total": 2164},
        "actual": {**actual_support["plus45_pair_counts_by_team"], "total": actual_support["plus45_pair_count_total"]},
        "passed": actual_support["raw_denominator_assertion_passed"],
    })

    p1_m1 = get_path(diag2, "P1_plus15_to_plus45_pair_persistence", "summary", "models", "EqualTeam", "M1")
    obs = float(p1_m1["observed_share"]["equal_game_mean_available_games"])
    null = float(p1_m1["permutation_null_mean"]["equal_game_mean_available_games"])
    gate["assertions"].append({"name": "JC_DIAG2_P1_EqualTeam_M1_observed_mass_share",
                               "expected": 0.8305414523474803, "actual": obs, "tolerance_abs": 5e-9,
                               "passed": near(obs, 0.8305414523474803)})
    gate["assertions"].append({"name": "JC_DIAG2_P1_EqualTeam_M1_permutation_null",
                               "expected": 0.6201172173403376, "actual": null, "tolerance_abs": 5e-9,
                               "passed": near(null, 0.6201172173403376)})
    edges3 = [float(x) for x in diag2["P4_observed_cutoff_distance_quartiles"]["distance_quartile_edges_ft"]]
    gate["assertions"].append({"name": "JC_DIAG2_P4_distance_quartile_edges_ft",
                               "expected": EXPECTED_P4_EDGES, "actual": edges3, "tolerance_abs": 5e-9,
                               "passed": len(edges3) == 3 and all(near(edges3[i], EXPECTED_P4_EDGES[i]) for i in range(3))})
    edges2 = [float(x) for x in diag2["P3_one_step_M0_error_deciles"]["decile_edges_ft"]]
    gate["assertions"].append({"name": "JC_DIAG2_P3_M0_plus1_decile_edges_ft",
                               "expected": EXPECTED_P3_EDGES, "actual": edges2, "tolerance_abs": 5e-9,
                               "passed": len(edges2) == 9 and all(near(edges2[i], EXPECTED_P3_EDGES[i]) for i in range(9))})
    expected_p3_count = int(diag2["P3_one_step_M0_error_deciles"]["pair_count_total"])
    expected_p4_count = int(diag2["P4_observed_cutoff_distance_quartiles"]["pair_count_total"])
    gate["assertions"].append({"name": "JC_DIAG2_P3_frozen_common_support_pair_count",
                               "expected": expected_p3_count,
                               "actual": actual_support["p3_common_1_15_45_pair_count_total"],
                               "passed": expected_p3_count == 2164 and
                                        actual_support["p3_common_1_15_45_pair_count_total"] == expected_p3_count})
    gate["assertions"].append({"name": "JC_DIAG2_P4_frozen_common_support_pair_count",
                               "expected": expected_p4_count,
                               "actual": actual_support["p4_cutoff_plus45_pair_count_total"],
                               "passed": expected_p4_count == 2164 and
                                        actual_support["p4_cutoff_plus45_pair_count_total"] == expected_p4_count})

    gate["raw_frame_support"] = actual_support
    gate["published_values_references"] = {
        "jc_diag1_result_sha256": hashes["jc_diag_results"],
        "jc_diag2_result_sha256": hashes["jc_diag2_results"],
        "jc_diag2_preregistration_sha256": hashes["jc_diag2_preregistration"],
    }
    gate["all_assertions_passed"] = all(row["passed"] for row in gate["assertions"])
    if not gate["all_assertions_passed"]:
        gate["failure"] = "one or more frozen provenance assertions failed; Q1-Q4 not run"
        write_failure(output_path, gate)
        for item in gate["assertions"]:
            print("PROVENANCE", json.dumps(item, sort_keys=True))
        return None, None, None, gate

    print(f"PROVENANCE 8 frozen source hashes + preregistration hash: {len(hash_checks)} PASS")
    for item in gate["assertions"]:
        print("PROVENANCE", json.dumps(item, sort_keys=True))
    print("PROVENANCE raw-frame +45 denominator: Home 1064 + Away 1100 = 2164 PASS")
    return jc, archive, starts, gate


def write_json(path: Path, payload: dict) -> tuple[str, int]:
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def write_failure(path: Path, gate: dict) -> None:
    payload = {
        "schema_version": 1, "analysis": "NHL JC-DIAG3 pair-geometry shrink diagnosis",
        "base_commit": BASE_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                             "sha256": PREREG_SHA256},
        "provenance_gate": gate, "all_assertions_passed": False,
        "Q1_Q4": "not_run_due_to_provenance_failure",
    }
    try:
        digest, size = write_json(path, payload)
        print(f"FAILURE JSON path={path} sha256={digest} bytes={size}")
    except FileExistsError:
        print(f"FAILURE JSON NOT WRITTEN: output already exists at {path}")


def finite_float(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def make_pair_data(jc: dict, archive: dict, starts_manifest: dict, gate: dict) -> tuple[dict, list[str], list[str], list[str]]:
    games = list(jc["population"]["games"])
    starts = starts_manifest["starts"]
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in archive["scenarios"].values()}
    scored_ids = gate["raw_frame_support"]["scored_start_ids"]
    scored_set = set(scored_ids)
    jc_rows = {(r["scenario_id"], int(r["horizon_ordinal_increment"])): r
               for r in jc["scenario_measurements"]}
    records = {}
    for row in starts:
        sid = f"{row['game']}|{row['period']}|{row['cutoff_seq']}"
        if sid not in scored_set:
            continue
        scenario = scenario_by_id[sid]
        initial_rows = scenario["initial_state"]["players"]
        initial = {p["id"]: np.asarray([p["x"], p["y"]], dtype=np.float64) for p in initial_rows}
        if len(initial) != len(initial_rows):
            raise RuntimeError(f"duplicate initial-state track ID in {sid}")
        team_by_id = {p["id"]: p["team"] for p in initial_rows}
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        records[sid] = {"game": scenario["game"], "period": row["period"], "horizons": {}}
        for h in (1, 15, 45):
            frame = frames[h]
            observed_players = (frame.get("observed") or {}).get("players") or {}
            model_players = {m: frame.get("models", {}).get(m, {}).get("players", {}) for m in MODELS}
            common = [pid for pid in initial if finite_xy(observed_players.get(pid)) and
                      all(finite_xy(model_players[m].get(pid)) for m in MODELS)]
            eligible = all(sum(team_by_id[pid] == t for pid in common) >= 2 for t in TEAMS)
            if eligible != bool(jc_rows[(sid, h)]["eligible"]):
                raise RuntimeError(f"frozen JC eligibility mismatch while building pair support: {sid} +{h}")
            pairs_by_team = {}
            for team in TEAMS:
                ids = sorted(pid for pid in common if team_by_id[pid] == team)
                observed = {pid: np.asarray(observed_players[pid], dtype=np.float64) for pid in ids}
                predicted = {m: {pid: np.asarray(model_players[m][pid], dtype=np.float64) for pid in ids}
                             for m in MODELS}
                pair_map = {}
                for first, second in combinations(ids, 2):
                    obs_distance = float(np.linalg.norm(observed[first] - observed[second]))
                    errors = {}
                    for model in MODELS:
                        pred_distance = float(np.linalg.norm(predicted[model][first] - predicted[model][second]))
                        errors[model] = pred_distance - obs_distance
                    if any(not math.isfinite(value) for value in errors.values()):
                        raise RuntimeError(f"nonfinite pair error in frozen support: {sid} +{h} {team} {(first, second)}")
                    pair_map[(first, second)] = {
                        "errors_ft": errors,
                        "cutoff_distance_ft": float(np.linalg.norm(initial[first] - initial[second])),
                    }
                pairs_by_team[team] = pair_map
            records[sid]["horizons"][h] = pairs_by_team

    if len(records) != 172:
        raise RuntimeError(f"expected 172 +45-scored starts in pair data, found {len(records)}")
    p3_rows, p4_rows = [], []
    for sid, start in records.items():
        for team in TEAMS:
            sets = [set(start["horizons"][h][team]) for h in (1, 15, 45)]
            for pair in sorted(set.intersection(*sets)):
                p1, p15, p45 = (start["horizons"][h][team][pair] for h in (1, 15, 45))
                p3_rows.append({"game": start["game"], "start_id": sid, "team": team,
                                "pair": list(pair), "baseline_abs_error_plus1_ft": abs(p1["errors_ft"]["M0"]),
                                "cutoff_distance_ft": p45["cutoff_distance_ft"],
                                "errors_by_horizon_ft": {"1": p1["errors_ft"], "15": p15["errors_ft"],
                                                         "45": p45["errors_ft"]}})
            for pair, p45 in start["horizons"][45][team].items():
                p4_rows.append({"game": start["game"], "start_id": sid, "team": team,
                                "pair": list(pair), "cutoff_distance_ft": p45["cutoff_distance_ft"],
                                "errors_ft": p45["errors_ft"]})
    return records, games, p3_rows, p4_rows


def metric_slope(rows: list[dict]) -> float | None:
    if not rows:
        return None
    x = np.asarray([r["x"] for r in rows], dtype=np.float64)
    y = np.asarray([r["y"] for r in rows], dtype=np.float64)
    w = np.asarray([r["weight"] for r in rows], dtype=np.float64)
    denom = float(np.dot(w, x * x))
    return float(np.dot(w, x * y) / denom) if math.isfinite(denom) and denom > 0 else None


def weighted_midrank(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    result = np.empty(len(values), dtype=np.float64)
    cumulative = 0.0
    i = 0
    while i < len(order):
        j = i + 1
        val = values[order[i]]
        while j < len(order) and values[order[j]] == val:
            j += 1
        group = order[i:j]
        group_weight = float(weights[group].sum())
        rank = cumulative + group_weight / 2.0
        result[group] = rank
        cumulative += group_weight
        i = j
    return result


def weighted_corr(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> float | None:
    sw = float(w.sum())
    if sw <= 0 or not math.isfinite(sw):
        return None
    ma = float(np.dot(w, a) / sw)
    mb = float(np.dot(w, b) / sw)
    da, db = a - ma, b - mb
    va, vb = float(np.dot(w, da * da)), float(np.dot(w, db * db))
    if va <= 0 or vb <= 0 or not math.isfinite(va + vb):
        return None
    return float(np.dot(w, da * db) / math.sqrt(va * vb))


def fit_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"kappa": None, "pearson": None, "spearman": None, "through_origin_r_squared": None}
    x = np.asarray([r["x"] for r in rows], dtype=np.float64)
    y = np.asarray([r["y"] for r in rows], dtype=np.float64)
    w = np.asarray([r["weight"] for r in rows], dtype=np.float64)
    den = float(np.dot(w, x * x))
    num = float(np.dot(w, x * y))
    kappa = num / den if den > 0 and math.isfinite(den) else None
    pearson = weighted_corr(x, y, w)
    rx, ry = weighted_midrank(x, w), weighted_midrank(y, w)
    spearman = weighted_corr(rx, ry, w)
    yden = float(np.dot(w, y * y))
    r2 = (1.0 - float(np.dot(w, (y - kappa * x) ** 2)) / yden
          if kappa is not None and yden > 0 and math.isfinite(yden) else None)
    return {"kappa": finite_float(kappa) if kappa is not None else None,
            "pearson": finite_float(pearson) if pearson is not None else None,
            "spearman": finite_float(spearman) if spearman is not None else None,
            "through_origin_r_squared": finite_float(r2) if r2 is not None else None}


def bootstrap_mean(values: dict[str, float | None], games: list[str], draws: np.ndarray) -> dict:
    present = [values.get(game) for game in games]
    valid_game_count = sum(v is not None and math.isfinite(float(v)) for v in present)
    if valid_game_count != len(games):
        return {"equal_game_mean": None, "bootstrap_95_ci": None, "valid_draws": 0,
                "available_games": valid_game_count, "games": values}
    arr = np.asarray([float(values[g]) for g in games], dtype=np.float64)
    estimate = float(arr.mean())
    boot = arr[draws].mean(axis=1)
    ci = [float(np.quantile(boot, .025, method="linear")), float(np.quantile(boot, .975, method="linear"))]
    return {"equal_game_mean": estimate, "bootstrap_95_ci": ci, "valid_draws": len(boot),
            "available_games": valid_game_count, "games": values}


def build_q1(records: dict, games: list[str], draws: np.ndarray) -> tuple[dict, dict]:
    output, cell_audit = {}, {}
    eligible_sids_by_h = {}
    eligible_cells_by_h = {}
    pair_rows_by_h_model_group = {}
    for h in HORIZONS:
        cells = {}
        for sid, start in records.items():
            for team in TEAMS:
                pairs = start["horizons"][h][team]
                n = len(pairs)
                x = [float(v["errors_ft"]["M0"]) for v in pairs.values()]
                sxx = float(np.dot(x, x)) if x else 0.0
                reason = None
                if n < MIN_PAIRS:
                    reason = "fewer_than_three_common_pairs"
                elif not math.isfinite(sxx) or sxx <= 0:
                    reason = "zero_or_undefined_m0_squared_denominator"
                cells[(sid, team)] = {"pair_count": n, "sum_m0_squared_ft2": sxx,
                                      "eligible": reason is None, "reason": reason}
        eligible_sids = {sid for sid in records if all(cells[(sid, team)]["eligible"] for team in TEAMS)}
        eligible_sids_by_h[h] = eligible_sids
        eligible_cells_by_h[h] = {key for key, value in cells.items() if value["eligible"]}
        cell_audit[str(h)] = {
            "per_start_team": {f"{sid}|{team}": value for (sid, team), value in sorted(cells.items())},
            "eligible_home_cells": sum(cells[(sid, "Home")]["eligible"] for sid in records),
            "eligible_away_cells": sum(cells[(sid, "Away")]["eligible"] for sid in records),
            "eligible_equalteam_starts": len(eligible_sids),
            "excluded_by_team": {},
        }
        for team in TEAMS:
            reasons = defaultdict(lambda: {"cells": 0, "pair_rows": 0})
            for sid in records:
                cell = cells[(sid, team)]
                if not cell["eligible"]:
                    item = reasons[cell["reason"]]
                    item["cells"] += 1
                    item["pair_rows"] += cell["pair_count"]
                elif team in TEAMS and sid not in eligible_sids:
                    item = reasons["other_team_cell_not_estimable_for_EqualTeam"]
                    item["cells"] += 1
                    item["pair_rows"] += cell["pair_count"]
            cell_audit[str(h)]["excluded_by_team"][team] = dict(reasons)

        output[str(h)] = {}
        for group in GROUPS:
            output[str(h)][group] = {}
            for candidate in CANDIDATES:
                rows = []
                raw_pairs = zero_pairs = 0
                excluded = defaultdict(lambda: {"cells": 0, "pair_rows": 0})
                selected_sids = eligible_sids if group == "EqualTeam" else set(records)
                for sid in records:
                    team_list = TEAMS if group == "EqualTeam" else (group,)
                    for team in team_list:
                        pair_map = records[sid]["horizons"][h][team]
                        raw_pairs += len(pair_map)
                        cell = cells[(sid, team)]
                        if not cell["eligible"]:
                            reason = cell["reason"]
                            excluded[reason]["cells"] += 1
                            excluded[reason]["pair_rows"] += len(pair_map)
                            continue
                        if group == "EqualTeam" and sid not in selected_sids:
                            excluded["other_team_cell_not_estimable_for_EqualTeam"]["cells"] += 1
                            excluded["other_team_cell_not_estimable_for_EqualTeam"]["pair_rows"] += len(pair_map)
                            continue
                        pair_weight = 1.0 / len(pair_map) if group == "EqualTeam" else 1.0
                        for pair, value in pair_map.items():
                            x = float(value["errors_ft"]["M0"])
                            y = float(value["errors_ft"][candidate])
                            zero_pairs += x == 0.0
                            rows.append({"game": records[sid]["game"], "start_id": sid, "team": team,
                                         "pair": list(pair), "x": x, "y": y, "weight": pair_weight})
                fit = fit_stats(rows)
                game_fits = {}
                for game in games:
                    game_rows = [r for r in rows if r["game"] == game]
                    game_fits[game] = metric_slope(game_rows)
                equal_game = bootstrap_mean(game_fits, games, draws)
                per_start = {
                    sid: metric_slope([r for r in rows if r["start_id"] == sid])
                    for sid in sorted(records)
                    if any(r["start_id"] == sid for r in rows)
                }
                output[str(h)][group][candidate] = {
                    "pooled_through_origin_fit": fit,
                    "equal_game_kappa": equal_game,
                    "raw_common_pair_count": raw_pairs,
                    "included_pair_count": len(rows),
                    "eligible_start_count": len({r["start_id"] for r in rows}),
                    "represented_game_count": len({r["game"] for r in rows}),
                    "m0_exact_zero_pair_count_in_fit": zero_pairs,
                    "pairs_excluded_for_zero_m0_individually": 0,
                    "pairs_excluded_for_nonfinite_m0": 0,
                    "exclusions": dict(excluded),
                    "per_game_kappa": game_fits,
                    "per_start_team_kappa": {
                        f"{sid}|{team}": metric_slope([
                            r for r in rows if r["start_id"] == sid and r["team"] == team])
                        for sid in sorted(records) for team in (TEAMS if group == "EqualTeam" else (group,))
                        if any(r["start_id"] == sid and r["team"] == team for r in rows)
                    },
                    "per_start_kappa": per_start,
                }
                pair_rows_by_h_model_group[(h, group, candidate)] = rows
    return {"by_horizon": output, "cell_eligibility_and_exclusions": cell_audit}, {
        "eligible_sids_by_horizon": eligible_sids_by_h,
        "eligible_cells_by_horizon": eligible_cells_by_h,
        "pair_rows": pair_rows_by_h_model_group,
        "cells": cell_audit,
    }


def percentile_ci(values: list[float | None], min_valid: int = 9500) -> tuple[list[float] | None, int]:
    valid = np.asarray([float(v) for v in values if v is not None and math.isfinite(float(v))], dtype=np.float64)
    if len(valid) < min_valid:
        return None, len(valid)
    return [float(np.quantile(valid, .025, method="linear")),
            float(np.quantile(valid, .975, method="linear"))], len(valid)


def q2_ratio_bootstrap(game_ratios: dict[str, np.ndarray], games: list[str], draws: np.ndarray) -> dict:
    medians, shares = [], []
    for indices in draws:
        arrays = [game_ratios[games[int(i)]] for i in indices if len(game_ratios[games[int(i)]])]
        if len(arrays) != len(indices):
            medians.append(None)
            shares.append(None)
            continue
        values = np.concatenate(arrays)
        medians.append(float(np.median(values)))
        shares.append(float(np.mean((values >= .3) & (values <= .7))))
    median_ci, median_n = percentile_ci(medians)
    share_ci, share_n = percentile_ci(shares)
    return {"median_95_bootstrap_ci": median_ci, "median_valid_draws": median_n,
            "share_03_07_95_bootstrap_ci": share_ci, "share_valid_draws": share_n,
            "total_draws": len(draws)}


def build_q2(q1_data: dict, records: dict, games: list[str], draws: np.ndarray) -> dict:
    eligible_cells = q1_data["eligible_cells_by_horizon"][45]
    all_pairs = []
    for sid in sorted(records):
        start = records[sid]
        for team in TEAMS:
            if (sid, team) not in eligible_cells:
                continue
            for pair, value in start["horizons"][45][team].items():
                all_pairs.append({"game": start["game"], "start_id": sid, "team": team,
                                  "pair": list(pair), "m0_error_ft": float(value["errors_ft"]["M0"]),
                                  "errors_ft": {m: float(value["errors_ft"][m]) for m in MODELS}})
    if not all_pairs:
        raise RuntimeError("Q2 has no pairs after the preregistered cell eligibility gate")
    threshold = float(np.median([abs(r["m0_error_ft"]) for r in all_pairs]))
    output = {"threshold_median_abs_m0_error_ft": threshold,
              "support_pair_count_before_zero_exclusion": len(all_pairs),
              "m0_exact_zero_count_before_ratio_filter": sum(r["m0_error_ft"] == 0 for r in all_pairs),
              "candidate_cohorts": {}, "pair_level_ratios": {}}
    for candidate in CANDIDATES:
        candidates = {}
        pair_level = []
        for cohort, predicate in (("full_support", lambda r: True),
                                  ("abs_m0_at_or_above_median", lambda r: abs(r["m0_error_ft"]) >= threshold)):
            cohort_rows = [r for r in all_pairs if predicate(r)]
            ratio_rows = []
            for row in cohort_rows:
                x = row["m0_error_ft"]
                if x == 0.0 or not math.isfinite(x):
                    continue
                ratio = row["errors_ft"][candidate] / x
                if not math.isfinite(ratio):
                    continue
                ratio_rows.append({**row, "ratio": float(ratio)})
            values = np.asarray([r["ratio"] for r in ratio_rows], dtype=np.float64)
            per_game = {}
            game_arrays = {}
            for game in games:
                gvals = np.asarray([r["ratio"] for r in ratio_rows if r["game"] == game], dtype=np.float64)
                game_arrays[game] = gvals
                per_game[game] = {
                    "pair_count": int(len(gvals)),
                    "median": float(np.median(gvals)) if len(gvals) else None,
                    "q1": float(np.quantile(gvals, .25, method="linear")) if len(gvals) else None,
                    "q3": float(np.quantile(gvals, .75, method="linear")) if len(gvals) else None,
                    "share_03_07": float(np.mean((gvals >= .3) & (gvals <= .7))) if len(gvals) else None,
                }
            bootstrap = q2_ratio_bootstrap(game_arrays, games, draws)
            candidates[cohort] = {
                "raw_pair_count_in_cohort": len(cohort_rows),
                "ratio_pair_count": len(ratio_rows),
                "exact_zero_m0_excluded": sum(r["m0_error_ft"] == 0 for r in cohort_rows),
                "negative_ratio_count": int(np.sum(values < 0)) if len(values) else 0,
                "median_ratio": float(np.median(values)) if len(values) else None,
                "median_ratio_bootstrap_95_ci": bootstrap["median_95_bootstrap_ci"],
                "median_valid_draws": bootstrap["median_valid_draws"],
                "ratio_iqr_q1_q3": ([float(np.quantile(values, .25, method="linear")),
                                     float(np.quantile(values, .75, method="linear"))] if len(values) else None),
                "share_ratio_in_0_3_to_0_7": (float(np.mean((values >= .3) & (values <= .7))) if len(values) else None),
                "share_ratio_in_0_3_to_0_7_bootstrap_95_ci": bootstrap["share_03_07_95_bootstrap_ci"],
                "share_valid_draws": bootstrap["share_valid_draws"],
                "per_game": per_game,
            }
            if cohort == "full_support":
                pair_level = [{"game": r["game"], "start_id": r["start_id"], "team": r["team"],
                               "pair": r["pair"], "m0_error_ft": r["m0_error_ft"],
                               "candidate_error_ft": r["errors_ft"][candidate], "ratio": r["ratio"],
                               "in_magnitude_subset": abs(r["m0_error_ft"]) >= threshold}
                              for r in ratio_rows]
        output["candidate_cohorts"][candidate] = candidates
        output["pair_level_ratios"][candidate] = pair_level
    return output


def binned_metric(rows: list[dict], bin_key: str | None, bin_count: int,
                  candidate: str, kappa: float, games: list[str], draws: np.ndarray) -> dict:
    grouped: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
    pair_counts = [0] * bin_count
    starts_by_bin = [set() for _ in range(bin_count)]
    games_by_bin = [set() for _ in range(bin_count)]
    for row in rows:
        b = int(row[bin_key]) if bin_key else 0
        if b < 0 or b >= bin_count:
            raise RuntimeError(f"invalid bin assignment {b} for {bin_key}")
        errs = (row["errors_by_horizon_ft"]["45"] if "errors_by_horizon_ft" in row
                else row["errors_ft"])
        x, y = float(errs["M0"]), float(errs[candidate])
        val = {"residual_ft": y - kappa * x, "raw_signed_delta_ft": y - x}
        grouped[(row["game"], row["start_id"], row["team"], b)].append(val)
        pair_counts[b] += 1
        starts_by_bin[b].add(row["start_id"])
        games_by_bin[b].add(row["game"])

    # Equal pair weight within start/team/bin, then equal represented-team weight within start/bin.
    start_bin = defaultdict(lambda: {"teams": {}, "pair_count": 0})
    for (game, sid, team, b), values in grouped.items():
        start_bin[(game, sid, b)]["teams"][team] = {
            "residual_ft": float(np.mean([v["residual_ft"] for v in values])),
            "raw_signed_delta_ft": float(np.mean([v["raw_signed_delta_ft"] for v in values])),
            "pair_count": len(values),
        }
        start_bin[(game, sid, b)]["pair_count"] += len(values)

    by_bin = []
    all_start_rows = []
    for b in range(bin_count):
        start_rows = []
        for (game, sid, bin_id), value in sorted(start_bin.items()):
            if bin_id != b:
                continue
            teams = value["teams"]
            item = {"game": game, "start_id": sid, "bin": b + 1,
                    "represented_teams": sorted(teams), "pair_count": value["pair_count"]}
            for metric in ("residual_ft", "raw_signed_delta_ft"):
                item[metric] = float(np.mean([team_values[metric] for team_values in teams.values()]))
            start_rows.append(item)
        all_start_rows.extend(start_rows)
        per_game = {}
        for metric in ("residual_ft", "raw_signed_delta_ft"):
            per_game[metric] = {}
            for game in games:
                vals = [r[metric] for r in start_rows if r["game"] == game]
                per_game[metric][game] = float(np.mean(vals)) if vals else None
        metric_summaries = {}
        for metric in ("residual_ft", "raw_signed_delta_ft"):
            # Whole-game bootstrap. Any sampled occurrence without this bin makes that draw undefined.
            gm = per_game[metric]
            valid_game_count = sum(gm[g] is not None for g in games)
            point = float(np.mean([gm[g] for g in games])) if valid_game_count == len(games) else None
            boot = []
            for indices in draws:
                sampled = [gm[games[int(i)]] for i in indices]
                boot.append(float(np.mean(sampled)) if all(v is not None for v in sampled) else None)
            ci, valid_n = percentile_ci(boot)
            metric_summaries[metric] = {"equal_game_mean": point, "bootstrap_95_ci": ci,
                                        "valid_draws": valid_n, "available_games": valid_game_count,
                                        "per_game_mean": gm}
        by_bin.append({"bin": b + 1, "pair_count": pair_counts[b],
                       "scored_start_count": len(starts_by_bin[b]),
                       "represented_game_count": len(games_by_bin[b]),
                       "start_team_bin_cell_count": sum(key[3] == b for key in grouped),
                       "not_estimable": pair_counts[b] == 0,
                       "metrics": metric_summaries})
    return {"bins": by_bin, "per_start_bin_values": all_start_rows}


def build_q3(records: dict, p3_rows: list[dict], p4_rows: list[dict], q1_data: dict, q1_summary: dict,
             games: list[str], draws: np.ndarray, p3_edges: list[float], p4_edges: list[float]) -> tuple[dict, dict]:
    eligible_cells = q1_data["eligible_cells_by_horizon"][45]
    q3_data = [r for r in p3_rows if (r["start_id"], r["team"]) in eligible_cells]
    q4_data = [r for r in p4_rows if (r["start_id"], r["team"]) in eligible_cells]
    for row in q3_data:
        row["baseline_error_decile"] = int(np.searchsorted(p3_edges, row["baseline_abs_error_plus1_ft"], side="right"))
    for row in q4_data:
        row["distance_quartile"] = int(np.searchsorted(p4_edges, row["cutoff_distance_ft"], side="right"))
    output = {"fixed_m0_plus1_error_decile_edges_ft": p3_edges,
              "fixed_observed_cutoff_distance_quartile_edges_ft": p4_edges,
              "p3_common_one_15_45_pair_count_before_q1_cell_gate": len(p3_rows),
              "p4_cutoff_plus45_pair_count_before_q1_cell_gate": len(p4_rows),
              "m0_plus1_exact_zero_pair_count_before_q1_cell_gate": sum(r["baseline_abs_error_plus1_ft"] == 0.0 for r in p3_rows),
              "m0_plus1_exact_zero_pair_count_after_q1_cell_gate": sum(r["baseline_abs_error_plus1_ft"] == 0.0 for r in q3_data),
              "q1_eligible_start_team_cell_count": len(eligible_cells),
              "p3_pair_count_after_q1_cell_gate": len(q3_data),
              "p4_pair_count_after_q1_cell_gate": len(q4_data),
              "by_candidate": {}}
    pair_level_values = []
    for candidate in CANDIDATES:
        kappa = q1_summary["by_horizon"]["45"]["EqualTeam"][candidate]["pooled_through_origin_fit"]["kappa"]
        if kappa is None:
            raise RuntimeError(f"Q3 cannot be computed: Q1 EqualTeam +45 {candidate} kappa undefined")
        overall = binned_metric(q3_data, None, 1, candidate, kappa, games, draws)
        output["by_candidate"][candidate] = {
            "fixed_global_kappa_from_Q1_EqualTeam_plus45": kappa,
            "overall_common_three_horizon_support": overall["bins"][0],
            "overall_per_start_values": overall["per_start_bin_values"],
            "by_fixed_m0_plus1_error_decile": binned_metric(q3_data, "baseline_error_decile", 10,
                                                              candidate, kappa, games, draws),
            "by_fixed_cutoff_distance_quartile": binned_metric(q4_data, "distance_quartile", 4,
                                                                candidate, kappa, games, draws),
        }
        for row in q3_data:
            err = row["errors_by_horizon_ft"]["45"]
            pair_level_values.append({"candidate": candidate, "game": row["game"], "start_id": row["start_id"], "team": row["team"],
                                      "pair": row["pair"], "m0_plus1_abs_error_ft": row["baseline_abs_error_plus1_ft"],
                                      "decile": row["baseline_error_decile"],
                                      "cutoff_distance_ft": row["cutoff_distance_ft"],
                                      "distance_quartile": int(np.searchsorted(p4_edges, row["cutoff_distance_ft"], side="right")),
                                      "m0_plus45_error_ft": err["M0"],
                                      "candidate_plus45_error_ft": err[candidate],
                                      "candidate_minus_m0_signed_delta_ft": err[candidate] - err["M0"],
                                      "residual_ft": err[candidate] - kappa * err["M0"]})
    output["pair_level_values"] = pair_level_values
    output["bin_support_counts"] = {
        "p3_pair_count_by_decile": [sum(r["baseline_error_decile"] == b for r in q3_data) for b in range(10)],
        "p4_pair_count_by_quartile": [sum(r["distance_quartile"] == b for r in q4_data) for b in range(4)],
    }
    return output, {"p3_rows": q3_data, "p4_rows": q4_data}


def build_q4(q1: dict, q1_data: dict, q3: dict, games: list[str]) -> dict:
    output = {"horizon_ordinal_increment": 45, "by_candidate": {}}
    for candidate in CANDIDATES:
        group_values = {}
        for group in GROUPS:
            q1_item = q1["by_horizon"]["45"][group][candidate]
            game_kappa = q1_item["per_game_kappa"]
            rows = q1_data["pair_rows"][(45, group, candidate)]
            loo = {}
            for omitted in games:
                loo[omitted] = metric_slope([r for r in rows if r["game"] != omitted])
            group_values[group] = {
                "per_game_kappa": game_kappa,
                "leave_one_game_out_pair_pooled_kappa": loo,
                "positive_game_kappa_count": sum(v is not None and v > 0 for v in game_kappa.values()),
                "negative_game_kappa_count": sum(v is not None and v < 0 for v in game_kappa.values()),
                "kappa_between_zero_and_one_count": sum(v is not None and 0 < v < 1 for v in game_kappa.values()),
            }
        kappa = q1["by_horizon"]["45"]["EqualTeam"][candidate]["pooled_through_origin_fit"]["kappa"]
        residual_by_game = {}
        team_residual_by_game = {team: {} for team in TEAMS}
        for game in games:
            vals_by_start = defaultdict(lambda: defaultdict(list))
            for sid, start in q1_data["records"].items():
                if start["game"] != game:
                    continue
                for team in TEAMS:
                    if (sid, team) not in q1_data["eligible_cells_by_horizon"][45]:
                        continue
                    for value in start["horizons"][45][team].values():
                        x, y = value["errors_ft"]["M0"], value["errors_ft"][candidate]
                        vals_by_start[sid][team].append(y - kappa * x)
            start_means, team_vals = [], {team: [] for team in TEAMS}
            for sid, team_map in vals_by_start.items():
                for team in TEAMS:
                    if team_map[team]:
                        team_mean = float(np.mean(team_map[team]))
                        team_vals[team].append(team_mean)
                present = [float(np.mean(team_map[t])) for t in TEAMS if team_map[t]]
                if present:
                    start_means.append(float(np.mean(present)))
            mean_resid = float(np.mean(start_means)) if start_means else None
            residual_by_game[game] = {"mean_residual_ft": mean_resid,
                                      "sign": "positive" if mean_resid is not None and mean_resid > 0 else
                                             "negative" if mean_resid is not None and mean_resid < 0 else
                                             "zero_or_unavailable"}
            for team in TEAMS:
                mean_team = float(np.mean(team_vals[team])) if team_vals[team] else None
                team_residual_by_game[team][game] = {"mean_residual_ft": mean_team,
                    "sign": "positive" if mean_team is not None and mean_team > 0 else
                           "negative" if mean_team is not None and mean_team < 0 else "zero_or_unavailable"}
        output["by_candidate"][candidate] = {
            "by_group": group_values,
            "equalteam_per_game_residual_sign": residual_by_game,
            "per_team_per_game_residual_sign": team_residual_by_game,
            "equalteam_residual_sign_counts": {
                sign: sum(v["sign"] == sign for v in residual_by_game.values())
                for sign in ("positive", "negative", "zero_or_unavailable")},
        }
    return output


def run_analysis(jc: dict, archive: dict, starts: dict, gate: dict, output_path: Path) -> None:
    games = list(jc["population"]["games"])
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)
    records, pair_games, p3_rows, p4_rows = make_pair_data(jc, archive, starts, gate)
    diag2 = read_json(DIAG2_RESULTS)
    expected_p3 = int(diag2["P3_one_step_M0_error_deciles"]["pair_count_total"])
    expected_p4 = int(diag2["P4_observed_cutoff_distance_quartiles"]["pair_count_total"])
    if len(p3_rows) != expected_p3 or len(p4_rows) != expected_p4:
        raise RuntimeError(f"fixed-bin support mismatch before Q1-Q4: P3 {len(p3_rows)}/{expected_p3}, "
                           f"P4 {len(p4_rows)}/{expected_p4}")
    q1, q1_data = build_q1(records, pair_games, draws)
    q1_data["records"] = records
    q2 = build_q2(q1_data, records, games, draws)
    p3_edges = [float(x) for x in diag2["P3_one_step_M0_error_deciles"]["decile_edges_ft"]]
    p4_edges = [float(x) for x in diag2["P4_observed_cutoff_distance_quartiles"]["distance_quartile_edges_ft"]]
    q3, _ = build_q3(records, p3_rows, p4_rows, q1_data, q1, games, draws, p3_edges, p4_edges)
    q4 = build_q4(q1, q1_data, q3, games)

    q1_pair_values = []
    for h in HORIZONS:
        for sid, start in records.items():
            for team in TEAMS:
                for pair, value in start["horizons"][h][team].items():
                    q1_pair_values.append({"horizon": h, "game": start["game"], "start_id": sid,
                                           "team": team, "pair": list(pair),
                                           "errors_ft": value["errors_ft"]})
    result = {
        "schema_version": 1,
        "analysis": "NHL JC-DIAG3 pair-geometry shrink diagnosis",
        "base_commit": BASE_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                             "sha256": PREREG_SHA256},
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "source_hashes": gate["actual_source_hashes"],
        "provenance_gate": gate,
        "population": {
            "game_count": len(games), "games": games,
            "evaluation_design": "leave-one-whole-game-out development predictions",
            "rollout_starts": 200, "plus45_group_scored_starts": 172,
            "plus45_within_team_pairs": {"Home": 1064, "Away": 1100, "total": 2164},
            "eligible_one_skater_training_windows": 454983,
            "timebase": "ordinal Image Id increments, not seconds",
            "independent_tracking_population_available": False,
            "adoption_boundary": "descriptive only; no adoption, NHL simulator, or probability claim",
        },
        "method": {
            "pair_error": "predicted within-team pair distance minus observed target pair distance, feet",
            "pair_identity": "sorted track IDs within one frozen game-period-start and team; no cross-game join",
            "minimum_pairs_per_start_team_cell": MIN_PAIRS,
            "equalteam_weight": "each eligible start/team cell has total weight 1; pair weight is inverse cell pair count",
            "ols": "through origin; no intercept",
            "r_squared": "uncentered through-origin R2 = 1 - weighted SSE / weighted sum(y^2)",
            "bootstrap_draws": BOOTSTRAPS, "bootstrap_seed": SEED,
            "bootstrap_unit": "whole game, sampled with replacement; equal game weight; shared draw matrix",
            "bootstrap_ci": "95% linear percentile interval; requires at least 9,500 defined draws",
            "q1_horizons": list(HORIZONS),
            "q2_ratio": "candidate signed pair error divided by M0 signed pair error; negative ratios retained; exact-zero denominator excluded",
            "q2_high_magnitude_cohort": "absolute M0 +45 error greater than or equal to median absolute M0 +45 error",
            "q3_global_residual_slope": "Q1 +45 pair-pooled EqualTeam slope, fixed across all bins",
            "q3_p3_cutpoints_source": "JC-DIAG2 result, verbatim; fixed during bootstrap",
            "q3_p4_cutpoints_source": "JC-DIAG2 result, verbatim; fixed during bootstrap",
            "simulation_or_refit_performed": False,
        },
        "support_audit": {
            "raw_frame_support": gate["raw_frame_support"],
            "q1_cell_eligibility_and_exclusions": q1["cell_eligibility_and_exclusions"],
            "p3_common_three_horizon_pair_count": len(p3_rows),
            "p4_cutoff_plus45_pair_count": len(p4_rows),
        },
        "Q1_through_origin_slopes": q1,
        "Q1_pair_level_support": q1_pair_values,
        "Q2_pair_ratio_distribution_plus45": q2,
        "Q3_fixed_slope_residual_structure_plus45": q3,
        "Q4_game_stability_plus45": q4,
    }
    digest, size = write_json(output_path, result)
    print(f"RESULT path={output_path} sha256={digest} bytes={size}")
    print(f"EVALUATOR sha256={result['evaluator_sha256']}")
    for q in ("Q1", "Q2", "Q3", "Q4"):
        print(f"{q} complete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="verify provenance only; do not calculate Q1-Q4")
    parser.add_argument("--output", type=Path,
                        default=RESULTS / "jc-diag3-pair-shrink-2026-10-23-v1.json")
    args = parser.parse_args()
    try:
        jc, archive, starts, gate = run_provenance_gate(args.output)
    except Exception as exc:
        hashes, checks = source_hash_gate()
        gate = {"expected_source_hashes": EXPECTED_HASHES, "actual_source_hashes": hashes,
                "source_hash_checks": checks, "assertions": [], "all_assertions_passed": False,
                "failure": f"provenance gate raised {type(exc).__name__}: {exc}"}
        write_failure(args.output, gate)
        raise SystemExit("JC-DIAG3 provenance gate raised; Q1-Q4 stopped") from exc
    if not gate.get("all_assertions_passed"):
        raise SystemExit("JC-DIAG3 provenance gate failed; Q1-Q4 stopped")
    if args.gate_only:
        print("GATE-ONLY PASS; Q1-Q4 were not calculated")
        return
    run_analysis(jc, archive, starts, gate, args.output)


if __name__ == "__main__":
    main()
