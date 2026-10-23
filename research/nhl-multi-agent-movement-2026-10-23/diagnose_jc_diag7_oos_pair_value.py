#!/usr/bin/python3
"""Run preregistered NHL JC-DIAG7 out-of-sample pair-value analysis."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research/nhl-multi-agent-movement-2026-10-23"
RESULTS = RESEARCH / "results"
PREREG = ROOT / "docs/research/NHL-JC-DIAG7-PREREG-2026-10-23.md"
REPORT = ROOT / "docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md"
DEFAULT_OUTPUT = RESULTS / "jc-diag7-oos-pair-value-2026-10-23-v1.json"
DIAG6_JSON = RESULTS / "jc-diag6-distance-conditioned-2026-10-23-v1.json"
DIAG6_REPORT = ROOT / "docs/research/NHL-JC-DIAG6-REPORT-2026-10-23.md"
DIAG6_EVALUATOR = RESEARCH / "diagnose_distance_conditioned_persistence.py"
DIAG6_PREREG = ROOT / "docs/research/NHL-JC-DIAG6-PREREG-2026-10-23.md"

SOURCE_BASE = "a7b50ffc3d597f8e7d89a5a23826e37b7107891a"
CORRECTION_COMMIT = "f7be2a19d3860ff17156c0c3d0de6d411424a782"
PREREG_COMMIT = "596089cb00cf6ed64f8d11fde319cfb8786a9a60"
PREREG_SHA256 = "e5644b1a65098ffa070cf81bbdd8e46978558358ca74696276936124823aab99"
DIAG6_JSON_SHA256 = "8dfe2f551727484e43c612c5e2ede85ce0d237f4f479edb89e7ad1e5e59c62ed"
DIAG6_REPORT_SHA256 = "cf72e2646e00a3da27ccff849f96e9e00cbb2f22bfd12433b4f9feba03d67e45"
DIAG6_EVALUATOR_SHA256 = "71e162ffa625fde1067413913d3a0ff9b63c1c64e657a24684efd73d289f1c37"
DIAG6_PREREG_SHA256 = "f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48"

SEED = 20261024
BOOTSTRAPS = 10_000
DISTANCE_MIN_TRAIN_PAIRS = 30
HORIZON = 45
TEAMS = ("Home", "Away")
CANDIDATES = ("M1", "M2")
MATERIALITY_BAR_PCT = 5.0
EXPECTED_DIAG6 = {
    "M1_Q1_gap": 0.3751768756918231,
    "M2_Q1_gap": 0.35885185351280086,
    "M1_Q2_retained_fraction": 0.8933858227557131,
    "M2_Q2_retained_fraction": 0.9442712649286923,
    "M1_Q3_raw_between_bin_share": 0.6102114758698477,
    "M2_Q3_raw_between_bin_share": 0.5921480205186526,
    "M1_Q3_rank_between_bin_share": 0.436971230453636,
    "M2_Q3_rank_between_bin_share": 0.44036099329465817,
    "M1_plus45_delta_sd_rounded": 3.0274,
    "M2_plus45_delta_sd_rounded": 3.0550,
}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_diag6_module():
    spec = importlib.util.spec_from_file_location("diag6_frozen", DIAG6_EVALUATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load pinned DIAG6 evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ancestor_check(commit: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def add_check(rows: list[dict], name: str, expected, actual, passed: bool) -> None:
    rows.append({"name": name, "expected": expected, "actual": actual, "passed": bool(passed)})


def reassert_diag6_values(diag6: dict) -> list[dict]:
    checks = []
    q1 = diag6["Q1"]["transitions"]["plus15_to_plus45"]["series"]
    q3 = diag6["Q3"]["series"]
    q2 = diag6["Q5"]["primary_retained_fractions"]
    for model in CANDIDATES:
        name = f"{model}_Q1_gap"
        actual = q1[f"{model}_delta_Q1_raw"]["conditioned"]["summaries"]["gap"]["equal_game_mean"]
        add_check(checks, name, EXPECTED_DIAG6[name], actual, actual == EXPECTED_DIAG6[name])
        name = f"{model}_Q2_retained_fraction"
        actual = q2[model]["equal_game_mean_ratio"]
        add_check(checks, name, EXPECTED_DIAG6[name], actual, actual == EXPECTED_DIAG6[name])
        name = f"{model}_Q3_raw_between_bin_share"
        actual = q3[f"{model}_delta"]["raw"]["between_bin_share"]["point"]
        add_check(checks, name, EXPECTED_DIAG6[name], actual, actual == EXPECTED_DIAG6[name])
        name = f"{model}_Q3_rank_between_bin_share"
        actual = q3[f"{model}_delta"]["within_cell_midranks"]["between_bin_share"]["point"]
        add_check(checks, name, EXPECTED_DIAG6[name], actual, actual == EXPECTED_DIAG6[name])
        name = f"{model}_plus45_delta_sd_rounded"
        actual = diag6["Q4"]["pair_spread"][f"{model}_delta_DIAG5"]["45"]["raw"]["sd_population"]
        add_check(checks, name, EXPECTED_DIAG6[name], round(actual, 4), round(actual, 4) == EXPECTED_DIAG6[name])
    pop = diag6["population"]
    checks.extend([
        {"name": "DIAG6_game_count", "expected": 10, "actual": pop["game_count"], "passed": pop["game_count"] == 10},
        {"name": "DIAG6_scored_starts", "expected": 172, "actual": pop["plus45_scored_start_count"], "passed": pop["plus45_scored_start_count"] == 172},
        {"name": "DIAG6_pair_count", "expected": 2164, "actual": pop["plus45_pair_count"], "passed": pop["plus45_pair_count"] == 2164},
        {"name": "DIAG6_EqualTeam_starts", "expected": 142, "actual": pop["plus45_equalteam_cells"], "passed": pop["plus45_equalteam_cells"] == 142},
        {"name": "DIAG6_eligible_team_cells", "expected": 311, "actual": pop["plus45_eligible_team_cells"], "passed": pop["plus45_eligible_team_cells"] == 311},
    ])
    raw = diag6["provenance_gate"]["raw_frame_support"]
    checks.append({"name": "raw_rollout_starts", "expected": 200,
                   "actual": raw["rollout_start_count"], "passed": raw["rollout_start_count"] == 200})
    return checks


def verify_gate(diag6_module) -> tuple[dict, dict | None]:
    pinned = {
        "diag6_result": (DIAG6_JSON, DIAG6_JSON_SHA256),
        "diag6_corrected_report": (DIAG6_REPORT, DIAG6_REPORT_SHA256),
        "diag6_evaluator": (DIAG6_EVALUATOR, DIAG6_EVALUATOR_SHA256),
        "diag6_preregistration": (DIAG6_PREREG, DIAG6_PREREG_SHA256),
        "diag7_preregistration": (PREREG, PREREG_SHA256),
    }
    hash_rows = []
    for name, (path, expected) in pinned.items():
        actual = sha256_file(path)
        hash_rows.append({"name": name, "path": display_path(path), "expected_sha256": expected,
                          "actual_sha256": actual, "missing": actual is None,
                          "passed": actual == expected})
    for name, (path, expected) in diag6_module.INPUTS.items():
        actual = sha256_file(path)
        hash_rows.append({"name": f"DIAG6_source:{name}", "path": display_path(path),
                          "expected_sha256": expected, "actual_sha256": actual,
                          "missing": actual is None, "passed": actual == expected})
    ancestry = {"source_base": ancestor_check(SOURCE_BASE),
                "correction_commit": ancestor_check(CORRECTION_COMMIT),
                "preregistration_commit": ancestor_check(PREREG_COMMIT)}
    gate = {
        "source_base": SOURCE_BASE,
        "correction_commit": CORRECTION_COMMIT,
        "preregistration_commit": PREREG_COMMIT,
        "preregistration_sha256": {"expected": PREREG_SHA256, "actual": sha256_file(PREREG)},
        "artifact_hashes": hash_rows,
        "artifact_hash_pass_count": f"{sum(r['passed'] for r in hash_rows)}/{len(hash_rows)}",
        "ancestry": ancestry,
        "diag6_value_assertions": [],
        "diag6_upstream_gate": None,
        "all_assertions_passed": False,
        "Q1_Q3_calculated": False,
    }
    if not all(r["passed"] for r in hash_rows) or not all(ancestry.values()):
        gate["failure"] = "missing/mismatched pinned artifact or commit ancestry; DIAG7 Q1-Q3 not run"
        return gate, None
    try:
        diag6_json = json.loads(DIAG6_JSON.read_text(encoding="utf-8"))
        value_checks = reassert_diag6_values(diag6_json)
        upstream_gate, data = diag6_module.run_gate()
        gate["diag6_value_assertions"] = value_checks
        gate["diag6_upstream_gate"] = upstream_gate
    except Exception as exc:
        gate["failure"] = f"DIAG6 provenance/value gate raised {type(exc).__name__}: {exc}; DIAG7 Q1-Q3 not run"
        return gate, None
    gate["all_assertions_passed"] = (
        all(r["passed"] for r in hash_rows)
        and all(ancestry.values())
        and all(r["passed"] for r in value_checks)
        and bool(upstream_gate.get("all_assertions_passed"))
    )
    if not gate["all_assertions_passed"]:
        gate["failure"] = "one or more pinned hashes, DIAG6 values, or inherited source checks failed; DIAG7 Q1-Q3 not run"
        return gate, None
    gate["pass_counts"] = {
        "pinned_artifact_hashes": gate["artifact_hash_pass_count"],
        "DIAG6_value_assertions": f"{sum(r['passed'] for r in value_checks)}/{len(value_checks)}",
        "DIAG6_source_hashes": upstream_gate["pass_counts"]["frozen_source_hashes"],
        "DIAG6_reassertions": upstream_gate["pass_counts"]["DIAG5_reassertions"],
    }
    return gate, data


def collect_rows(d6, diag6_json: dict, data: dict) -> tuple[list[dict], list[str], dict]:
    d4 = data["diag4"]
    records, games = d4.build_records(data["jc"], data["archive"], data["starts"], data["raw_support"])
    predictions = diag6_json["distance_predictions"]
    rows = []
    bin_counts = {str(i + 1): 0 for i in range(4)}
    bin_team_counts = {str(i + 1): {team: 0 for team in TEAMS} for i in range(4)}
    player_fields = set()
    for scenario in data["archive"]["scenarios"].values():
        for player in scenario["initial_state"]["players"]:
            player_fields.update(player)
    for sid, start in records.items():
        game, period = start["game"], start["period"]
        for team in TEAMS:
            for pair, observed in start["horizons"][HORIZON][team].items():
                b = d6.pair_bin(observed)
                lookup = f"{game}|{team}|+45|bin{b + 1}"
                delta = {model: float(observed["errors_ft"][model]) - float(observed["errors_ft"]["M0"])
                         for model in CANDIDATES}
                a_values = {}
                for model in CANDIDATES:
                    pred = predictions[f"{model}_delta_Q1_raw"].get(lookup)
                    if pred is None or not math.isfinite(float(pred)):
                        raise RuntimeError(f"missing frozen DIAG6 A prediction for {lookup}/{model}")
                    a_values[model] = float(pred)
                pair_ids = tuple(sorted(str(x) for x in pair))
                # Full source scope is retained; numeric track-ID collisions never join games/starts.
                identity_key = (game, str(period), sid, team, pair_ids)
                # The prereg permits game-scoped repeated pairs for the generic training-only
                # variance components. This key is never used to match a held-out identity.
                variance_group_key = (game, str(period), team, pair_ids)
                rows.append({"game": game, "period": str(period), "start_id": sid,
                             "team": team, "pair_ids": list(pair_ids),
                             "identity_key": identity_key, "variance_group_key": variance_group_key,
                             "distance_bin": b,
                             "delta": delta, "A": a_values})
                bin_counts[str(b + 1)] += 1
                bin_team_counts[str(b + 1)][team] += 1
    if len(rows) != 2164:
        raise RuntimeError(f"expected 2,164 frozen +45 pair rows; found {len(rows)}")
    support = {
        "game_count": len(games), "games": games,
        "raw_rollout_start_count": 200, "scored_start_count": len(records),
        "pair_row_count": len(rows), "pair_rows_by_distance_bin": bin_counts,
        "pair_rows_by_distance_bin_and_team": bin_team_counts,
        "source_player_field_names": sorted(player_fields),
        "verified_cross_game_pair_identity_field": None,
        "cross_game_identity_semantics": "No verified stable cross-game identity field; id/raw_id remain scoped track identifiers.",
        "identity_join_rule": "game-period-start-team plus sorted source track IDs; cross-game joins prohibited",
        "variance_component_grouping_rule": "game-period-team plus sorted track IDs across starts, training variance only; never used for held-out identity matching",
        "all_A_predictions_present": True,
    }
    return rows, games, support


def fit_bin_means(rows: list[dict], candidate: str, fit_games: set[str]) -> tuple[dict, list[dict]]:
    means, audit = {}, []
    for team in TEAMS:
        for b in range(4):
            team_values = [r["delta"][candidate] for r in rows
                           if r["game"] in fit_games and r["team"] == team and r["distance_bin"] == b]
            pooled_values = [r["delta"][candidate] for r in rows
                             if r["game"] in fit_games and r["distance_bin"] == b]
            fallback = len(team_values) < DISTANCE_MIN_TRAIN_PAIRS
            chosen = pooled_values if fallback else team_values
            if not chosen:
                raise RuntimeError(f"empty distance fit: {candidate}/{team}/bin{b + 1}/{sorted(fit_games)}")
            means[(team, b)] = float(np.mean(chosen))
            audit.append({"team": team, "distance_bin": b + 1,
                          "team_training_pairs": len(team_values),
                          "pooled_training_pairs": len(pooled_values) if fallback else None,
                          "fallback_fired": fallback, "training_games": sorted(fit_games),
                          "mean_ft": means[(team, b)]})
    return means, audit


def oof_training_residuals(rows: list[dict], candidate: str, training_games: set[str]) -> tuple[list[dict], list[dict]]:
    residual_rows, fit_audits = [], []
    for residual_game in sorted(training_games):
        fit_games = training_games - {residual_game}
        if not fit_games:
            continue
        means, audit = fit_bin_means(rows, candidate, fit_games)
        for row in rows:
            if row["game"] == residual_game:
                residual = row["delta"][candidate] - means[(row["team"], row["distance_bin"])]
                residual_rows.append({"identity_key": row["identity_key"],
                                      "variance_group_key": row["variance_group_key"],
                                      "game": residual_game,
                                      "residual": float(residual)})
        fit_audits.extend({**item, "residual_game": residual_game} for item in audit)
    return residual_rows, fit_audits


def variance_components(residual_rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in residual_rows:
        groups[row["variance_group_key"]].append(float(row["residual"]))
    counts = np.asarray([len(values) for values in groups.values()], dtype=np.float64)
    n_total, group_count = int(counts.sum()), len(counts)
    summary = {"observation_count": n_total, "group_count": group_count,
               "groups_with_at_least_two_observations": int(np.sum(counts >= 2)),
               "grouping_scope": "game-period-team-sorted-track-pair across starts; training variance components only",
               "heldout_identity_matching_uses_this_grouping": False,
               "within_degrees_of_freedom": n_total - group_count,
               "between_denominator": None, "within_variance": None,
               "tau2": None, "status": "not_estimable"}
    if group_count < 2 or n_total <= group_count:
        summary["reason"] = "insufficient repeated pair-key observations for variance components"
        return summary
    group_means = np.asarray([np.mean(values) for values in groups.values()], dtype=np.float64)
    grand_mean = float(np.mean([r["residual"] for r in residual_rows]))
    ssw = float(sum(np.sum((np.asarray(values) - np.mean(values)) ** 2)
                    for values in groups.values()))
    ssb = float(np.sum(counts * (group_means - grand_mean) ** 2))
    within_df = n_total - group_count
    denominator = float(n_total - np.sum(counts * counts) / n_total)
    if within_df <= 0 or denominator <= 0:
        summary["reason"] = "nonpositive variance-component degrees of freedom"
        return summary
    within = ssw / within_df
    tau2 = max(0.0, (ssb - within * (group_count - 1)) / denominator)
    if not math.isfinite(within) or not math.isfinite(tau2):
        summary["reason"] = "nonfinite variance component"
        return summary
    summary.update({"between_denominator": denominator, "within_variance": within,
                    "tau2": tau2, "status": "estimated", "SSW": ssw, "SSB": ssb,
                    "grand_mean": grand_mean})
    return summary


def pair_effects(residual_rows: list[dict], variance: dict) -> tuple[dict, dict]:
    groups = defaultdict(list)
    for row in residual_rows:
        groups[row["identity_key"]].append(float(row["residual"]))
    shrunk, raw = {}, {}
    audit = {"fewer_than_two_training_rows": 0, "zero_weight_or_nonestimable": 0,
             "nonzero_weight_groups": 0}
    for key, values in groups.items():
        n = len(values)
        raw[key] = float(np.mean(values))
        if n < 2:
            audit["fewer_than_two_training_rows"] += 1
            continue
        if variance["status"] != "estimated":
            audit["zero_weight_or_nonestimable"] += 1
            continue
        within, tau2 = variance["within_variance"], variance["tau2"]
        denom = tau2 + within / n
        weight = tau2 / denom if denom > 0.0 else 0.0
        if weight > 0.0:
            shrunk[key] = {"weight": float(weight), "correction": float(weight * raw[key]),
                           "n": n, "raw_mean": raw[key]}
            audit["nonzero_weight_groups"] += 1
        else:
            audit["zero_weight_or_nonestimable"] += 1
    return {"shrunk": shrunk, "raw": raw}, audit


def predict_b_c(row: dict, effects: dict) -> tuple[float, float, str, str]:
    a = float(row["A"])
    b_item = effects["shrunk"].get(row["identity_key"])
    c_value = effects["raw"].get(row["identity_key"])
    if b_item is None:
        b, b_reason = a, "unseen_or_weight_zero"
    else:
        b, b_reason = a + b_item["correction"], "shrunk_pair_residual"
    if c_value is None:
        c, c_reason = a, "unseen_pair"
    else:
        c, c_reason = a + c_value, "unshrunk_pair_residual"
    return float(b), float(c), b_reason, c_reason


def q1_predictions(rows: list[dict], games: list[str], candidate: str) -> dict:
    per_game = {model: {} for model in ("A", "B", "C")}
    fold_support = {}
    for heldout in games:
        outer_train = set(games) - {heldout}
        train_residuals, train_audit = oof_training_residuals(rows, candidate, outer_train)
        vc = variance_components(train_residuals)
        effects, effect_audit = pair_effects(train_residuals, vc)
        held_rows = [r for r in rows if r["game"] == heldout]
        variant_targets = {model: [] for model in ("A", "B", "C")}
        fallback_counts = Counter()
        for row in held_rows:
            a = row["A"][candidate]
            model_row = {**row, "A": a}
            b, c, b_reason, c_reason = predict_b_c(model_row, effects)
            variant_targets["A"].append(a)
            variant_targets["B"].append(b)
            variant_targets["C"].append(c)
            fallback_counts["B_unseen_or_zero_weight"] += int(b_reason == "unseen_or_weight_zero")
            fallback_counts["B_nonzero_weight"] += int(b_reason == "shrunk_pair_residual")
            fallback_counts["C_unseen"] += int(c_reason == "unseen_pair")
            fallback_counts["C_training_mean_used"] += int(c_reason == "unshrunk_pair_residual")

        inner_mse = {model: [] for model in ("A", "B", "C")}
        for inner_held in sorted(outer_train):
            inner_train = outer_train - {inner_held}
            means, _ = fit_bin_means(rows, candidate, inner_train)
            inner_train_residuals, _ = oof_training_residuals(rows, candidate, inner_train)
            inner_vc = variance_components(inner_train_residuals)
            inner_effects, _ = pair_effects(inner_train_residuals, inner_vc)
            test_rows = [r for r in rows if r["game"] == inner_held]
            inner_errors = {model: [] for model in ("A", "B", "C")}
            for row in test_rows:
                a_inner = means[(row["team"], row["distance_bin"])]
                inner_row = {**row, "A": a_inner}
                b_inner, c_inner, _, _ = predict_b_c(inner_row, inner_effects)
                inner_errors["A"].append(row["delta"][candidate] - a_inner)
                inner_errors["B"].append(row["delta"][candidate] - b_inner)
                inner_errors["C"].append(row["delta"][candidate] - c_inner)
            for model, values in inner_errors.items():
                array = np.asarray(values, dtype=np.float64)
                if not len(array):
                    raise RuntimeError(f"empty inner sigma fold {heldout}/{inner_held}/{model}")
                inner_mse[model].append(float(np.mean(array * array)))
        sigmas = {model: math.sqrt(float(np.mean(values))) for model, values in inner_mse.items()}
        if any(not math.isfinite(value) or value <= 0.0 for value in sigmas.values()):
            raise RuntimeError(f"invalid training-only sigma for {candidate}/{heldout}: {sigmas}")

        target = np.asarray([r["delta"][candidate] for r in held_rows], dtype=np.float64)
        if any(len(variant_targets[m]) != len(target) for m in variant_targets):
            raise RuntimeError(f"Q1 common support mismatch for {candidate}/{heldout}")
        for model in per_game:
            pred = np.asarray(variant_targets[model], dtype=np.float64)
            errors = target - pred
            sigma = sigmas[model]
            log_scores = -0.5 * (math.log(2.0 * math.pi * sigma * sigma) + (errors * errors) / (sigma * sigma))
            centered = errors - float(np.mean(errors))
            per_game[model][heldout] = {
                "pair_count": int(len(errors)),
                "mae": float(np.mean(np.abs(errors))),
                "mse": float(np.mean(errors * errors)),
                "rmse": float(math.sqrt(np.mean(errors * errors))),
                "mean_gaussian_log_score": float(np.mean(log_scores)),
                "residual_population_variance": float(np.mean(centered * centered)),
                "sigma_training_inner_oof": float(sigma),
            }
        fold_support[heldout] = {
            "training_games": sorted(outer_train),
            "training_residual_row_count": len(train_residuals),
            "training_pair_group_count": vc["group_count"],
            "variance_components": vc,
            "pair_effect_fit_audit": effect_audit,
            "heldout_pair_count": len(held_rows),
            "heldout_pair_counts_by_bin": dict(Counter(str(r["distance_bin"] + 1) for r in held_rows)),
            "heldout_unseen_and_weight_counts": dict(fallback_counts),
            "training_oof_distance_fit_count": len(train_audit),
            "training_only_sigma_by_variant": sigmas,
        }
    return {"per_game": per_game, "fold_support": fold_support}


def bootstrap_q1(per_game: dict, games: list[str], draws: np.ndarray) -> dict:
    metrics = ("mae", "mse", "mean_gaussian_log_score", "residual_population_variance")
    output = {"variants": {}, "paired_differences": {}, "relative_B_RMSE_improvement_pct": {}}
    arrays = {variant: {metric: np.asarray([per_game[variant][g][metric] for g in games], dtype=np.float64)
                        for metric in metrics} for variant in ("A", "B", "C")}
    for variant in arrays:
        point_rmse = math.sqrt(float(np.mean(arrays[variant]["mse"])))
        boot_rmse = np.sqrt(arrays[variant]["mse"][draws].mean(axis=1))
        output["variants"][variant] = {
            "equal_game_mae": float(np.mean(arrays[variant]["mae"])),
            "equal_game_rmse": point_rmse,
            "equal_game_mean_gaussian_log_score": float(np.mean(arrays[variant]["mean_gaussian_log_score"])),
            "equal_game_residual_sd": float(math.sqrt(np.mean(arrays[variant]["residual_population_variance"]))),
            "bootstrap_rmse_95_ci": [float(np.quantile(boot_rmse, .025, method="linear")),
                                     float(np.quantile(boot_rmse, .975, method="linear"))],
        }
    for compared in ("B", "C"):
        output["paired_differences"][f"{compared}_minus_A"] = {}
        for metric in ("mae", "mse", "mean_gaussian_log_score"):
            av, cv = arrays["A"][metric], arrays[compared][metric]
            if metric == "mse":
                boot = np.sqrt(cv[draws].mean(axis=1)) - np.sqrt(av[draws].mean(axis=1))
                point = math.sqrt(float(cv.mean())) - math.sqrt(float(av.mean()))
                metric_name = "rmse"
            else:
                boot = cv[draws].mean(axis=1) - av[draws].mean(axis=1)
                point = float(cv.mean() - av.mean())
                metric_name = metric
            output["paired_differences"][f"{compared}_minus_A"][metric_name] = {
                "point": point,
                "bootstrap_95_ci": [float(np.quantile(boot, .025, method="linear")),
                                    float(np.quantile(boot, .975, method="linear"))],
            }
    a_rmse = math.sqrt(float(arrays["A"]["mse"].mean()))
    b_rmse = math.sqrt(float(arrays["B"]["mse"].mean()))
    improvement = 100.0 * (a_rmse - b_rmse) / a_rmse
    boot_a = np.sqrt(arrays["A"]["mse"][draws].mean(axis=1))
    boot_b = np.sqrt(arrays["B"]["mse"][draws].mean(axis=1))
    boot_improvement = 100.0 * (boot_a - boot_b) / boot_a
    lower, upper = (float(np.quantile(boot_improvement, q, method="linear")) for q in (.025, .975))
    output["relative_B_RMSE_improvement_pct"] = {
        "point": float(improvement), "bootstrap_95_ci": [lower, upper],
        "materiality_bar_pct": MATERIALITY_BAR_PCT,
        "interval_lower_exceeds_bar": bool(lower > MATERIALITY_BAR_PCT),
        "interval_includes_zero": bool(lower <= 0.0 <= upper),
    }
    a_spread = math.sqrt(float(arrays["A"]["residual_population_variance"].mean()))
    b_spread = math.sqrt(float(arrays["B"]["residual_population_variance"].mean()))
    boot_a_spread = np.sqrt(arrays["A"]["residual_population_variance"][draws].mean(axis=1))
    boot_b_spread = np.sqrt(arrays["B"]["residual_population_variance"][draws].mean(axis=1))
    spread_draws = 1.0 - boot_b_spread / boot_a_spread
    output["A_vs_B_spread_reduction"] = {
        "point": float(1.0 - b_spread / a_spread),
        "bootstrap_95_ci": [float(np.quantile(spread_draws, .025, method="linear")),
                            float(np.quantile(spread_draws, .975, method="linear"))],
    }
    return output


def q1_run(rows: list[dict], games: list[str], bootstrap_draws: np.ndarray) -> dict:
    output = {"definition": "outer leave-one-game-out; +45 candidate-minus-M0 delta; equal-game metrics",
              "pair_count_common_support": len(rows), "candidates": {}}
    for candidate in CANDIDATES:
        fit = q1_predictions(rows, games, candidate)
        summary = bootstrap_q1(fit["per_game"], games, bootstrap_draws)
        output["candidates"][candidate] = {
            **summary, "per_game": fit["per_game"],
            "outer_fold_training_and_fallback_audit": fit["fold_support"],
            "identical_variant_pair_support": True,
        }
        for game in games:
            counts = [fit["per_game"][variant][game]["pair_count"] for variant in ("A", "B", "C")]
            if len(set(counts)) != 1:
                raise RuntimeError(f"variant support mismatch: {candidate}/{game}/{counts}")
    return output


def q2_run(rows: list[dict]) -> dict:
    observations_by_key = defaultdict(set)
    bins = defaultdict(Counter)
    for row in rows:
        observations_by_key[(row["identity_key"], row["distance_bin"])].add(row["game"])
        bins[row["distance_bin"]][row["team"]] += 1
    eligible_by_bin = {str(b + 1): 0 for b in range(4)}
    for (_, b), seen_games in observations_by_key.items():
        if len(seen_games) >= 2:
            eligible_by_bin[str(b + 1)] += 1
    eligible_total = sum(eligible_by_bin.values())
    candidates = {}
    for candidate in CANDIDATES:
        candidates[candidate] = {
            "status": "not_estimable_no_verified_cross_game_pair_keys" if eligible_total == 0 else "unexpected_verified_key_requires_review",
            "within_pair_sign_agreement": None, "different_pair_sign_agreement": None,
            "sign_agreement_difference": None, "within_pair_spearman": None,
            "different_pair_spearman": None, "spearman_difference": None,
            "bootstrap_95_ci": None,
            "eligible_pair_keys_observed_in_at_least_two_games": eligible_total,
            "eligible_pair_keys_by_distance_bin": eligible_by_bin,
            "eligible_game_pair_cells": 0,
            "reason": ("The frozen source defines sorted track-ID pairs within one game-period-start-team; "
                       "cross-game athlete identity is unverified. No cross-game pair join is permitted."),
        }
    return {
        "definition": "within-bin centered +45 deltas; same verified pair across games versus within-cell different-pair derangements",
        "status": "not_estimable_no_verified_cross_game_pair_keys" if eligible_total == 0 else "unexpected_verified_key_requires_review",
        "pair_observation_counts_by_bin_and_team": {
            str(b + 1): {team: int(bins[b][team]) for team in TEAMS} for b in range(4)},
        "eligible_verified_pair_keys_by_bin": eligible_by_bin,
        "eligible_verified_pair_key_count": eligible_total,
        "candidates": candidates,
        "registered_bootstrap_draws": BOOTSTRAPS, "bootstrap_seed": SEED,
        "bootstrap_executed": eligible_total > 0,
        "registered_derangements_per_estimable_cell": 10_000,
        "executed_derangement_count": 10_000 * eligible_total if eligible_total else 0,
    }


def q3_decision(q1: dict, q2: dict, support: dict, rows: list[dict], games: list[str]) -> dict:
    bin_by_game = {game: {str(b + 1): 0 for b in range(4)} for game in games}
    for row in rows:
        bin_by_game[row["game"]][str(row["distance_bin"] + 1)] += 1
    outer_support, collapses = {}, []
    for game in games:
        train_counts = {str(b + 1): sum(r["distance_bin"] == b and r["game"] != game for r in rows)
                        for b in range(4)}
        for bin_name, count in bin_by_game[game].items():
            if count == 0:
                collapses.append({"heldout_game": game, "distance_bin": int(bin_name), "support": "heldout_zero"})
        for bin_name, count in train_counts.items():
            if count == 0:
                collapses.append({"heldout_game": game, "distance_bin": int(bin_name), "support": "outer_training_zero"})
        outer_support[game] = {"heldout_pair_count_by_bin": bin_by_game[game],
                               "outer_training_pair_count_by_bin": train_counts}
    candidate_decisions = {}
    for candidate, result in q1["candidates"].items():
        improvement = result["relative_B_RMSE_improvement_pct"]
        if improvement["interval_includes_zero"]:
            reading = "pair_identity_line_closes_interval_includes_zero"
        elif improvement["interval_lower_exceeds_bar"]:
            reading = "transferable_value_meets_materiality"
        else:
            reading = "positive_but_below_materiality_or_nonpositive"
        candidate_decisions[candidate] = {
            "Q1_relative_RMSE_improvement_pct": improvement,
            "Q1_interval_includes_zero": improvement["interval_includes_zero"],
            "Q1_materiality_met": improvement["interval_lower_exceeds_bar"],
            "Q2_status": q2["candidates"][candidate]["status"],
            "registered_reading": reading,
        }
    all_q1_close = all(row["Q1_interval_includes_zero"] for row in candidate_decisions.values())
    if all_q1_close:
        decision = ("The pair-identity line closes on these ten inspected development games: "
                    "the Q1 B−A interval includes zero, and Q2 has no estimable verified cross-game "
                    "pair identities; no correction prototype or label program is justified. "
                    "Record DIAG2–DIAG6 persistence as a descriptive property of these ten games only.")
    elif q2["status"] == "not_estimable_no_verified_cross_game_pair_keys":
        decision = "Q1 determines the registered reading; Q2 is non-estimable because the frozen data do not provide verified cross-game pair identities."
    else:
        decision = "Apply the registered candidate-wise Q1/Q2 reading; no label program or gate change is authorized."
    return {
        "materiality_bar_pct": MATERIALITY_BAR_PCT,
        "materiality_justification": "5% of the frozen approximately 3.03 ft +45 delta SD is about 0.15 ft.",
        "A_vs_B_spread_reduction": {candidate: values["A_vs_B_spread_reduction"]
                                    for candidate, values in q1["candidates"].items()},
        "per_game_and_bin_support": outer_support,
        "support_collapses": collapses,
        "candidate_readings": candidate_decisions,
        "overall_registered_reading": "pair_identity_line_closes" if all_q1_close else "candidate_specific",
        "decision_sentence": decision,
        "population_boundary": support["game_count"] == 10 and "inspected development" in decision,
    }


def fmt_metric(row: dict, digits: int = 4) -> str:
    point, ci = row.get("point"), row.get("bootstrap_95_ci")
    if point is None:
        return "not estimable"
    interval = f"[{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]" if ci else "[interval unavailable]"
    return f"{point:.{digits}f} {interval}"


def render_report(result: dict, runtime_seconds: float, result_hash: str, result_bytes: int) -> str:
    gate = result["provenance_gate"]
    lines = [
        "# NHL JC-DIAG7: out-of-sample value of pair identity", "",
        f"Source base: {SOURCE_BASE}. Correction commit: {CORRECTION_COMMIT}. Preregistration commit: {PREREG_COMMIT}.",
        "Branch: research/nhl-multi-agent-movement-2026-10-23.", "",
        "## Population and identity boundary", "",
        "Ten inspected development games, 200 rollout starts (172 with +45 scoring support), 2,164 +45 within-team pair observations, 142 EqualTeam starts, and 311 eligible team cells. Image Id remains ordinal, not seconds; there is no independent tracking sample.", "",
        "The source player objects expose history, id, jersey, raw_id, team, x, and y. The id-like values are scoped track identifiers; none is verified as a stable cross-game athlete or pair key. Cross-game athlete identity is unverified, so track-ID collisions were not joined across games. B and C used the registered fallback to A for unseen pairs; Q2 is non-estimable where stable cross-game identity is required. For the preregistered training-only variance components, repeated pairs were grouped by game-period-team and sorted track IDs across starts; this generic variance grouping was never used to match a held-out identity.", "",
        "## Provenance gate", "",
        f"Gate: **{'PASS' if gate['all_assertions_passed'] else 'FAIL'}**; pinned artifact hashes {gate['pass_counts']['pinned_artifact_hashes']}; DIAG6 value checks {gate['pass_counts']['DIAG6_value_assertions']}; inherited DIAG6 source hashes {gate['pass_counts']['DIAG6_source_hashes']}; inherited reassertions {gate['pass_counts']['DIAG6_reassertions']}.", "",
        "| Artifact | Path | Expected SHA-256 | Actual SHA-256 | Status |", "|---|---|---|---|---|",
    ]
    for row in gate["artifact_hashes"]:
        lines.append(f"| {row['name']} | {row['path']} | {row['expected_sha256']} | {row['actual_sha256']} | {'PASS' if row['passed'] else 'FAIL'} |")
    lines += ["", "All frozen DIAG6 values and the full DIAG6 upstream source chain were reasserted before Q1–Q3.", "",
              "## Q1. Held-out pair-delta scores", "",
              "Outer leave-one-game-out scoring. A is the stored DIAG6 distance-only prediction. B adds a training-only variance-component-shrunk pair residual; C adds the unshrunk training pair residual and is only an overfit control. Metrics use identical pair rows and equal game weighting. Gaussian sigma uses inner leave-one-game-out training residuals.", "",
              "| Candidate | Variant | MAE (ft) | RMSE (ft) | Mean Gaussian log score | Residual SD (ft) |", "|---|---|---:|---:|---:|---:|"]
    for candidate, candidate_result in result["Q1"]["candidates"].items():
        for variant, row in candidate_result["variants"].items():
            lines.append(f"| {candidate} | {variant} | {row['equal_game_mae']:.5f} | {row['equal_game_rmse']:.5f} | {row['equal_game_mean_gaussian_log_score']:.5f} | {row['equal_game_residual_sd']:.5f} |")
        for label, diff in candidate_result["paired_differences"].items():
            lines.append(f"| {candidate} | {label} MAE difference | {fmt_metric(diff['mae'])} |  |  |  |")
            lines.append(f"| {candidate} | {label} RMSE difference |  | {fmt_metric(diff['rmse'])} |  |  |")
            lines.append(f"| {candidate} | {label} log-score difference |  |  | {fmt_metric(diff['mean_gaussian_log_score'], 5)} |  |")
        improvement = candidate_result["relative_B_RMSE_improvement_pct"]
        lines.append(f"| {candidate} | B relative RMSE improvement | {fmt_metric(improvement, 3)}% | materiality lower bound above {MATERIALITY_BAR_PCT:.1f}%: {improvement['interval_lower_exceeds_bar']} |  |  |")
        lines.append("")
    lines += ["### Per-game held-out scores", "",
              "Each game is evaluated only by its outer fold. Pair counts are common to A/B/C.", "",
              "| Candidate | Game | Pairs | A MAE | B MAE | C MAE | A RMSE | B RMSE | C RMSE | A log score | B log score | C log score |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for candidate, candidate_result in result["Q1"]["candidates"].items():
        g = candidate_result["per_game"]
        for game in result["population"]["games"]:
            n = g["A"][game]["pair_count"]
            lines.append(f"| {candidate} | {game} | {n} | {g['A'][game]['mae']:.4f} | {g['B'][game]['mae']:.4f} | {g['C'][game]['mae']:.4f} | {g['A'][game]['rmse']:.4f} | {g['B'][game]['rmse']:.4f} | {g['C'][game]['rmse']:.4f} | {g['A'][game]['mean_gaussian_log_score']:.4f} | {g['B'][game]['mean_gaussian_log_score']:.4f} | {g['C'][game]['mean_gaussian_log_score']:.4f} |")
    lines += ["", "### Pair support and shrinkage audit", "",
              "| Candidate | Held-out pairs | B unseen/zero-weight | B nonzero weight | C unseen | C mean used |", "|---|---:|---:|---:|---:|---:|"]
    for candidate, candidate_result in result["Q1"]["candidates"].items():
        folds = candidate_result["outer_fold_training_and_fallback_audit"]
        lines.append(f"| {candidate} | {sum(f['heldout_pair_count'] for f in folds.values())} | {sum(f['heldout_unseen_and_weight_counts']['B_unseen_or_zero_weight'] for f in folds.values())} | {sum(f['heldout_unseen_and_weight_counts']['B_nonzero_weight'] for f in folds.values())} | {sum(f['heldout_unseen_and_weight_counts']['C_unseen'] for f in folds.values())} | {sum(f['heldout_unseen_and_weight_counts']['C_training_mean_used'] for f in folds.values())} |")
    lines += ["", "Variance components use the preregistered one-way random-intercept method-of-moments estimator. The table reports its training-only SSW, SSB, denominator, within variance, and tau²; grouping is game-period-team plus sorted track IDs across starts and is never used for held-out identity matching.", "",
              "| Candidate | Outer heldout game | Variance status | N rows | J groups | Repeated groups | SSW | SSB | Between denominator | Within variance | tau² |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for candidate, candidate_result in result["Q1"]["candidates"].items():
        for game, fold in candidate_result["outer_fold_training_and_fallback_audit"].items():
            vc = fold["variance_components"]
            within = "NA" if vc["within_variance"] is None else f"{vc['within_variance']:.6g}"
            tau = "NA" if vc["tau2"] is None else f"{vc['tau2']:.6g}"
            ssw = "NA" if vc.get("SSW") is None else f"{vc['SSW']:.6g}"
            ssb = "NA" if vc.get("SSB") is None else f"{vc['SSB']:.6g}"
            denominator = "NA" if vc.get("between_denominator") is None else f"{vc['between_denominator']:.6g}"
            lines.append(f"| {candidate} | {game} | {vc['status']} | {vc['observation_count']} | {vc['group_count']} | {vc['groups_with_at_least_two_observations']} | {ssw} | {ssb} | {denominator} | {within} | {tau} |")
    lines += ["", "## Q2. Distance-matched pair-identity concordance", "",
              "Pair observations by frozen distance bin:", "",
              "| Bin | Home pairs | Away pairs | Total | Verified pair keys seen in at least two games |", "|---:|---:|---:|---:|---:|"]
    q2 = result["Q2"]
    for bin_name, team_counts in q2["pair_observation_counts_by_bin_and_team"].items():
        total = team_counts["Home"] + team_counts["Away"]
        lines.append(f"| {bin_name} | {team_counts['Home']} | {team_counts['Away']} | {total} | {q2['eligible_verified_pair_keys_by_bin'][bin_name]} |")
    lines += ["", "| Candidate | Q2 status | Within-pair sign agreement | Different-pair sign agreement | Difference [95%] | Within-pair Spearman | Different-pair Spearman | Difference [95%] | Eligible game-pair cells |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for candidate, row in q2["candidates"].items():
        lines.append(f"| {candidate} | {row['status']} | NA | NA | NA | NA | NA | NA | {row['eligible_game_pair_cells']} |")
    lines += ["", "Q2 has no estimable concordance values because the frozen source has no verified cross-game pair identity. No derangements or Q2 bootstrap intervals were run because eligible support was zero. Numeric track-ID collisions were not treated as identity matches.", "",
              "## Q3. Materiality and support", "",
              f"The preregistered materiality bar is {MATERIALITY_BAR_PCT:.1f}% relative RMSE reduction, approximately 0.15 ft at the frozen +45 delta SD of about 3.03 ft.", "",
              "| Candidate | B−A relative RMSE improvement [95%] | A-vs-B residual spread reduction [95%] | Per-game support identical |", "|---|---:|---:|---|"]
    for candidate, row in result["Q1"]["candidates"].items():
        lines.append(f"| {candidate} | {fmt_metric(row['relative_B_RMSE_improvement_pct'], 3)}% | {fmt_metric(row['A_vs_B_spread_reduction'], 5)} | {row['identical_variant_pair_support']} |")
    lines += ["", "| Held-out game | Pair count | Bin 1 | Bin 2 | Bin 3 | Bin 4 | Outer training bin counts |", "|---|---:|---:|---:|---:|---:|---|"]
    for game, data_row in result["Q3"]["per_game_and_bin_support"].items():
        bins, train = data_row["heldout_pair_count_by_bin"], data_row["outer_training_pair_count_by_bin"]
        lines.append(f"| {game} | {sum(bins.values())} | {bins['1']} | {bins['2']} | {bins['3']} | {bins['4']} | {train} |")
    lines.append("")
    lines.append("Support collapses: none." if not result["Q3"]["support_collapses"] else
                  f"Support collapses: {json.dumps(result['Q3']['support_collapses'], sort_keys=True)}.")
    registered_reading = ("Q1 interval includes zero → the pair-identity line closes: no correction, no labels, and the DIAG2–DIAG6 persistence is recorded as a descriptive property of the ten inspected games only. Q2 may contradict; if it does, report \"structure present, immaterial out of sample\" and do not narrate a winner.")
    lines += ["", "## Decision", "", "Registered reading applied (verbatim):", "",
              f"> {registered_reading}", "",
              result["Q3"]["decision_sentence"], "",
              "This is a leave-one-game-out comparison within the same ten inspected development games, not an independent later-game evaluation. Track IDs are local; no cross-game player-pair interpretation is supported.", "",
              "## Reproduction", "",
              "Gate-only: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag7_oos_pair_value.py --gate-only",
              "Full run: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag7_oos_pair_value.py",
              "Checks: git diff --check; ast.parse; deterministic rerun to /tmp/jc-diag7-oos-pair-value-repeat.json with --no-report; cmp against the committed result.", "",
              f"Primary runtime: {runtime_seconds:.3f} seconds. Evaluator SHA-256: {result['evaluator_sha256']}. Result SHA-256: {result_hash}; byte count: {result_bytes}.", ""]
    return "\n".join(lines)


def write_json(path: Path, payload: dict) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gate-only", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    d6 = load_diag6_module()
    gate, data = verify_gate(d6)
    if args.gate_only:
        print(json.dumps(gate, sort_keys=True, indent=2))
        if not gate["all_assertions_passed"]:
            raise SystemExit(2)
        return
    if not gate["all_assertions_passed"] or data is None:
        failure = {"schema_version": 1, "analysis": "NHL JC-DIAG7 out-of-sample pair value",
                   "source_base": SOURCE_BASE, "preregistration_commit": PREREG_COMMIT,
                   "provenance_gate": gate, "Q1_Q3_calculated": False}
        write_json(args.output, failure)
        print(json.dumps(gate, sort_keys=True, indent=2))
        raise SystemExit(2)
    diag6_json = json.loads(DIAG6_JSON.read_text(encoding="utf-8"))
    rows, games, support = collect_rows(d6, diag6_json, data)
    draws = np.random.default_rng(SEED).integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)
    q1 = q1_run(rows, games, draws)
    q2 = q2_run(rows)
    q3 = q3_decision(q1, q2, support, rows, games)
    gate["Q1_Q3_calculated"] = True
    result = {
        "schema_version": 1,
        "analysis": "NHL JC-DIAG7 out-of-sample value of pair identity",
        "source_base": SOURCE_BASE, "correction_commit": CORRECTION_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "path": str(PREREG.relative_to(ROOT)),
                            "sha256": PREREG_SHA256},
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "provenance_gate": gate, "population": support,
        "distance_bins_ft": [17.038243596734116, 25.896550730297974, 36.18400154397977],
        "bootstrap": {"cluster": "whole game", "draws": BOOTSTRAPS, "seed": SEED,
                      "game_weight": "equal", "one_shared_index_matrix": True},
        "Q1": q1, "Q2": q2, "Q3": q3, "Q1_Q3_calculated": True,
    }
    result_hash, result_bytes = write_json(args.output, result)
    runtime = time.monotonic() - started
    report_path = None
    if not args.no_report and args.output.resolve() == DEFAULT_OUTPUT.resolve():
        report_path = REPORT
        report_path.write_text(render_report(result, runtime, result_hash, result_bytes), encoding="utf-8")
    print(json.dumps({"gate_passed": True, "output": str(args.output.resolve()),
                      "sha256": result_hash, "bytes": result_bytes,
                      "report": str(report_path) if report_path else None,
                      "runtime_seconds": round(runtime, 3),
                      "Q1_reading": {m: result["Q3"]["candidate_readings"][m]["registered_reading"] for m in CANDIDATES},
                      "Q2_status": q2["status"]}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
