#!/usr/bin/env python3
"""Read-only JC-DIAG2 pair-persistence and pair-stratum attribution."""
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
PREREG = ROOT / "docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md"
DIAG1_PREREG = ROOT / "docs/research/NHL-JC-ATTRIBUTION-PREREG-2026-10-23.md"
DIAG1_RESULTS = RESULTS / "jc-attribution-jcdiag-2026-10-23-v1.json"
BASE_COMMIT = "46f23ad691d0da1e6841f41f86f25e4bad8d7af8"
PREREG_COMMIT = "b5b439310d0c97964f209af8cd29e9e04831b5fe"
PREREG_SHA256 = "2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234"
DIAG1_RESULTS_SHA256 = "f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c"
EXPECTED_HASHES = {
    "jc_results": "0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c",
    "movement_comparison": "1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8",
    "fold_models": "194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a",
    "scenario_archive": "a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce",
    "rollout_starts": "07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de",
    "jc_diag_preregistration": "c9e3da3ca12ff5197e3ed5b9eed9775548a85b6c427d60465641d28ac1c5bd4c",
    "jc_diag_results": DIAG1_RESULTS_SHA256,
    "jc_diag2_preregistration": PREREG_SHA256,
}
PATHS = {
    "jc_results": RESULTS / "joint-coherence-jc-2026-10-23-v1.json",
    "movement_comparison": RESULTS / "movement_comparison-bc91d1610de5.json",
    "fold_models": RESULTS / "fold_models-bc91d1610de5.json",
    "scenario_archive": RESULTS / "scenario_archive-bc91d1610de5.json.gz",
    "rollout_starts": DATA / "rollout_starts.json.gz",
    "jc_diag_preregistration": DIAG1_PREREG,
    "jc_diag_results": DIAG1_RESULTS,
    "jc_diag2_preregistration": PREREG,
}
TASK_NAMED_STARTS = RESULTS / "rollout_starts-2026-10-23.json"
MODELS = ("M0", "M1", "M2")
TEAMS = ("Home", "Away")
TRANSITIONS = {
    "plus15_to_plus45": (15, 45),
    "plus15_to_plus30": (15, 30),
    "plus30_to_plus45": (30, 45),
}
BOOTSTRAPS = 10_000
PERMUTATIONS = 10_000
SEED = 20261024
MIN_PAIRS = 3


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
            all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in value))


def linear_quantile(values, q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q, method="linear"))


def percentile_interval(values) -> list[float] | None:
    if not values:
        return None
    array = np.asarray(values, dtype=np.float64)
    return [linear_quantile(array, 0.025), linear_quantile(array, 0.975)]


def source_hashes() -> dict[str, str]:
    absent = [str(path) for path in PATHS.values() if not path.is_file()]
    if absent:
        raise RuntimeError(f"required frozen inputs are absent: {absent}")
    actual = {name: sha256_file(path) for name, path in PATHS.items()}
    if actual != EXPECTED_HASHES:
        raise RuntimeError(f"frozen-input provenance mismatch; expected {EXPECTED_HASHES}, got {actual}")
    if TASK_NAMED_STARTS.exists():
        raise RuntimeError(
            f"task-named start manifest appeared at {TASK_NAMED_STARTS}; resolve provenance before proceeding"
        )
    return actual


def field(obj: dict, *path):
    value = obj
    for key in path:
        value = value[key]
    return value


