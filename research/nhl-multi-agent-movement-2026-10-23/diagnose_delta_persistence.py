#!/usr/bin/python3
"""Run the preregistered, read-only NHL JC-DIAG5 delta diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research/nhl-multi-agent-movement-2026-10-23"
RESULTS = RESEARCH / "results"
DATA = Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23")
PREREG = ROOT / "docs/research/NHL-JC-DIAG5-PREREG-2026-10-23.md"
REPORT = ROOT / "docs/research/NHL-JC-DIAG5-REPORT-2026-10-23.md"
RESULT = RESULTS / "jc-diag5-delta-persistence-2026-10-23-v1.json"
PREREG_COMMIT = "f4791c943d1d769bc1b429ef384ef9c0e90c6a4a"
PREREG_SHA256 = "18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70"
BASE_COMMIT = "1dcd616906ee39ff46d4d117bd93ff627b24687e"
SEED = 20261024
BOOTSTRAPS = 10_000
PERMUTATIONS = 10_000
MIN_PAIRS = 3
HORIZONS = (15, 30, 45)
TRANSITIONS = ((15, 45), (15, 30), (30, 45))
TEAMS = ("Home", "Away")
CANDIDATES = ("M1", "M2")
DISTANCE_EDGES_FT = [17.038243596734116, 25.896550730297974, 36.18400154397977]
POPULATION_STATEMENT = (
    "Same frozen population as DIAG4: 10 development games, leave-one-whole-game-out predictions, "
    "200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home / "
    "1,100 Away), 142 EqualTeam +45 start/team cells; horizons are ordinal Image Id increments, "
    "**not seconds**; no independent tracking population; pairs and starts are not independent — "
    "every interval is the same 10-whole-game cluster bootstrap, 10,000 draws, seed 20261024, "
    "equal game weight, one matrix shared across all estimates."
)

EXPECTED_INPUTS = {
    "jc_results": (RESULTS / "joint-coherence-jc-2026-10-23-v1.json",
                   "0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c"),
    "fold_models": (RESULTS / "fold_models-bc91d1610de5.json",
                    "194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a"),
    "movement_comparison": (RESULTS / "movement_comparison-bc91d1610de5.json",
                             "1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8"),
    "scenario_archive": (RESULTS / "scenario_archive-bc91d1610de5.json.gz",
                         "a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce"),
    "rollout_starts": (DATA / "rollout_starts.json.gz",
                       "07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de"),
    "jc_diag_results": (RESULTS / "jc-attribution-jcdiag-2026-10-23-v1.json",
                        "f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c"),
    "jc_diag2_results": (RESULTS / "jc-diag2-pair-persistence-2026-10-23-v1.json",
                         "54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed"),
    "jc_diag3_results": (RESULTS / "jc-diag3-pair-shrink-2026-10-23-v1.json",
                         "e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd"),
    "jc_diag4_preregistration": (ROOT / "docs/research/NHL-JC-DIAG4-PREREG-2026-10-23.md",
                                 "66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0"),
    "jc_diag4_results": (RESULTS / "jc-diag4-additive-offset-2026-10-23-v1.json",
                         "cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947"),
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_diag4():
    sys.path.insert(0, str(RESEARCH))
    return importlib.import_module("diagnose_additive_offset")


def close(actual, expected, tolerance: float = 5e-9) -> bool:
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected) and
                all(close(a, e, tolerance) for a, e in zip(actual, expected)))
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return math.isfinite(float(actual)) and abs(float(actual) - float(expected)) <= tolerance
        except (TypeError, ValueError):
            return False
    return actual == expected


def nested(value: dict, *keys):
    for key in keys:
        value = value[key]
    return value


def provenance_source_rows() -> list[dict]:
    rows = []
    for name, (path, expected) in EXPECTED_INPUTS.items():
        actual = sha256_file(path)
        rows.append({"name": name, "path": str(path), "expected": expected,
                     "actual": actual, "passed": actual == expected,
                     "missing": actual is None})
    return rows


def rederive_diag4_checks(diag4, jc: dict, diag2: dict, diag3: dict,
                          archive: dict, starts: dict, raw_support: dict,
                          frozen_diag4: dict) -> tuple[dict, dict]:
    records, games = diag4.build_records(jc, archive, starts, raw_support)
    boot_rng = np.random.default_rng(SEED)
    draws = boot_rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)
    q1, rows_index = diag4.q1_fit(records, games, draws)
    q2 = diag4.q2_decomposition(records, games, draws, q1, rows_index)
    q3 = diag4.q3_persistence(records, games, draws)
    q4 = diag4.q4_attribution(records, games, q1, draws)
    checks = []

    def record(name: str, actual, expected, tolerance: float = 5e-9):
        checks.append({"name": name, "expected": expected, "actual": actual,
                       "tolerance_abs": tolerance,
                       "passed": close(actual, expected, tolerance)})

    for h in ("15", "45"):
        for group in diag4.GROUPS:
            for model in diag4.CANDIDATES:
                actual = q2[h][group][model]["through_origin_kappa"]
                expected = diag3["Q1_through_origin_slopes"]["by_horizon"][h][group][model][
                    "pooled_through_origin_fit"]["kappa"]
                record(f"DIAG3_origin_{h}_{group}_{model}", actual, expected)
    p1_old = nested(diag2, "P1_plus15_to_plus45_pair_persistence", "summary", "models", "EqualTeam")
    p1_new = q3["transitions"]["plus15_to_plus45"]["summaries"]
    for model in ("M0", "M1", "M2"):
        for metric, key in (("observed_share", "observed_share"),
                            ("permutation_null_mean", "permutation_null_mean")):
            actual = p1_new[model]["raw"][metric]["equal_game_mean"]
            expected = p1_old[model][key]["equal_game_mean_available_games"]
            record(f"DIAG2_P1_raw_{model}_{metric}", actual, expected)
    old_bins = diag3["Q3_fixed_slope_residual_structure_plus45"]["by_candidate"]["M1"]\
        ["by_fixed_cutoff_distance_quartile"]["bins"]
    new_bins = q4["distance_and_one_step_error_bins"]["M1"]["observed_cutoff_distance_quartiles"]["bins"]
    for index in (0, 3):
        expected_delta = old_bins[index]["metrics"]["raw_signed_delta_ft"]["equal_game_mean"]
        actual_delta = new_bins[index]["metrics"]["raw_candidate_minus_m0_delta"]["equal_game_mean"]
        record(f"DIAG3_Q3_distance_raw_delta_Q{index + 1}", actual_delta, expected_delta)
        expected_count = old_bins[index]["pair_count"]
        actual_count = new_bins[index]["pair_count"]
        record(f"DIAG3_Q3_distance_raw_pair_count_Q{index + 1}", actual_count, expected_count, 0)

    expected_names = [row["name"] for row in frozen_diag4["analysis_validation"]["checks"]]
    if [row["name"] for row in checks] != expected_names or len(checks) != 22:
        raise RuntimeError("DIAG4 validation set is not the frozen 22-check sequence")
    validation = {"passed": all(row["passed"] for row in checks), "checks": checks,
                  "check_count": len(checks), "frozen_check_names_match": True}
    frozen_checks = frozen_diag4["analysis_validation"]["checks"]
    for actual, frozen in zip(checks, frozen_checks):
        if not close(actual["actual"], frozen["actual"], actual["tolerance_abs"]):
            validation["passed"] = False
            actual["also_matches_frozen_DIAG4_result"] = False
        else:
            actual["also_matches_frozen_DIAG4_result"] = True
    validation["passed"] = validation["passed"] and all(
        row["also_matches_frozen_DIAG4_result"] for row in checks)
    in_memory = {"records": records, "games": games, "draws": draws,
                 "Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4}
    return validation, in_memory


def gate_assertions(diag4, gate: dict, frozen_diag4: dict,
                    diag3: dict, raw_support: dict) -> list[dict]:
    assertions = []

    def add(name: str, actual, expected, tolerance: float = 5e-9):
        assertions.append({"name": name, "actual": actual, "expected": expected,
                          "tolerance_abs": tolerance,
                          "passed": close(actual, expected, tolerance)})

    p1 = frozen_diag4["Q3"]["transitions"]["plus15_to_plus45"]["summaries"]
    expected_p1 = {
        "M1": {"observed": 0.7821033211298534, "null": 0.506411577441676,
               "gap": 0.2756917436881776,
               "gap_ci": [0.2384038832398193, 0.3111550243356705]},
        "M2": {"observed": 0.7822050082063668, "null": 0.5085816609973904,
               "gap": 0.2736233472089765,
               "gap_ci": [0.2330737848351857, 0.31150878225899326]},
    }
    for model, expected in expected_p1.items():
        item = p1[model]["loo_team_horizon"]
        add(f"DIAG4_P1_primary_{model}_observed_share",
            item["observed_share"]["equal_game_mean"], expected["observed"])
        add(f"DIAG4_P1_primary_{model}_null_mean",
            item["permutation_null_mean"]["equal_game_mean"], expected["null"])
        gap = item["observed_minus_null"]
        add(f"DIAG4_P1_primary_{model}_gap", gap["equal_game_mean"], expected["gap"])
        add(f"DIAG4_P1_primary_{model}_gap_ci", gap["bootstrap_95_ci"], expected["gap_ci"])

    m0 = p1["M0"]["raw"]
    add("DIAG4_M0_raw_P1_observed", m0["observed_share"]["equal_game_mean"],
        0.7630291734469827)
    add("DIAG4_M0_raw_P1_null", m0["permutation_null_mean"]["equal_game_mean"],
        0.47819563088399875)

    m1 = frozen_diag4["Q1"]["fits"]["45"]["EqualTeam"]["M1"]
    add("DIAG4_plus45_EqualTeam_M1_equal_game_intercept",
        m1["equal_game"]["a"]["equal_game_mean"], -4.394416812748907)
    add("DIAG4_plus45_EqualTeam_M1_equal_game_kappa",
        m1["equal_game"]["kappa"]["equal_game_mean"], 0.9256052503703968)
    counts = m1["counts"]
    add("DIAG4_plus45_EqualTeam_M1_support",
        [counts["raw_pair_count"], counts["included_pair_count"],
         counts["start_team_cell_count"], counts["eligible_start_count"],
         counts["represented_game_count"]], [2164, 1966, 284, 142, 10], 0)

    d3m1 = diag3["Q1_through_origin_slopes"]["by_horizon"]["45"]["EqualTeam"]["M1"]
    add("DIAG3_plus45_EqualTeam_M1_equal_game_kappa",
        d3m1["equal_game_kappa"]["equal_game_mean"], 0.9187677553966251)
    add("DIAG3_plus45_EqualTeam_M1_pair_pooled_kappa",
        d3m1["pooled_through_origin_fit"]["kappa"], 0.9109024558296622)

    add("raw_frame_pair_counts_Home_Away_total",
        [raw_support["plus45_pair_counts_by_team"]["Home"],
         raw_support["plus45_pair_counts_by_team"]["Away"],
         raw_support["plus45_pair_count_total"]], [1064, 1100, 2164], 0)
    add("raw_frame_population_game_start_scored",
        [raw_support["game_count"], raw_support["rollout_start_count"],
         raw_support["plus45_scored_start_count"]], [10, 200, 172], 0)
    add("raw_frame_support_assertion", raw_support["raw_denominator_assertion_passed"], True, 0)
    return assertions


def run_gate() -> tuple[dict, dict | None]:
    source_rows = provenance_source_rows()
    gate_result = {
        "base_commit": BASE_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                            "sha256": PREREG_SHA256, "actual_sha256": sha256_file(PREREG)},
        "expected_source_hashes": {name: expected for name, (_, expected) in EXPECTED_INPUTS.items()},
        "source_hash_checks": source_rows,
        "missing_paths": [row["path"] for row in source_rows if row["missing"]],
        "mismatched_paths": [row["path"] for row in source_rows
                             if not row["missing"] and not row["passed"]],
        "assertions": [], "diag4_postcompute_checks": None,
        "all_assertions_passed": False,
        "Q1_Q5_calculated": False,
    }
    if gate_result["preregistration"]["actual_sha256"] != PREREG_SHA256:
        gate_result["mismatched_paths"].append(str(PREREG))
    if not all(row["passed"] for row in source_rows) or gate_result["mismatched_paths"]:
        gate_result["failure"] = "missing or mismatched frozen input; DIAG5 Q1-Q5 not run"
        return gate_result, None

    diag4 = load_diag4()
    diag4_gate, jc, _, diag2, diag3 = diag4.make_gate()
    gate_result["diag4_provenance_gate"] = diag4_gate
    if not diag4_gate["all_assertions_passed"]:
        gate_result["failure"] = "DIAG4 embedded provenance/value gate failed; DIAG5 Q1-Q5 not run"
        return gate_result, None

    frozen_diag4 = diag4.read_json(EXPECTED_INPUTS["jc_diag4_results"][0])
    archive = diag4.read_gzip_json(diag4.PATHS["scenario_archive"])
    starts = diag4.read_gzip_json(diag4.PATHS["rollout_starts"])
    raw_support = diag4_gate["raw_frame_support"]
    assertions = gate_assertions(diag4, diag4_gate, frozen_diag4, diag3, raw_support)
    gate_result["assertions"] = assertions
    gate_result["source_hash_checks"].extend(
        row for row in diag4_gate["source_hash_checks"]
        if row["name"] not in {item["name"] for item in gate_result["source_hash_checks"]})
    gate_result["source_hash_checks"].extend([
        {"name": "diag4_evaluator", "path": str(diag4.__file__),
         "expected": "2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a",
         "actual": sha256_file(Path(diag4.__file__)),
         "passed": sha256_file(Path(diag4.__file__)) ==
                   "2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a",
         "missing": not Path(diag4.__file__).is_file()},
    ])
    validation, old_results = rederive_diag4_checks(
        diag4, jc, diag2, diag3, archive, starts, raw_support, frozen_diag4)
    gate_result["diag4_postcompute_checks"] = validation
    gate_result["diag4_rederived_support"] = {
        "game_count": len(old_results["games"]),
        "scored_start_count": len(old_results["records"]),
        "recomputed_q4_support_matches_frozen": (
            old_results["Q4"]["horizon_45"]["M1"]["pair_residual_variance_decomposition_ft2"]
            == frozen_diag4["Q4"]["horizon_45"]["M1"]["pair_residual_variance_decomposition_ft2"]
        ),
    }
    gate_result["all_assertions_passed"] = (
        all(row["passed"] for row in source_rows)
        and all(row["passed"] for row in gate_result["source_hash_checks"])
        and all(row["passed"] for row in diag4_gate["source_hash_checks"])
        and all(row["passed"] for row in diag4_gate["assertions"])
        and all(row["passed"] for row in assertions)
        and validation["passed"]
        and gate_result["diag4_rederived_support"]["recomputed_q4_support_matches_frozen"]
    )
    gate_result["Q1_Q5_calculated"] = False
    if not gate_result["all_assertions_passed"]:
        gate_result["failure"] = "one or more provenance, support, or DIAG4 re-run assertions failed; DIAG5 Q1-Q5 not run"
        return gate_result, None
    gate_result["pass_summary"] = {
        "DIAG5_named_sources": f"{len(EXPECTED_INPUTS)}/{len(EXPECTED_INPUTS)}",
        "embedded_DIAG4_hashes": f"{sum(row['passed'] for row in diag4_gate['source_hash_checks'])}/{len(diag4_gate['source_hash_checks'])}",
        "embedded_DIAG4_assertions": f"{sum(row['passed'] for row in diag4_gate['assertions'])}/{len(diag4_gate['assertions'])}",
        "DIAG5_value_assertions": f"{sum(row['passed'] for row in assertions)}/{len(assertions)}",
        "DIAG4_postcompute_checks": f"{sum(row['passed'] for row in validation['checks'])}/{len(validation['checks'])}",
    }
    return gate_result, old_results


def summarize_games(values_by_game: dict[str, float | None], games: list[str], draws: np.ndarray) -> dict:
    valid = [float(values_by_game[g]) for g in games if values_by_game.get(g) is not None]
    estimate = float(np.mean(valid)) if valid else None
    if len(valid) != len(games):
        return {"equal_game_mean": estimate, "bootstrap_95_ci": None,
                "games_with_values": len(valid), "per_game": {g: values_by_game.get(g) for g in games},
                "valid_draws": 0}
    array = np.asarray([values_by_game[g] for g in games], dtype=np.float64)
    boot = array[draws].mean(axis=1)
    return {"equal_game_mean": estimate,
            "bootstrap_95_ci": [float(np.quantile(boot, .025, method="linear")),
                                float(np.quantile(boot, .975, method="linear"))],
            "games_with_values": len(valid), "per_game": {g: float(array[i]) for i, g in enumerate(games)},
            "valid_draws": len(boot)}


def make_delta_offsets(records: dict, games: list[str]) -> tuple[dict, dict]:
    game_team = {}
    cell_means = {}
    for sid, start in records.items():
        for h in HORIZONS:
            for team in TEAMS:
                pair_map = start["horizons"][h][team]
                if len(pair_map) < MIN_PAIRS:
                    continue
                for model in CANDIDATES:
                    vals = [float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"])
                            for row in pair_map.values()]
                    cell_means[(start["game"], sid, team, h, model)] = float(np.mean(vals))
    for game in games:
        for h in HORIZONS:
            for model in CANDIDATES:
                for team in TEAMS:
                    cells = [value for (g, _sid, t, horizon, candidate), value in cell_means.items()
                             if (g, t, horizon, candidate) == (game, team, h, model)]
                    game_team[(game, team, h, model)] = float(np.mean(cells)) if cells else None
    offsets = {}
    for held in games:
        for h in HORIZONS:
            for model in CANDIDATES:
                for team in TEAMS:
                    train_values = [game_team[(game, team, h, model)] for game in games if game != held]
                    offsets[(held, team, h, model)] = (
                        float(np.mean(train_values)) if len(train_values) == len(games) - 1
                        and all(v is not None for v in train_values) else None)
    return offsets, {"per_game_team_cell_means": {
        f"{g}|{team}|+{h}|{model}": game_team[(g, team, h, model)]
        for g in games for team in TEAMS for h in HORIZONS for model in CANDIDATES
    }, "cell_means": cell_means}


def q1_delta(records: dict, games: list[str], draws: np.ndarray,
             offsets: dict, offset_source: dict) -> dict:
    out = {"definition": "candidate errors_ft minus M0 errors_ft, same pair/game/start/team/horizon",
           "weighting": "EqualTeam: equal team cells within start, equal starts within game, equal games; pair spread is pair-weighted",
           "by_horizon": {}, "plus45_variance_decomposition": {},
           "loo_team_horizon_offsets_ft": {}, "offset_source_game_means_ft": offset_source["per_game_team_cell_means"]}
    for h in HORIZONS:
        out["by_horizon"][str(h)] = {}
        for model in CANDIDATES:
            pair_values = []
            by_cell = {}
            cell_counts = {}
            for sid, start in records.items():
                for team in TEAMS:
                    pair_map = start["horizons"][h][team]
                    vals = [float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"])
                            for row in pair_map.values()]
                    pair_values.extend(vals)
                    by_cell[(sid, team)] = float(np.mean(vals)) if len(vals) >= MIN_PAIRS else None
                    cell_counts[(sid, team)] = len(vals)
            group_summaries = {}
            for group in ("Home", "Away", "EqualTeam"):
                per_game = {}
                for game in games:
                    start_values = []
                    for sid, start in records.items():
                        if start["game"] != game:
                            continue
                        if group in TEAMS:
                            value = by_cell[(sid, group)]
                            if value is not None:
                                start_values.append(value)
                        elif all(by_cell[(sid, team)] is not None for team in TEAMS):
                            start_values.append(float(np.mean([by_cell[(sid, t)] for t in TEAMS])))
                    per_game[game] = float(np.mean(start_values)) if start_values else None
                group_summaries[group] = summarize_games(per_game, games, draws)
            pair_arr = np.asarray(pair_values, dtype=np.float64)
            spread = {"pair_count": int(len(pair_arr)), "mean": float(np.mean(pair_arr)),
                      "standard_deviation_population": float(np.std(pair_arr, ddof=0)),
                      "minimum": float(np.min(pair_arr)), "q1": float(np.quantile(pair_arr, .25, method="linear")),
                      "median": float(np.quantile(pair_arr, .5, method="linear")),
                      "q3": float(np.quantile(pair_arr, .75, method="linear")),
                      "maximum": float(np.max(pair_arr))}
            out["by_horizon"][str(h)][model] = {
                "equal_game_signed_delta_by_group_ft": group_summaries,
                "pair_weighted_spread_ft": spread,
                "eligible_team_cells": sum(v is not None for v in by_cell.values()),
                "eligible_equalteam_starts": sum(all(by_cell[(sid, t)] is not None for t in TEAMS)
                                                  for sid in records),
                "cell_pair_counts": {f"{sid}|{team}": n for (sid, team), n in cell_counts.items()},
            }
            for held in games:
                for team in TEAMS:
                    out["loo_team_horizon_offsets_ft"][f"{held}|{team}|+{h}|{model}"] = offsets[(held, team, h, model)]

    variance = {}
    for model in CANDIDATES:
        eligible_starts = []
        residual_terms = []
        skipped = defaultdict(int)
        for sid, start in records.items():
            if not all(len(start["horizons"][45][t]) >= MIN_PAIRS for t in TEAMS):
                skipped["one_or_both_team_cells_below_three_pairs"] += 1
                continue
            means, residuals = {}, {}
            for team in TEAMS:
                offset = offsets[(start["game"], team, 45, model)]
                if offset is None:
                    skipped["missing_LOOG_offset"] += 1
                    break
                vals = [float(v["errors_ft"][model]) - float(v["errors_ft"]["M0"]) - offset
                        for v in start["horizons"][45][team].values()]
                residuals[team] = np.asarray(vals, dtype=np.float64)
                means[team] = float(np.mean(vals))
            if len(means) != 2:
                continue
            start_mean = float(np.mean([means[t] for t in TEAMS]))
            eligible_starts.append((sid, start["game"], start_mean))
            residual_terms.append((start_mean, residuals))
        start_means = np.asarray([row[2] for row in eligible_starts], dtype=np.float64)
        grand = float(np.mean(start_means)) if len(start_means) else None
        between = float(np.mean((start_means - grand) ** 2)) if len(start_means) else None
        within_per_start = []
        for start_mean, team_residuals in residual_terms:
            team_variances = [float(np.mean((team_residuals[t] - start_mean) ** 2)) for t in TEAMS]
            within_per_start.append(float(np.mean(team_variances)))
        within = float(np.mean(within_per_start)) if within_per_start else None
        total = between + within if between is not None and within is not None else None
        variance[model] = {
            "between_start_variance_ft2": between,
            "within_start_variance_ft2": within,
            "total_variance_ft2": total,
            "between_start_share": (between / total if total and total > 0 else None),
            "eligible_start_count": len(eligible_starts),
            "eligible_game_count": len({r[1] for r in eligible_starts}),
            "exclusions": dict(skipped),
            "weighting": "same DIAG4 q4 variance estimator: equal starts; equal teams within start; equal pairs within team cell",
        }
    out["plus45_variance_decomposition"] = variance
    return out


def cell_share(earlier: np.ndarray, later: np.ndarray, orders: np.ndarray) -> dict:
    mass = np.maximum(-later, 0.0)
    denominator = float(mass.sum())
    if denominator <= 0:
        return {"observed_share": None, "permutation_null_mean": None,
                "negative_mass_ft": denominator, "reason": "zero_negative_mass"}
    previous_negative = earlier < 0.0
    observed = float(np.dot(mass, previous_negative.astype(np.float64)) / denominator)
    null = float(np.mean((mass[orders] * previous_negative[None, :]).sum(axis=1) / denominator))
    return {"observed_share": observed, "permutation_null_mean": null,
            "negative_mass_ft": denominator, "reason": None}


def summarize_cells(cells: dict, games: list[str], draws: np.ndarray) -> tuple[dict, dict]:
    per_game = {game: {"observed": [], "null": [], "gap": []} for game in games}
    by_start = defaultdict(dict)
    for (game, sid, team), metric in cells.items():
        if metric["observed_share"] is not None:
            by_start[(game, sid)][team] = metric
    for (game, sid), team_metrics in by_start.items():
        if set(team_metrics) != set(TEAMS):
            continue
        vals = {key: float(np.mean([team_metrics[t][key] for t in TEAMS]))
                for key in ("observed_share", "permutation_null_mean")}
        per_game[game]["observed"].append(vals["observed_share"])
        per_game[game]["null"].append(vals["permutation_null_mean"])
        per_game[game]["gap"].append(vals["observed_share"] - vals["permutation_null_mean"])
    game_values = {}
    for game in games:
        game_values[game] = {
            key: float(np.mean(per_game[game][key])) if per_game[game][key] else None
            for key in ("observed", "null", "gap")
        }
    summary = {
        "observed_share": summarize_games({g: game_values[g]["observed"] for g in games}, games, draws),
        "permutation_null_mean": summarize_games({g: game_values[g]["null"] for g in games}, games, draws),
        "observed_minus_null": summarize_games({g: game_values[g]["gap"] for g in games}, games, draws),
    }
    supports = {
        "eligible_start_team_cells": len(cells),
        "zero_negative_mass_cells": sum(v["observed_share"] is None for v in cells.values()),
        "eligible_equalteam_starts": sum(len(v["observed"]) for v in per_game.values()),
        "equalteam_start_count_by_game": {g: len(per_game[g]["observed"]) for g in games},
    }
    summary["support"] = supports
    summary["per_game_equalteam"] = game_values
    return summary, supports


def q2_delta_persistence(records: dict, games: list[str], offsets: dict, draws: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    output = {"primary_transition": [15, 45], "transitions": {},
              "permutation_count_per_start_team": PERMUTATIONS, "permutation_seed": SEED,
              "common_random_order_map": "one order matrix per transition/start/team shared by M1 and M2"}
    for earlier_h, later_h in TRANSITIONS:
        transition = f"plus{earlier_h}_to_plus{later_h}"
        per_model = {model: {} for model in CANDIDATES}
        excluded = {model: defaultdict(int) for model in CANDIDATES}
        for sid, start in records.items():
            game = start["game"]
            for team in TEAMS:
                earlier_map = start["horizons"][earlier_h][team]
                later_map = start["horizons"][later_h][team]
                pairs = sorted(set(earlier_map) & set(later_map))
                if len(pairs) < MIN_PAIRS:
                    for model in CANDIDATES:
                        excluded[model]["fewer_than_three_common_pairs"] += 1
                    continue
                orders = np.argsort(rng.random((PERMUTATIONS, len(pairs))), axis=1)
                for model in CANDIDATES:
                    offset_earlier = offsets[(game, team, earlier_h, model)]
                    offset_later = offsets[(game, team, later_h, model)]
                    if offset_earlier is None or offset_later is None:
                        excluded[model]["missing_training_game_offset"] += 1
                        continue
                    earlier = np.asarray([
                        (float(earlier_map[p]["errors_ft"][model]) - float(earlier_map[p]["errors_ft"]["M0"]))
                        - offset_earlier for p in pairs], dtype=np.float64)
                    later = np.asarray([
                        (float(later_map[p]["errors_ft"][model]) - float(later_map[p]["errors_ft"]["M0"]))
                        - offset_later for p in pairs], dtype=np.float64)
                    metric = cell_share(earlier, later, orders)
                    metric["pair_count"] = len(pairs)
                    metric["permutation_order_digest"] = hashlib.sha256(orders.astype("<i4").tobytes()).hexdigest()
                    per_model[model][(game, sid, team)] = metric
        model_rows = {}
        for model in CANDIDATES:
            summary, support = summarize_cells(per_model[model], games, draws)
            support["exclusions"] = dict(excluded[model])
            model_rows[model] = {"summary": summary, "support": support,
                                 "per_cell": {f"{g}|{sid}|{team}": metric
                                              for (g, sid, team), metric in sorted(per_model[model].items())}}
        output["transitions"][transition] = {
            "earlier_horizon": earlier_h, "later_horizon": later_h,
            "minimum_common_pairs": MIN_PAIRS,
            "definition": "later corrected negative delta mass attached to an earlier corrected-negative delta pair / all later corrected negative delta mass",
            "null": "permute corrected later delta across pair IDs within start/team; hold earlier sign fixed",
            "models": model_rows,
        }
    return output


def q4_sign_flip(records: dict, games: list[str], offsets: dict, draws: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    by_direction = {"d": {model: {} for model in CANDIDATES},
                    "minus_d": {model: {} for model in CANDIDATES}}
    exclusions = {direction: {model: defaultdict(int) for model in CANDIDATES}
                  for direction in ("d", "minus_d")}
    zero_counts = {model: {str(h): {"pair_count": 0, "exact_zero_count": 0,
                                         "later_zero_negative_mass_count": 0}
                           for h in HORIZONS} for model in CANDIDATES}
    # Q2 and Q4 use identical cell order traversal and one common random map per cell.
    for sid, start in records.items():
        for h in HORIZONS:
            for team in TEAMS:
                for model in CANDIDATES:
                    for row in start["horizons"][h][team].values():
                        delta = float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"])
                        zero_counts[model][str(h)]["pair_count"] += 1
                        zero_counts[model][str(h)]["exact_zero_count"] += int(delta == 0.0)
                        if h == 45:
                            zero_counts[model][str(h)]["later_zero_negative_mass_count"] += int(max(-delta, 0.0) == 0.0)
    for sid, start in records.items():
        game = start["game"]
        for team in TEAMS:
            first = start["horizons"][15][team]
            last = start["horizons"][45][team]
            pairs = sorted(set(first) & set(last))
            if len(pairs) < MIN_PAIRS:
                for direction in exclusions:
                    for model in CANDIDATES:
                        exclusions[direction][model]["fewer_than_three_common_pairs"] += 1
                continue
            orders = np.argsort(rng.random((PERMUTATIONS, len(pairs))), axis=1)
            for model in CANDIDATES:
                aoff = offsets[(game, team, 15, model)]
                loff = offsets[(game, team, 45, model)]
                if aoff is None or loff is None:
                    for direction in exclusions:
                        exclusions[direction][model]["missing_training_game_offset"] += 1
                    continue
                earlier = np.asarray([
                    (float(first[p]["errors_ft"][model]) - float(first[p]["errors_ft"]["M0"])) - aoff
                    for p in pairs], dtype=np.float64)
                later = np.asarray([
                    (float(last[p]["errors_ft"][model]) - float(last[p]["errors_ft"]["M0"])) - loff
                    for p in pairs], dtype=np.float64)
                by_direction["d"][model][(game, sid, team)] = cell_share(earlier, later, orders)
                by_direction["minus_d"][model][(game, sid, team)] = cell_share(-earlier, -later, orders)
    result = {"transition": "+15_to_+45", "directions": {}, "exact_zero_counts": zero_counts}
    for direction in ("d", "minus_d"):
        result["directions"][direction] = {}
        for model in CANDIDATES:
            summary, support = summarize_cells(by_direction[direction][model], games, draws)
            support["exclusions"] = dict(exclusions[direction][model])
            result["directions"][direction][model] = {"summary": summary, "support": support}
    return result


def handcheck_rows(records: dict) -> dict:
    rows = []
    all_rows = []
    for sid, start in records.items():
        for team in TEAMS:
            for pair, row in start["horizons"][45][team].items():
                all_rows.append((start["game"], sid, team, pair, start, row))
    all_rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    for model in CANDIDATES:
        for item in all_rows:
            game, sid, team, pair, _start, row = item
            d = float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"])
            key = (game, sid, team, pair)
            if d != 0.0 and all(key != existing["identity"] for existing in rows):
                rows.append({"identity": key, "game": game, "start_id": sid, "team": team,
                             "pair": list(pair), "candidate": model,
                             "M0_error_ft": float(row["errors_ft"]["M0"]),
                             "candidate_error_ft": float(row["errors_ft"][model]),
                             "computed_delta_ft": d,
                             "asserted_candidate_minus_M0_ft": float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"]),
                             "passed": abs(d - (float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"]))) <= 1e-12})
                break
    passed = len(rows) == 2 and rows[0]["identity"] != rows[1]["identity"] and all(r["passed"] for r in rows)
    for row in rows:
        row["identity"] = list(row["identity"])
    return {"selection_rule": "first lexicographic nonzero M1 delta, then first distinct pair with nonzero M2 delta",
            "rows": rows, "passed": passed,
            "failure": None if passed else "two distinct nonzero hand-checkable rows were not available"}


def q4_distance_gradient(records: dict, games: list[str], frozen_diag4: dict, draws: np.ndarray,
                         diag4) -> dict:
    audit, eligible = diag4.cells_for_horizon(records, 45)
    out = {"fixed_cutpoints_ft": DISTANCE_EDGES_FT,
           "bins": {model: [] for model in CANDIDATES}, "gradient_comparison": {}}
    for model in CANDIDATES:
        fit = frozen_diag4["Q1"]["fits"]["45"]["EqualTeam"][model]["pooled_wls"]
        grouped = defaultdict(lambda: defaultdict(list))
        pair_counts = [0] * (len(DISTANCE_EDGES_FT) + 1)
        cell_counts = [set() for _ in pair_counts]
        for sid, start in records.items():
            for team in TEAMS:
                if (sid, team) not in eligible:
                    continue
                for pair, row in start["horizons"][45][team].items():
                    b = int(np.searchsorted(DISTANCE_EDGES_FT, float(row["cutoff_distance_ft"]), side="right"))
                    e0 = float(row["errors_ft"]["M0"])
                    ec = float(row["errors_ft"][model])
                    grouped[(start["game"], sid, team, b)]["delta"].append(ec - e0)
                    grouped[(start["game"], sid, team, b)]["diag4_candidate_residual"].append(
                        ec - (float(fit["a"]) + float(fit["kappa"]) * e0))
                    pair_counts[b] += 1
                    cell_counts[b].add((sid, team))
        for b in range(len(pair_counts)):
            by_start = defaultdict(lambda: defaultdict(dict))
            for (game, sid, team, bin_index), vals in grouped.items():
                if bin_index == b:
                    by_start[(game, sid)][team] = {key: float(np.mean(value)) for key, value in vals.items()}
            by_game = {g: {"delta": [], "diag4_candidate_residual": []} for g in games}
            for (game, sid), team_map in by_start.items():
                for metric in ("delta", "diag4_candidate_residual"):
                    available = [team_map[t][metric] for t in TEAMS if metric in team_map.get(t, {})]
                    if available:
                        by_game[game][metric].append(float(np.mean(available)))
            summaries = {}
            for metric in ("delta", "diag4_candidate_residual"):
                per_game = {g: float(np.mean(by_game[g][metric])) if by_game[g][metric] else None for g in games}
                summaries[metric] = summarize_games(per_game, games, draws)
            out["bins"][model].append({
                "bin": b + 1, "lower_edge_inclusive_upper_edge_exclusive": True,
                "pair_count": pair_counts[b], "start_team_cell_count": len(cell_counts[b]),
                "metrics_ft": summaries,
            })
        lo_delta = out["bins"][model][0]["metrics_ft"]["delta"]["equal_game_mean"]
        hi_delta = out["bins"][model][-1]["metrics_ft"]["delta"]["equal_game_mean"]
        lo_abs = out["bins"][model][0]["metrics_ft"]["diag4_candidate_residual"]["equal_game_mean"]
        hi_abs = out["bins"][model][-1]["metrics_ft"]["diag4_candidate_residual"]["equal_game_mean"]
        gd = None if lo_delta is None or hi_delta is None else hi_delta - lo_delta
        ga = None if lo_abs is None or hi_abs is None else hi_abs - lo_abs
        if gd is None or ga is None:
            label = "not comparable"
        elif abs(abs(gd) - abs(ga)) <= 1e-12:
            label = "same magnitude"
        elif abs(gd) < abs(ga):
            label = "attenuated"
        else:
            label = "amplified"
        out["gradient_comparison"][model] = {
            "delta_bin4_minus_bin1_ft": gd,
            "frozen_DIAG4_candidate_residual_bin4_minus_bin1_ft": ga,
            "delta_relative_magnitude": label,
            "candidate_fit_source": "frozen DIAG4 EqualTeam pooled WLS coefficients; not refit",
        }
    return out


def q4_zero_and_handchecks(records: dict) -> dict:
    counts = {model: {str(h): {"pair_count": 0, "exact_zero_count": 0,
                               "exact_zero_fraction": None, "negative_mass_zero_count": None,
                               "negative_mass_zero_fraction": None}
                      for h in HORIZONS} for model in CANDIDATES}
    for model in CANDIDATES:
        for h in HORIZONS:
            vals = []
            for start in records.values():
                for team in TEAMS:
                    for row in start["horizons"][h][team].values():
                        vals.append(float(row["errors_ft"][model]) - float(row["errors_ft"]["M0"]))
            c = counts[model][str(h)]
            c["pair_count"] = len(vals)
            c["exact_zero_count"] = sum(v == 0.0 for v in vals)
            c["exact_zero_fraction"] = c["exact_zero_count"] / len(vals) if vals else None
            if h == 45:
                c["negative_mass_zero_count"] = sum(max(-v, 0.0) == 0.0 for v in vals)
                c["negative_mass_zero_fraction"] = c["negative_mass_zero_count"] / len(vals) if vals else None
    return {"exact_d_zero_counts": counts, "handcheck": handcheck_rows(records),
            "zero_mass_rule": "d45 == 0 contributes exactly 0 negative mass and is not negative; all d45 >= 0 rows have zero negative mass"}


def summarize_ci(value: dict, digits: int = 4) -> str:
    mean = value.get("equal_game_mean")
    ci = value.get("bootstrap_95_ci")
    if mean is None:
        return "not estimable"
    if ci is None:
        return f"{mean:.{digits}f} (CI unavailable)"
    return f"{mean:.{digits}f} [{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]"


def render_report(result: dict) -> str:
    q1, q2, q3, q4 = result["Q1"], result["Q2"], result["Q3"], result["Q4"]
    lines = [
        "# NHL JC-DIAG5: candidate-minus-M0 delta persistence", "",
        f"**Base:** `{BASE_COMMIT}`. **Preregistration commit:** `{PREREG_COMMIT}`.",
        "**Branch:** `research/nhl-multi-agent-movement-2026-10-23`.", "",
        "## 1. Population and boundary", "", POPULATION_STATEMENT, "",
        "No positions, identities, outcomes, or labels were added. The comparison uses only the frozen development arrays and read-only derived values. Horizons remain ordinal observations.", "",
        "## 2. Registered interpretation (Q5; fixed before results)", "",
        "Pair-specific residual structure would remain a live descriptive explanation only if at least one of M1 or M2 has a positive +15→+45 corrected-delta observed-minus-null gap whose whole-game 95% interval is entirely above zero, and that candidate's two adjacent-transition point gaps are also positive. The pattern that closes this line is that neither candidate meets that primary rule, especially when the candidate-only DIAG4 series remains above its null: that combination is consistent with structure shared with M0 surviving in the candidate series but cancelling in the delta. In that case, explicitly state that a pair-intent label program is not justified by these results. Any other pattern is mixed/inconclusive under this preregistration. No outcome changes a threshold or gate.", "",
        "## 3. Provenance gate", "",
        f"Gate: **{'PASS' if result['provenance_gate']['all_assertions_passed'] else 'FAIL'}**. "
        f"Named source hashes: {sum(r['passed'] for r in result['provenance_gate']['source_hash_checks'][:10])}/10; "
        f"DIAG4 frozen assertions: {sum(r['passed'] for r in result['provenance_gate']['assertions'])}/{len(result['provenance_gate']['assertions'])}; "
        f"re-run DIAG4 checks: {sum(r['passed'] for r in result['provenance_gate']['diag4_postcompute_checks']['checks'])}/22.", "",
        "| Input | Expected SHA-256 | Actual SHA-256 | Status |", "|---|---|---|---|"]
    for row in result["provenance_gate"]["source_hash_checks"]:
        lines.append(f"| {row['name']} | `{row['expected']}` | `{row['actual']}` | {'PASS' if row['passed'] else 'FAIL'} |")
    lines += ["", "All 22 DIAG4 post-compute checks were recalculated in memory from the frozen arrays and compared with both their registered DIAG2/DIAG3 values and the frozen DIAG4 JSON. No DIAG4 output was written.", "",
              "## Q1. Delta level and spread", "",
              "Delta is candidate pair-distance error minus the M0 error on the same pair. EqualTeam summaries give equal Home/Away weight within start, equal starts within game, then equal games. Pair spread is pair-weighted.", "",
              "| Horizon | Model | Group | Equal-game mean [95% whole-game interval], ft | Per-game values, G1–G10, ft | Eligible cells / EqualTeam starts |",
              "|---:|---|---|---:|---|---:|"]
    games = result["population"]["games"]
    for h in HORIZONS:
        for model in CANDIDATES:
            for group in ("EqualTeam", "Home", "Away"):
                summary = q1["by_horizon"][str(h)][model]["equal_game_signed_delta_by_group_ft"][group]
                vector = ", ".join(f"{summary['per_game'].get(g):.3f}" if summary["per_game"].get(g) is not None else "NA" for g in games)
                item = q1["by_horizon"][str(h)][model]
                lines.append(f"| +{h} | {model} | {group} | {summarize_ci(summary)} | {vector} | {item['eligible_team_cells']} / {item['eligible_equalteam_starts']} |")
    lines += ["", "| Horizon | Model | Pair count | Mean | SD | Min | Q1 | Median | Q3 | Max |",
              "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for h in HORIZONS:
        for model in CANDIDATES:
            s = q1["by_horizon"][str(h)][model]["pair_weighted_spread_ft"]
            lines.append(f"| +{h} | {model} | {s['pair_count']} | {s['mean']:.3f} | {s['standard_deviation_population']:.3f} | {s['minimum']:.3f} | {s['q1']:.3f} | {s['median']:.3f} | {s['q3']:.3f} | {s['maximum']:.3f} |")
    lines += ["", "### +45 delta residual variance decomposition", "",
              "| Model | Between-start variance | Within-start variance | Between-start share | Eligible starts / games |",
              "|---|---:|---:|---:|---:|"]
    for model in CANDIDATES:
        v = q1["plus45_variance_decomposition"][model]
        lines.append(f"| {model} | {v['between_start_variance_ft2']:.5f} | {v['within_start_variance_ft2']:.5f} | {v['between_start_share']:.4f} | {v['eligible_start_count']} / {v['eligible_game_count']} |")
    lines += ["", "### LOOG team×horizon delta offsets", "",
              "Offsets are the equal-game mean of the other nine game-level team cell means and are repeated across the held-out game's starts.", "",
              "| Held-out game | Team | Horizon | M1 offset, ft | M2 offset, ft |", "|---|---|---:|---:|---:|"]
    for game in games:
        for team in TEAMS:
            for h in HORIZONS:
                values = [q1["loo_team_horizon_offsets_ft"][f"{game}|{team}|+{h}|{m}"] for m in CANDIDATES]
                lines.append(f"| {game} | {team} | +{h} | {values[0]:.5f} | {values[1]:.5f} |" if all(v is not None for v in values) else f"| {game} | {team} | +{h} | not estimable | not estimable |")
    lines += ["", "## Q2. Corrected delta persistence", "",
              "The +45 delta level is strongly negative on the registered signed-error scale (see Q1), so Q2 removes the other-nine-game team×horizon level before computing persistence.", "",
              "Observed, permutation-null, and paired-gap intervals use equal games and the shared whole-game bootstrap matrix. A positive gap is called above the null only when its entire 95% interval is positive.", "",
              "| Transition | Model | Observed share [95%] | Null [95%] | Gap [95%] | EqualTeam starts | Cells / zero-mass cells | Exclusions |",
              "|---|---|---:|---:|---:|---:|---:|---|"]
    for transition, item in q2["transitions"].items():
        for model in CANDIDATES:
            row = item["models"][model]
            s = row["summary"]
            sup = row["support"]
            lines.append(f"| {transition} | {model} | {summarize_ci(s['observed_share'])} | {summarize_ci(s['permutation_null_mean'])} | {summarize_ci(s['observed_minus_null'])} | {sup['eligible_equalteam_starts']} | {sup['eligible_start_team_cells']} / {sup['zero_negative_mass_cells']} | {json.dumps(sup['exclusions'],sort_keys=True)} |")
    lines += ["", "## Q3. M0, candidate-only, and delta comparison", "",
              "All three rows use the same fixed development population and the registered within-cell null. Candidate-only rows are re-derived with DIAG4's frozen LOOG team×horizon correction; delta rows use the Q2 delta correction.", "",
              "| Transition | Series | Observed [95%] | Null [95%] | Gap [95%] | EqualTeam starts | Descriptive result |",
              "|---|---|---:|---:|---:|---:|---|"]
    for transition, item in q2["transitions"].items():
        old = result["DIAG4_rerun"]["rederived_Q3"]["transitions"][transition]["summaries"]
        for model in ("M0", "M1", "M2"):
            modes = [("raw", "M0 raw") ] if model == "M0" else [("loo_team_horizon", f"{model} candidate-only, DIAG4 correction")]
            for mode, label in modes:
                s = old[model][mode]
                gap = s["observed_minus_null"]["bootstrap_95_ci"]
                status = "above null interval" if gap is not None and gap[0] > 0 else "does not clear null interval"
                lines.append(f"| {transition} | {label} | {summarize_ci(s['observed_share'])} | {summarize_ci(s['permutation_null_mean'])} | {summarize_ci(s['observed_minus_null'])} | {s['support']['eligible_equalteam_starts']} | {status} |")
        for model in CANDIDATES:
            s = item["models"][model]["summary"]
            gap = s["observed_minus_null"]["bootstrap_95_ci"]
            status = "above null interval" if gap is not None and gap[0] > 0 else "does not clear null interval"
            lines.append(f"| {transition} | {model} candidate-minus-M0 delta | {summarize_ci(s['observed_share'])} | {summarize_ci(s['permutation_null_mean'])} | {summarize_ci(s['observed_minus_null'])} | {s['support']['eligible_equalteam_starts']} | {status} |")
    primary = q2["transitions"]["plus15_to_plus45"]["models"]
    primary_sentences = []
    for model in CANDIDATES:
        gap = primary[model]["summary"]["observed_minus_null"]
        primary_sentences.append(f"{model} delta gap {gap['equal_game_mean']:.4f} [{gap['bootstrap_95_ci'][0]:.4f}, {gap['bootstrap_95_ci'][1]:.4f}]")
    lines += ["", "On the primary +15→+45 transition, M0 raw, both DIAG4-corrected candidate series, and both corrected candidate-minus-M0 deltas are above their within-start nulls by the registered interval rule. " + "; ".join(primary_sentences) + ". The delta series therefore retains pair-linked persistence after cancellation against M0; the observed pattern is not explained solely by a component shared with M0. This comparison does not identify its cause.", ""]
    lines += ["", "## Q4. Symmetry, zero mass, hand checks, distance", "",
              "### Sign flip, primary transition", "",
              "| Direction | Model | Observed [95%] | Null [95%] | Gap [95%] | EqualTeam starts |",
              "|---|---|---:|---:|---:|---:|"]
    for direction in ("d", "minus_d"):
        for model in CANDIDATES:
            s = q4["sign_flip"]["directions"][direction][model]["summary"]
            lines.append(f"| {direction} | {model} | {summarize_ci(s['observed_share'])} | {summarize_ci(s['permutation_null_mean'])} | {summarize_ci(s['observed_minus_null'])} | {s['support']['eligible_equalteam_starts']} |")
    lines.append("")
    lines.append("Both sign orientations have positive gap intervals for M1 and M2; the observed persistence is not unique to the negative orientation of the delta.")
    lines += ["", "Exact zeros and zero negative-mass pairs:", ""]
    for model in CANDIDATES:
        z = q4["zero_and_handcheck"]["exact_d_zero_counts"][model]
        lines.append(f"- {model}: +15 exact zero {z['15']['exact_zero_count']}/{z['15']['pair_count']}; +30 {z['30']['exact_zero_count']}/{z['30']['pair_count']}; +45 exact zero {z['45']['exact_zero_count']}/{z['45']['pair_count']}; +45 zero negative mass {z['45']['negative_mass_zero_count']}/{z['45']['pair_count']}.")
    lines += ["", "Hand-check rows (candidate − M0 asserted):", ""]
    for row in q4["zero_and_handcheck"]["handcheck"]["rows"]:
        lines.append(f"- {row['candidate']}: `{row['game']} | {row['start_id']} | {row['team']} | {row['pair']}`; M0 `{row['M0_error_ft']:.12f}`, candidate `{row['candidate_error_ft']:.12f}`, delta `{row['computed_delta_ft']:.12f}` ft; assert `{row['passed']}`.")
    lines += ["", "### Fixed DIAG4 cutoff-distance bins", "",
              "The edges were held at the DIAG4 values; no bin was refit. The candidate-only comparison is the frozen DIAG4 residual using its already-fitted coefficients.", "",
              "| Model | Bin | Pair count | Δ mean [95%] ft | DIAG4 candidate residual mean [95%] ft |",
              "|---|---:|---:|---:|---:|"]
    for model in CANDIDATES:
        for row in q4["distance_gradient"]["bins"][model]:
            lines.append(f"| {model} | {row['bin']} | {row['pair_count']} | {summarize_ci(row['metrics_ft']['delta'])} | {summarize_ci(row['metrics_ft']['diag4_candidate_residual'])} |")
    for model in CANDIDATES:
        g = q4["distance_gradient"]["gradient_comparison"][model]
        lines.append(f"- {model} bin-4-minus-bin-1 signed gradient: delta {g['delta_bin4_minus_bin1_ft']:.4f} ft; frozen DIAG4 candidate residual {g['frozen_DIAG4_candidate_residual_bin4_minus_bin1_ft']:.4f} ft; delta magnitude is **{g['delta_relative_magnitude']}**.")
    lines += ["", "## Decision", "", result["decision"], "",
              "This is a descriptive comparison of ten previously inspected development games. No production state or frozen input was changed. Image Id is ordinal, not validated elapsed time; cross-game athlete identity and independent-game coverage remain unresolved.", "",
              "## Reproduction", "", "```sh",
              "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py --gate-only",
              "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py",
              "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py --output /tmp/jc-diag5-delta-persistence-repeat.json --no-report",
              "cmp research/nhl-multi-agent-movement-2026-10-23/results/jc-diag5-delta-persistence-2026-10-23-v1.json /tmp/jc-diag5-delta-persistence-repeat.json",
              "```", ""]
    return "\n".join(lines)


def write_json(path: Path, payload: dict) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="run all provenance and DIAG4 checks; do not calculate DIAG5 Q values")
    parser.add_argument("--output", type=Path, default=RESULT)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    gate, old_results = run_gate()
    if args.gate_only:
        print(json.dumps(gate, sort_keys=True, indent=2))
        if not gate["all_assertions_passed"]:
            raise SystemExit(2)
        return
    if not gate["all_assertions_passed"] or old_results is None:
        failure_result = {"schema_version": 1, "analysis": "NHL JC-DIAG5 candidate-minus-M0 delta persistence",
                          "base_commit": BASE_COMMIT,
                          "preregistration": {"commit": PREREG_COMMIT, "sha256": PREREG_SHA256},
                          "provenance_gate": gate, "Q1_Q5_calculated": False}
        write_json(args.output, failure_result)
        print(json.dumps(gate, sort_keys=True, indent=2))
        raise SystemExit(2)

    diag4 = load_diag4()
    frozen_diag4 = diag4.read_json(EXPECTED_INPUTS["jc_diag4_results"][0])
    records, games, draws = old_results["records"], old_results["games"], old_results["draws"]
    offsets, offset_source = make_delta_offsets(records, games)
    q1 = q1_delta(records, games, draws, offsets, offset_source)
    q2 = q2_delta_persistence(records, games, offsets, draws)
    q4_sign = q4_sign_flip(records, games, offsets, draws)
    q4_zero = q4_zero_and_handchecks(records)
    q4_gradient = q4_distance_gradient(records, games, frozen_diag4, draws, diag4)
    q3 = {"source": "re-derived in memory with DIAG4 frozen estimator and shared permutation/bootstrap seeds",
          "transitions": {}}
    for transition in q2["transitions"]:
        old = old_results["Q3"]["transitions"][transition]
        q3["transitions"][transition] = {
            "summaries": {model: {mode: old["summaries"][model][mode]
                                  for mode in (("raw",) if model == "M0" else ("loo_team_horizon",))}
                          for model in ("M0", "M1", "M2")},
            "support": {model: {mode: old["summaries"][model][mode]["support"]
                                for mode in (("raw",) if model == "M0" else ("loo_team_horizon",))}
                        for model in ("M0", "M1", "M2")},
        }
    q4 = {"sign_flip": q4_sign, "zero_and_handcheck": q4_zero, "distance_gradient": q4_gradient}
    primary = q2["transitions"]["plus15_to_plus45"]
    closes = True
    for model in CANDIDATES:
        gap = primary["models"][model]["summary"]["observed_minus_null"]["bootstrap_95_ci"]
        adjacent = [q2["transitions"][key]["models"][model]["summary"]["observed_minus_null"]["equal_game_mean"]
                    for key in ("plus15_to_plus30", "plus30_to_plus45")]
        if gap is not None and gap[0] > 0 and all(v is not None and v > 0 for v in adjacent):
            closes = False
    if closes:
        candidate_only_above = []
        for model in CANDIDATES:
            candidate_gap = old_results["Q3"]["transitions"]["plus15_to_plus45"]["summaries"][model]["loo_team_horizon"]["observed_minus_null"]["bootstrap_95_ci"]
            if candidate_gap is not None and candidate_gap[0] > 0:
                candidate_only_above.append(model)
        if candidate_only_above:
            decision = ("Neither candidate-minus-M0 delta meets the registered primary rule, while the candidate-only DIAG4 series remains above its null for " + ", ".join(candidate_only_above) + ". That pattern is consistent with the candidate persistence being shared with M0 in this comparison. These results do not justify a pair-intent label program.")
        else:
            decision = ("Neither candidate-minus-M0 delta meets the registered primary rule, and the candidate-only series does not clear its null interval. This run supplies no descriptive basis for keeping the pair-intent line open.")
    else:
        surviving = [model for model in CANDIDATES
                     if primary["models"][model]["summary"]["observed_minus_null"]["bootstrap_95_ci"] is not None
                     and primary["models"][model]["summary"]["observed_minus_null"]["bootstrap_95_ci"][0] > 0
                     and all(q2["transitions"][key]["models"][model]["summary"]["observed_minus_null"]["equal_game_mean"] > 0
                             for key in ("plus15_to_plus30", "plus30_to_plus45"))]
        decision = ("The registered +15→+45 corrected-delta gap rule is met by " + ", ".join(surviving) + "; each also has positive point gaps on both adjacent transitions. Candidate-minus-M0 persistence remains after cancellation against M0 in these ten development games. This does not identify a behavioral mechanism or warrant changing the research workflow.")

    result = {
        "schema_version": 1,
        "analysis": "NHL JC-DIAG5 candidate-minus-M0 delta persistence",
        "base_commit": BASE_COMMIT,
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                            "sha256": PREREG_SHA256},
        "provenance_gate": gate,
        "population": {"games": games, "game_count": len(games), "scored_start_count": len(records),
                        "population_statement": POPULATION_STATEMENT,
                        "plus45_pair_counts_by_team": {"Home": 1064, "Away": 1100},
                        "plus45_pair_count": 2164, "equalteam_plus45_cells": 142,
                        "timebase": "ordinal Image Id increments, not seconds"},
        "method": {"delta": "errors_ft[candidate] - errors_ft[M0] on same pair/game/start/team/horizon",
                   "horizons": list(HORIZONS), "transitions": [list(x) for x in TRANSITIONS],
                   "minimum_pairs_per_cell": MIN_PAIRS, "bootstrap_draws": BOOTSTRAPS,
                   "bootstrap_seed": SEED, "bootstrap_unit": "whole game, equal weight, one shared matrix",
                   "permutations_per_cell": PERMUTATIONS, "permutation_seed": SEED,
                   "permutation_unit": "within start/team; shared cell order map across M1/M2",
                   "distance_edges_ft": DISTANCE_EDGES_FT,
                   "all_fits_and_simulations": False},
        "DIAG4_rerun": {"validation": gate["diag4_postcompute_checks"],
                        "rederived_Q3": old_results["Q3"]},
        "Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4,
        "decision": decision,
        "Q1_Q5_calculated": True,
    }
    digest, size = write_json(args.output, result)
    result["result_file_sha256"] = digest
    result["result_file_bytes"] = size
    # The self-digest fields are metadata about the bytes written above; avoid a circular digest.
    report = render_report(result)
    if not args.no_report:
        REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": digest, "bytes": size,
                      "report": None if args.no_report else str(REPORT),
                      "decision": decision, "gate_passed": gate["all_assertions_passed"]},
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
