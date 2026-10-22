#!/usr/bin/env python3
"""Fit deterministic, frame-index skater forecasts on the ten-game development release."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np


HORIZON = 15
INPUT_FRAMES = 6
RINK_X = (-100.0, 100.0)
RINK_Y = (-42.5, 42.5)
RIDGE_ALPHA = 0.1
BOUND_QUANTILE = 0.995
BOOTSTRAP_SEED = 20261022
BOOTSTRAP_REPLICATES = 10000


def frame_number(image_id: str) -> int:
    try:
        return int(image_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        raise ValueError("invalid Image Id: %r" % image_id)


def verify_release(data_dir: Path) -> None:
    manifest = json.loads((data_dir / "download-manifest.json").read_text(encoding="utf-8"))
    if len(manifest.get("files", [])) != manifest.get("asset_count"):
        raise RuntimeError("manifest asset_count mismatch")
    for index, asset in enumerate(manifest["files"], 1):
        path = data_dir / asset["name"]
        if not path.is_file() or path.stat().st_size != int(asset["bytes"]):
            raise RuntimeError("release asset missing or wrong size: %s" % path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().lower() != asset["sha256"].lower():
            raise RuntimeError("release asset changed after quality audit: %s" % path)
        print("verified model input asset %d/%d: %s" %
              (index, len(manifest["files"]), asset["name"]), flush=True)


def fit_ridge(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    design = np.column_stack((np.ones(len(z)), z))
    gram = design.T @ design / len(design)
    rhs = design.T @ y / len(design)
    penalty = np.eye(gram.shape[0]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    coef = np.linalg.solve(gram + penalty, rhs)
    return coef, mean, scale


def predict_ridge(model: tuple[np.ndarray, np.ndarray, np.ndarray],
                  x: np.ndarray) -> np.ndarray:
    coef, mean, scale = model
    return np.column_stack((np.ones(len(x)), (x - mean) / scale)) @ coef


def baseline_endpoint(features: np.ndarray, position: np.ndarray) -> np.ndarray:
    return position + HORIZON * features[:, :2]


def constrain_prediction(candidate: np.ndarray, position: np.ndarray,
                          current_velocity: np.ndarray, speed_limit: float,
                          acceleration_limit: float) -> np.ndarray:
    """Project average displacement velocity into speed and acceleration disks."""
    velocity = (candidate - position) / HORIZON
    v0_norm = np.linalg.norm(current_velocity, axis=1)
    v0_scale = np.minimum(1.0, speed_limit / np.maximum(v0_norm, 1e-12))
    v0 = current_velocity * v0_scale[:, None]
    direction = velocity - v0
    direction_norm = np.linalg.norm(direction, axis=1)
    delta_sq = np.sum(direction * direction, axis=1)
    dot = np.sum(v0 * direction, axis=1)
    c = np.sum(v0 * v0, axis=1) - speed_limit * speed_limit
    discriminant = np.maximum(0.0, (2.0 * dot) ** 2 - 4.0 * delta_sq * c)
    speed_lambda = np.ones(len(candidate))
    moving = delta_sq > 1e-16
    speed_lambda[moving] = (-2.0 * dot[moving] + np.sqrt(discriminant[moving])) / (
        2.0 * delta_sq[moving])
    acceleration_radius = acceleration_limit * HORIZON / 2.0
    acceleration_lambda = np.minimum(
        1.0, acceleration_radius / np.maximum(direction_norm, 1e-12))
    fraction = np.minimum(1.0, np.minimum(speed_lambda, acceleration_lambda))
    constrained_velocity = v0 + fraction[:, None] * direction
    endpoint = position + HORIZON * constrained_velocity
    endpoint[:, 0] = np.clip(endpoint[:, 0], *RINK_X)
    endpoint[:, 1] = np.clip(endpoint[:, 1], *RINK_Y)
    return endpoint


def angular_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    dot = np.sum(a * b, axis=1)
    return np.abs(np.arctan2(cross, dot))


def extract_examples(data_dir: Path, audit: dict, limit_files: int = 0) -> tuple[dict, dict]:
    files = sorted(data_dir.glob("*.Tracking_*.csv"))
    if len(files) != 33:
        raise RuntimeError("expected 33 tracking files, got %d" % len(files))
    period_audit = {row["file"]: row for row in audit["period_files"]}
    if limit_files:
        files = files[:limit_files]
    game_names = sorted(audit["games"])
    game_index = {name: idx for idx, name in enumerate(game_names)}
    capacity = sum(int(period_audit[path.name]["valid_windows"]) for path in files)
    if not limit_files and capacity != int(audit["overall"]["valid_windows"]):
        raise RuntimeError("audit window totals do not reconcile")

    features = np.empty((capacity, 4), dtype=np.float32)
    positions = np.empty((capacity, 2), dtype=np.float32)
    targets = np.empty((capacity, 2), dtype=np.float32)
    groups = np.empty(capacity, dtype=np.int8)
    eligible = np.ones(capacity, dtype=bool)
    used = 0
    all_conflicts = 0
    profiles: dict[tuple, dict] = {}

    time_axis = np.arange(INPUT_FRAMES, dtype=float)
    linear_design = np.column_stack((np.ones(INPUT_FRAMES), time_axis))
    linear_coeff = np.linalg.pinv(linear_design)
    quadratic_design = np.column_stack((np.ones(INPUT_FRAMES), time_axis, time_axis ** 2))
    quadratic_coeff = np.linalg.pinv(quadratic_design)
    first_half_design = np.column_stack((np.ones(3), np.arange(3, dtype=float)))
    first_half_coeff = np.linalg.pinv(first_half_design)
    last_half_design = np.column_stack((np.ones(3), np.arange(3, dtype=float)))
    last_half_coeff = np.linalg.pinv(last_half_design)

    for file_no, path in enumerate(files, 1):
        game = path.name.split(".Tracking_", 1)[0]
        if game not in game_index or path.name not in period_audit:
            raise RuntimeError("tracking file missing from audited population: %s" % path.name)
        file_gate = period_audit[path.name]
        first_frame = int(file_gate["start_frame"])
        last_frame = int(file_gate["end_frame"])
        split_frame = (first_frame + last_frame) / 2.0
        histories: dict[tuple, list[tuple[int, float, float]]] = {}
        last_target: dict[tuple, int] = {}
        current_players: dict[tuple, tuple[float, float]] = {}
        current = None
        jersey_map: dict[tuple, set[str]] = collections.defaultdict(set)
        conflicted: set[tuple] = set()
        prior_indices: dict[tuple, list[int]] = collections.defaultdict(list)
        observed_frame_count: collections.Counter = collections.Counter()
        file_profile: dict[tuple, dict] = {}
        file_used_start = used

        def finish_frame() -> None:
            nonlocal current_players, current, used
            if current is None:
                return
            for entity_key in list(histories):
                if entity_key not in current_players:
                    histories[entity_key] = []
                    last_target.pop(entity_key, None)
            for entity_key, (x, y) in current_players.items():
                base = entity_key[:3]
                if base not in conflicted:
                    observed_frame_count[base] += 1
                series = histories.setdefault(entity_key, [])
                if series and current["seq"] - series[-1][0] != 1:
                    series.clear()
                    last_target.pop(entity_key, None)
                series.append((current["seq"], x, y))
                if len(series) > 21:
                    del series[:-21]
                if len(series) != 21 or (entity_key in last_target and
                                         current["seq"] - last_target[entity_key] < HORIZON):
                    continue

                xy = np.asarray([(point[1], point[2]) for point in series], dtype=float)
                input_xy = xy[:INPUT_FRAMES]
                lin = linear_coeff @ input_xy
                quad = quadratic_coeff @ input_xy
                velocity = lin[1]
                acceleration = 2.0 * quad[2]
                start_v = first_half_coeff @ input_xy[:3]
                end_v = last_half_coeff @ input_xy[3:]
                turn = float(angular_difference(start_v[1][None, :],
                                                end_v[1][None, :])[0] / 3.0)
                speed = float(np.linalg.norm(velocity))
                accel_mag = float(np.linalg.norm(acceleration))
                idx = used
                if idx >= capacity:
                    raise RuntimeError("extracted more windows than audited")
                features[idx] = (velocity[0], velocity[1], acceleration[0], acceleration[1])
                positions[idx] = xy[INPUT_FRAMES - 1]
                targets[idx] = xy[-1]
                groups[idx] = game_index[game]
                eligible[idx] = base not in conflicted
                if base not in conflicted:
                    prior_indices[base].append(idx)
                used += 1
                profile = file_profile.setdefault(base, {
                    "frames": 0, "first": {"speed": [], "accel": [], "turn": []},
                    "second": {"speed": [], "accel": [], "turn": []},
                })
                half = "first" if current["seq"] <= split_frame else "second"
                profile[half]["speed"].append(speed)
                profile[half]["accel"].append(accel_mag)
                if np.linalg.norm(start_v[1]) > 0.1 and np.linalg.norm(end_v[1]) > 0.1:
                    profile[half]["turn"].append(turn)
                last_target[entity_key] = current["seq"]
            current_players = {}
            current = None

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"Image Id", "Player or Puck", "Team", "Player Id", "Player Jersey Number",
                        "Rink Location X (Feet)", "Rink Location Y (Feet)"}
            if not required.issubset(reader.fieldnames or []):
                raise RuntimeError("tracking schema changed in %s" % path)
            for line_no, row in enumerate(reader, 2):
                image = (row["Image Id"] or "").strip()
                seq = frame_number(image)
                if current is None or image != current["image"]:
                    finish_frame()
                    current = {"image": image, "seq": seq}
                if (row["Player or Puck"] or "").strip() != "Player":
                    continue
                team = (row["Team"] or "").strip()
                track_id = (row["Player Id"] or "").strip()
                jersey = (row["Player Jersey Number"] or "").strip()
                if not track_id or not jersey:
                    continue
                base = (team, track_id, "")
                jersey_map[base].add(jersey)
                if len(jersey_map[base]) > 1 and base not in conflicted:
                    conflicted.add(base)
                    all_conflicts += 1
                    for idx in prior_indices.pop(base, []):
                        eligible[idx] = False
                try:
                    x = float(row["Rink Location X (Feet)"])
                    y = float(row["Rink Location Y (Feet)"])
                except (TypeError, ValueError):
                    continue
                if not (math.isfinite(x) and math.isfinite(y) and
                        RINK_X[0] <= x <= RINK_X[1] and RINK_Y[0] <= y <= RINK_Y[1]):
                    continue
                entity_key = (team, track_id, "", jersey)
                if entity_key in current_players:
                    raise RuntimeError("duplicate track/jersey row at %s:%d" % (path.name, line_no))
                current_players[entity_key] = (x, y)
        finish_frame()

        for base, count in observed_frame_count.items():
            stable_profile = file_profile.setdefault(base, {
                "frames": 0, "first": {"speed": [], "accel": [], "turn": []},
                "second": {"speed": [], "accel": [], "turn": []},
            })
            stable_profile["frames"] = count
            if base not in conflicted:
                jersey = next(iter(jersey_map[base]))
                profiles[(game, path.name, base[0], base[1], jersey)] = stable_profile
        observed_conflicts = len(conflicted)
        if observed_conflicts != int(file_gate["identity_conflicts"]):
            raise RuntimeError("identity conflict count differs from quality audit for %s: %d != %d" %
                               (path.name, observed_conflicts, file_gate["identity_conflicts"]))
        file_used = used - file_used_start
        if file_used != int(file_gate["valid_windows"]):
            raise RuntimeError("window count differs from quality audit for %s: %d != %d" %
                               (path.name, file_used, file_gate["valid_windows"]))
        print("extracted %d/%d: %s (%d windows; %d conflicted IDs)" %
              (file_no, len(files), path.name, file_used, observed_conflicts), flush=True)

    if used != capacity:
        raise RuntimeError("extracted window population differs from audit: %d != %d" %
                           (used, capacity))
    expected_conflicts = sum(int(period_audit[path.name]["identity_conflicts"]) for path in files)
    if all_conflicts != expected_conflicts:
        raise RuntimeError("conflicted identity population differs from audit")
    eligible_count = int(eligible.sum())
    data = {
        "features": features[:used][eligible], "position": positions[:used][eligible],
        "target": targets[:used][eligible], "group": groups[:used][eligible],
        "game_names": game_names, "eligible_windows": eligible_count,
        "raw_windows": used, "conflicted_ids": all_conflicts,
        "excluded_windows": used - eligible_count,
    }
    return data, profiles


def sample_radius(errors: np.ndarray) -> float:
    ordered = np.sort(errors)
    rank = min(len(ordered), max(1, math.ceil(0.90 * (len(ordered) + 1))))
    return float(ordered[rank - 1])


def score_predictions(target: np.ndarray, position: np.ndarray,
                      prediction: np.ndarray) -> dict:
    error = np.linalg.norm(prediction - target, axis=1)
    target_disp = target - position
    predicted_disp = prediction - position
    target_mag = np.linalg.norm(target_disp, axis=1)
    pred_mag = np.linalg.norm(predicted_disp, axis=1)
    heading_mask = target_mag >= 1.0
    heading = angular_difference(target_disp[heading_mask], predicted_disp[heading_mask])
    return {
        "position_error_mean_ft": float(np.mean(error)),
        "position_error_median_ft": float(np.median(error)),
        "position_error_p90_ft": float(np.quantile(error, 0.90)),
        "displacement_magnitude_error_mean_ft_per_15_image_id_increments": float(np.mean(np.abs(pred_mag - target_mag))),
        "heading_error_mean_degrees": float(np.degrees(np.mean(heading))) if len(heading) else None,
        "heading_examples": int(heading_mask.sum()),
        "examples": int(len(target)),
    }


def rankdata(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty(len(arr), dtype=float)
    ranks[order] = np.arange(len(arr), dtype=float)
    return ranks


def summarize_profiles(profiles: dict) -> dict:
    qualified = []
    for key, value in profiles.items():
        if value["frames"] < 3000:
            continue
        first, second = value["first"], value["second"]
        if min(len(first["speed"]), len(second["speed"])) < 100:
            continue
        row = {"n_frames": value["frames"]}
        for metric in ("speed", "accel", "turn"):
            if min(len(first[metric]), len(second[metric])) < 100:
                row[metric] = None
                continue
            if metric == "speed":
                row[metric] = (float(np.median(first[metric])), float(np.median(second[metric])))
            elif metric == "accel":
                row[metric] = (float(np.quantile(first[metric], 0.95)),
                               float(np.quantile(second[metric], 0.95)))
            else:
                row[metric] = (float(np.median(first[metric])), float(np.median(second[metric])))
        qualified.append(row)

    stability = {}
    for metric in ("speed", "accel", "turn"):
        pairs = [row[metric] for row in qualified if row[metric] is not None]
        if len(pairs) < 3:
            stability[metric] = {"n_entities": len(pairs), "spearman_split_half": None,
                                 "median_absolute_half_difference": None}
            continue
        first = [pair[0] for pair in pairs]
        second = [pair[1] for pair in pairs]
        corr = float(np.corrcoef(rankdata(first), rankdata(second))[0, 1])
        if not math.isfinite(corr):
            corr = None
        stability[metric] = {
            "n_entities": len(pairs), "spearman_split_half": corr,
            "median_absolute_half_difference": float(np.median(np.abs(np.asarray(first) - second))),
        }
    return {"qualified_track_period_entities": len(qualified), "metrics": stability}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path,
                        default=Path("/root/lp-research-data/stathletes-big-data-cup-2026"))
    parser.add_argument("--study-dir", type=Path,
                        default=Path(__file__).resolve().parent)
    parser.add_argument("--smoke-files", type=int, default=0,
                        help="extract only the first N files and exit without fitting")
    args = parser.parse_args()
    started = time.perf_counter()
    output_dir = args.study_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.study_dir / "quality" / "tracking_quality.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit["manifest"]["status"] != "PASS" or not all(
            audit["gates"][key] for key in ("release_integrity", "tracking_coordinate_validity",
                                            "forecast_window_coverage")):
        raise RuntimeError("required movement input gate failed")
    verify_release(args.data_dir)
    data, profiles = extract_examples(args.data_dir, audit, args.smoke_files)
    print("eligible windows %d/%d after excluding %d conflicted track-period IDs" %
          (data["eligible_windows"], data["raw_windows"], data["conflicted_ids"]), flush=True)
    if args.smoke_files:
        print(json.dumps({"status": "extraction-smoke-pass", "files": args.smoke_files,
                          "sample": {key: data[key] for key in
                                     ("raw_windows", "eligible_windows", "conflicted_ids", "excluded_windows")}},
                         indent=2, sort_keys=True))
        return
    windows_by_game = np.bincount(data["group"], minlength=len(data["game_names"]))
    if data["eligible_windows"] < 10000 or np.any(windows_by_game < 1000):
        raise RuntimeError("post-quarantine coverage fails: %d windows; per-game=%s" %
                           (data["eligible_windows"], windows_by_game.tolist()))

    x = data["features"].astype(float)
    position = data["position"].astype(float)
    target = data["target"].astype(float)
    group = data["group"].astype(int)
    games = data["game_names"]
    n = len(target)
    cv_pred = baseline_endpoint(x, position)
    ridge_pred = np.empty((n, 2), dtype=float)
    constrained_pred = np.empty((n, 2), dtype=float)
    radii = {"constant_velocity": {}, "learned_kinematic": {}, "constrained_kinematic": {}}
    by_game = {name: {} for name in games}
    fold_models = []

    for fold, test_game in enumerate(games):
        test_mask = group == fold
        train_games = [idx for idx in range(len(games)) if idx != fold]
        calibration_game = (fold + 1) % len(games)
        fit_games = [idx for idx in train_games if idx != calibration_game]
        fit_mask = np.isin(group, fit_games)
        calibration_mask = group == calibration_game
        train_mask = ~test_mask
        cv_cal_error = np.linalg.norm(cv_pred[calibration_mask] - target[calibration_mask], axis=1)
        radii["constant_velocity"][test_game] = sample_radius(cv_cal_error)

        residual = target - cv_pred
        calibration_model = fit_ridge(x[fit_mask], residual[fit_mask])
        calibration_pred = cv_pred[calibration_mask] + predict_ridge(calibration_model, x[calibration_mask])
        calibration_error = np.linalg.norm(calibration_pred - target[calibration_mask], axis=1)
        radii["learned_kinematic"][test_game] = sample_radius(calibration_error)
        v_limit_cal = float(np.quantile(np.linalg.norm(x[fit_mask, :2], axis=1), BOUND_QUANTILE))
        a_limit_cal = float(np.quantile(np.linalg.norm(x[fit_mask, 2:4], axis=1), BOUND_QUANTILE))
        calibration_constrained = constrain_prediction(
            calibration_pred, position[calibration_mask], x[calibration_mask, :2],
            v_limit_cal, a_limit_cal)
        calibration_constrained_error = np.linalg.norm(
            calibration_constrained - target[calibration_mask], axis=1)
        radii["constrained_kinematic"][test_game] = sample_radius(calibration_constrained_error)

        final_model = fit_ridge(x[train_mask], residual[train_mask])
        ridge_pred[test_mask] = cv_pred[test_mask] + predict_ridge(final_model, x[test_mask])
        v_limit = float(np.quantile(np.linalg.norm(x[train_mask, :2], axis=1), BOUND_QUANTILE))
        a_limit = float(np.quantile(np.linalg.norm(x[train_mask, 2:4], axis=1), BOUND_QUANTILE))
        constrained_pred[test_mask] = constrain_prediction(
            ridge_pred[test_mask], position[test_mask], x[test_mask, :2], v_limit, a_limit)
        fold_models.append({"heldout_game": test_game, "calibration_game": games[calibration_game],
                            "fit_games_for_calibration": len(fit_games),
                            "fit_games_for_test": len(train_games),
                            "speed_limit_ft_per_image_id_increment": v_limit,
                            "acceleration_limit_ft_per_image_id_increment2": a_limit})

        for name, prediction in (("constant_velocity", cv_pred),
                                 ("learned_kinematic", ridge_pred),
                                 ("constrained_kinematic", constrained_pred)):
            by_game[test_game][name] = score_predictions(
                target[test_mask], position[test_mask], prediction[test_mask])
            error = np.linalg.norm(prediction[test_mask] - target[test_mask], axis=1)
            by_game[test_game][name]["prediction_radius_90_ft"] = radii[name][test_game]
            by_game[test_game][name]["prediction_radius_coverage"] = float(
                np.mean(error <= radii[name][test_game]))
        print("scored outer fold %d/%d: %s" % (fold + 1, len(games), test_game), flush=True)

    candidate_names = ["constant_velocity", "learned_kinematic", "constrained_kinematic"]
    metric_names = ["position_error_mean_ft", "position_error_median_ft", "position_error_p90_ft",
                    "displacement_magnitude_error_mean_ft_per_15_image_id_increments",
                    "heading_error_mean_degrees", "prediction_radius_coverage"]
    overall = {}
    for candidate in candidate_names:
        overall[candidate] = {}
        for metric in metric_names:
            values = [by_game[game][candidate][metric] for game in games
                      if by_game[game][candidate][metric] is not None]
            overall[candidate][metric + "_equal_game_mean"] = float(np.mean(values))

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bootstrap_indices = rng.integers(0, len(games), size=(BOOTSTRAP_REPLICATES, len(games)))
    intervals = {}
    for left, right in (("learned_kinematic", "constant_velocity"),
                        ("constrained_kinematic", "learned_kinematic"),
                        ("constrained_kinematic", "constant_velocity")):
        intervals[left + "_minus_" + right] = {}
        for metric in metric_names:
            left_vals = np.array([by_game[g][left][metric] for g in games], dtype=float)
            right_vals = np.array([by_game[g][right][metric] for g in games], dtype=float)
            delta = left_vals - right_vals
            draws = np.mean(delta[bootstrap_indices], axis=1)
            intervals[left + "_minus_" + right][metric] = {
                "equal_game_mean_delta": float(np.mean(delta)),
                "bootstrap_95_percentile_interval": [float(np.quantile(draws, 0.025)),
                                                       float(np.quantile(draws, 0.975))],
            }

    profiles_summary = summarize_profiles(profiles)
    summary = {
        "study": "NHL ten-game frame-index kinematics comparison",
        "protocol": "docs/research/NHL-TEN-GAME-KINEMATICS-PREDICTION-PROTOCOL-2026-10-22.md",
        "development_games": games,
        "quality_gate_disposition": audit["gates"],
        "sample": {"raw_windows": data["raw_windows"], "eligible_windows": data["eligible_windows"],
                   "excluded_conflicted_track_period_ids": data["conflicted_ids"],
                   "excluded_windows": data["excluded_windows"],
                   "windows_by_game": {g: int(windows_by_game[i]) for i, g in enumerate(games)}},
        "candidates": overall,
        "paired_game_cluster_bootstrap_differences": intervals,
        "by_game": by_game,
        "outer_folds": fold_models,
        "player_movement_reliability": profiles_summary,
        "runtime_seconds_total_including_release_hash_and_extraction": round(time.perf_counter() - started, 3),
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
                      "unit": "whole game"},
        "interpretation_limit": "15 Image Id increments; no validated conversion to elapsed seconds.",
    }
    out_json = output_dir / "kinematics_model_comparison.json"
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    columns = ["game", "candidate"] + metric_names + ["examples"]
    csv_rows = [",".join(columns)]
    for game in games:
        for candidate in candidate_names:
            result = by_game[game][candidate]
            csv_rows.append(",".join([game, candidate] +
                                     ["" if result.get(name) is None else str(result[name])
                                      for name in metric_names] + [str(result["examples"])]))
    (output_dir / "kinematics_scores_by_game.csv").write_text("\n".join(csv_rows) + "\n", encoding="utf-8")
    print(json.dumps({"sample": summary["sample"], "candidates": overall,
                      "paired_differences": intervals,
                      "player_movement_reliability": profiles_summary,
                      "runtime_seconds": summary["runtime_seconds_total_including_release_hash_and_extraction"],
                      "output": str(out_json)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