def gate_checks(hashes: dict[str, str]) -> tuple[dict, dict]:
    jc = read_json(PATHS["jc_results"])
    diag1 = read_json(PATHS["jc_diag_results"])
    if diag1.get("source_hashes", {}).get("jc_results") != EXPECTED_HASHES["jc_results"]:
        raise RuntimeError("JC-DIAG result references a different JC result artifact")
    if diag1.get("source_hashes", {}).get("movement_comparison") != EXPECTED_HASHES["movement_comparison"]:
        raise RuntimeError("JC-DIAG result references a different movement comparison")
    if diag1.get("source_hashes", {}).get("fold_models") != EXPECTED_HASHES["fold_models"]:
        raise RuntimeError("JC-DIAG result references different fold models")
    if diag1.get("source_hashes", {}).get("scenario_archive") != EXPECTED_HASHES["scenario_archive"]:
        raise RuntimeError("JC-DIAG result references a different scenario archive")
    if diag1.get("source_hashes", {}).get("rollout_starts") != EXPECTED_HASHES["rollout_starts"]:
        raise RuntimeError("JC-DIAG result references a different rollout-start source")
    if diag1.get("preregistration", {}).get("sha256") != EXPECTED_HASHES["jc_diag_preregistration"]:
        raise RuntimeError("JC-DIAG result references a different preregistration")

    expected = {
        "plus45_M1_signed_pair_error_ft": {
            "estimate": -3.990319961,
            "ci": [-4.745503058, -3.277490265],
            "tol": 5.1e-9,
            "estimate_path": ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds",
                              "45", "within_team_pair_distribution", "M1", "metrics", "signed_mean"),
        },
        "plus45_M2_signed_pair_error_ft": {
            "estimate": -4.018689088,
            "ci": [-4.765197406, -3.325853562],
            "tol": 5.1e-9,
            "estimate_path": ("Q2_signed_pair_error_distribution", "horizons_ordinal_increments_not_seconds",
                              "45", "within_team_pair_distribution", "M2", "metrics", "signed_mean"),
        },
        "plus45_M1_individual_radial_gain_ft": {
            "estimate": 1.129584368,
            "tol": 5.1e-9,
            "estimate_path": ("Q5_plus45_individual_group_dissociation", "candidates", "M1",
                              "individual_radial_gain_ft"),
        },
        "plus15_M1_Home_signed_pair_bias_ft": {
            "estimate": -0.8193,
            "tol": 5.1e-5,
            "estimate_path": ("Q1_pair_type_and_team_decomposition", "horizons_ordinal_increments_not_seconds",
                              "15", "by_team", "Home", "model_estimates", "M1", "signed_pair_bias_ft"),
        },
    }
    checks = []
    for name, spec in expected.items():
        summary = field(diag1, *spec["estimate_path"])
        if "estimate" in summary:
            actual_estimate = float(summary["estimate"])
        else:
            actual_estimate = float(summary["equal_game_mean_available_games"])
        passed = math.isclose(actual_estimate, spec["estimate"], rel_tol=0.0, abs_tol=spec["tol"])
        check = {"name": name, "expected": spec["estimate"], "actual": actual_estimate,
                 "tolerance": spec["tol"], "passed": passed}
        if "ci" in spec:
            actual_ci = summary["bootstrap_95_percentile_interval"]
            check["expected_ci"] = spec["ci"]
            check["actual_ci"] = actual_ci
            check["ci_passed"] = all(math.isclose(float(actual_ci[i]), spec["ci"][i], rel_tol=0.0,
                                                     abs_tol=spec["tol"]) for i in range(2))
            passed = passed and check["ci_passed"]
            check["passed"] = passed
        checks.append(check)

    q1_45 = field(diag1, "Q1_pair_type_and_team_decomposition", "horizons_ordinal_increments_not_seconds",
                  "45", "by_team")
    home_pairs = int(q1_45["Home"]["model_estimates"]["M0"]["signed_pair_bias_ft"]["pair_count_total"])
    away_pairs = int(q1_45["Away"]["model_estimates"]["M0"]["signed_pair_bias_ft"]["pair_count_total"])
    pair_check = {"name": "plus45_pair_denominators", "expected_home": 1064, "actual_home": home_pairs,
                  "expected_away": 1100, "actual_away": away_pairs, "expected_total": 2164,
                  "actual_total": home_pairs + away_pairs,
                  "passed": home_pairs == 1064 and away_pairs == 1100 and home_pairs + away_pairs == 2164}
    checks.append(pair_check)

    correction = diag1.get("provenance_gate", {}).get("manager_correction_before_attribution", {})
    if correction.get("source_artifact_sha256") != EXPECTED_HASHES["jc_results"]:
        raise RuntimeError("JC-DIAG correction record does not cite the pinned JC result artifact")
    if correction.get("corrected_reference_ft") != 3.1045 or correction.get("recomputed_float_ft") != 3.1044985489019927:
        raise RuntimeError("JC-DIAG correction record no longer matches the authoritative 3.1045 ft correction")
    if not all(check["passed"] for check in checks):
        for check in checks:
            print("PROVENANCE", json.dumps(check, sort_keys=True))
        raise RuntimeError("published JC-DIAG assertion failed; P1-P4 were not run")

    output = {
        "source_hashes": hashes,
        "task_named_rollout_starts_path": str(TASK_NAMED_STARTS),
        "task_named_rollout_starts_path_exists": False,
        "effective_rollout_starts_path": str(PATHS["rollout_starts"]),
        "effective_rollout_starts_sha256": EXPECTED_HASHES["rollout_starts"],
        "checks": checks,
        "all_assertions_passed": True,
        "jc_diag_manager_correction_revalidated": {
            "corrected_field": correction["corrected_field"],
            "initial_typo_ft": correction["initial_typo_ft"],
            "corrected_reference_ft": correction["corrected_reference_ft"],
            "recomputed_float_ft": correction["recomputed_float_ft"],
            "source_artifact_sha256": correction["source_artifact_sha256"],
        },
    }
    print(f"PROVENANCE frozen input hashes: {len(hashes)} PASS")
    for check in checks:
        print(f"PROVENANCE {check['name']}: expected={check.get('expected', check.get('expected_total'))} "
              f"actual={check.get('actual', check.get('actual_total'))} PASS")
        if "actual_ci" in check:
            print(f"PROVENANCE {check['name']} CI: {check['actual_ci']} PASS")
    return jc, {"diag1": diag1, "gate": output}


