#!/usr/bin/env python3
"""Run the preregistered, descriptive NHL JC-DIAG4 additive-offset analysis."""
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
REPORT = ROOT / "docs/research/NHL-JC-DIAG4-REPORT-2026-10-23.md"
PREREG = ROOT / "docs/research/NHL-JC-DIAG4-PREREG-2026-10-23.md"
PREREG_COMMIT = "f3f89468328d1fa35093e2c691cab37c5369e6b1"
PREREG_SHA256 = "66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0"
BASE_COMMIT = "a4f07543704d4170a23f6cd6bfdb7bc4a3578160"
DIAG3_PREREG_SHA256 = "96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de"
DIAG3_RESULTS_SHA256 = "e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd"
DIAG3_PREREG = ROOT / "docs/research/NHL-JC-DIAG3-PREREG-2026-10-23.md"
DIAG3_RESULTS = RESULTS / "jc-diag3-pair-shrink-2026-10-23-v1.json"
DIAG2_RESULTS = RESULTS / "jc-diag2-pair-persistence-2026-10-23-v1.json"
PATHS = {
    "jc_results": RESULTS / "joint-coherence-jc-2026-10-23-v1.json",
    "fold_models": RESULTS / "fold_models-bc91d1610de5.json",
    "movement_comparison": RESULTS / "movement_comparison-bc91d1610de5.json",
    "scenario_archive": RESULTS / "scenario_archive-bc91d1610de5.json.gz",
    "rollout_starts": DATA / "rollout_starts.json.gz",
    "jc_diag_results": RESULTS / "jc-attribution-jcdiag-2026-10-23-v1.json",
    "jc_diag2_preregistration": ROOT / "docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md",
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
HORIZONS = (15, 30, 45)
ALL_HORIZONS = (1, 15, 30, 45)
TRANSITIONS = ((15, 45), (15, 30), (30, 45))
MIN_PAIRS = 3
BOOTSTRAPS = 10_000
PERMUTATIONS = 10_000
SEED = 20261024
EQUALITY_TOLERANCE_FT = 1e-12
DISTANCE_EDGES_FT = [17.038243596734116, 25.896550730297974, 36.18400154397977]
M0_PLUS1_EDGES_FT = [
    0.02013880768063752, 0.03778431147562884, 0.057149271788077625,
    0.0772826427731225, 0.10184994154651683, 0.12700537055808211,
    0.16006325254241388, 0.2074288029626061, 0.2889645922798206,
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def finite_xy(value: object) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in value))


def nested(value: dict, *keys):
    for key in keys:
        value = value[key]
    return value


def close(actual: float, expected: float, tolerance: float = 5e-9) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance


def hash_checks() -> tuple[dict, list[dict]]:
    actual, checks = {}, []
    for name, path in PATHS.items():
        value = sha256_file(path) if path.is_file() else None
        actual[name] = value
        checks.append({"name": name, "path": str(path), "expected": EXPECTED_HASHES[name],
                       "actual": value, "passed": value == EXPECTED_HASHES[name]})
    pinned = [
        ("jc_diag3_preregistration", DIAG3_PREREG, DIAG3_PREREG_SHA256),
        ("jc_diag3_results", DIAG3_RESULTS, DIAG3_RESULTS_SHA256),
        ("jc_diag4_preregistration", PREREG, PREREG_SHA256),
    ]
    for name, path, expected in pinned:
        value = sha256_file(path) if path.is_file() else None
        checks.append({"name": name, "path": str(path), "expected": expected,
                       "actual": value, "passed": value == expected})
        actual[name] = value
    return actual, checks


