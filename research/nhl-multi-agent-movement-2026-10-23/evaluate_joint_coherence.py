#!/usr/bin/env python3
"""Deterministic, label-only group scoring for the frozen NHL movement timelines."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261024
BOOTSTRAPS = 10_000
PRIMARY_HORIZONS = (1, 15, 30, 45)
DIAGNOSTIC_HORIZONS = tuple(range(1, 46))
MODELS = ("M0", "M1", "M2")
TEAMS = ("Home", "Away")
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
PREREG_SHA256 = "5ec697c63d80a1afe3ee2cb95b2c7a30ea633c0a9fb7ff9483983e2bd1501773"
INPUT_HASHES = {
    "rollout_starts_sha256": "07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de",
    "scenario_archive_sha256": "a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce",
    "movement_comparison_sha256": "1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8",
    "fold_models_sha256": "194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a",
}
LP_PREREG_COMMIT = "748e0090d18ee4a6cac09aa57429d347f9d5efae"
GPH_PREREG_COMMIT = "7e55ba30f40f83c8c251abf450512d740c89a1fd"
LP_PREDICTION_COMMIT = "bc91d1610de5c99a0bdf396738e9d2f493c3d215"
GPH_CONTROLLER_COMMIT = "252ed6d95fbb6a9ac8db5a65aed920139777432a"

METRICS = (
    "centroid_pooled_error_ft",
    "centroid_home_error_ft",
    "centroid_away_error_ft",
    "team_spacing_error_ft",
    "team_spacing_home_error_ft",
    "team_spacing_away_error_ft",
    "pair_distance_error_mean_ft",
    "pair_distance_error_p90_ft",
    "nearest_opponent_quantile_gap_ft",
    "team_spacing_signed_home_bias_ft",
    "team_spacing_signed_away_bias_ft",
    "team_spacing_signed_equal_team_bias_ft",
    "nearest_opponent_signed_quantile_bias_ft",
)
PRIMARY_FAMILIES = {
    "pooled_centroid": ("centroid_pooled_error_ft",),
    "team_spacing": ("team_spacing_error_ft",),
    "all_pair_distance": ("pair_distance_error_mean_ft", "pair_distance_error_p90_ft"),
    "nearest_opponent": ("nearest_opponent_quantile_gap_ft",),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def finite_xy(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in value))


def vec(value) -> np.ndarray:
    return np.asarray(value, dtype=np.float64)


def linear_quantile(values, q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q, method="linear"))


def _pair_distances(ids: list[str], points: dict[str, np.ndarray]) -> list[float]:
    return [float(np.linalg.norm(points[a] - points[b])) for a, b in combinations(ids, 2)]


def score_state(scenario: dict, frame: dict, step: int) -> dict:
    initial_rows = scenario["initial_state"]["players"]
    initial = {}
    teams = {}
    for row in initial_rows:
        pid = row["id"]
        if pid in initial:
            raise RuntimeError(f"{scenario['scenario_id']} step {step}: duplicate cutoff track {pid}")
        if row.get("team") not in TEAMS or not finite_xy([row.get("x"), row.get("y")]):
            raise RuntimeError(f"{scenario['scenario_id']} step {step}: invalid cutoff player {pid}")
        initial[pid] = np.asarray([row["x"], row["y"]], dtype=np.float64)
        teams[pid] = row["team"]

    observed = frame.get("observed")
    observed_players = (observed or {}).get("players") or {}
    predicted = {}
    for model in MODELS:
        model_frame = frame.get("models", {}).get(model)
        if not model_frame or not isinstance(model_frame.get("players"), dict):
            raise RuntimeError(f"{scenario['scenario_id']} step {step}: missing {model} player timeline")
        predicted[model] = model_frame["players"]

    common = [pid for pid in initial
              if finite_xy(observed_players.get(pid)) and
              all(finite_xy(predicted[m].get(pid)) for m in MODELS)]
    common_by_team = {team: [pid for pid in common if teams[pid] == team] for team in TEAMS}
    counts = {
        "cutoff_players": len(initial),
        "observed_target_players": sum(finite_xy(xy) for xy in observed_players.values()),
        "observed_ids_not_in_cutoff": sum(pid not in initial for pid, xy in observed_players.items() if finite_xy(xy)),
        "common_skaters": len(common),
        "common_home_skaters": len(common_by_team["Home"]),
        "common_away_skaters": len(common_by_team["Away"]),
        "home_within_team_pairs": len(common_by_team["Home"]) * (len(common_by_team["Home"]) - 1) // 2,
        "away_within_team_pairs": len(common_by_team["Away"]) * (len(common_by_team["Away"]) - 1) // 2,
        "within_team_pairs": sum(len(v) * (len(v) - 1) // 2 for v in common_by_team.values()),
        "all_unique_pairs": len(common) * (len(common) - 1) // 2,
        "nearest_opponent_skaters": len(common) if all(common_by_team[t] for t in TEAMS) else 0,
        "missing_xy_rows_reported": (observed or {}).get("missing_xy_count"),
        "conflicted_present_flag": (observed or {}).get("conflicted_present"),
    }
    if observed is None:
        return {"scenario_id": scenario["scenario_id"], "game": scenario["game"],
                "period": scenario["period"], "cutoff_seq": scenario["cutoff_seq"],
                "horizon_ordinal_increment": step, "eligible": False,
                "exclusion_reason": "observed target frame unavailable", "counts": counts, "models": {}}
    if any(len(common_by_team[t]) < 2 for t in TEAMS):
        return {"scenario_id": scenario["scenario_id"], "game": scenario["game"],
                "period": scenario["period"], "cutoff_seq": scenario["cutoff_seq"],
                "horizon_ordinal_increment": step, "eligible": False,
                "exclusion_reason": "fewer than two common labeled skaters on a team", "counts": counts, "models": {}}

    actual = {pid: vec(observed_players[pid]) for pid in common}
    initial_common = {pid: initial[pid] for pid in common}
    results = {}
    for model in MODELS:
        sim = {pid: vec(predicted[model][pid]) for pid in common}
        metrics = {}
        for team, key in (("Home", "home"), ("Away", "away")):
            ids = common_by_team[team]
            obs_displacements = np.asarray([actual[pid] - initial_common[pid] for pid in ids])
            sim_displacements = np.asarray([sim[pid] - initial_common[pid] for pid in ids])
            metrics[f"centroid_{key}_error_ft"] = float(np.linalg.norm(sim_displacements.mean(axis=0) - obs_displacements.mean(axis=0)))
            observed_team_distances = _pair_distances(ids, actual)
            simulated_team_distances = _pair_distances(ids, sim)
            metrics[f"team_spacing_{key}_error_ft"] = abs(float(np.mean(simulated_team_distances) - np.mean(observed_team_distances)))
            metrics[f"team_spacing_signed_{key}_bias_ft"] = float(np.mean(simulated_team_distances) - np.mean(observed_team_distances))

        all_obs_displacements = np.asarray([actual[pid] - initial_common[pid] for pid in common])
        all_sim_displacements = np.asarray([sim[pid] - initial_common[pid] for pid in common])
        metrics["centroid_pooled_error_ft"] = float(np.linalg.norm(all_sim_displacements.mean(axis=0) - all_obs_displacements.mean(axis=0)))
        metrics["team_spacing_error_ft"] = (metrics["team_spacing_home_error_ft"] + metrics["team_spacing_away_error_ft"]) / 2.0
        metrics["team_spacing_signed_equal_team_bias_ft"] = (metrics["team_spacing_signed_home_bias_ft"] + metrics["team_spacing_signed_away_bias_ft"]) / 2.0

        pair_errors = [abs(float(np.linalg.norm(sim[a] - sim[b]) - np.linalg.norm(actual[a] - actual[b])))
                       for a, b in combinations(common, 2)]
        metrics["pair_distance_error_mean_ft"] = float(np.mean(pair_errors))
        metrics["pair_distance_error_p90_ft"] = linear_quantile(pair_errors, 0.90)

        observed_nearest = []
        simulated_nearest = []
        for pid in common:
            opponent_team = "Away" if teams[pid] == "Home" else "Home"
            opponents = common_by_team[opponent_team]
            observed_nearest.append(min(float(np.linalg.norm(actual[pid] - actual[q])) for q in opponents))
            simulated_nearest.append(min(float(np.linalg.norm(sim[pid] - sim[q])) for q in opponents))
        observed_q = [linear_quantile(observed_nearest, q) for q in QUANTILES]
        simulated_q = [linear_quantile(simulated_nearest, q) for q in QUANTILES]
        signed_quantile_gaps = [p - o for p, o in zip(simulated_q, observed_q)]
        metrics["nearest_opponent_quantile_gap_ft"] = float(np.mean(np.abs(signed_quantile_gaps)))
        metrics["nearest_opponent_signed_quantile_bias_ft"] = float(np.mean(signed_quantile_gaps))
        metrics["nearest_opponent_signed_gaps_by_quantile_ft"] = {
            str(q): gap for q, gap in zip(QUANTILES, signed_quantile_gaps)
        }
        results[model] = metrics

    return {"scenario_id": scenario["scenario_id"], "game": scenario["game"],
            "period": scenario["period"], "cutoff_seq": scenario["cutoff_seq"],
            "horizon_ordinal_increment": step, "eligible": True, "exclusion_reason": None,
            "counts": counts, "models": results}


def ci_for_game_values(values: np.ndarray, draw_matrix: np.ndarray) -> list[float]:
    means = values[draw_matrix].mean(axis=1)
    return [float(np.quantile(means, 0.025, method="linear")),
            float(np.quantile(means, 0.975, method="linear"))]


def build_summary(rows: list[dict], games: list[str], draws: np.ndarray) -> tuple[dict, dict]:
    summary = {}
    paired = {}
    for step in DIAGNOSTIC_HORIZONS:
        rows_h = [r for r in rows if r["horizon_ordinal_increment"] == step]
        eligible = [r for r in rows_h if r["eligible"]]
        game_means = {m: {} for m in MODELS}
        coverage = {m: {} for m in MODELS}
        horizon_summary = {}
        for model in MODELS:
            model_summary = {}
            for metric in METRICS:
                by_game = {}
                state_counts = {}
                for game in games:
                    sample = [r for r in eligible if r["game"] == game]
                    vals = [r["models"][model][metric] for r in sample]
                    state_counts[game] = len(vals)
                    by_game[game] = float(np.mean(vals)) if vals else None
                present_games = [g for g in games if by_game[g] is not None]
                values = np.asarray([by_game[g] for g in present_games], dtype=np.float64)
                all_games = len(present_games) == len(games)
                model_summary[metric] = {
                    "equal_game_mean_available_games": float(values.mean()) if len(values) else None,
                    "bootstrap_95_percentile_interval": ci_for_game_values(values, draws) if all_games else None,
                    "game_means": by_game,
                    "games_with_states": len(present_games),
                    "states_by_game": state_counts,
                    "states_total": sum(state_counts.values()),
                }
                game_means[model][metric] = by_game
                coverage[model][metric] = {"states": sum(state_counts.values()), "games": len(present_games)}

            cell_rows = [r for r in eligible]
            pair_counts = [r["counts"]["all_unique_pairs"] for r in cell_rows]
            home_pairs = [r["counts"]["home_within_team_pairs"] for r in cell_rows]
            away_pairs = [r["counts"]["away_within_team_pairs"] for r in cell_rows]
            common_counts = [r["counts"]["common_skaters"] for r in cell_rows]
            model_summary["counts"] = {
                "requested_rollout_starts": len(rows_h),
                "scored_states": len(cell_rows),
                "states_by_game": {g: sum(r["game"] == g for r in cell_rows) for g in games},
                "represented_games": sum(any(r["game"] == g for r in cell_rows) for g in games),
                "common_skaters_total": sum(common_counts),
                "mean_common_skaters_per_state": float(np.mean(common_counts)) if common_counts else None,
                "all_unique_pairs_total": sum(pair_counts),
                "mean_all_unique_pairs_per_state": float(np.mean(pair_counts)) if pair_counts else None,
                "home_within_team_pairs_total": sum(home_pairs),
                "mean_home_pairs_per_state": float(np.mean(home_pairs)) if home_pairs else None,
                "away_within_team_pairs_total": sum(away_pairs),
                "mean_away_pairs_per_state": float(np.mean(away_pairs)) if away_pairs else None,
                "within_team_pairs_total": sum(home_pairs) + sum(away_pairs),
                "mean_within_team_pairs_per_state": float(np.mean(np.asarray(home_pairs) + np.asarray(away_pairs))) if home_pairs else None,
            }
            horizon_summary[model] = model_summary

        paired_h = {}
        for candidate in ("M1", "M2"):
            metrics_out = {}
            for metric in METRICS:
                per_game_delta = {}
                for game in games:
                    left, right = game_means[candidate][metric][game], game_means["M0"][metric][game]
                    per_game_delta[game] = (left - right) if left is not None and right is not None else None
                present = [g for g in games if per_game_delta[g] is not None]
                vals = np.asarray([per_game_delta[g] for g in present], dtype=np.float64)
                full = len(present) == len(games)
                interval = ci_for_game_values(vals, draws) if full else None
                metrics_out[metric] = {
                    "candidate_minus_M0_equal_game_mean_available_games": float(vals.mean()) if len(vals) else None,
                    "paired_game_cluster_bootstrap_95_percentile_interval": interval,
                    "game_deltas": per_game_delta,
                    "games_with_states": len(present),
                    "improvement_supported": bool(interval is not None and interval[1] < 0.0),
                }
            paired_h[candidate] = metrics_out

        summary[str(step)] = {
            "horizon_ordinal_increment_not_seconds": step,
            "group_states": len(eligible),
            "requested_starts": len(rows_h),
            "ineligible_reasons": dict(Counter(r["exclusion_reason"] for r in rows_h if not r["eligible"])),
            "models": horizon_summary,
        }
        paired[str(step)] = paired_h
    return summary, paired


def load_one_step(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    section = data["one_step_plus_15_ordinal_increments"]
    metrics = {}
    for model in MODELS:
        mean = section["absolute_game_bootstrap"][model]["position_error_mean"]
        metrics[model] = {
            "equal_game_mean_ft": mean["equal_game_mean"],
            "game_cluster_bootstrap_95_percentile_interval_ft": mean["bootstrap_95_percentile_interval"],
            "per_game_mean_ft": {g: section["by_game"][g][model]["position_error_mean"] for g in data["games"]},
            "examples_by_game": {g: section["by_game"][g][model]["examples"] for g in data["games"]},
        }
    paired_out = {}
    for candidate in ("M1", "M2"):
        key = f"{candidate}_minus_M0"
        row = section["paired_game_bootstrap"][key]["position_error_mean"]
        m0 = metrics["M0"]["equal_game_mean_ft"]
        metrics[candidate]["relative_change_vs_M0_percent"] = 100.0 * (metrics[candidate]["equal_game_mean_ft"] / m0 - 1.0)
        paired_out[candidate] = {
            "candidate_minus_M0_mean_ft": row["equal_game_mean_delta"],
            "paired_game_cluster_bootstrap_95_percentile_interval_ft": row["bootstrap_95_percentile_interval"],
            "relative_change_percent_point_estimate": metrics[candidate]["relative_change_vs_M0_percent"],
        }
    return {"horizon_ordinal_increment_not_seconds": 15,
            "metric": "held-out one-step endpoint radial error",
            "models": metrics, "paired_candidate_minus_M0": paired_out}


def load_rollout_endpoint_error(data: dict) -> dict:
    result = {}
    for step in PRIMARY_HORIZONS:
        absolute = data["rollout_absolute_game_bootstrap"][str(step)]
        paired = data["rollout_paired_game_bootstrap"][str(step)]
        result[str(step)] = {
            "horizon_ordinal_increment_not_seconds": step,
            "models": {
                model: absolute[model]["position_error_mean"]
                for model in MODELS
            },
            "paired_candidate_minus_M0": {
                model: paired[f"{model}_minus_M0"]["position_error_mean"]
                for model in ("M1", "M2")
            },
        }
    return result


def decide(one_step: dict, paired: dict) -> dict:
    out = {}
    metric_by_family = PRIMARY_FAMILIES
    for candidate in ("M1", "M2"):
        family_status = {}
        qualifying_by_step = {}
        potential_by_step = {}
        for step in (1, 45):
            status = {}
            for family, metrics in metric_by_family.items():
                intervals = [paired[str(step)][candidate][metric]["paired_game_cluster_bootstrap_95_percentile_interval"]
                             for metric in metrics]
                if any(interval is None for interval in intervals):
                    status[family] = None
                else:
                    status[family] = all(interval[1] < 0.0 for interval in intervals)
            family_status[str(step)] = status
            qualifying_by_step[str(step)] = sum(value is True for value in status.values())
            potential_by_step[str(step)] = qualifying_by_step[str(step)] + sum(value is None for value in status.values())

        one_step_pct = one_step["models"][candidate]["relative_change_vs_M0_percent"]
        if one_step_pct > 2.0:
            verdict = "FAIL"
        elif all(qualifying_by_step[str(step)] >= 3 for step in (1, 45)):
            verdict = "GROUP_COHERENT"
        elif any(potential_by_step[str(step)] >= 3 for step in (1, 45)):
            verdict = "NOT_ESTIMABLE"
        else:
            verdict = "FAIL"
        out[candidate] = {
            "verdict": verdict,
            "relative_one_step_endpoint_change_percent": one_step_pct,
            "one_step_endpoint_limit_percent": 2.0,
            "group_family_status_by_primary_horizon": family_status,
            "qualifying_families_by_horizon": qualifying_by_step,
            "potential_families_including_unavailable_by_horizon": potential_by_step,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results_dir = ROOT / "research/nhl-multi-agent-movement-2026-10-23/results"
    prereg = ROOT / "docs/research/NHL-JOINT-COHERENCE-PREREG-2026-10-23.md"
    paths = {
        "scenario_archive": results_dir / "scenario_archive-bc91d1610de5.json.gz",
        "movement_comparison": results_dir / "movement_comparison-bc91d1610de5.json",
        "fold_models": results_dir / "fold_models-bc91d1610de5.json",
        "rollout_starts": args.data_dir / "rollout_starts.json.gz",
        "preregistration": prereg,
    }
    actual_hashes = {key: sha256(path) for key, path in paths.items()}
    expected = {
        "scenario_archive": INPUT_HASHES["scenario_archive_sha256"],
        "movement_comparison": INPUT_HASHES["movement_comparison_sha256"],
        "fold_models": INPUT_HASHES["fold_models_sha256"],
        "rollout_starts": INPUT_HASHES["rollout_starts_sha256"],
        "preregistration": PREREG_SHA256,
    }
    if actual_hashes != expected:
        raise RuntimeError(f"frozen input hash mismatch: {actual_hashes}")

    archive = load_gzip_json(paths["scenario_archive"])
    starts = load_gzip_json(paths["rollout_starts"])["starts"]
    base_metrics = json.loads(paths["movement_comparison"].read_text(encoding="utf-8"))
    games = list(base_metrics["games"])
    if len(games) != 10 or len(starts) != 200:
        raise RuntimeError(f"frozen population mismatch: {len(games)} games, {len(starts)} starts")
    counts = Counter(row["game"] for row in starts)
    if set(counts) != set(games) or any(counts[g] != 20 for g in games):
        raise RuntimeError(f"expected 20 starts in each of the ten games: {dict(counts)}")
    if archive["legendarypicks_git_commit"] != LP_PREDICTION_COMMIT:
        raise RuntimeError("archived prediction commit differs from preregistration")
    if archive["gridiron_physics_git_commit"] != GPH_CONTROLLER_COMMIT:
        raise RuntimeError("archived controller commit differs from preregistration")

    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in archive["scenarios"].values()}
    if len(scenario_by_id) != len(archive["scenarios"]):
        raise RuntimeError("duplicate archived scenario_id")
    start_ids = []
    for row in starts:
        expected_id = f"{row['game']}|{row['period']}|{row['cutoff_seq']}"
        if expected_id in start_ids:
            raise RuntimeError(f"duplicate frozen rollout start: {expected_id}")
        if expected_id not in scenario_by_id:
            raise RuntimeError(f"rollout start has no archived trajectory: {expected_id}")
        start_ids.append(expected_id)

    scenario_rows = []
    for scenario_id in start_ids:
        scenario = scenario_by_id[scenario_id]
        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        if len(frames) != 46 or any(step not in frames for step in range(46)):
            raise RuntimeError(f"{scenario_id}: expected archived cutoff plus 45 steps")
        for step in DIAGNOSTIC_HORIZONS:
            scenario_rows.append(score_state(scenario, frames[step], step))

    if not scenario_rows or any(sum(r["eligible"] for r in scenario_rows if r["horizon_ordinal_increment"] == h) > 200
                                for h in DIAGNOSTIC_HORIZONS):
        raise RuntimeError("invalid joint-scoring state population")

    rng = np.random.default_rng(SEED)
    draw_matrix = rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)))
    summary, paired = build_summary(scenario_rows, games, draw_matrix)
    one_step = load_one_step(paths["movement_comparison"])
    decisions = decide(one_step, paired)
    payload = {
        "schema_version": 1,
        "milestone": "JC",
        "status": "development-only measurement; no adoption",
        "preregistration": {
            "file": "docs/research/NHL-JOINT-COHERENCE-PREREG-2026-10-23.md",
            "sha256": PREREG_SHA256,
            "legendarypicks_commit": LP_PREREG_COMMIT,
            "gridiron_commit": GPH_PREREG_COMMIT,
        },
        "source_hashes": actual_hashes,
        "prediction_artifact_commits": {
            "legendarypicks": LP_PREDICTION_COMMIT,
            "gridiron_movement_controller": GPH_CONTROLLER_COMMIT,
        },
        "evaluation_code_sha256": sha256(Path(__file__).resolve()),
        "evaluation_environment": {"python": platform.python_version(), "numpy": np.__version__},
        "population": {
            "games": games,
            "game_count": len(games),
            "evaluation_design": "leave one whole game out; frozen prediction archive",
            "eligible_one_skater_windows": 454_983,
            "rollout_starts": len(start_ids),
            "starts_per_game": {game: counts[game] for game in games},
            "development_only": True,
            "independent_population_available": False,
            "timebase": "ordinal Image Id suffix increments; no validated seconds",
        },
        "specification": {
            "models": list(MODELS),
            "primary_horizons_ordinal_increments_not_seconds": list(PRIMARY_HORIZONS),
            "full_diagnostic_horizons_ordinal_increments_not_seconds": list(DIAGNOSTIC_HORIZONS),
            "bootstrap_draws": BOOTSTRAPS,
            "bootstrap_game_cluster_seed": SEED,
            "bootstrap_quantile_interpolation": "linear",
            "paired_game_weighting": "equal game; same 10-game draw matrix for all comparisons",
            "group_state_rule": "at least two common labeled skaters on each team",
            "predictors_or_policy_changes": "none; existing archived paths only",
            "signed_spacing_profiles_are_descriptive_only": True,
        },
        "one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds": one_step,
        "rollout_endpoint_radial_error_by_primary_horizon_ordinal_increment_not_seconds":
            load_rollout_endpoint_error(base_metrics),
        "per_horizon_ordinal_increment_not_seconds": summary,
        "paired_candidate_minus_M0_by_horizon_ordinal_increment_not_seconds": paired,
        "jc_decisions": decisions,
        "scenario_measurements": scenario_rows,
        "scenario_count_in_input_archive": len(archive["scenarios"]),
        "scenario_count_scored": len(start_ids),
        "randomness": "none in movement scoring; deterministic whole-game bootstrap only",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with args.output.open("xb") as f:
        f.write(encoded)
    print(json.dumps({"output": str(args.output), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "bytes": len(encoded), "scenarios": len(start_ids),
                      "group_scored_by_horizon": {str(h): summary[str(h)]["group_states"] for h in PRIMARY_HORIZONS},
                      "decisions": decisions}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