def game_cluster_summary(rows: list[dict], value_key: str, games: list[str], draws: np.ndarray,
                         *, pair_count_key: str = "pair_count") -> dict:
    by_game: dict[str, list[float]] = {game: [] for game in games}
    starts_by_game: dict[str, set[str]] = {game: set() for game in games}
    pair_count_by_game = {game: 0 for game in games}
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        game = row["game"]
        by_game[game].append(float(value))
        starts_by_game[game].add(row["start_id"])
        pair_count_by_game[game] += int(row.get(pair_count_key, 0))
    game_means = {game: float(np.mean(values)) if values else None for game, values in by_game.items()}
    valid = [value for value in game_means.values() if value is not None]
    estimate = float(np.mean(valid)) if valid else None
    ci = None
    if len(valid) == len(games):
        values = np.asarray([game_means[game] for game in games], dtype=np.float64)
        bootstrap = values[draws].mean(axis=1)
        ci = [linear_quantile(bootstrap, 0.025), linear_quantile(bootstrap, 0.975)]
    return {
        "equal_game_mean_available_games": estimate,
        "bootstrap_95_percentile_interval": ci,
        "game_means": game_means,
        "games_with_values": len(valid),
        "scored_starts": sum(len(value) for value in starts_by_game.values()),
        "pair_count_total_on_metric_support": sum(pair_count_by_game.values()),
        "pair_count_by_game_on_metric_support": pair_count_by_game,
    }


def json_pair(pair: tuple[str, str]) -> list[str]:
    return [pair[0], pair[1]]


def build_states(jc: dict, starts: list[dict], archive: dict) -> tuple[dict, dict, list[str], list[str]]:
    games = list(jc["population"]["games"])
    start_ids = [f"{row['game']}|{row['period']}|{row['cutoff_seq']}" for row in starts]
    if len(start_ids) != 200 or len(set(start_ids)) != 200:
        raise RuntimeError(f"rollout manifest must contain 200 unique starts; got {len(start_ids)}")
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in archive["scenarios"].values()}
    if len(scenario_by_id) != len(archive["scenarios"]) or set(start_ids) - scenario_by_id.keys():
        raise RuntimeError("rollout manifest and archived scenario IDs are not a one-to-one match")
    jc_rows = jc["scenario_measurements"]
    jc_by_key = {(row["scenario_id"], int(row["horizon_ordinal_increment"])): row for row in jc_rows}
    expected_grid = {(sid, h) for sid in start_ids for h in range(1, 46)}
    if len(jc_by_key) != len(jc_rows) or set(jc_by_key) != expected_grid:
        raise RuntimeError("frozen JC grid is not exactly the 200 starts by 45 horizons")

    states = {}
    support_audit = {}
    for sid in start_ids:
        scenario = scenario_by_id[sid]
        game = scenario["game"]
        initial_rows = scenario["initial_state"]["players"]
        initial = {}
        team_by_id = {}
        for player in initial_rows:
            pid = player["id"]
            if pid in initial:
                raise RuntimeError(f"duplicate cutoff track {pid} in {sid}")
            if player.get("team") not in TEAMS or not finite_xy([player.get("x"), player.get("y")]):
                raise RuntimeError(f"invalid cutoff coordinates or team for {pid} in {sid}")
            initial[pid] = np.asarray([player["x"], player["y"]], dtype=np.float64)
            team_by_id[pid] = player["team"]
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        if set(frames) != set(range(46)):
            raise RuntimeError(f"invalid archived step grid for {sid}")
        states[sid] = {"game": game, "horizons": {}}
        for horizon in (1, 15, 30, 45):
            frame = frames[horizon]
            observed_players = (frame.get("observed") or {}).get("players") or {}
            model_players = {model: frame.get("models", {}).get(model, {}).get("players", {}) for model in MODELS}
            common = [pid for pid in initial if finite_xy(observed_players.get(pid)) and
                      all(finite_xy(model_players[m].get(pid)) for m in MODELS)]
            by_team = {team: sorted(pid for pid in common if team_by_id[pid] == team) for team in TEAMS}
            eligible = all(len(by_team[team]) >= 2 for team in TEAMS)
            jc_row = jc_by_key[(sid, horizon)]
            if bool(jc_row["eligible"]) != eligible:
                raise RuntimeError(f"JC eligibility mismatch for {sid} +{horizon}")
            counts = jc_row["counts"]
            expected_counts = {
                "common_skaters": len(common),
                "common_home_skaters": len(by_team["Home"]),
                "common_away_skaters": len(by_team["Away"]),
                "home_within_team_pairs": len(by_team["Home"]) * (len(by_team["Home"]) - 1) // 2,
                "away_within_team_pairs": len(by_team["Away"]) * (len(by_team["Away"]) - 1) // 2,
            }
            if any(int(counts[key]) != value for key, value in expected_counts.items()):
                raise RuntimeError(f"JC track/pair support mismatch for {sid} +{horizon}: {expected_counts} vs {counts}")
            observed = {pid: np.asarray(observed_players[pid], dtype=np.float64) for pid in common}
            predictions = {model: {pid: np.asarray(model_players[model][pid], dtype=np.float64) for pid in common}
                           for model in MODELS}
            team_pairs = {}
            for team in TEAMS:
                pair_map = {}
                for first, second in combinations(by_team[team], 2):
                    pair = (first, second)
                    observed_distance = float(np.linalg.norm(observed[first] - observed[second]))
                    error_by_model = {}
                    for model in MODELS:
                        predicted_distance = float(np.linalg.norm(predictions[model][first] - predictions[model][second]))
                        error_by_model[model] = predicted_distance - observed_distance
                    pair_map[pair] = {
                        "errors_ft": error_by_model,
                        "observed_cutoff_distance_ft": float(np.linalg.norm(initial[first] - initial[second])),
                    }
                team_pairs[team] = pair_map
            states[sid]["horizons"][horizon] = {
                "eligible": eligible,
                "common_track_count": len(common),
                "team_track_counts": {team: len(by_team[team]) for team in TEAMS},
                "team_pair_counts": {team: len(team_pairs[team]) for team in TEAMS},
                "team_pairs": team_pairs,
            }
        support_audit[sid] = {str(h): states[sid]["horizons"][h]["team_pair_counts"] for h in (1, 15, 30, 45)}

    scored45 = [sid for sid in start_ids if states[sid]["horizons"][45]["eligible"]]
    if len(scored45) != 172:
        raise RuntimeError(f"expected 172 +45 JC group-scored starts, found {len(scored45)}")
    totals = {team: sum(states[sid]["horizons"][45]["team_pair_counts"][team] for sid in scored45)
              for team in TEAMS}
    if totals != {"Home": 1064, "Away": 1100} or sum(totals.values()) != 2164:
        raise RuntimeError(f"raw frame reconstruction of +45 pair denominators failed: {totals}")
    return states, support_audit, start_ids, scored45