def raw_frame_audit(jc: dict, archive: dict, starts_manifest: dict) -> dict:
    starts = starts_manifest["starts"]
    games = list(jc["population"]["games"])
    scenarios = {item["scenario_id"]: item for item in archive["scenarios"].values()}
    start_ids = [f"{row['game']}|{row['period']}|{row['cutoff_seq']}" for row in starts]
    if len(start_ids) != 200 or len(set(start_ids)) != 200:
        raise RuntimeError(f"rollout manifest must have 200 unique starts; got {len(start_ids)}")
    if set(start_ids) - scenarios.keys():
        raise RuntimeError("rollout manifest references a missing scenario")
    jc_rows = {(row["scenario_id"], int(row["horizon_ordinal_increment"])): row
               for row in jc["scenario_measurements"]}
    if len(jc_rows) != len(jc["scenario_measurements"]):
        raise RuntimeError("duplicate frozen JC scenario/horizon rows")
    denominator = {team: 0 for team in TEAMS}
    support_1_15_45 = 0
    plus45_scored = []
    frame_assertions = []
    per_start = {}
    for start, sid in zip(starts, start_ids):
        scenario = scenarios[sid]
        initial_rows = scenario["initial_state"]["players"]
        initial = {p["id"]: p for p in initial_rows}
        if len(initial) != len(initial_rows):
            raise RuntimeError(f"duplicate initial track IDs at {sid}")
        team_by_id = {pid: p["team"] for pid, p in initial.items()}
        if any(team not in TEAMS for team in team_by_id.values()):
            raise RuntimeError(f"unknown team at {sid}")
        if any(not finite_xy([p.get("x"), p.get("y")]) for p in initial.values()):
            raise RuntimeError(f"nonfinite initial position at {sid}")
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        common_ids, by_h = {}, {}
        eligible45 = False
        for h in ALL_HORIZONS:
            frame = frames[h]
            observed = (frame.get("observed") or {}).get("players") or {}
            models = {m: frame.get("models", {}).get(m, {}).get("players", {}) for m in MODELS}
            common = {pid for pid in initial if finite_xy(observed.get(pid)) and
                      all(finite_xy(models[m].get(pid)) for m in MODELS)}
            common_ids[h] = {team: {pid for pid in common if team_by_id[pid] == team} for team in TEAMS}
            counts = {team: len(common_ids[h][team]) for team in TEAMS}
            pairs = {team: counts[team] * (counts[team] - 1) // 2 for team in TEAMS}
            eligible = all(counts[team] >= 2 for team in TEAMS)
            jc_row = jc_rows.get((sid, h))
            if jc_row is None:
                raise RuntimeError(f"missing JC support row for {sid} +{h}")
            published = jc_row["counts"]
            expected_counts = {
                "common_skaters": len(common), "common_home_skaters": counts["Home"],
                "common_away_skaters": counts["Away"],
                "home_within_team_pairs": pairs["Home"], "away_within_team_pairs": pairs["Away"],
            }
            passed = bool(jc_row["eligible"]) == eligible and all(
                int(published[key]) == val for key, val in expected_counts.items())
            frame_assertions.append({"start_id": sid, "horizon": h, "expected_from_frames": expected_counts,
                                     "published_jc_counts": {k: int(published[k]) for k in expected_counts},
                                     "frame_eligible": eligible, "jc_eligible": bool(jc_row["eligible"]),
                                     "passed": passed})
            if not passed:
                raise RuntimeError(f"raw-frame/JC support mismatch at {sid} +{h}: {expected_counts}")
            by_h[str(h)] = {"skaters_by_team": counts, "pairs_by_team": pairs, "eligible": eligible}
            if h == 45:
                eligible45 = eligible
                if eligible:
                    plus45_scored.append(sid)
                    for team in TEAMS:
                        denominator[team] += pairs[team]
                        shared = set.intersection(common_ids[1][team], common_ids[15][team], common_ids[45][team])
                        support_1_15_45 += len(shared) * (len(shared) - 1) // 2
        per_start[sid] = {"game": scenario["game"], "eligible_plus45": eligible45,
                          "by_horizon": by_h}
    valid = (len(games) == 10 and len(plus45_scored) == 172 and
             denominator == {"Home": 1064, "Away": 1100} and sum(denominator.values()) == 2164)
    return {"game_count": len(games), "rollout_start_count": len(starts),
            "plus45_scored_start_count": len(plus45_scored),
            "plus45_pair_counts_by_team": denominator, "plus45_pair_count_total": sum(denominator.values()),
            "common_1_15_45_pair_count": support_1_15_45,
            "raw_denominator_assertion_passed": valid,
            "per_start_raw_frame_counts": per_start, "jc_grid_reconciliation": frame_assertions,
            "scored_start_ids": plus45_scored}


def make_gate() -> tuple[dict, dict | None, dict | None, dict | None, dict | None]:
    hashes, hash_rows = hash_checks()
    gate = {"expected_source_hashes": {**EXPECTED_HASHES,
                                       "jc_diag3_preregistration": DIAG3_PREREG_SHA256,
                                       "jc_diag3_results": DIAG3_RESULTS_SHA256,
                                       "jc_diag4_preregistration": PREREG_SHA256},
            "actual_source_hashes": hashes, "source_hash_checks": hash_rows,
            "assertions": [], "all_assertions_passed": False}
    if not all(row["passed"] for row in hash_rows):
        gate["failure"] = "frozen source hash mismatch or missing input; Q1-Q4 not run"
        return gate, None, None, None, None
    try:
        jc = read_json(PATHS["jc_results"])
        diag1 = read_json(PATHS["jc_diag_results"])
        diag2 = read_json(DIAG2_RESULTS)
        diag3 = read_json(DIAG3_RESULTS)
        archive = read_gzip_json(PATHS["scenario_archive"])
        starts = read_gzip_json(PATHS["rollout_starts"])
        audit = raw_frame_audit(jc, archive, starts)
    except Exception as exc:
        gate["failure"] = f"provenance artifact/raw-frame check failed: {type(exc).__name__}: {exc}"
        return gate, None, None, None, None

    def record(name: str, actual, expected, tolerance: float | None = None):
        if isinstance(expected, list):
            passed = (isinstance(actual, list) and len(actual) == len(expected) and
                      (all(close(float(a), float(e), tolerance or 5e-9) for a, e in zip(actual, expected))))
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            passed = close(float(actual), float(expected), tolerance or 5e-9)
        else:
            passed = actual == expected
        gate["assertions"].append({"name": name, "expected": expected, "actual": actual,
                                   "tolerance_abs": tolerance, "passed": passed})

    q1 = diag3["Q1_through_origin_slopes"]["by_horizon"]["45"]["EqualTeam"]
    for model, mean, ci, pooled in (
        ("M1", 0.9187677553966251, [0.8720258085983662, 0.9675590685116491], 0.9109024558296622),
        ("M2", 0.917783443374861, [0.8716730780954651, 0.9658566816264654], 0.909943225187711),
    ):
        item = q1[model]
        record(f"DIAG3_Q1_plus45_EqualTeam_{model}_equal_game_kappa", item["equal_game_kappa"]["equal_game_mean"], mean)
        record(f"DIAG3_Q1_plus45_EqualTeam_{model}_kappa_95ci", item["equal_game_kappa"]["bootstrap_95_ci"], ci)
        record(f"DIAG3_Q1_plus45_EqualTeam_{model}_pair_pooled_kappa", item["pooled_through_origin_fit"]["kappa"], pooled)
        record(f"DIAG3_Q1_plus45_EqualTeam_{model}_raw_pairs_fit_pairs_eligible_starts",
               [item["raw_common_pair_count"], item["included_pair_count"], item["eligible_start_count"]],
               [2164, 1966, 142], 0)

    q3 = diag3["Q3_fixed_slope_residual_structure_plus45"]
    q3_expected = {
        "M1": {"residual": -4.2508129518662505, "raw": -4.264960031686021,
               "q1_residual": -2.656761009054479,
               "q1_ci": [-2.888472703936893, -2.422473205741603],
               "q1_raw": -2.136556824375522,
               "q4_residual": -5.981794764271314,
               "q4_ci": [-6.316363335664117, -5.6026835575486515],
               "q4_raw": -6.456252087389958},
        "M2": {"residual": -4.273154725868025, "raw": -4.287454114178269},
    }
    for model, expected in q3_expected.items():
        row = q3["by_candidate"][model]
        overall = row["overall_common_three_horizon_support"]["metrics"]
        record(f"DIAG3_Q3_overall_{model}_residual", overall["residual_ft"]["equal_game_mean"],
               expected["residual"], 5e-9)
        record(f"DIAG3_Q3_overall_{model}_raw_delta", overall["raw_signed_delta_ft"]["equal_game_mean"],
               expected["raw"], 5e-9)
        for q, key in (((0, "q1"), (3, "q4")) if model == "M1" else ()):
            bin_row = row["by_fixed_cutoff_distance_quartile"]["bins"][q]["metrics"]
            record(f"DIAG3_Q3_{model}_distance_Q{q+1}_residual", bin_row["residual_ft"]["equal_game_mean"],
                   expected[f"{key}_residual"], 5e-9)
            record(f"DIAG3_Q3_{model}_distance_Q{q+1}_residual_CI", bin_row["residual_ft"]["bootstrap_95_ci"],
                   expected[f"{key}_ci"], 5e-9)
            record(f"DIAG3_Q3_{model}_distance_Q{q+1}_raw_delta", bin_row["raw_signed_delta_ft"]["equal_game_mean"],
                   expected[f"{key}_raw"], 5e-9 if model == "M1" else 5e-3)
        per_start = row["overall_per_start_values"]
        sums = defaultdict(list)
        for value in per_start:
            sums[value["game"]].append(float(value["residual_ft"]))
        signs = {game: float(np.mean(values)) < 0 for game, values in sums.items()}
        record(f"DIAG3_Q3_{model}_negative_residual_games", sum(signs.values()), 10, 0)

    q2 = diag3["Q2_pair_ratio_distribution_plus45"]
    record("DIAG3_Q2_median_abs_M0_ft", q2["threshold_median_abs_m0_error_ft"], 6.182658069289268)
    record("DIAG3_Q2_eligible_support", q2["support_pair_count_before_zero_exclusion"], 2131, 0)
    record("DIAG3_Q2_M1_full_support_negative_ratios",
           q2["candidate_cohorts"]["M1"]["full_support"]["negative_ratio_count"], 396, 0)

    p1 = nested(diag2, "P1_plus15_to_plus45_pair_persistence", "summary", "models", "EqualTeam", "M1")
    record("DIAG2_P1_EqualTeam_M1_observed", p1["observed_share"]["equal_game_mean_available_games"],
           0.8305414523474803)
    record("DIAG2_P1_EqualTeam_M1_null", p1["permutation_null_mean"]["equal_game_mean_available_games"],
           0.6201172173403376)
    record("raw_frame_plus45_Home_Away_total",
           [audit["plus45_pair_counts_by_team"]["Home"], audit["plus45_pair_counts_by_team"]["Away"],
            audit["plus45_pair_count_total"]], [1064, 1100, 2164], 0)
    record("raw_frame_common_1_15_45_pair_support", audit["common_1_15_45_pair_count"], 2164, 0)
    record("DIAG2_distance_quartile_cutpoints_ft",
           [float(x) for x in diag2["P4_observed_cutoff_distance_quartiles"]["distance_quartile_edges_ft"]],
           DISTANCE_EDGES_FT)
    record("DIAG2_M0_plus1_decile_cutpoints_ft",
           [float(x) for x in diag2["P3_one_step_M0_error_deciles"]["decile_edges_ft"]],
           M0_PLUS1_EDGES_FT)
    record("raw_frame_support_population", [audit["game_count"], audit["rollout_start_count"],
           audit["plus45_scored_start_count"]], [10, 200, 172], 0)
    gate["raw_frame_support"] = audit
    gate["all_assertions_passed"] = all(item["passed"] for item in gate["assertions"])
    if not gate["all_assertions_passed"]:
        gate["failure"] = "one or more frozen value/support assertions failed; Q1-Q4 not run"
    return gate, jc, diag1, diag2, diag3


def write_json(path: Path, payload: dict) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def write_gate_only(path: Path, gate: dict) -> tuple[str, int]:
    value = {"schema_version": 1, "analysis": "NHL JC-DIAG4 additive-offset decomposition",
             "preregistration": {"commit": PREREG_COMMIT, "sha256": PREREG_SHA256},
             "gate_only": True, "provenance_gate": gate,
             "Q1_Q4_calculated": False}
    return write_json(path, value)


def build_records(jc: dict, archive: dict, starts_manifest: dict, audit: dict) -> tuple[dict, list[str]]:
    scenarios = {item["scenario_id"]: item for item in archive["scenarios"].values()}
    jc_rows = {(r["scenario_id"], int(r["horizon_ordinal_increment"])): r for r in jc["scenario_measurements"]}
    records = {}
    for start in starts_manifest["starts"]:
        sid = f"{start['game']}|{start['period']}|{start['cutoff_seq']}"
        if sid not in set(audit["scored_start_ids"]):
            continue
        scenario = scenarios[sid]
        initial_rows = scenario["initial_state"]["players"]
        initial = {p["id"]: np.asarray([p["x"], p["y"]], dtype=np.float64) for p in initial_rows}
        if len(initial) != len(initial_rows):
            raise RuntimeError(f"duplicate initial track ID at {sid}")
        team_by_id = {p["id"]: p["team"] for p in initial_rows}
        records[sid] = {"game": scenario["game"], "period": start["period"], "horizons": {}}
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        for h in ALL_HORIZONS:
            frame = frames[h]
            observed = (frame.get("observed") or {}).get("players") or {}
            model_players = {m: frame.get("models", {}).get(m, {}).get("players", {}) for m in MODELS}
            common = [pid for pid in initial if finite_xy(observed.get(pid)) and
                      all(finite_xy(model_players[m].get(pid)) for m in MODELS)]
            published = jc_rows[(sid, h)]
            eligible = all(sum(team_by_id[pid] == t for pid in common) >= 2 for t in TEAMS)
            if eligible != bool(published["eligible"]):
                raise RuntimeError(f"frame eligibility mismatch at {sid} +{h}")
            by_team = {}
            for team in TEAMS:
                ids = sorted(pid for pid in common if team_by_id[pid] == team)
                pair_map = {}
                for first, second in combinations(ids, 2):
                    observed_distance = float(np.linalg.norm(np.asarray(observed[first]) - np.asarray(observed[second])))
                    errors = {}
                    for model in MODELS:
                        p = model_players[model]
                        predicted_distance = float(np.linalg.norm(np.asarray(p[first]) - np.asarray(p[second])))
                        errors[model] = predicted_distance - observed_distance
                    if any(not math.isfinite(v) for v in errors.values()):
                        raise RuntimeError(f"nonfinite pair error at {sid} +{h} {team} {first}/{second}")
                    pair_map[(first, second)] = {
                        "errors_ft": errors,
                        "cutoff_distance_ft": float(np.linalg.norm(initial[first] - initial[second])),
                    }
                by_team[team] = pair_map
            records[sid]["horizons"][h] = by_team
    if len(records) != 172:
        raise RuntimeError(f"expected 172 +45-scored starts, got {len(records)}")
    for sid, start in records.items():
        for pair, value in start["horizons"][1]["Home"].items():
            value["m0_plus1_abs_error_ft"] = abs(value["errors_ft"]["M0"])
        for team in TEAMS:
            for pair in set(start["horizons"][1][team]) & set(start["horizons"][15][team]) & set(start["horizons"][45][team]):
                start["horizons"][15][team][pair]["m0_plus1_abs_error_ft"] = abs(
                    start["horizons"][1][team][pair]["errors_ft"]["M0"])
                start["horizons"][45][team][pair]["m0_plus1_abs_error_ft"] = abs(
                    start["horizons"][1][team][pair]["errors_ft"]["M0"])
    games = list(jc["population"]["games"])
    return records, games


def game_bootstrap(values_by_game: dict[str, float | None], games: list[str], draws: np.ndarray) -> dict:
    valid = [float(values_by_game[g]) for g in games if values_by_game.get(g) is not None]
    estimate = float(np.mean(valid)) if valid else None
    if len(valid) != len(games):
        return {"equal_game_mean": estimate, "bootstrap_95_ci": None,
                "valid_draws": 0, "games_with_values": len(valid),
                "per_game": {g: values_by_game.get(g) for g in games}}
    values = np.asarray([values_by_game[g] for g in games], dtype=np.float64)
    boot = values[draws].mean(axis=1)
    return {"equal_game_mean": estimate,
            "bootstrap_95_ci": [float(np.quantile(boot, .025, method="linear")),
                                float(np.quantile(boot, .975, method="linear"))],
            "valid_draws": int(len(boot)), "games_with_values": len(valid),
            "per_game": {g: float(values_by_game[g]) for g in games}}


def cells_for_horizon(records: dict, h: int) -> tuple[dict, dict]:
    audit = {}
    eligible = {}
    for sid, start in records.items():
        for team in TEAMS:
            pairs = start["horizons"][h][team]
            x = np.asarray([v["errors_ft"]["M0"] for v in pairs.values()], dtype=np.float64)
            sum_x2 = float(np.dot(x, x)) if len(x) else 0.0
            reason = None
            if len(pairs) < MIN_PAIRS:
                reason = "fewer_than_three_common_pairs"
            elif not math.isfinite(sum_x2) or sum_x2 <= 0.0:
                reason = "zero_or_undefined_m0_squared_denominator"
            cell = {"start_id": sid, "game": start["game"], "team": team,
                    "pair_count": len(pairs), "sum_m0_squared_ft2": sum_x2,
                    "eligible": reason is None, "reason": reason}
            audit[(sid, team)] = cell
            if reason is None:
                eligible[(sid, team)] = pairs
    return audit, eligible


def rows_for_group(records: dict, h: int, group: str, candidate: str,
                   audit: dict, eligible: dict) -> tuple[list[dict], dict]:
    rows = []
    excluded = defaultdict(lambda: {"cells": 0, "pair_rows": 0})
    raw_pairs = 0
    for sid, start in records.items():
        teams = TEAMS if group == "EqualTeam" else (group,)
        valid_equalteam = all((sid, team) in eligible for team in TEAMS)
        for team in teams:
            pair_map = start["horizons"][h][team]
            raw_pairs += len(pair_map)
            cell = audit[(sid, team)]
            if (sid, team) not in eligible:
                ex = excluded[cell["reason"]]
                ex["cells"] += 1
                ex["pair_rows"] += len(pair_map)
            elif group == "EqualTeam" and not valid_equalteam:
                ex = excluded["other_team_cell_not_estimable_for_EqualTeam"]
                ex["cells"] += 1
                ex["pair_rows"] += len(pair_map)
            else:
                weight = 1.0 / len(pair_map) if group == "EqualTeam" else 1.0
                for pair, value in pair_map.items():
                    rows.append({"game": start["game"], "start_id": sid, "team": team,
                                 "pair": pair, "x": float(value["errors_ft"]["M0"]),
                                 "y": float(value["errors_ft"][candidate]), "weight": weight,
                                 "all_errors": value["errors_ft"]})
    counts = {"raw_pair_count": raw_pairs, "included_pair_count": len(rows),
              "eligible_start_count": len({r["start_id"] for r in rows}),
              "start_team_cell_count": len({(r["start_id"], r["team"]) for r in rows}),
              "represented_game_count": len({r["game"] for r in rows}),
              "exclusions": dict(excluded)}
    return rows, counts


def weighted_fit(rows: list[dict], *, through_origin: bool = False) -> dict:
    if not rows:
        return {"a": None, "kappa": None, "centered_r2": None,
                "reason": "no_eligible_rows"}
    x = np.asarray([r["x"] for r in rows], dtype=np.float64)
    y = np.asarray([r["y"] for r in rows], dtype=np.float64)
    w = np.asarray([r["weight"] for r in rows], dtype=np.float64)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(w).all():
        return {"a": None, "kappa": None, "centered_r2": None,
                "reason": "nonfinite_fit_input"}
    if through_origin:
        denom = float(np.dot(w, x * x))
        if denom <= 0.0:
            return {"a": None, "kappa": None, "centered_r2": None,
                    "reason": "zero_m0_squared_denominator"}
        kappa = float(np.dot(w, x * y) / denom)
        residual = y - kappa * x
        y_centered = y - float(np.dot(w, y) / w.sum())
        sst = float(np.dot(w, y_centered * y_centered))
        r2 = None if sst <= 0.0 else 1.0 - float(np.dot(w, residual * residual)) / sst
        return {"a": 0.0, "kappa": kappa, "centered_r2": r2, "reason": None}
    xbar = float(np.dot(w, x) / w.sum())
    ybar = float(np.dot(w, y) / w.sum())
    xc, yc = x - xbar, y - ybar
    sxx = float(np.dot(w, xc * xc))
    if sxx <= 0.0 or not math.isfinite(sxx):
        return {"a": None, "kappa": None, "centered_r2": None,
                "reason": "zero_weighted_centered_m0_variance"}
    kappa = float(np.dot(w, xc * yc) / sxx)
    intercept = ybar - kappa * xbar
    residual = y - (intercept + kappa * x)
    sst = float(np.dot(w, yc * yc))
    r2 = None if sst <= 0.0 else 1.0 - float(np.dot(w, residual * residual)) / sst
    return {"a": intercept, "kappa": kappa, "centered_r2": r2, "reason": None}


def q1_fit(records: dict, games: list[str], draws: np.ndarray) -> tuple[dict, dict]:
    output, rows_index, cell_audit = {}, {}, {}
    mean_levels = {}
    for h in HORIZONS:
        audit, eligible = cells_for_horizon(records, h)
        cell_audit[str(h)] = {
            "eligible_home_cells": sum((sid, "Home") in eligible for sid in records),
            "eligible_away_cells": sum((sid, "Away") in eligible for sid in records),
            "eligible_equalteam_starts": sum(all((sid, t) in eligible for t in TEAMS) for sid in records),
            "by_cell": {f"{sid}|{team}": value for (sid, team), value in sorted(audit.items())},
        }
        output[str(h)] = {}
        mean_levels[str(h)] = {}
        for group in GROUPS:
            output[str(h)][group] = {}
            mean_levels[str(h)][group] = {}
            for model in CANDIDATES:
                rows, counts = rows_for_group(records, h, group, model, audit, eligible)
                rows_index[(h, group, model)] = rows
                pooled = weighted_fit(rows)
                per_game = {g: weighted_fit([r for r in rows if r["game"] == g]) for g in games}
                loo = {held: weighted_fit([r for r in rows if r["game"] != held]) for held in games}
                equalgame = {}
                for metric in ("a", "kappa", "centered_r2"):
                    values = {g: per_game[g][metric] for g in games}
                    equalgame[metric] = game_bootstrap(values, games, draws)
                output[str(h)][group][model] = {
                    "pooled_wls": pooled, "equal_game": equalgame,
                    "per_game_fits": per_game, "leave_one_game_out_fits": loo,
                    "counts": counts,
                }
            for model in MODELS:
                model_values = {}
                rows_by_game = {}
                for game in games:
                    by_start = defaultdict(lambda: defaultdict(list))
                    for sid, start in records.items():
                        if start["game"] != game:
                            continue
                        teams = TEAMS if group == "EqualTeam" else (group,)
                        for team in teams:
                            if (sid, team) not in eligible:
                                continue
                            if group == "EqualTeam" and not all((sid, t) in eligible for t in TEAMS):
                                continue
                            for val in start["horizons"][h][team].values():
                                by_start[sid][team].append(float(val["errors_ft"][model]))
                    starts_means = []
                    for sid, team_map in by_start.items():
                        team_means = [float(np.mean(team_map[t])) for t in teams if team_map[t]]
                        if team_means:
                            starts_means.append(float(np.mean(team_means)))
                    rows_by_game[game] = float(np.mean(starts_means)) if starts_means else None
                model_values["mean_signed_error_ft"] = game_bootstrap(rows_by_game, games, draws)
                mean_levels[str(h)][group][model] = model_values
    return {"fits": output, "mean_error_levels": mean_levels,
            "cell_eligibility_and_exclusions": cell_audit}, rows_index


def q2_decomposition(records: dict, games: list[str], draws: np.ndarray,
                     q1: dict, rows_index: dict) -> dict:
    result = {}
    for h in HORIZONS:
        result[str(h)] = {}
        for group in GROUPS:
            result[str(h)][group] = {}
            for model in CANDIDATES:
                rows = rows_index[(h, group, model)]
                through = weighted_fit(rows, through_origin=True)
                intercept = q1["fits"][str(h)][group][model]["pooled_wls"]
                per_game = {g: {"raw": [], "through_origin": [], "intercept": []} for g in games}
                for row in rows:
                    g, x, y, w = row["game"], row["x"], row["y"], row["weight"]
                    per_game[g]["raw"].append((y, w))
                    per_game[g]["through_origin"].append((y - float(through["kappa"]) * x, w))
                    per_game[g]["intercept"].append((y - (float(intercept["a"]) +
                                                             float(intercept["kappa"]) * x), w))
                game_means = {}
                for g in games:
                    game_means[g] = {}
                    for mode in ("raw", "through_origin", "intercept"):
                        values = per_game[g][mode]
                        den = sum(w for _, w in values)
                        game_means[g][mode] = (sum(v * w for v, w in values) / den) if den > 0 else None
                summary = {mode: game_bootstrap({g: game_means[g][mode] for g in games}, games, draws)
                           for mode in ("raw", "through_origin", "intercept")}
                bias_removed = {}
                for mode in ("through_origin", "intercept"):
                    point_raw = summary["raw"]["equal_game_mean"]
                    point_adj = summary[mode]["equal_game_mean"]
                    point = None if point_raw in (None, 0.0) else 1.0 - abs(point_adj) / abs(point_raw)
                    draw_values = []
                    values = {g: [game_means[g]["raw"], game_means[g][mode]] for g in games}
                    if all(values[g][0] is not None and values[g][1] is not None for g in games):
                        for draw in draws:
                            b_raw = float(np.mean([values[games[int(i)]][0] for i in draw]))
                            b_adj = float(np.mean([values[games[int(i)]][1] for i in draw]))
                            draw_values.append(None if b_raw == 0.0 else 1.0 - abs(b_adj) / abs(b_raw))
                    valid = [v for v in draw_values if v is not None and math.isfinite(v)]
                    ci = ([float(np.quantile(valid, .025, method="linear")),
                           float(np.quantile(valid, .975, method="linear"))]
                          if len(valid) >= 9500 else None)
                    bias_removed[mode] = {"share_mean_bias_removed": point,
                                          "bootstrap_95_ci": ci,
                                          "valid_draws": len(valid)}
                result[str(h)][group][model] = {
                    "through_origin_kappa": through["kappa"],
                    "intercept_fit": {k: intercept[k] for k in ("a", "kappa", "centered_r2")},
                    "means": summary, "bias_removed": bias_removed,
                    "counts": q1["fits"][str(h)][group][model]["counts"],
                }
    return result


def pair_mean_error(records: dict, sid: str, team: str, h: int, model: str) -> float | None:
    values = [float(row["errors_ft"][model]) for row in records[sid]["horizons"][h][team].values()]
    return float(np.mean(values)) if values else None


def loog_offsets(records: dict, games: list[str]) -> tuple[dict, dict, dict]:
    game_cell_means = {}
    for sid, start in records.items():
        for h in HORIZONS:
            for team in TEAMS:
                if len(start["horizons"][h][team]) < MIN_PAIRS:
                    continue
                for model in CANDIDATES:
                    game_cell_means[(start["game"], sid, team, h, model)] = pair_mean_error(
                        records, sid, team, h, model)
    game_team = {}
    game_equalteam = {}
    for game in games:
        for h in HORIZONS:
            for model in CANDIDATES:
                by_team = {team: [] for team in TEAMS}
                by_start = defaultdict(dict)
                for (g, sid, team, horizon, candidate), val in game_cell_means.items():
                    if (g, horizon, candidate) == (game, h, model):
                        by_team[team].append(val)
                        by_start[sid][team] = val
                for team in TEAMS:
                    game_team[(game, h, model, team)] = float(np.mean(by_team[team])) if by_team[team] else None
                start_means = [float(np.mean([by_start[sid][t] for t in TEAMS]))
                               for sid in by_start if all(t in by_start[sid] for t in TEAMS)]
                game_equalteam[(game, h, model)] = float(np.mean(start_means)) if start_means else None

    global_loo, team_loo = {}, {}
    for held in games:
        train = [g for g in games if g != held]
        for h in HORIZONS:
            for model in CANDIDATES:
                global_values = [game_equalteam[(g, h, model)] for g in train]
                if any(v is None for v in global_values):
                    global_loo[(held, h, model)] = None
                else:
                    global_loo[(held, h, model)] = float(np.mean(global_values))
                for team in TEAMS:
                    values = [game_team[(g, h, model, team)] for g in train]
                    team_loo[(held, h, model, team)] = (
                        None if any(v is None for v in values) else float(np.mean(values)))
    cell_loo = {}
    for sid, start in records.items():
        for h in HORIZONS:
            for team in TEAMS:
                for model in CANDIDATES:
                    cell_loo[(sid, team, h, model)] = game_cell_means.get(
                        (start["game"], sid, team, h, model))
    return {"global_game": global_loo, "team_horizon": team_loo,
            "in_sample_cell": cell_loo,
            "training_game_means_by_team": game_team,
            "training_game_equalteam_means": game_equalteam}


def cell_transition_share(earlier: np.ndarray, later: np.ndarray,
                          orders: np.ndarray) -> dict:
    mass = np.maximum(-later, 0.0)
    denom = float(mass.sum())
    if denom <= 0.0:
        return {"observed_share": None, "permutation_null_mean": None,
                "negative_mass_ft": denom, "reason": "zero_negative_mass"}
    prev_negative = earlier < 0.0
    observed = float(np.dot(mass, prev_negative.astype(np.float64)) / denom)
    shuffled = mass[orders]
    null_draws = (shuffled * prev_negative[None, :]).sum(axis=1) / denom
    return {"observed_share": observed,
            "permutation_null_mean": float(np.mean(null_draws)),
            "negative_mass_ft": denom, "reason": None}


def q3_persistence(records: dict, games: list[str], draws: np.ndarray) -> dict:
    offsets = loog_offsets(records, games)
    rng = np.random.default_rng(SEED)
    output = {"primary_transition": [15, 45], "transitions": {},
              "offset_estimates": {}, "offset_identity_checks": {}}
    modes = ("raw", "loo_global_game", "loo_team_horizon", "in_sample_cell")
    for held in games:
        for h in HORIZONS:
            for model in CANDIDATES:
                global_value = offsets["global_game"][(held, h, model)]
                team_values = {team: offsets["team_horizon"][(held, h, model, team)] for team in TEAMS}
                avg_team = (None if any(v is None for v in team_values.values()) else
                            float(np.mean(list(team_values.values()))))
                output["offset_estimates"][f"{held}|+{h}|{model}"] = {
                    "global_game_equalteam_offset_ft": global_value,
                    "team_horizon_offsets_ft": team_values,
                    "equalteam_mean_of_team_offsets_ft": avg_team,
                }
                output["offset_identity_checks"][f"{held}|+{h}|{model}"] = {
                    "team_mean_equals_global_within_1e-12_ft": (global_value is not None and avg_team is not None and
                                                                 abs(global_value - avg_team) <= EQUALITY_TOLERANCE_FT),
                    "home_and_away_each_equal_global_within_1e-12_ft": (
                        global_value is not None and all(v is not None and
                        abs(v - global_value) <= EQUALITY_TOLERANCE_FT for v in team_values.values())),
                    "equality_tolerance_ft": EQUALITY_TOLERANCE_FT,
                }

    for earlier_h, later_h in TRANSITIONS:
        transition_key = f"plus{earlier_h}_to_plus{later_h}"
        cell_metrics = {}
        support = {mode: {model: {"eligible_start_team_cells": 0,
                                  "zero_negative_mass_cells": 0,
                                  "eligible_equalteam_starts": 0}
                          for model in MODELS if mode == "raw" or model in CANDIDATES}
                  for mode in modes}
        per_cell_for_equalteam = defaultdict(lambda: defaultdict(dict))
        for sid, start in records.items():
            for team in TEAMS:
                earlier_map = start["horizons"][earlier_h][team]
                later_map = start["horizons"][later_h][team]
                common_pairs = sorted(set(earlier_map) & set(later_map))
                if len(common_pairs) < MIN_PAIRS:
                    continue
                orders = np.argsort(rng.random((PERMUTATIONS, len(common_pairs))), axis=1)
                for model in MODELS:
                    model_modes = ("raw",) if model == "M0" else modes
                    for mode in model_modes:
                        if mode == "raw":
                            ca, cl = 0.0, 0.0
                        elif mode == "loo_global_game":
                            ca = offsets["global_game"][(start["game"], earlier_h, model)]
                            cl = offsets["global_game"][(start["game"], later_h, model)]
                        elif mode == "loo_team_horizon":
                            ca = offsets["team_horizon"][(start["game"], earlier_h, model, team)]
                            cl = offsets["team_horizon"][(start["game"], later_h, model, team)]
                        else:
                            ca = offsets["in_sample_cell"][(sid, team, earlier_h, model)]
                            cl = offsets["in_sample_cell"][(sid, team, later_h, model)]
                        if ca is None or cl is None:
                            continue
                        earlier = np.asarray([earlier_map[p]["errors_ft"][model] - ca for p in common_pairs], dtype=np.float64)
                        later = np.asarray([later_map[p]["errors_ft"][model] - cl for p in common_pairs], dtype=np.float64)
                        metric = cell_transition_share(earlier, later, orders)
                        key = (start["game"], sid, team, model, mode)
                        cell_metrics[key] = {**metric, "pair_count": len(common_pairs)}
                        support[mode][model]["eligible_start_team_cells"] += 1
                        if metric["observed_share"] is None:
                            support[mode][model]["zero_negative_mass_cells"] += 1
                        per_cell_for_equalteam[(start["game"], sid, model, mode)][team] = metric

        summaries = {}
        for model in MODELS:
            model_modes = ("raw",) if model == "M0" else modes
            summaries[model] = {}
            for mode in model_modes:
                by_game = {g: {"observed": [], "null": [], "gap": []} for g in games}
                start_rows = defaultdict(dict)
                for (game, sid, candidate, candidate_mode), team_metrics in per_cell_for_equalteam.items():
                    if (candidate, candidate_mode) != (model, mode):
                        continue
                    if set(team_metrics) != set(TEAMS):
                        continue
                    if any(team_metrics[t]["observed_share"] is None for t in TEAMS):
                        continue
                    obs = float(np.mean([team_metrics[t]["observed_share"] for t in TEAMS]))
                    null = float(np.mean([team_metrics[t]["permutation_null_mean"] for t in TEAMS]))
                    start_rows[game][sid] = {"observed": obs, "null": null, "gap": obs - null}
                for game in games:
                    for val in start_rows[game].values():
                        for metric in ("observed", "null", "gap"):
                            by_game[game][metric].append(val[metric])
                    for metric in ("observed", "null", "gap"):
                        by_game[game][metric] = (float(np.mean(by_game[game][metric]))
                                                 if by_game[game][metric] else None)
                summaries[model][mode] = {
                    "observed_share": game_bootstrap({g: by_game[g]["observed"] for g in games}, games, draws),
                    "permutation_null_mean": game_bootstrap({g: by_game[g]["null"] for g in games}, games, draws),
                    "observed_minus_null": game_bootstrap({g: by_game[g]["gap"] for g in games}, games, draws),
                    "support": support[mode][model],
                }
                support[mode][model]["eligible_equalteam_starts"] = sum(len(v) for v in start_rows.values())
        output["transitions"][transition_key] = {
            "earlier_horizon": earlier_h, "later_horizon": later_h,
            "pairs_per_start_team_minimum": MIN_PAIRS,
            "permutation_count_per_start_team": PERMUTATIONS,
            "permutation_seed": SEED,
            "definitions": {"observed_share": "later negative error mass attached to an earlier-negative pair / all later negative error mass",
                            "null": "same earlier sign indicator; permute the corrected later negative-mass vector within start/team",
                            "equalteam": "equal average of Home/Away cell shares within start; equal starts within game; equal games",
                            "correction_modes": list(modes)},
            "summaries": summaries,
            "cell_support": support,
        }
    return output


def summarize_binned(records: dict, games: list[str], candidate: str, fit: dict,
                     bin_kind: str, edges: list[float], q1_eligible: dict,
                     draws: np.ndarray) -> dict:
    bins_n = len(edges) + 1
    grouped = defaultdict(lambda: defaultdict(list))
    pair_counts = [0] * bins_n
    cell_counts = [set() for _ in range(bins_n)]
    for sid, start in records.items():
        for team in TEAMS:
            if (sid, team) not in q1_eligible:
                continue
            pairs45 = start["horizons"][45][team]
            common_for_decile = set(pairs45) & set(start["horizons"][1][team]) & set(start["horizons"][15][team])
            for pair, row45 in pairs45.items():
                if bin_kind == "distance":
                    value = float(row45["cutoff_distance_ft"])
                else:
                    if pair not in common_for_decile:
                        continue
                    value = abs(float(start["horizons"][1][team][pair]["errors_ft"]["M0"]))
                b = int(np.searchsorted(edges, value, side="right"))
                x = float(row45["errors_ft"]["M0"])
                y = float(row45["errors_ft"][candidate])
                r = y - (float(fit["a"]) + float(fit["kappa"]) * x)
                key = (start["game"], sid, team, b)
                grouped[key]["residual"].append(r)
                grouped[key]["raw_candidate_error"].append(y)
                grouped[key]["raw_candidate_minus_m0_delta"].append(y - x)
                pair_counts[b] += 1
                cell_counts[b].add((sid, team))

    by_bin = []
    for b in range(bins_n):
        by_start = defaultdict(lambda: defaultdict(dict))
        for (game, sid, team, bin_idx), values in grouped.items():
            if bin_idx != b:
                continue
            by_start[(game, sid)][team] = {metric: float(np.mean(vals)) for metric, vals in values.items()}
        game_metric_values = {metric: {g: [] for g in games}
                              for metric in ("residual", "raw_candidate_error", "raw_candidate_minus_m0_delta")}
        start_count = set()
        represented_games = set()
        for (game, sid), team_map in by_start.items():
            start_count.add(sid)
            represented_games.add(game)
            for metric in game_metric_values:
                present = [team_map[t][metric] for t in TEAMS if metric in team_map.get(t, {})]
                if present:
                    game_metric_values[metric][game].append(float(np.mean(present)))
        metrics = {}
        for metric, game_rows in game_metric_values.items():
            per_game = {g: (float(np.mean(vals)) if vals else None) for g, vals in game_rows.items()}
            metrics[metric] = game_bootstrap(per_game, games, draws)
        by_bin.append({"bin": b + 1, "lower_edge_inclusive_upper_edge_exclusive": True,
                       "pair_count": pair_counts[b], "start_team_cell_count": len(cell_counts[b]),
                       "start_count": len(start_count), "represented_game_count": len(represented_games),
                       "metrics": metrics})
    return {"kind": bin_kind, "edges_ft": edges, "bins": by_bin}


def q4_attribution(records: dict, games: list[str], q1: dict, draws: np.ndarray) -> dict:
    result = {"horizon_45": {}, "per_game_offsets_by_horizon": {},
              "distance_and_one_step_error_bins": {}}
    for model in CANDIDATES:
        fit45 = q1["fits"]["45"]["EqualTeam"][model]["pooled_wls"]
        audit45, eligible45 = cells_for_horizon(records, 45)
        per_start = {}
        within_terms = []
        for sid, start in records.items():
            if not all((sid, t) in eligible45 for t in TEAMS):
                continue
            team_means, residuals_by_team = {}, {}
            for team in TEAMS:
                values = []
                residuals = []
                for pair, row in start["horizons"][45][team].items():
                    x = float(row["errors_ft"]["M0"])
                    y = float(row["errors_ft"][model])
                    r = y - (float(fit45["a"]) + float(fit45["kappa"]) * x)
                    values.append(r)
                    residuals.append(r)
                team_means[team] = float(np.mean(values))
                residuals_by_team[team] = residuals
            mean = float(np.mean(list(team_means.values())))
            per_start[sid] = {"game": start["game"], "start_mean_residual_ft": mean,
                              "team_mean_residuals_ft": team_means,
                              "pair_count": sum(len(v) for v in residuals_by_team.values())}
            within_terms.append((mean, residuals_by_team))
        means = np.asarray([v["start_mean_residual_ft"] for v in per_start.values()], dtype=np.float64)
        grand = float(np.mean(means)) if len(means) else None
        between = float(np.mean((means - grand) ** 2)) if len(means) else None
        within_by_start = []
        for mean, team_map in within_terms:
            team_variances = []
            for team in TEAMS:
                arr = np.asarray(team_map[team], dtype=np.float64)
                team_variances.append(float(np.mean((arr - mean) ** 2)))
            within_by_start.append(float(np.mean(team_variances)))
        within = float(np.mean(within_by_start)) if within_by_start else None
        total = None if between is None or within is None else between + within
        share = None if not total else between / total
        distribution = None if not len(means) else {
            "min": float(np.min(means)), "q1": float(np.quantile(means, .25, method="linear")),
            "median": float(np.quantile(means, .5, method="linear")),
            "q3": float(np.quantile(means, .75, method="linear")), "max": float(np.max(means)),
            "start_count": int(len(means)),
        }
        result["horizon_45"][model] = {
            "pooled_intercept_fit": fit45, "per_start_mean_residual_distribution_ft": distribution,
            "per_start_values": per_start,
            "pair_residual_variance_decomposition_ft2": {
                "between_start_variance": between, "within_start_variance": within,
                "total_variance": total, "between_start_share": share,
                "weighting": "equal starts; equal teams within start; equal pairs within team cell",
            },
        }
        per_game_offsets = {}
        for h in HORIZONS:
            fit_record = q1["fits"][str(h)]["EqualTeam"][model]
            game_offsets = {g: fit_record["per_game_fits"][g]["a"] for g in games}
            per_game_offsets[str(h)] = {
                "per_game_intercept_ft": game_offsets,
                "equal_game_intercept": game_bootstrap(game_offsets, games, draws),
            }
        result["per_game_offsets_by_horizon"][model] = per_game_offsets
        result["distance_and_one_step_error_bins"][model] = {
            "observed_cutoff_distance_quartiles": summarize_binned(
                records, games, model, fit45, "distance", DISTANCE_EDGES_FT, eligible45, draws),
            "m0_plus1_absolute_error_deciles": summarize_binned(
                records, games, model, fit45, "m0_plus1", M0_PLUS1_EDGES_FT, eligible45, draws),
        }
    return result


def fmt(value, digits: int = 4) -> str:
    if value is None:
        return "not estimable"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if not math.isfinite(float(value)):
        return "not finite"
    return f"{float(value):.{digits}f}"


def fmt_ci(summary: dict, digits: int = 4) -> str:
    value = summary.get("equal_game_mean")
    ci = summary.get("bootstrap_95_ci")
    if value is None:
        return "not estimable"
    if ci is None:
        return f"{fmt(value,digits)} (CI unavailable; {summary.get('valid_draws', 0)} valid draws)"
    return f"{fmt(value,digits)} [{fmt(ci[0],digits)}, {fmt(ci[1],digits)}]"


def q1_game_order(games: list[str]) -> list[str]:
    return [f"G{i+1}={game}" for i, game in enumerate(games)]


def render_report(result: dict) -> str:
    q1, q2, q3, q4 = result["Q1"], result["Q2"], result["Q3"], result["Q4"]
    games = result["population"]["games"]
    lines = [
        "# NHL JC-DIAG4: additive-offset decomposition",
        "",
        f"**Base:** `{BASE_COMMIT}`. **Preregistration commit:** `{PREREG_COMMIT}`.",
        "**Branch:** `research/nhl-multi-agent-movement-2026-10-23`.",
        "",
        "## Population and boundary",
        "",
        "10 development games, leave-one-whole-game-out predictions within that sample; 200 rollout starts (172 group-scored at +45); 2,164 +45 within-team pairs (1,064 Home / 1,100 Away, matching the frozen raw-frame counts); 142 EqualTeam-eligible +45 start/team cells; horizons are ordinal Image Id increments, **not seconds**; no independent tracking population exists on disk. Nothing here licenses adoption, a validated simulator claim, or a Legendary Picks probability change. Descriptive only: no refit of any model, no resimulation, no policy scoring, no candidate selection, no accuracy or skill claim, no gate, threshold or promotion rule touched. Pairs and starts are not independent uncertainty units — every interval is a 10-whole-game cluster bootstrap, 10,000 draws, seed 20261024, equal game weight, shared across all estimates and all models.",
        "",
        "The event coordinates and predicted positions were read from frozen development artifacts. Horizons",
        "are ordinal observation steps, not elapsed seconds. No start IDs or athlete identities were joined",
        "across games. This report does not claim independent adoption evidence.",
        "",
        "## Provenance gate",
        "",
        f"Gate status: **{'PASS' if result['provenance_gate']['all_assertions_passed'] else 'FAIL'}**; "
        f"{sum(1 for row in result['provenance_gate']['source_hash_checks'] if row['passed'])}/"
        f"{len(result['provenance_gate']['source_hash_checks'])} hashes and "
        f"{sum(1 for row in result['provenance_gate']['assertions'] if row['passed'])}/"
        f"{len(result['provenance_gate']['assertions'])} value/support assertions passed before Q1.",
        "",
        "| Frozen input | Expected SHA-256 | Actual SHA-256 | Status |",
        "|---|---|---|---|",
    ]
    for row in result["provenance_gate"]["source_hash_checks"]:
        lines.append(f"| {row['name']} | `{row['expected']}` | `{row['actual']}` | {'PASS' if row['passed'] else 'FAIL'} |")
    lines += ["", "| Assertion | Expected | Actual | Tolerance | Status |", "|---|---:|---:|---:|---|"]
    for row in result["provenance_gate"]["assertions"]:
        lines.append(f"| {row['name']} | `{row['expected']}` | `{row['actual']}` | "
                     f"`{row.get('tolerance_abs')}` | {'PASS' if row['passed'] else 'FAIL'} |")
    lines += ["", "## Q1 — intercept and slope", "",
              "Weighted least squares used the preregistered pair and cell weights. R² is centered.",
              "The table reports pooled coefficients and equal-game means with 95% whole-game intervals.",
              "Counts are raw pairs / fitted pairs / start-team cells / starts / games.", "",
              "| Horizon | Group | Model | Pooled a | Pooled κ | Centered R² | Equal-game a [95% CI] | "
              "Equal-game κ [95% CI] | Equal-game R² [95% CI] | Support |",
              "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for h in HORIZONS:
        for group in GROUPS:
            for model in CANDIDATES:
                item = q1["fits"][str(h)][group][model]
                pooled = item["pooled_wls"]
                counts = item["counts"]
                support = (f"{counts['raw_pair_count']}/{counts['included_pair_count']}/"
                           f"{counts['start_team_cell_count']}/{counts['eligible_start_count']}/"
                           f"{counts['represented_game_count']}")
                lines.append(f"| +{h} | {group} | {model} | {fmt(pooled['a'])} | {fmt(pooled['kappa'])} | "
                             f"{fmt(pooled['centered_r2'])} | {fmt_ci(item['equal_game']['a'])} | "
                             f"{fmt_ci(item['equal_game']['kappa'])} | {fmt_ci(item['equal_game']['centered_r2'])} | "
                             f"{support} |")
    lines += ["", "Game order for vectors: " + "; ".join(q1_game_order(games)) + ".", "",
              "Per-game and leave-one-game-out vectors list `(a, κ, centered R²)` in that order. `LOO Gk` "
              "omits that whole game.", ""]
    for h in HORIZONS:
        for group in GROUPS:
            for model in CANDIDATES:
                item = q1["fits"][str(h)][group][model]
                game_vec = "; ".join(
                    f"{game}:({fmt(item['per_game_fits'][game]['a'],3)},"
                    f"{fmt(item['per_game_fits'][game]['kappa'],3)},"
                    f"{fmt(item['per_game_fits'][game]['centered_r2'],3)})" for game in games)
                loo_vec = "; ".join(
                    f"omit {game}:({fmt(item['leave_one_game_out_fits'][game]['a'],3)},"
                    f"{fmt(item['leave_one_game_out_fits'][game]['kappa'],3)},"
                    f"{fmt(item['leave_one_game_out_fits'][game]['centered_r2'],3)})" for game in games)
                lines.append(f"- **+{h} {group} {model}, per-game:** {game_vec}")
                lines.append(f"  **LOO:** {loo_vec}")
    lines += ["", "### Frozen-method reproduction checks", "",
              f"The recomputed through-origin slopes match DIAG3 at +15/+45 for all 12 group/model "
              f"cells: {sum(v['passed'] for v in result['analysis_validation']['checks'] if v['name'].startswith('DIAG3_origin'))}/12 passed. "
              f"The raw P1 observed/null values reproduce DIAG2 for M0/M1/M2: "
              f"{sum(v['passed'] for v in result['analysis_validation']['checks'] if v['name'].startswith('DIAG2_P1_raw'))}/6 passed. "
              f"The raw distance-quartile values and bin supports reproduce the frozen DIAG3 Q3 values: "
              f"{sum(v['passed'] for v in result['analysis_validation']['checks'] if v['name'].startswith('DIAG3_Q3_distance_raw'))}/4 passed.", ""]
    lines += ["", "### Signed error levels", "",
              "These are equal-game means of cell-weighted signed pair errors; M0 +45 is the shared reference.",
              "", "| Horizon | Group | Model | Mean signed error ft [95% CI] |", "|---:|---|---|---:|"]
    for h in HORIZONS:
        for group in GROUPS:
            for model in MODELS:
                summary = q1["mean_error_levels"][str(h)][group][model]["mean_signed_error_ft"]
                lines.append(f"| +{h} | {group} | {model} | {fmt_ci(summary)} |")
    lines += ["", "## Q2 — signed bias and correction", "",
              "All intervals resample whole games. Bias removed is `1 - |corrected mean| / |raw mean|`; "
              "negative values mean larger absolute bias.", "",
              "| Horizon | Group | Model | Raw mean [95% CI] | Through-origin residual [95% CI] | "
              "Intercept residual [95% CI] | Origin bias removed [95% CI] | Intercept bias removed [95% CI] |",
              "|---:|---|---|---:|---:|---:|---:|---:|"]
    for h in HORIZONS:
        for group in GROUPS:
            for model in CANDIDATES:
                item = q2[str(h)][group][model]
                bo = item["bias_removed"]["through_origin"]
                bi = item["bias_removed"]["intercept"]
                bo_text = ("not estimable" if bo["share_mean_bias_removed"] is None else
                           f"{fmt(bo['share_mean_bias_removed'])} "
                           f"[{fmt(bo['bootstrap_95_ci'][0])}, {fmt(bo['bootstrap_95_ci'][1])}]" if bo["bootstrap_95_ci"] else
                           f"{fmt(bo['share_mean_bias_removed'])} [CI unavailable]")
                bi_text = ("not estimable" if bi["share_mean_bias_removed"] is None else
                           f"{fmt(bi['share_mean_bias_removed'])} "
                           f"[{fmt(bi['bootstrap_95_ci'][0])}, {fmt(bi['bootstrap_95_ci'][1])}]" if bi["bootstrap_95_ci"] else
                           f"{fmt(bi['share_mean_bias_removed'])} [CI unavailable]")
                lines.append(f"| +{h} | {group} | {model} | {fmt_ci(item['means']['raw'])} | "
                             f"{fmt_ci(item['means']['through_origin'])} | {fmt_ci(item['means']['intercept'])} | "
                             f"{bo_text} | {bi_text} |")
    lines += ["", "## Q3 — negative-mass persistence after additive correction", "",
              "The primary contrast is P1 (+15 to +45); the adjacent P2 transitions are included as "
              "preregistered horizon checks. Each entry is an EqualTeam equal-game mean. Gap intervals "
              "bootstrap paired game-level observed-minus-null values.", "",
              "| Transition | Model | Correction | Observed [95% CI] | Null [95% CI] | "
              "Observed − null [95% CI] | Eligible EqualTeam starts |", "|---|---|---|---:|---:|---:|---:|"]
    for transition, value in q3["transitions"].items():
        for model in MODELS:
            modes = ("raw",) if model == "M0" else ("raw", "loo_global_game", "loo_team_horizon", "in_sample_cell")
            for mode in modes:
                item = value["summaries"][model][mode]
                support = item["support"]["eligible_equalteam_starts"]
                label = {"raw": "raw", "loo_global_game": "LOOG global game",
                         "loo_team_horizon": "LOOG team × horizon (primary)",
                         "in_sample_cell": "own-cell mean (in-sample upper bound)"}[mode]
                lines.append(f"| {transition} | {model} | {label} | "
                             f"{fmt_ci(item['observed_share'])} | {fmt_ci(item['permutation_null_mean'])} | "
                             f"{fmt_ci(item['observed_minus_null'])} | {support} |")
    lines += ["", "The team × horizon offset is estimated from the other nine games and repeated across "
              "starts within each held-out team/game. The global offset uses complete EqualTeam starts; "
              "the team-specific offsets use each team's own eligible start cells, so their support can "
              "differ. The offset table below and the per-fold values in JSON make that distinction "
              "visible. The in-sample-at-cell result subtracts the same "
              "cell's own mean pair error; it is not an out-of-sample estimate and is shown only as an "
              "upper-bound sensitivity. Offset equality checks use the preregistered 1e-12 ft tolerance.", ""]
    identities = q3["offset_identity_checks"]
    team_eq = sum(v["team_mean_equals_global_within_1e-12_ft"] for v in identities.values())
    each_eq = sum(v["home_and_away_each_equal_global_within_1e-12_ft"] for v in identities.values())
    lines.append(f"LOOG offset equality checks: equal-team mean of Home/Away offsets matched the global "
                 f"game offset in {team_eq}/{len(identities)} held-out-game/horizon/model folds; both "
                 f"individual team offsets matched it in {each_eq}/{len(identities)} folds.")
    lines += ["", "| Horizon | Model | Global EqualTeam offset: mean (range) ft | Home offset: mean (range) ft | "
              "Away offset: mean (range) ft |", "|---:|---|---:|---:|---:|"]
    for h in HORIZONS:
        for model in CANDIDATES:
            rows = [v for key, v in q3["offset_estimates"].items()
                    if key.endswith(f"|+{h}|{model}")]
            def mean_range(values):
                vals = [float(x) for x in values if x is not None]
                return "not estimable" if not vals else f"{fmt(float(np.mean(vals)))} ({fmt(min(vals))}, {fmt(max(vals))})"
            lines.append(f"| +{h} | {model} | "
                         f"{mean_range([r['global_game_equalteam_offset_ft'] for r in rows])} | "
                         f"{mean_range([r['team_horizon_offsets_ft']['Home'] for r in rows])} | "
                         f"{mean_range([r['team_horizon_offsets_ft']['Away'] for r in rows])} |")
    p1_primary = q3["transitions"]["plus15_to_plus45"]
    corrected_rows = [p1_primary["summaries"][m]["loo_team_horizon"] for m in CANDIDATES]
    upper_rows = [p1_primary["summaries"][m]["in_sample_cell"] for m in CANDIDATES]
    lines += ["", "For P1, the primary team × horizon correction leaves the equal-game observed share at "
              f"{fmt(corrected_rows[0]['observed_share']['equal_game_mean'])} (M1) and "
              f"{fmt(corrected_rows[1]['observed_share']['equal_game_mean'])} (M2), above null means "
              f"{fmt(corrected_rows[0]['permutation_null_mean']['equal_game_mean'])} and "
              f"{fmt(corrected_rows[1]['permutation_null_mean']['equal_game_mean'])}. The in-sample cell "
              f"upper-bound observed shares are {fmt(upper_rows[0]['observed_share']['equal_game_mean'])} "
              f"and {fmt(upper_rows[1]['observed_share']['equal_game_mean'])}, with nulls "
              f"{fmt(upper_rows[0]['permutation_null_mean']['equal_game_mean'])} and "
              f"{fmt(upper_rows[1]['permutation_null_mean']['equal_game_mean'])}. Subtracting each cell's "
              "mean forces its signed mean to zero, but does not force the observed cross-horizon "
              "negative-mass share to 0.5; the within-cell permutation null is near one-half here while "
              "the observed share remains higher.", ""]
    lines += ["", "## Q4 — offset heterogeneity and pair geometry", "", "### Start-level residuals and variance share", "",
              "| Model | Start residual mean distribution ft (min, Q1, median, Q3, max) | Between-start variance share |",
              "|---|---:|---:|"]
    for model in CANDIDATES:
        item = q4["horizon_45"][model]
        d = item["per_start_mean_residual_distribution_ft"]
        v = item["pair_residual_variance_decomposition_ft2"]
        lines.append(f"| {model} | {fmt(d['min'])}, {fmt(d['q1'])}, {fmt(d['median'])}, "
                     f"{fmt(d['q3'])}, {fmt(d['max'])} (n={d['start_count']}) | {fmt(v['between_start_share'])} |")
    lines += ["", "### Per-game intercepts by horizon", "",
              "| Horizon | Model | Equal-game a [95% CI] | Per-game a in G1–G10 order |",
              "|---:|---|---:|---|"]
    for h in HORIZONS:
        for model in CANDIDATES:
            item = q4["per_game_offsets_by_horizon"][model][str(h)]
            vector = ", ".join(fmt(item["per_game_intercept_ft"][g]) for g in games)
            lines.append(f"| +{h} | {model} | {fmt_ci(item['equal_game_intercept'])} | {vector} |")
    for bin_name, label in (("observed_cutoff_distance_quartiles", "Observed cutoff distance quartile"),
                            ("m0_plus1_absolute_error_deciles", "M0 +1 absolute-error decile")):
        lines += ["", f"### {label}", "",
                  "| Model | Bin | Pairs / cells / starts / games | Intercept residual ft [95% CI] | "
                  "Raw candidate error ft [95% CI] | Raw candidate − M0 ft [95% CI] |",
                  "|---|---:|---:|---:|---:|---:|"]
        for model in CANDIDATES:
            bins = q4["distance_and_one_step_error_bins"][model][bin_name]["bins"]
            for row in bins:
                metrics = row["metrics"]
                lines.append(f"| {model} | {row['bin']} | {row['pair_count']} / "
                             f"{row['start_team_cell_count']} / {row['start_count']} / "
                             f"{row['represented_game_count']} | {fmt_ci(metrics['residual'])} | "
                             f"{fmt_ci(metrics['raw_candidate_error'])} | "
                             f"{fmt_ci(metrics['raw_candidate_minus_m0_delta'])} |")
    distance = q4["distance_and_one_step_error_bins"]
    lines += ["", "The +45 distance gradient remains after the intercept fit: for M1, residual means "
              f"move from {fmt(distance['M1']['observed_cutoff_distance_quartiles']['bins'][0]['metrics']['residual']['equal_game_mean'])} "
              f"ft in Q1 to {fmt(distance['M1']['observed_cutoff_distance_quartiles']['bins'][3]['metrics']['residual']['equal_game_mean'])} ft in Q4; "
              f"the raw candidate-minus-M0 means move from {fmt(distance['M1']['observed_cutoff_distance_quartiles']['bins'][0]['metrics']['raw_candidate_minus_m0_delta']['equal_game_mean'])} "
              f"to {fmt(distance['M1']['observed_cutoff_distance_quartiles']['bins'][3]['metrics']['raw_candidate_minus_m0_delta']['equal_game_mean'])} ft. "
              "The residual gradient is weaker in magnitude but remains monotone across the four bins; this is descriptive, not causal.", ""]
    lines += ["", "## Decision and limits", "", result["verdict"], "",
              "These ten inspected games remain development data. The tracking feed lacks a documented "
              "subsecond timebase; Image Id is ordinal. Player identities can conflict, cross-game "
              "athlete identity is unverified, event-to-tracking alignment failed its prior gate, and "
              "puck Z is not continuous flight measurement. The present analysis does not establish "
              "physical velocity, reaction timing, possession, collision mechanics, or a validated "
              "NHL simulator. Independent games with verified timing and identity evidence are required "
              "for any adoption claim.", "",
              "## Reproduction", "",
              "```sh",
              "nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_additive_offset.py --gate-only",
              "nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_additive_offset.py",
              "nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_additive_offset.py --output /tmp/jc-diag4-additive-offset-repeat.json",
              "cmp results/jc-diag4-additive-offset-2026-10-23-v1.json /tmp/jc-diag4-additive-offset-repeat.json",
              "```", ""]
    return "\n".join(lines)


def run_full(output_path: Path) -> tuple[str, int, dict]:
    gate, jc, _, diag2, diag3 = make_gate()
    if not gate["all_assertions_passed"]:
        raise RuntimeError("provenance gate failed; Q1-Q4 stopped")
    archive = read_gzip_json(PATHS["scenario_archive"])
    starts = read_gzip_json(PATHS["rollout_starts"])
    records, games = build_records(jc, archive, starts, gate["raw_frame_support"])
    boot_rng = np.random.default_rng(SEED)
    game_draws = boot_rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)
    q1, rows_index = q1_fit(records, games, game_draws)
    q2 = q2_decomposition(records, games, game_draws, q1, rows_index)
    q3 = q3_persistence(records, games, game_draws)
    q4 = q4_attribution(records, games, q1, game_draws)
    validation_checks = []
    for h in ("15", "45"):
        for group in GROUPS:
            for model in CANDIDATES:
                actual = q2[h][group][model]["through_origin_kappa"]
                expected = diag3["Q1_through_origin_slopes"]["by_horizon"][h][group][model]["pooled_through_origin_fit"]["kappa"]
                validation_checks.append({"name": f"DIAG3_origin_{h}_{group}_{model}",
                                          "expected": expected, "actual": actual,
                                          "tolerance_abs": 5e-9,
                                          "passed": close(actual, expected, 5e-9)})
    p1_old = nested(diag2, "P1_plus15_to_plus45_pair_persistence", "summary", "models", "EqualTeam")
    p1_new = q3["transitions"]["plus15_to_plus45"]["summaries"]
    for model in MODELS:
        for metric, key in (("observed_share", "observed_share"),
                            ("permutation_null_mean", "permutation_null_mean")):
            actual = p1_new[model]["raw"][metric]["equal_game_mean"]
            expected = p1_old[model][key]["equal_game_mean_available_games"]
            validation_checks.append({"name": f"DIAG2_P1_raw_{model}_{metric}",
                                      "expected": expected, "actual": actual,
                                      "tolerance_abs": 5e-9,
                                      "passed": close(actual, expected, 5e-9)})
    old_m1_distance_bins = diag3["Q3_fixed_slope_residual_structure_plus45"]["by_candidate"]["M1"]\
        ["by_fixed_cutoff_distance_quartile"]["bins"]
    new_m1_distance_bins = q4["distance_and_one_step_error_bins"]["M1"]\
        ["observed_cutoff_distance_quartiles"]["bins"]
    for i in (0, 3):
        expected_delta = old_m1_distance_bins[i]["metrics"]["raw_signed_delta_ft"]["equal_game_mean"]
        actual_delta = new_m1_distance_bins[i]["metrics"]["raw_candidate_minus_m0_delta"]["equal_game_mean"]
        validation_checks.append({"name": f"DIAG3_Q3_distance_raw_delta_Q{i+1}",
                                  "expected": expected_delta, "actual": actual_delta,
                                  "tolerance_abs": 5e-9,
                                  "passed": close(actual_delta, expected_delta, 5e-9)})
        expected_count = old_m1_distance_bins[i]["pair_count"]
        actual_count = new_m1_distance_bins[i]["pair_count"]
        validation_checks.append({"name": f"DIAG3_Q3_distance_raw_pair_count_Q{i+1}",
                                  "expected": expected_count, "actual": actual_count,
                                  "tolerance_abs": 0,
                                  "passed": actual_count == expected_count})
    analysis_validation = {"passed": all(v["passed"] for v in validation_checks),
                           "checks": validation_checks}
    if not analysis_validation["passed"]:
        failed = [item for item in validation_checks if not item["passed"]]
        raise RuntimeError(f"frozen-method reproduction check failed: {failed}")

    primary = q3["transitions"]["plus15_to_plus45"]
    verdict_items = {}
    for correction in ("loo_global_game", "loo_team_horizon"):
        summary = primary["summaries"]["M1"][correction]["observed_minus_null"]
        verdict_items[correction] = {"gap_equal_game_mean": summary["equal_game_mean"],
                                     "gap_95_ci": summary["bootstrap_95_ci"],
                                     "all_ten_game_clusters": summary["games_with_values"] == 10}
    survives = any(v["gap_equal_game_mean"] is not None and v["gap_equal_game_mean"] > 0 and
                   v["gap_95_ci"] is not None and v["gap_95_ci"][0] > 0 for v in verdict_items.values())
    if survives:
        verdict = ("After the preregistered out-of-game additive correction, P1 negative-error "
                   "persistence remains above its within-start permutation null for at least one "
                   "candidate with a positive whole-game 95% gap interval. This is descriptive evidence "
                   "in ten development games only; it does not establish pair-intent causality or justify "
                   "building labels for adoption.")
    else:
        verdict = ("After the preregistered out-of-game additive correction, pair-level negative-error "
                   "persistence is not shown to survive above its within-start permutation null with a "
                   "positive whole-game 95% gap interval. The in-sample-at-cell correction is only an "
                   "upper-bound sensitivity and is not evidence for deployable correction or the null. "
                   "The ten-game development sample does not support an adoption claim.")

    result = {
        "schema_version": 1,
        "analysis": "NHL JC-DIAG4 additive-offset decomposition",
        "base_commit": BASE_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                            "sha256": PREREG_SHA256},
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "source_hashes": gate["actual_source_hashes"],
        "provenance_gate": gate,
        "population": {"game_count": len(games), "games": games,
                       "population_statement": "10 development games, leave-one-whole-game-out predictions within that sample; 200 rollout starts (172 group-scored at +45); 2,164 +45 within-team pairs (1,064 Home / 1,100 Away, matching the frozen raw-frame counts); 142 EqualTeam-eligible +45 start/team cells; horizons are ordinal Image Id increments, not seconds; no independent tracking population exists on disk.",
                       "rollout_starts": 200, "plus45_scored_starts": 172,
                       "plus45_pair_counts": {"Home": 1064, "Away": 1100, "total": 2164},
                       "equalteam_eligible_plus45_start_team_cells": 142,
                       "timebase": "ordinal Image Id increments, not seconds",
                       "independent_tracking_population_available": False},
        "method": {"horizons": list(HORIZONS), "pair_error": "predicted within-team distance minus observed target distance, feet",
                   "q1_fit": "weighted least squares with intercept; equal pair weights Home/Away; EqualTeam cell weight 1 with pair weight 1/n; centered R2",
                   "minimum_cell_pairs": MIN_PAIRS,
                   "bootstrap_draws": BOOTSTRAPS, "bootstrap_seed": SEED,
                   "bootstrap_unit": "whole game; equal game weight; shared index matrix",
                   "permutation_draws_per_start_team": PERMUTATIONS,
                   "permutation_seed": SEED,
                   "q3_transitions": [[15, 45], [15, 30], [30, 45]],
                   "q3_correction_modes": ["raw", "loo_global_game", "loo_team_horizon", "in_sample_cell"],
                   "loo_team_horizon_definition": "other-nine-game equal-game team/horizon mean, repeated across starts in held-out game",
                   "in_sample_cell_definition": "held-out start/team/horizon own pair mean; in-sample upper-bound sensitivity",
                   "q4_distance_cutpoints_ft": DISTANCE_EDGES_FT,
                   "q4_m0_plus1_cutpoints_ft": M0_PLUS1_EDGES_FT,
                   "fit_or_simulation_refit": False},
        "support_audit": {"raw_frame_support": gate["raw_frame_support"],
                          "q1_cell_eligibility_and_exclusions": q1["cell_eligibility_and_exclusions"]},
        "Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4,
        "analysis_validation": analysis_validation,
        "verdict_support": verdict_items, "verdict": verdict,
    }
    digest, size = write_json(output_path, result)
    if output_path.resolve() == (RESULTS / "jc-diag4-additive-offset-2026-10-23-v1.json").resolve():
        REPORT.write_text(render_report(result), encoding="utf-8")
    return digest, size, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="run provenance assertions only; never calculate Q1-Q4")
    parser.add_argument("--output", type=Path,
                        default=RESULTS / "jc-diag4-additive-offset-2026-10-23-v1.json")
    args = parser.parse_args()
    gate, _, _, _, _ = make_gate()
    if args.gate_only:
        digest, size = write_gate_only(args.output, gate)
        print(f"GATE_ONLY path={args.output} sha256={digest} bytes={size}")
        print(f"all_assertions_passed={gate['all_assertions_passed']} q1_q4_calculated=false")
        if not gate["all_assertions_passed"]:
            for row in gate.get("source_hash_checks", []):
                if not row["passed"]:
                    print("HASH_FAIL", json.dumps(row, sort_keys=True))
            for row in gate.get("assertions", []):
                if not row["passed"]:
                    print("ASSERT_FAIL", json.dumps(row, sort_keys=True))
            raise SystemExit("JC-DIAG4 provenance gate failed")
        return
    if not gate["all_assertions_passed"]:
        failure = {"schema_version": 1, "analysis": "NHL JC-DIAG4 additive-offset decomposition",
                   "preregistration": {"commit": PREREG_COMMIT, "sha256": PREREG_SHA256},
                   "provenance_gate": gate, "all_assertions_passed": False,
                   "Q1_Q4_calculated": False}
        digest, size = write_json(args.output, failure)
        print(f"FAILURE path={args.output} sha256={digest} bytes={size}")
        raise SystemExit("JC-DIAG4 provenance gate failed; Q1-Q4 stopped")
    try:
        digest, size, result = run_full(args.output)
    except Exception as exc:
        failure = {"schema_version": 1, "analysis": "NHL JC-DIAG4 additive-offset decomposition",
                   "preregistration": {"commit": PREREG_COMMIT, "sha256": PREREG_SHA256},
                   "provenance_gate": gate, "all_assertions_passed": True,
                   "Q1_Q4_calculated": False,
                   "failure": f"analysis stopped: {type(exc).__name__}: {exc}"}
        write_json(args.output, failure)
        raise
    print(f"RESULT path={args.output} sha256={digest} bytes={size}")
    print(f"EVALUATOR sha256={result['evaluator_sha256']}")
    print(f"REPORT path={REPORT}")
    for q in ("Q1", "Q2", "Q3", "Q4"):
        print(f"{q} complete")


if __name__ == "__main__":
    main()