def make_transition_rows(states: dict, scored45: list[str], transition: tuple[int, int],
                         permutation_rng: np.random.Generator) -> list[dict]:
    earlier, later = transition
    records = []
    for sid in scored45:
        game = states[sid]["game"]
        for team in TEAMS:
            earlier_pairs = states[sid]["horizons"][earlier]["team_pairs"][team]
            later_pairs = states[sid]["horizons"][later]["team_pairs"][team]
            common_pairs = sorted(earlier_pairs.keys() & later_pairs.keys())
            count = len(common_pairs)
            rec = {"game": game, "start_id": sid, "team": team, "pair_count": count,
                   "pairs": [json_pair(pair) for pair in common_pairs], "models": {}}
            if count < MIN_PAIRS:
                rec["not_estimable_reason"] = "fewer_than_three_common_pairs"
                for model in MODELS:
                    rec["models"][model] = {"observed_share": None, "permutation_null_mean": None,
                                             "observed_minus_null": None, "negative_mass_later_ft": None,
                                             "not_estimable_reason": "fewer_than_three_common_pairs"}
                records.append(rec)
                continue

            previous_errors = {
                model: np.asarray([earlier_pairs[pair]["errors_ft"][model] for pair in common_pairs], dtype=np.float64)
                for model in MODELS
            }
            later_errors = {
                model: np.asarray([later_pairs[pair]["errors_ft"][model] for pair in common_pairs], dtype=np.float64)
                for model in MODELS
            }
            # One within-start/team permutation map is shared across models.
            permutation_order = np.argsort(permutation_rng.random((PERMUTATIONS, count)), axis=1)
            for model in MODELS:
                prev_negative = previous_errors[model] < 0.0
                negative_mass = np.maximum(-later_errors[model], 0.0)
                denominator = float(negative_mass.sum())
                if denominator <= 0.0:
                    rec["models"][model] = {"observed_share": None, "permutation_null_mean": None,
                                             "observed_minus_null": None, "negative_mass_later_ft": denominator,
                                             "not_estimable_reason": "no_negative_error_mass_at_later_horizon"}
                    continue
                numerator = float((negative_mass * prev_negative).sum())
                observed_share = numerator / denominator
                shuffled_mass = negative_mass[permutation_order]
                null_shares = (shuffled_mass * prev_negative[None, :]).sum(axis=1) / denominator
                null_mean = float(np.mean(null_shares))
                rec["models"][model] = {
                    "observed_share": observed_share,
                    "permutation_null_mean": null_mean,
                    "observed_minus_null": observed_share - null_mean,
                    "negative_mass_later_ft": denominator,
                    "persistent_negative_mass_ft": numerator,
                    "not_estimable_reason": None,
                }
            records.append(rec)
    return records


def transition_summary(records: list[dict], games: list[str], draws: np.ndarray) -> dict:
    output = {"support_by_team": {}, "models": {}}
    metrics = ("observed_share", "permutation_null_mean", "observed_minus_null")
    for team in (*TEAMS, "EqualTeam"):
        team_rows = [row for row in records if row["team"] == team] if team != "EqualTeam" else []
        if team == "EqualTeam":
            by_start = {}
            for row in records:
                by_start.setdefault(row["start_id"], {})[row["team"]] = row
            for sid, pair in by_start.items():
                if set(pair) != set(TEAMS):
                    continue
                game = pair["Home"]["game"]
                models_row = {"game": game, "start_id": sid,
                              "pair_count": pair["Home"]["pair_count"] + pair["Away"]["pair_count"],
                              "models": {}}
                for model in MODELS:
                    h = pair["Home"]["models"][model]
                    a = pair["Away"]["models"][model]
                    models_row["models"][model] = {
                        metric: (float(np.mean([h[metric], a[metric]]))
                                 if h[metric] is not None and a[metric] is not None else None)
                        for metric in metrics
                    }
                output["support_by_team"][team] = None
                team_rows.append(models_row)
        else:
            output["support_by_team"][team] = {
                "start_team_rows": len(team_rows),
                "eligible_start_team_rows": sum(any(row["models"][model]["observed_share"] is not None
                                                     for model in MODELS) for row in team_rows),
                "common_pair_count_total": sum(row["pair_count"] for row in team_rows),
                "under_three_pair_rows": sum(row["pair_count"] < MIN_PAIRS for row in team_rows),
                "games_with_pair_rows": len({row["game"] for row in team_rows}),
            }
        output["models"][team] = {}
        for model in MODELS:
            model_out = {}
            for metric in metrics:
                metric_rows = []
                for row in team_rows:
                    if team == "EqualTeam":
                        value = row["models"][model][metric]
                    else:
                        value = row["models"][model].get(metric)
                    metric_rows.append({"game": row["game"], "start_id": row["start_id"],
                                        "pair_count": row["pair_count"], metric: value})
                model_out[metric] = game_cluster_summary(metric_rows, metric, games, draws)
            output["models"][team][model] = model_out
    output["equal_team_support_note"] = "EqualTeam averages Home/Away within each start only when both are estimable."
    return output


def make_pair_strata(states: dict, scored45: list[str]) -> tuple[list[dict], list[dict]]:
    p3_rows, p4_rows = [], []
    for sid in scored45:
        game = states[sid]["game"]
        for team in TEAMS:
            pair_sets = [set(states[sid]["horizons"][h]["team_pairs"][team]) for h in (1, 15, 45)]
            common_three = sorted(set.intersection(*pair_sets))
            for pair in common_three:
                p3_rows.append({
                    "game": game, "start_id": sid, "team": team, "pair": json_pair(pair),
                    "baseline_abs_error_plus1_ft": abs(states[sid]["horizons"][1]["team_pairs"][team][pair]["errors_ft"]["M0"]),
                    "observed_cutoff_pair_distance_ft": states[sid]["horizons"][45]["team_pairs"][team][pair]["observed_cutoff_distance_ft"],
                    "errors_ft": {str(h): {model: states[sid]["horizons"][h]["team_pairs"][team][pair]["errors_ft"][model]
                                             for model in MODELS} for h in (1, 15, 45)},
                })
            for pair, value in states[sid]["horizons"][45]["team_pairs"][team].items():
                p4_rows.append({
                    "game": game, "start_id": sid, "team": team, "pair": json_pair(pair),
                    "observed_cutoff_pair_distance_ft": value["observed_cutoff_distance_ft"],
                    "errors_ft": {model: value["errors_ft"][model] for model in MODELS},
                })
    return p3_rows, p4_rows


def apply_bins(rows: list[dict], value_key: str, quantile_count: int, bin_key: str) -> list[float]:
    if not rows:
        raise RuntimeError(f"no pair rows available to define {bin_key}")
    probs = np.arange(1, quantile_count, dtype=np.float64) / quantile_count
    values = np.asarray([row[value_key] for row in rows], dtype=np.float64)
    edges = np.quantile(values, probs, method="linear").tolist()
    for row in rows:
        row[bin_key] = int(np.searchsorted(edges, float(row[value_key]), side="right"))
    return [float(x) for x in edges]


def stratified_delta_rows(rows: list[dict], bin_key: str, bin_count: int, candidate: str,
                          horizon: int | None, *, p3: bool, games: list[str], draws: np.ndarray) -> dict:
    metric_rows_by_bin = {b: [] for b in range(bin_count)}
    contribution_by_game_bin = {game: {b: 0.0 for b in range(bin_count)} for game in games}
    positive_total_by_game = {game: 0.0 for game in games}
    pair_counts = {b: 0 for b in range(bin_count)}
    starts_by_bin = {b: set() for b in range(bin_count)}
    games_by_bin = {b: set() for b in range(bin_count)}
    support_by_game_start_team: dict[tuple[str, str, str], int] = {}
    for row in rows:
        support_by_game_start_team[(row["game"], row["start_id"], row["team"])] = \
            support_by_game_start_team.get((row["game"], row["start_id"], row["team"]), 0) + 1
    starts_per_game = {
        game: len({row["start_id"] for row in rows if row["game"] == game}) for game in games
    }
    by_cell: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
    for row in rows:
        b = int(row[bin_key])
        pair_counts[b] += 1
        starts_by_bin[b].add(row["start_id"])
        games_by_bin[b].add(row["game"])
        if p3:
            error_map = row["errors_ft"][str(horizon)]
        else:
            error_map = row["errors_ft"]
        signed_delta = float(error_map[candidate] - error_map["M0"])
        abs_delta = float(abs(error_map[candidate]) - abs(error_map["M0"]))
        copy = dict(row)
        copy["signed_delta_ft"] = signed_delta
        copy["absolute_error_delta_ft"] = abs_delta
        by_cell[(row["game"], row["start_id"], row["team"], b)].append(copy)
        denominator_pairs = support_by_game_start_team[(row["game"], row["start_id"], row["team"])]
        weight = 1.0 / (10.0 * starts_per_game[row["game"]] * 2.0 * denominator_pairs)
        positive = weight * max(abs_delta, 0.0)
        contribution_by_game_bin[row["game"]][b] += positive
        positive_total_by_game[row["game"]] += positive

    start_bin: dict[tuple[str, str, int], dict] = {}
    for (game, sid, team, b), cell_rows in by_cell.items():
        key = (game, sid, b)
        rec = start_bin.setdefault(key, {"game": game, "start_id": sid, "bin": b,
                                         "team_cell_values": defaultdict(list), "pair_count": 0})
        rec["team_cell_values"][team] = {
            "signed_delta_ft": float(np.mean([x["signed_delta_ft"] for x in cell_rows])),
            "absolute_error_delta_ft": float(np.mean([x["absolute_error_delta_ft"] for x in cell_rows])),
            "pair_count": len(cell_rows),
        }
        rec["pair_count"] += len(cell_rows)
    for (game, sid, b), rec in start_bin.items():
        teams = rec.pop("team_cell_values")
        rec["represented_teams"] = sorted(teams)
        rec["signed_delta_ft"] = float(np.mean([v["signed_delta_ft"] for v in teams.values()]))
        rec["absolute_error_delta_ft"] = float(np.mean([v["absolute_error_delta_ft"] for v in teams.values()]))
        rec["team_pair_counts"] = {team: int(v["pair_count"]) for team, v in teams.items()}
        metric_rows_by_bin[b].append(rec)

    bin_results = []
    for b in range(bin_count):
        summary = {"bin": b + 1, "pair_count": pair_counts[b], "scored_starts": len(starts_by_bin[b]),
                   "represented_games": len(games_by_bin[b]),
                   "start_team_cells": sum(1 for key in by_cell if key[3] == b),
                   "per_game_positive_absolute_error_delta_weighted_ft": {
                       game: contribution_by_game_bin[game][b] for game in games},
                   "per_game_total_positive_absolute_error_delta_weighted_ft": positive_total_by_game}
        for metric in ("signed_delta_ft", "absolute_error_delta_ft"):
            summary[metric] = game_cluster_summary(metric_rows_by_bin[b], metric, games, draws)
        boot_share = []
        for index_row in draws:
            num = float(np.mean([contribution_by_game_bin[games[int(i)]][b] for i in index_row]))
            den = float(np.mean([positive_total_by_game[games[int(i)]] for i in index_row]))
            boot_share.append(num / den if den > 0.0 else None)
        valid_shares = [x for x in boot_share if x is not None]
        share_interval = percentile_interval(valid_shares) if len(valid_shares) >= 9500 else None
        total_contribution = float(np.mean([contribution_by_game_bin[g][b] for g in games]))
        total_positive = float(np.mean([positive_total_by_game[g] for g in games]))
        summary["positive_delta_contribution_share"] = {
            "estimate": total_contribution / total_positive if total_positive > 0.0 else None,
            "bootstrap_95_percentile_interval": share_interval,
            "valid_draws": len(valid_shares),
            "unavailable_draws": BOOTSTRAPS - len(valid_shares),
        }
        summary["not_estimable"] = pair_counts[b] == 0
        bin_results.append(summary)
    return {"bins": bin_results, "per_start_bin_values": [
        {key: value for key, value in row.items() if key != "per_game_total_positive_absolute_error_delta_weighted_ft"}
        for b in range(bin_count) for row in metric_rows_by_bin[b]
    ]}


def exact_zero_summary(rows: list[dict], candidate: str, horizon: int, games: list[str], draws: np.ndarray) -> dict:
    groups = {"exact_zero_at_plus1": [], "nonzero_at_plus1": []}
    for row in rows:
        group = "exact_zero_at_plus1" if row["baseline_abs_error_plus1_ft"] == 0.0 else "nonzero_at_plus1"
        error_map = row["errors_ft"][str(horizon)]
        groups[group].append({
            "game": row["game"], "start_id": row["start_id"], "team": row["team"], "pair_count": 1,
            "signed_delta_ft": float(error_map[candidate] - error_map["M0"]),
            "absolute_error_delta_ft": float(abs(error_map[candidate]) - abs(error_map["M0"])),
        })
    out = {}
    for name, group_rows in groups.items():
        # Pair values are averaged within start/team before equal-team/start/game weighting.
        cells = defaultdict(list)
        for row in group_rows:
            cells[(row["game"], row["start_id"], row["team"])].append(row)
        starts = defaultdict(dict)
        for (game, sid, team), cell_rows in cells.items():
            starts[(game, sid)][team] = {
                "signed_delta_ft": float(np.mean([r["signed_delta_ft"] for r in cell_rows])),
                "absolute_error_delta_ft": float(np.mean([r["absolute_error_delta_ft"] for r in cell_rows])),
                "pair_count": len(cell_rows),
            }
        start_rows = []
        for (game, sid), team_values in starts.items():
            for metric in ("signed_delta_ft", "absolute_error_delta_ft"):
                vals = [team_values[t][metric] for t in TEAMS if t in team_values]
                start_rows.append({"game": game, "start_id": sid, "pair_count": sum(v["pair_count"] for v in team_values.values()),
                                   metric: float(np.mean(vals))})
        # Merge separate metric rows into one record per start for paired summaries.
        by_key = {}
        for row in start_rows:
            key = (row["game"], row["start_id"])
            by_key.setdefault(key, {"game": key[0], "start_id": key[1], "pair_count": row["pair_count"]}).update(row)
        merged = list(by_key.values())
        out[name] = {
            "pair_count": len(group_rows),
            "scored_starts": len(starts),
            "represented_games": len({r["game"] for r in group_rows}),
            "signed_delta_ft": game_cluster_summary(merged, "signed_delta_ft", games, draws),
            "absolute_error_delta_ft": game_cluster_summary(merged, "absolute_error_delta_ft", games, draws),
        }
    return out


def run_analysis(jc: dict, diag1_and_gate: dict, hashes: dict[str, str], output_path: Path) -> None:
    archive = read_gzip_json(PATHS["scenario_archive"])
    starts = read_gzip_json(PATHS["rollout_starts"])["starts"]
    states, support_audit, start_ids, scored45 = build_states(jc, starts, archive)
    games = list(jc["population"]["games"])
    bootstrap_rng = np.random.default_rng(SEED)
    game_draws = bootstrap_rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)
    permutation_rng = np.random.default_rng(SEED)

    transition_records = {}
    for label, transition in TRANSITIONS.items():
        transition_records[label] = make_transition_rows(states, scored45, transition, permutation_rng)
    p1 = {"transition": [15, 45], "population_start_count": len(scored45),
          "definition": "later negative-error mass on pairs with negative earlier error / all later negative-error mass",
          "permutation_null": "within-start/team shuffle later signed errors across stable pair IDs; preserve later error multiset",
          "transition_rows": transition_records["plus15_to_plus45"],
          "summary": transition_summary(transition_records["plus15_to_plus45"], games, game_draws)}
    p2 = {"fixed_population": "the same +45 JC-scored starts as P1", "transitions": {}}
    for label in ("plus15_to_plus30", "plus30_to_plus45"):
        lo, hi = TRANSITIONS[label]
        records = transition_records[label]
        p2["transitions"][label] = {
            "transition": [lo, hi], "population_start_count": len(scored45),
            "transition_rows": records,
            "summary": transition_summary(records, games, game_draws),
        }
    p2["descriptive_point_direction"] = {}
    for model in MODELS:
        for team in (*TEAMS, "EqualTeam"):
            first = p2["transitions"]["plus15_to_plus30"]["summary"]["models"][team][model]["observed_share"]["equal_game_mean_available_games"]
            second = p2["transitions"]["plus30_to_plus45"]["summary"]["models"][team][model]["observed_share"]["equal_game_mean_available_games"]
            if first is None or second is None:
                direction = "not_estimable"
            elif second > first:
                direction = "rises"
            elif second < first:
                direction = "falls"
            else:
                direction = "flat"
            p2["descriptive_point_direction"][f"{team}_{model}"] = {
                "plus15_to_plus30_share": first, "plus30_to_plus45_share": second,
                "direction_by_point_estimates": direction,
            }

    p3_pair_rows, p4_pair_rows = make_pair_strata(states, scored45)
    p3_edges = apply_bins(p3_pair_rows, "baseline_abs_error_plus1_ft", 10, "baseline_error_decile")
    p4_edges = apply_bins(p4_pair_rows, "observed_cutoff_pair_distance_ft", 4, "cutoff_distance_quartile")
    p3 = {"population_start_count": len(scored45), "pair_count_total": len(p3_pair_rows),
          "baseline": "M0 absolute signed pair error at +1 ordinal increment, computed per stable pair",
          "decile_edges_ft": p3_edges, "bin_assignment": "linear quantiles; cutpoint ties assigned to higher bin",
          "by_horizon": {}, "exact_zero_vs_nonzero_baseline": {}}
    for horizon in (15, 45):
        p3["by_horizon"][str(horizon)] = {}
        for candidate in ("M1", "M2"):
            p3["by_horizon"][str(horizon)][candidate] = stratified_delta_rows(
                p3_pair_rows, "baseline_error_decile", 10, candidate, horizon,
                p3=True, games=games, draws=game_draws)
            p3["exact_zero_vs_nonzero_baseline"][f"plus{horizon}_{candidate}"] = exact_zero_summary(
                p3_pair_rows, candidate, horizon, games, game_draws)
    p4 = {"population_start_count": len(scored45), "pair_count_total": len(p4_pair_rows),
          "baseline": "observed XY pair distance at frozen cutoff; no roles or positions inferred",
          "distance_quartile_edges_ft": p4_edges,
          "bin_assignment": "linear quantiles; cutpoint ties assigned to higher quartile",
          "by_candidate": {}}
    for candidate in ("M1", "M2"):
        p4["by_candidate"][candidate] = stratified_delta_rows(
            p4_pair_rows, "cutoff_distance_quartile", 4, candidate, None,
            p3=False, games=games, draws=game_draws)

    diag1 = diag1_and_gate["diag1"]
    result = {
        "schema_version": 1,
        "analysis": "NHL JC-DIAG2 pair-level spacing persistence",
        "base_commit": BASE_COMMIT,
        "preregistration": {"commit": PREREG_COMMIT, "file": str(PREREG.relative_to(ROOT)),
                             "sha256": PREREG_SHA256},
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "source_hashes": hashes,
        "provenance_gate": diag1_and_gate["gate"],
        "population": {
            "game_count": len(games), "games": games,
            "evaluation_design": "leave-one-whole-game-out development predictions",
            "rollout_starts": len(start_ids), "plus45_group_scored_starts": len(scored45),
            "eligible_one_skater_windows": 454983,
            "timebase": "ordinal Image Id suffix increments; not seconds",
            "independent_tracking_population_available": False,
            "adoption_boundary": "No adoption, NHL simulator, or Legendary Picks probability claim is licensed.",
            "task_named_start_manifest_resolution": {
                "task_path": str(TASK_NAMED_STARTS.relative_to(ROOT)),
                "exists": False,
                "effective_source": str(PATHS["rollout_starts"]),
                "effective_source_sha256": hashes["rollout_starts"],
            },
        },
        "method": {
            "models": list(MODELS), "teams": list(TEAMS),
            "pair_error": "predicted within-team pair distance minus observed target pair distance, feet",
            "common_pair_rule": "both endpoints common under frozen JC track eligibility; same unordered track-ID pair",
            "p1_minimum_common_pairs": MIN_PAIRS,
            "permutations_per_start_team_transition": PERMUTATIONS,
            "permutation_seed": SEED,
            "permutation_null": "shuffle later-horizon signed pair errors over pair IDs within each start/team; same permutation indices across models",
            "bootstrap_replicates": BOOTSTRAPS, "bootstrap_seed": SEED,
            "bootstrap_unit": "whole game, sampled with replacement, equal game weight; one common draw matrix",
            "bootstrap_interval": "95% percentile, linear interpolation; interval unavailable unless all ten games contribute",
            "ratio_interval_minimum_valid_draws": 9500,
            "p1_p2_population": "fixed starts JC group-eligible at +45 (172)",
            "p3_pair_support": "common pair across +1,+15,+45, on +45 group-scored starts",
            "p3_bin_cutpoints": "pooled empirical deciles of per-pair M0 absolute signed error at +1; linear quantile; fixed before bootstrap",
            "p4_pair_support": "common cutoff and +45 target/model pair support on +45 group-scored starts",
            "p4_bin_cutpoints": "pooled empirical quartiles of observed cutoff pair distance; linear quantile; fixed before bootstrap",
            "positive_contribution_weight": "1/(10 * eligible starts in game * 2 * eligible pairs in start/team)",
            "controller_or_policy_changed": False, "resimulation_performed": False,
        },
        "frozen_support_audit": {
            "per_start_per_horizon_team_pair_counts": support_audit,
            "plus45_pair_counts_by_team": {team: sum(states[sid]["horizons"][45]["team_pair_counts"][team]
                                                      for sid in scored45) for team in TEAMS},
            "p3_common_three_horizon_pair_count": len(p3_pair_rows),
            "p4_plus45_pair_count": len(p4_pair_rows),
        },
        "P1_plus15_to_plus45_pair_persistence": p1,
        "P2_adjacent_horizon_pair_persistence": p2,
        "P3_one_step_M0_error_deciles": p3,
        "P4_observed_cutoff_distance_quartiles": p4,
    }
    encoded = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(encoded)
    print(f"RESULT path={output_path} sha256={hashlib.sha256(encoded).hexdigest()} bytes={len(encoded)}")
    print(f"EVALUATOR sha256={result['evaluator_sha256']}")
    for section, payload in (("P1", p1), ("P2", p2), ("P3", p3), ("P4", p4)):
        print(f"{section} complete; detailed estimates, intervals, denominators, and exclusions are in JSON")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="run provenance assertions only; do not calculate P1-P4")
    parser.add_argument("--output", type=Path,
                        default=RESULTS / "jc-diag2-pair-persistence-2026-10-23-v1.json")
    args = parser.parse_args()
    hashes = source_hashes()
    jc, diag1_and_gate = gate_checks(hashes)
    if args.gate_only:
        print("GATE-ONLY PASS; P1-P4 were not calculated")
        return
    archive_size = PATHS["scenario_archive"].stat().st_size
    starts_size = PATHS["rollout_starts"].stat().st_size
    print(f"FROZEN INPUTS VERIFIED; scenario archive {archive_size} compressed bytes; starts {starts_size} bytes")
    run_analysis(jc, diag1_and_gate, hashes, args.output)


if __name__ == "__main__":
    main()
