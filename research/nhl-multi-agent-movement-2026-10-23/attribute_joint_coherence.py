#!/usr/bin/env python3
"""Read-only, deterministic attribution of the frozen NHL JC spacing failure."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "research/nhl-multi-agent-movement-2026-10-23/results"
DATA = Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23")
PREREG = ROOT / "docs/research/NHL-JC-ATTRIBUTION-PREREG-2026-10-23.md"
PREREG_SHA256 = "c9e3da3ca12ff5197e3ed5b9eed9775548a85b6c427d60465641d28ac1c5bd4c"
PREREG_COMMIT = "02714e04ced87df97ae394387d98bb7dc0b32c93"
BASE_COMMIT = "f147e67fa42b3f878674db6b9f018150934a37ed"
JC_SHA256 = "0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c"
EXPECTED_HASHES = {
    "jc_results": JC_SHA256,
    "movement_comparison": "1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8",
    "fold_models": "194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a",
    "scenario_archive": "a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce",
    "rollout_starts": "07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de",
    "preregistration": PREREG_SHA256,
}
PATHS = {
    "jc_results": RESULTS / "joint-coherence-jc-2026-10-23-v1.json",
    "movement_comparison": RESULTS / "movement_comparison-bc91d1610de5.json",
    "fold_models": RESULTS / "fold_models-bc91d1610de5.json",
    "scenario_archive": RESULTS / "scenario_archive-bc91d1610de5.json.gz",
    "rollout_starts": DATA / "rollout_starts.json.gz",
    "preregistration": PREREG,
}
MODELS = ("M0", "M1", "M2")
CANDIDATES = ("M1", "M2")
PRIMARY_HORIZONS = (1, 15, 30, 45)
PAIR_QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
BOOTSTRAPS = 10_000
BOOTSTRAP_SEED = 20261024
ROLE_FIELDS = ("position", "position_group", "role", "player_role", "position_code")
ACTIVITY_TERMS = ("touch", "affected", "projected", "adjusted", "constraint_activity")
ID_TERMS = ("player", "track", "pair", "skater", "entity", "ids")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def finite_xy(value: object) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2 and
            all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in value))


def qlinear(values: list[float] | np.ndarray, q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q, method="linear"))


def pair_values(ids: list[str], points: dict[str, np.ndarray]):
    for first, second in combinations(ids, 2):
        yield first, second, points[first] - points[second]


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    left = 0
    while left < len(values):
        right = left + 1
        while right < len(values) and sorted_values[right] == sorted_values[left]:
            right += 1
        ranks[order[left:right]] = (left + 1 + right) / 2.0
        left = right
    return ranks


def spearman(x: list[float] | np.ndarray, y: list[float] | np.ndarray) -> float | None:
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    if len(xa) != len(ya) or len(xa) < 2 or np.ptp(xa) == 0 or np.ptp(ya) == 0:
        return None
    rx, ry = average_ranks(xa), average_ranks(ya)
    value = float(np.corrcoef(rx, ry)[0, 1])
    return value if math.isfinite(value) else None


def bootstrap_interval(game_values: dict[str, float | None], games: list[str], draws: np.ndarray):
    present = [g for g in games if game_values.get(g) is not None]
    values = [float(game_values[g]) for g in present]
    point = float(np.mean(values)) if values else None
    if len(present) != len(games):
        return point, None
    array = np.asarray([float(game_values[g]) for g in games], dtype=np.float64)
    boot = array[draws].mean(axis=1)
    return point, [qlinear(boot, 0.025), qlinear(boot, 0.975)]


def grouped_game_means(rows: list[dict], value_key: str, games: list[str]):
    buckets: dict[str, list[float]] = {g: [] for g in games}
    by_start: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        by_start[(row["game"], row["start_id"])].append(float(value))
    for (game, _start), values in by_start.items():
        buckets[game].append(float(np.mean(values)))
    return {g: float(np.mean(buckets[g])) if buckets[g] else None for g in games}


def summarize_rows(rows: list[dict], value_key: str, games: list[str], draws: np.ndarray,
                   *, pair_count_key: str | None = None) -> dict:
    game_means = grouped_game_means(rows, value_key, games)
    point, interval = bootstrap_interval(game_means, games, draws)
    by_start: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row.get(value_key) is None:
            continue
        key = (row["game"], row["start_id"])
        rec = by_start.setdefault(key, {"pairs": 0})
        rec["pairs"] += int(row.get(pair_count_key, 0)) if pair_count_key else 0
    pair_by_game = {g: sum(rec["pairs"] for (game, _), rec in by_start.items() if game == g) for g in games}
    return {
        "equal_game_mean_available_games": point,
        "bootstrap_95_percentile_interval": interval,
        "game_means": game_means,
        "scored_starts": len(by_start),
        "games_with_values": sum(game_means[g] is not None for g in games),
        "pair_count_total": sum(pair_by_game.values()) if pair_count_key else None,
        "pair_count_by_game": pair_by_game if pair_count_key else None,
        "mean_pairs_per_scored_start": (sum(pair_by_game.values()) / len(by_start)
                                         if pair_count_key and by_start else None),
    }


def pair_differences(rows_by_model: dict[str, list[dict]], value_key: str,
                     games: list[str], draws: np.ndarray, pair_count_key: str | None = None) -> dict:
    result = {}
    for candidate in CANDIDATES:
        base = {(r["game"], r["start_id"]): r for r in rows_by_model["M0"] if r.get(value_key) is not None}
        cand = {(r["game"], r["start_id"]): r for r in rows_by_model[candidate] if r.get(value_key) is not None}
        if base.keys() != cand.keys():
            raise RuntimeError(f"paired support mismatch for {candidate} / {value_key}")
        paired = []
        for key in sorted(base):
            paired.append({
                "game": key[0], "start_id": key[1],
                "delta": float(cand[key][value_key] - base[key][value_key]),
                "pair_count": min(int(cand[key].get(pair_count_key, 0)), int(base[key].get(pair_count_key, 0)))
                if pair_count_key else 0,
            })
        summary = summarize_rows(paired, "delta", games, draws,
                                 pair_count_key="pair_count" if pair_count_key else None)
        summary.pop("pair_count_by_game", None)
        result[candidate] = summary
    return result


def group_cell_summary(rows_by_model: dict[str, list[dict]], games: list[str], draws: np.ndarray) -> dict:
    metric_map = {
        "signed_pair_bias_ft": "signed",
        "absolute_cell_bias_ft": "absolute_cell",
        "mean_absolute_pair_error_ft": "pair_absolute",
    }
    out = {"model_estimates": {}, "paired_candidate_minus_M0": {}}
    for model in MODELS:
        out["model_estimates"][model] = {
            metric: summarize_rows(rows_by_model[model], field, games, draws, pair_count_key="pair_count")
            for metric, field in metric_map.items()
        }
    for metric, field in metric_map.items():
        out["paired_candidate_minus_M0"][metric] = pair_differences(
            rows_by_model, field, games, draws, pair_count_key="pair_count")
    return out


def explicit_role(row: dict) -> str | None:
    for key in ROLE_FIELDS:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().upper()
        if normalized in {"D", "DEF", "DEFENSE", "DEFENCE"}:
            return "D"
        if normalized in {"F", "FWD", "FORWARD"}:
            return "F"
    return None


def walk_dicts(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk_dicts(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_dicts(value, f"{path}[{index}]")


def candidate_activity_labels(archive: dict, comparison: dict) -> dict:
    found = []
    for scenario in archive["scenarios"].values():
        for frame in scenario.get("frames", []):
            for model in ("M1", "M2"):
                tree = frame.get("models", {}).get(model, {})
                for path, obj in walk_dicts(tree, f"frame.models.{model}"):
                    for key, value in obj.items():
                        name = key.lower()
                        label_word = any(term in name for term in ACTIVITY_TERMS)
                        id_word = any(term in name for term in ID_TERMS)
                        if label_word and id_word and isinstance(value, (dict, list, tuple, set)):
                            found.append(f"{path}.{key}")
    sample_constraints = []
    for path, obj in walk_dicts(comparison, "movement_comparison"):
        for key, value in obj.items():
            name = key.lower()
            if any(term in name for term in ACTIVITY_TERMS) and any(term in name for term in ID_TERMS):
                if isinstance(value, (dict, list, tuple, set)):
                    found.append(f"{path}.{key}")
    for index, sample in enumerate(comparison.get("rollout_samples", [])):
        constraints = sample.get("constraints")
        if isinstance(constraints, dict):
            sample_constraints.extend(sorted(constraints))
            for path, obj in walk_dicts(constraints, f"rollout_samples[{index}].constraints"):
                for key, value in obj.items():
                    name = key.lower()
                    if any(term in name for term in ACTIVITY_TERMS) and any(term in name for term in ID_TERMS):
                        if isinstance(value, (dict, list, tuple, set)):
                            found.append(f"{path}.{key}")
    return {
        "frame_model_fields": sorted({key for scenario in archive["scenarios"].values()
                                      for frame in scenario.get("frames", [])
                                      for model in ("M1", "M2")
                                      for key in frame.get("models", {}).get(model, {})}),
        "comparison_constraint_fields": sorted(set(sample_constraints)),
        "explicit_player_or_pair_activity_label_paths": sorted(set(found)),
        "linkable_activity_labels_found": bool(found),
        "interpretation": ("explicit player/pair activity labels are present; inspect reported paths"
                           if found else
                           "no per-player/per-pair constraint-activity labels found in frozen M1/M2 frames or comparison samples"),
    }


def format_estimate(result: dict) -> str:
    value = result.get("equal_game_mean_available_games")
    ci = result.get("bootstrap_95_percentile_interval")
    if value is None:
        return "not estimable"
    return f"{value:.6f}" + (f" [{ci[0]:.6f}, {ci[1]:.6f}]" if ci else " [interval unavailable]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=RESULTS / "jc-attribution-jcdiag-2026-10-23-v1.json")
    args = parser.parse_args()

    actual_hashes = {name: sha256_file(path) for name, path in PATHS.items()}
    if actual_hashes != EXPECTED_HASHES:
        raise RuntimeError(f"frozen-input provenance mismatch; expected {EXPECTED_HASHES}, got {actual_hashes}")
    jc = load_json(PATHS["jc_results"])
    if jc.get("source_hashes", {}).get("scenario_archive") != EXPECTED_HASHES["scenario_archive"]:
        raise RuntimeError("JC result records a different frozen scenario archive")
    if jc.get("source_hashes", {}).get("movement_comparison") != EXPECTED_HASHES["movement_comparison"]:
        raise RuntimeError("JC result records a different frozen movement comparison")
    if jc.get("source_hashes", {}).get("fold_models") != EXPECTED_HASHES["fold_models"]:
        raise RuntimeError("JC result records different frozen fold models")
    if jc.get("source_hashes", {}).get("rollout_starts") != EXPECTED_HASHES["rollout_starts"]:
        raise RuntimeError("JC result records a different rollout-start manifest")
    if jc.get("preregistration", {}).get("sha256") != "5ec697c63d80a1afe3ee2cb95b2c7a30ea633c0a9fb7ff9483983e2bd1501773":
        raise RuntimeError("JC result does not reference the frozen JC preregistration")

    games = list(jc["population"]["games"])
    if len(games) != 10:
        raise RuntimeError(f"expected ten frozen game clusters, found {len(games)}")
    measurement_rows = jc["scenario_measurements"]
    if len(measurement_rows) != 200 * 45:
        raise RuntimeError(f"expected 9,000 frozen start/horizon rows, found {len(measurement_rows)}")

    # Recompute the seven scalar checks enumerated by the task (it calls them six).
    expected_values = {
        "one_step_radial_M0_ft": 3.2222,
        "one_step_radial_M1_ft": 3.1186,
        # Manager correction 2026-10-23: use the frozen artifact's
        # one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds.models.M2.equal_game_mean_ft.
        "one_step_radial_M2_ft": 3.1045,
        "plus45_team_spacing_delta_M1_ft": 0.9365,
        "plus45_team_spacing_delta_M2_ft": 0.9445,
        "plus45_pooled_centroid_delta_M1_ft": -1.8550,
        "plus1_team_spacing_delta_M2_ft": 0.0139,
    }
    one_step = jc["one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds"]["models"]
    computed_values = {
        f"one_step_radial_{model}_ft": statistics.fmean(float(x) for x in one_step[model]["per_game_mean_ft"].values())
        for model in MODELS
    }
    corrected_m2_artifact_value = float(one_step["M2"]["equal_game_mean_ft"])
    if not math.isclose(computed_values["one_step_radial_M2_ft"], corrected_m2_artifact_value,
                        rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError(
            "recomputed M2 one-step radial mean differs from the artifact's equal_game_mean_ft: "
            f"{computed_values['one_step_radial_M2_ft']!r} vs {corrected_m2_artifact_value!r}"
        )
    scenarios_by_horizon = {(row["scenario_id"], row["horizon_ordinal_increment"]): row
                            for row in measurement_rows}
    if len(scenarios_by_horizon) != len(measurement_rows):
        raise RuntimeError("duplicate scenario/horizon records in frozen JC artifact")

    def paired_published_delta(horizon: int, candidate: str, metric: str) -> float:
        buckets: dict[str, list[float]] = {game: [] for game in games}
        for row in measurement_rows:
            if row["horizon_ordinal_increment"] != horizon or not row["eligible"]:
                continue
            values = row["models"]
            buckets[row["game"]].append(float(values[candidate][metric]) - float(values["M0"][metric]))
        if any(not buckets[game] for game in games):
            raise RuntimeError(f"provenance delta lacks one or more game clusters at +{horizon}")
        return statistics.fmean(statistics.fmean(buckets[game]) for game in games)

    computed_values["plus45_team_spacing_delta_M1_ft"] = paired_published_delta(45, "M1", "team_spacing_error_ft")
    computed_values["plus45_team_spacing_delta_M2_ft"] = paired_published_delta(45, "M2", "team_spacing_error_ft")
    computed_values["plus45_pooled_centroid_delta_M1_ft"] = paired_published_delta(45, "M1", "centroid_pooled_error_ft")
    computed_values["plus1_team_spacing_delta_M2_ft"] = paired_published_delta(1, "M2", "team_spacing_error_ft")

    print(f"PROVENANCE jc_results sha256={actual_hashes['jc_results']} PASS")
    checks = []
    for name, expected in expected_values.items():
        actual = computed_values[name]
        passed = abs(actual - expected) < 0.00005
        print(f"PROVENANCE {name}: recomputed={actual:.4f} expected={expected:+.4f} {'PASS' if passed else 'FAIL'}")
        checks.append({"name": name, "recomputed": actual, "expected": expected, "passed": passed})
    if not all(row["passed"] for row in checks):
        raise RuntimeError("published JC provenance assertion failed; attribution was not run")

    # Only after the frozen-value gate do we parse trajectory and comparison records.
    archive = load_gzip_json(PATHS["scenario_archive"])
    comparison = load_json(PATHS["movement_comparison"])
    starts = load_gzip_json(PATHS["rollout_starts"])["starts"]
    if len(starts) != 200:
        raise RuntimeError(f"rollout-start manifest size mismatch: {len(starts)}")
    start_ids = [f"{row['game']}|{row['period']}|{row['cutoff_seq']}" for row in starts]
    if len(set(start_ids)) != len(start_ids):
        raise RuntimeError("duplicate rollout start IDs in frozen start manifest")
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in archive["scenarios"].values()}
    if len(scenario_by_id) != len(archive["scenarios"]):
        raise RuntimeError("duplicate scenario IDs in frozen scenario archive")
    if set(start_ids) - scenario_by_id.keys():
        raise RuntimeError("one or more frozen starts are absent from the frozen scenario archive")
    jc_by_key = {(row["scenario_id"], int(row["horizon_ordinal_increment"])): row for row in measurement_rows}
    if set(jc_by_key) != {(sid, step) for sid in start_ids for step in range(1, 46)}:
        raise RuntimeError("JC measurement grid does not match the 200 starts x 45 horizons")

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.integers(0, len(games), size=(BOOTSTRAPS, len(games)), dtype=np.int16)

    role_keys_seen = set()
    role_labels_seen = set()
    cutoff_player_keys_seen = set()
    per_start_state: dict[tuple[str, int], dict] = {}
    q1_inputs: dict[tuple[int, str, str], dict[str, list[dict]]] = {}
    q2_start: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    q3_model_rows: dict[tuple[int, str, str, str], list[dict]] = defaultdict(list)
    group_reproduction_checks = []

    for sid in start_ids:
        scenario = scenario_by_id[sid]
        initial_rows = scenario["initial_state"]["players"]
        initial = {}
        team_by_id = {}
        role_by_id = {}
        for player in initial_rows:
            pid = player["id"]
            cutoff_player_keys_seen.update(player)
            if pid in initial:
                raise RuntimeError(f"duplicate cutoff track {sid}: {pid}")
            if player.get("team") not in {"Home", "Away"} or not finite_xy([player.get("x"), player.get("y")]):
                raise RuntimeError(f"invalid cutoff player in {sid}: {pid}")
            initial[pid] = np.asarray([player["x"], player["y"]], dtype=np.float64)
            team_by_id[pid] = player["team"]
            role_keys_seen.update(key for key in ROLE_FIELDS if key in player)
            role = explicit_role(player)
            if role is not None:
                role_by_id[pid] = role
                role_labels_seen.add(role)

        frames = {int(frame["step"]): frame for frame in scenario["frames"]}
        if set(frames) != set(range(46)):
            raise RuntimeError(f"invalid archived step grid for {sid}")

        for horizon in PRIMARY_HORIZONS + (2,):
            row = jc_by_key[(sid, horizon)]
            frame = frames[horizon]
            observed = frame.get("observed") or {}
            observed_players = observed.get("players") or {}
            model_players = {model: frame.get("models", {}).get(model, {}).get("players", {}) for model in MODELS}
            common = [pid for pid in initial if finite_xy(observed_players.get(pid)) and
                      all(finite_xy(model_players[m].get(pid)) for m in MODELS)]
            by_team = {team: [pid for pid in common if team_by_id[pid] == team] for team in ("Home", "Away")}
            eligible = all(len(by_team[team]) >= 2 for team in ("Home", "Away"))
            if bool(row["eligible"]) != eligible:
                raise RuntimeError(f"JC eligibility mismatch for {sid} +{horizon}")
            counts = row["counts"]
            expected_counts = {
                "common_skaters": len(common),
                "common_home_skaters": len(by_team["Home"]),
                "common_away_skaters": len(by_team["Away"]),
                "home_within_team_pairs": len(by_team["Home"]) * (len(by_team["Home"]) - 1) // 2,
                "away_within_team_pairs": len(by_team["Away"]) * (len(by_team["Away"]) - 1) // 2,
            }
            if any(int(counts[key]) != value for key, value in expected_counts.items()):
                raise RuntimeError(f"JC common-track/pair denominator mismatch for {sid} +{horizon}")
            if not eligible:
                continue

            observed_xy = {pid: np.asarray(observed_players[pid], dtype=np.float64) for pid in common}
            model_xy = {m: {pid: np.asarray(model_players[m][pid], dtype=np.float64) for pid in common}
                        for m in MODELS}
            start_id = sid
            per_start_state[(sid, horizon)] = {
                "game": scenario["game"], "start_id": start_id, "horizon": horizon,
                "common_ids": common, "observed": observed_xy, "models": model_xy,
                "teams": by_team, "roles": role_by_id,
            }

            q1_cells = {}
            for cell in ("Home", "Away", "ALL"):
                ids = common if cell == "ALL" else by_team[cell]
                q1_cells[("team", cell)] = {m: [] for m in MODELS}
            for pair_type in ("DD", "DF", "FF"):
                q1_cells[("role", pair_type)] = {m: [] for m in MODELS}
                for team in ("Home", "Away"):
                    q1_cells[("team_role", f"{team}_{pair_type}")] = {m: [] for m in MODELS}

            axis_by_team = {team: {m: {axis: [] for axis in ("x", "y")} for m in MODELS}
                            for team in ("Home", "Away")}
            errors_by_model = {m: [] for m in MODELS}
            for team in ("Home", "Away"):
                ids = by_team[team]
                for first, second, observed_delta in pair_values(ids, observed_xy):
                    observed_distance = float(np.linalg.norm(observed_delta))
                    pair_type = None
                    role1, role2 = role_by_id.get(first), role_by_id.get(second)
                    if role1 in {"D", "F"} and role2 in {"D", "F"}:
                        pair_type = "DD" if role1 == role2 == "D" else "FF" if role1 == role2 == "F" else "DF"
                    for model in MODELS:
                        sim_delta = model_xy[model][first] - model_xy[model][second]
                        signed = float(np.linalg.norm(sim_delta) - observed_distance)
                        abs_pair = abs(signed)
                        q1_cells[("team", team)][model].append((signed, abs_pair))
                        q1_cells[("team", "ALL")][model].append((signed, abs_pair))
                        errors_by_model[model].append(signed)
                        for axis_index, axis in enumerate(("x", "y")):
                            axis_by_team[team][model][axis].append(
                                float(abs(sim_delta[axis_index]) - abs(observed_delta[axis_index])))
                        if pair_type is not None:
                            q1_cells[("role", pair_type)][model].append((signed, abs_pair))
                            q1_cells[("team_role", f"{team}_{pair_type}")][model].append((signed, abs_pair))

            for cell_key, by_model_pairs in q1_cells.items():
                category, label = cell_key
                rows_by_model = q1_inputs.setdefault((horizon, category, label), {m: [] for m in MODELS})
                for model in MODELS:
                    values = by_model_pairs[model]
                    if not values:
                        continue
                    signed_mean = float(np.mean([v[0] for v in values]))
                    rows_by_model[model].append({
                        "game": scenario["game"], "start_id": start_id,
                        "signed": signed_mean,
                        "absolute_cell": abs(signed_mean),
                        "pair_absolute": float(np.mean([v[1] for v in values])),
                        "pair_count": len(values),
                    })

            for model in MODELS:
                signed_errors = errors_by_model[model]
                abs_errors = [abs(value) for value in signed_errors]
                q2 = {
                    "game": scenario["game"], "start_id": start_id,
                    "signed_mean": float(np.mean(signed_errors)),
                    "absolute_mean": float(np.mean(abs_errors)),
                    "share_over": float(np.mean(np.asarray(signed_errors) > 0)),
                    "share_under": float(np.mean(np.asarray(signed_errors) < 0)),
                    "share_tie": float(np.mean(np.asarray(signed_errors) == 0)),
                    "pair_count": len(signed_errors),
                }
                for quantile in PAIR_QUANTILES:
                    q2[f"signed_q{int(quantile * 100):02d}"] = qlinear(signed_errors, quantile)
                    q2[f"absolute_q{int(quantile * 100):02d}"] = qlinear(abs_errors, quantile)
                q2_start[(horizon, "all_within_team_pairs", model)].append(q2)

            q3_cells = {"Home": {}, "Away": {}, "equal_team": {}}
            for cell in ("Home", "Away", "equal_team"):
                for model in MODELS:
                    q3_cells[cell][model] = {}
                    for axis in ("x", "y"):
                        if cell == "equal_team":
                            team_signed = []
                            team_abs = []
                            team_abs_bias = []
                            pair_count = 0
                            for team in ("Home", "Away"):
                                errors = axis_by_team[team][model][axis]
                                if not errors:
                                    raise RuntimeError(f"empty within-team axis pair set: {sid} +{horizon}")
                                team_signed.append(float(np.mean(errors)))
                                team_abs.append(float(np.mean(np.abs(errors))))
                                team_abs_bias.append(abs(float(np.mean(errors))))
                                pair_count += len(errors)
                            signed_value = float(np.mean(team_signed))
                            abs_value = float(np.mean(team_abs))
                            abs_bias_value = float(np.mean(team_abs_bias))
                        else:
                            errors = axis_by_team[cell][model][axis]
                            signed_value = float(np.mean(errors))
                            abs_value = float(np.mean(np.abs(errors)))
                            abs_bias_value = abs(signed_value)
                            pair_count = len(errors)
                        q3_cells[cell][model][f"{axis}_signed"] = signed_value
                        q3_cells[cell][model][f"{axis}_absolute"] = abs_value
                        q3_cells[cell][model][f"{axis}_absolute_bias"] = abs_bias_value
                        q3_cells[cell][model][f"{axis}_pair_count"] = pair_count

            for cell, by_model in q3_cells.items():
                for axis in ("x", "y"):
                    for model in MODELS:
                        q3_model_rows[(horizon, cell, axis, model)].append({
                            "game": scenario["game"], "start_id": start_id,
                            "signed": by_model[model][f"{axis}_signed"],
                            "absolute": by_model[model][f"{axis}_absolute"],
                            "absolute_bias": by_model[model][f"{axis}_absolute_bias"],
                            "pair_count": by_model[model][f"{axis}_pair_count"],
                        })

    if len([r for r in measurement_rows if r["horizon_ordinal_increment"] == 45 and r["eligible"]]) != 172:
        raise RuntimeError("frozen JC +45 group-scored population does not match the task's 172-start denominator")
    if any(per_start_state.get((sid, 45)) is None for sid in start_ids
           if jc_by_key[(sid, 45)]["eligible"]):
        raise RuntimeError("missing coordinate reconstruction for an eligible +45 JC start")

    # Q1: cell estimates, support, and paired candidate-minus-M0 differences.
    q1 = {"horizons_ordinal_increments_not_seconds": {}}
    all_q1_cells = [("team", x) for x in ("Home", "Away", "ALL")]
    all_q1_cells += [("role", x) for x in ("DD", "DF", "FF")]
    all_q1_cells += [("team_role", f"{team}_{kind}") for team in ("Home", "Away") for kind in ("DD", "DF", "FF")]
    for horizon in PRIMARY_HORIZONS:
        out = {"by_team": {}, "by_pair_type": {}, "by_team_and_pair_type": {}}
        for category, label in all_q1_cells:
            rows = q1_inputs.get((horizon, category, label), {m: [] for m in MODELS})
            summary = group_cell_summary(rows, games, draws)
            if category != "team" and not role_labels_seen:
                summary["status"] = "not estimable"
                summary["reason"] = "frozen cutoff records contain no explicit D/F roles; no role inference permitted"
            if category == "team":
                out["by_team"][label] = summary
            elif category == "role":
                out["by_pair_type"][label] = summary
            else:
                team, pair_type = label.split("_", 1)
                out["by_team_and_pair_type"].setdefault(team, {})[pair_type] = summary
        q1["horizons_ordinal_increments_not_seconds"][str(horizon)] = out
    q1["role_labels"] = {
        "fields_checked_on_frozen_cutoff_players": list(ROLE_FIELDS),
        "cutoff_player_schema_fields": sorted(cutoff_player_keys_seen),
        "fields_found": sorted(role_keys_seen),
        "recognized_labels_found": sorted(role_labels_seen),
        "status": "estimable from explicit frozen source labels" if role_labels_seen else "not estimable",
        "reason": None if role_labels_seen else
        "cutoff player schema contains no explicit D/F role field; role-based pair cells are unavailable, not inferred",
    }

    # Q2: per-start distribution summaries, averaged within game and then equally across games.
    q2 = {"horizons_ordinal_increments_not_seconds": {}}
    q2_metric_keys = ["signed_mean", "absolute_mean", "share_over", "share_under", "share_tie"]
    q2_metric_keys += [f"signed_q{int(q * 100):02d}" for q in PAIR_QUANTILES]
    q2_metric_keys += [f"absolute_q{int(q * 100):02d}" for q in PAIR_QUANTILES]
    for horizon in (1, 2, 45):
        models_out = {}
        for model in MODELS:
            rows = q2_start[(horizon, "all_within_team_pairs", model)]
            metrics = {key: summarize_rows(rows, key, games, draws, pair_count_key="pair_count") for key in q2_metric_keys}
            models_out[model] = {"metrics": metrics,
                                 "pair_count_total": sum(r["pair_count"] for r in rows),
                                 "scored_starts": len(rows),
                                 "pair_counts_by_game": {g: sum(r["pair_count"] for r in rows if r["game"] == g) for g in games}}
        q2["horizons_ordinal_increments_not_seconds"][str(horizon)] = {
            "within_team_pair_distribution": models_out,
            "aggregation": "per-start pair distribution, mean starts within game, equal weight across games",
        }

    # Q3: source-coordinate axis projections for within-team pair separation.
    q3 = {"horizons_ordinal_increments_not_seconds": {}}
    for horizon in PRIMARY_HORIZONS:
        cells = {}
        for cell in ("Home", "Away", "equal_team"):
            for axis in ("x", "y"):
                model_summaries = {}
                for model in MODELS:
                    model_rows = q3_model_rows[(horizon, cell, axis, model)]
                    model_summaries[model] = {
                        "signed_axis_error_ft": summarize_rows(model_rows, "signed", games, draws, pair_count_key="pair_count"),
                        "absolute_pair_axis_error_ft": summarize_rows(model_rows, "absolute", games, draws, pair_count_key="pair_count"),
                        "absolute_axis_bias_ft": summarize_rows(model_rows, "absolute_bias", games, draws, pair_count_key="pair_count"),
                    }
                model_summaries["paired_candidate_minus_M0_absolute_pair_axis_error_ft"] = pair_differences(
                    {m: q3_model_rows[(horizon, cell, axis, m)] for m in MODELS}, "absolute", games, draws,
                    pair_count_key="pair_count")
                cells.setdefault(cell, {})[axis] = model_summaries
        q3["horizons_ordinal_increments_not_seconds"][str(horizon)] = cells

    # Q4: game and start concentration of +45 absolute team-spacing loss.
    rows45 = [row for row in measurement_rows if row["horizon_ordinal_increment"] == 45 and row["eligible"]]
    per_game_q4 = {candidate: {} for candidate in CANDIDATES}
    per_start_q4 = {candidate: [] for candidate in CANDIDATES}
    for row in rows45:
        values = row["models"]
        for candidate in CANDIDATES:
            loss = float(values[candidate]["team_spacing_error_ft"] - values["M0"]["team_spacing_error_ft"])
            per_game_q4[candidate].setdefault(row["game"], []).append(loss)
            per_start_q4[candidate].append({"game": row["game"], "start_id": row["scenario_id"], "loss_ft": loss})

    def defined_interval(samples: list[float | None], minimum_valid: int = 9500):
        valid = [float(x) for x in samples if x is not None and math.isfinite(float(x))]
        return {
            "interval": [qlinear(valid, 0.025), qlinear(valid, 0.975)] if len(valid) >= minimum_valid else None,
            "valid_draws": len(valid), "unavailable_draws": len(samples) - len(valid),
            "minimum_valid_draws": minimum_valid,
        }

    q4 = {"horizon_ordinal_increment_not_seconds": 45, "candidates": {}}
    for candidate in CANDIDATES:
        if any(not per_game_q4[candidate].get(game) for game in games):
            raise RuntimeError(f"+45 spacing attribution is missing one of ten games for {candidate}")
        game_delta = {game: float(np.mean(per_game_q4[candidate][game])) for game in games}
        net_mean, net_ci = bootstrap_interval(game_delta, games, draws)
        ordered_positive = sorted((value for value in game_delta.values() if value > 0), reverse=True)
        top3_sum = float(sum(ordered_positive[:3]))
        positive_sum = float(sum(ordered_positive))
        net_sum = float(sum(game_delta.values()))
        top3_game_share = top3_sum / positive_sum if positive_sum > 0 else None
        top3_net_share = top3_sum / net_sum if net_sum > 0 else None
        top3_boot, top3_net_boot = [], []
        for draw in draws:
            sample = [game_delta[games[int(index)]] for index in draw]
            pos = sorted((value for value in sample if value > 0), reverse=True)
            pos_sum = float(sum(pos))
            net_sample = float(sum(sample))
            sample_top3 = float(sum(pos[:3]))
            top3_boot.append(sample_top3 / pos_sum if pos_sum > 0 else None)
            top3_net_boot.append(sample_top3 / net_sample if net_sample > 0 else None)

        loo = {removed: statistics.fmean(value for game, value in game_delta.items() if game != removed)
               for removed in games}
        ordered_starts = sorted(per_start_q4[candidate], key=lambda row: (-row["loss_ft"], row["game"], row["start_id"]))
        n_starts = len(ordered_starts)
        worst_n = math.ceil(0.10 * n_starts)
        starts_per_game = {game: len(per_game_q4[candidate][game]) for game in games}

        def weighted_start_sums(rows: list[dict]):
            net = positive = 0.0
            for item in rows:
                weight = 1.0 / (len(games) * starts_per_game[item["game"]])
                net += item["loss_ft"] * weight
                positive += max(item["loss_ft"], 0.0) * weight
            return net, positive

        total_net_weighted, total_positive_weighted = weighted_start_sums(ordered_starts)
        worst_rows = ordered_starts[:worst_n]
        worst_net, worst_positive = weighted_start_sums(worst_rows)
        share_positive = worst_positive / total_positive_weighted if total_positive_weighted > 0 else None
        share_net = worst_positive / total_net_weighted if total_net_weighted > 0 else None

        retained_by_game = {game: [row["loss_ft"] for row in ordered_starts
                                   if row["game"] == game and row not in worst_rows] for game in games}
        dropped_game_means = {game: float(np.mean(values)) if values else None
                              for game, values in retained_by_game.items()}
        dropped_mean = (statistics.fmean(float(dropped_game_means[g]) for g in games)
                        if all(value is not None for value in dropped_game_means.values()) else None)

        boot_game_share, boot_start_share, boot_start_net_share = [], [], []
        for draw in draws:
            draw_games = [games[int(index)] for index in draw]
            draw_game_values = [game_delta[g] for g in draw_games]
            draw_positive = sorted((x for x in draw_game_values if x > 0), reverse=True)
            draw_positive_total = float(sum(draw_positive))
            draw_net_total = float(sum(draw_game_values))
            draw_top3 = float(sum(draw_positive[:3]))
            boot_game_share.append(draw_top3 / draw_positive_total if draw_positive_total > 0 else None)

            sampled_start_rows = []
            for occurrence, game in enumerate(draw_games):
                source_rows = [row for row in per_start_q4[candidate] if row["game"] == game]
                sampled_start_rows.extend((occurrence, game, row) for row in source_rows)
            if not sampled_start_rows:
                boot_start_share.append(None)
                boot_start_net_share.append(None)
                continue
            n_draw = len(sampled_start_rows)
            decile_n = math.ceil(0.10 * n_draw)
            ranked = sorted(sampled_start_rows,
                            key=lambda item: (-item[2]["loss_ft"], item[0], item[2]["start_id"]))
            draw_net = draw_positive_start = draw_worst_positive = 0.0
            starts_by_occurrence = {i: sum(item[0] == i for item in sampled_start_rows) for i in range(len(draw_games))}
            for item in sampled_start_rows:
                occurrence, _game, row = item
                weight = 1.0 / (len(draw_games) * starts_by_occurrence[occurrence])
                draw_net += row["loss_ft"] * weight
                draw_positive_start += max(row["loss_ft"], 0.0) * weight
            for occurrence, _game, row in ranked[:decile_n]:
                weight = 1.0 / (len(draw_games) * starts_by_occurrence[occurrence])
                draw_worst_positive += max(row["loss_ft"], 0.0) * weight
            boot_start_share.append(draw_worst_positive / draw_positive_start if draw_positive_start > 0 else None)
            boot_start_net_share.append(draw_worst_positive / draw_net if draw_net > 0 else None)

        q4["candidates"][candidate] = {
            "game_deltas_ft": [
                {"game": game, "delta_ft": game_delta[game], "sign": "positive" if game_delta[game] > 0 else
                 "negative" if game_delta[game] < 0 else "zero", "scored_starts": starts_per_game[game]}
                for game in games
            ],
            "game_sign_counts": {
                "positive": sum(value > 0 for value in game_delta.values()),
                "negative": sum(value < 0 for value in game_delta.values()),
                "zero": sum(value == 0 for value in game_delta.values()),
            },
            "equal_game_net_gap_ft": {"estimate": net_mean, "bootstrap_95_percentile_interval": net_ci},
            "leave_one_game_out_equal_game_means_ft": loo,
            "leave_one_game_out_range_ft": [min(loo.values()), max(loo.values())],
            "top_three_positive_game_share": {
                "numerator_positive_game_sum_ft": top3_sum,
                "denominator_positive_game_sum_ft": positive_sum,
                "share": top3_game_share,
                "bootstrap_95_percentile": defined_interval(boot_game_share),
                "top_three_sum_over_net_game_gap": top3_net_share,
                "top_three_over_net_gap_bootstrap_95_percentile": defined_interval(top3_net_boot),
                "net_game_delta_sum_ft": net_sum,
            },
            "per_start": {
                "scored_starts": n_starts,
                "starts_by_game": starts_per_game,
                "worst_decile_count": worst_n,
                "worst_decile_rule": "largest ceil(0.10*N) unweighted start losses; weighted contribution uses equal-game start weights",
                "worst_decile_start_ids": [
                    {"game": row["game"], "start_id": row["start_id"], "loss_ft": row["loss_ft"]}
                    for row in worst_rows
                ],
                "total_net_equal_game_gap_ft": total_net_weighted,
                "total_positive_weighted_loss_ft": total_positive_weighted,
                "worst_decile_positive_weighted_loss_ft": worst_positive,
                "worst_decile_share_of_positive_weighted_loss": share_positive,
                "worst_decile_share_of_net_gap": share_net,
                "worst_decile_share_bootstrap_95_percentile": defined_interval(boot_start_share),
                "worst_decile_over_net_gap_bootstrap_95_percentile": defined_interval(boot_start_net_share),
                "equal_game_mean_after_dropping_worst_decile_ft": dropped_mean,
                "sign_changes_after_dropping_worst_decile": (dropped_mean is not None and
                    ((dropped_mean > 0 > total_net_weighted) or (dropped_mean < 0 < total_net_weighted))),
                "retained_starts": sum(len(value) for value in retained_by_game.values()),
                "retained_starts_by_game": {game: len(values) for game, values in retained_by_game.items()},
                "per_start_deltas_ft": sorted(per_start_q4[candidate], key=lambda row: (row["game"], row["start_id"])),
            },
        }

    # Q5: paired per-start individual gain and group-spacing loss at +45.
    q5 = {"horizon_ordinal_increment_not_seconds": 45, "candidates": {}}
    q5_rows: dict[str, list[dict]] = {candidate: [] for candidate in CANDIDATES}
    spacing_lookup = {(row["scenario_id"], model): float(row["models"][model]["team_spacing_error_ft"])
                      for row in rows45 for model in MODELS}
    for row in rows45:
        sid = row["scenario_id"]
        state = per_start_state[(sid, 45)]
        radial = {}
        for model in MODELS:
            radial[model] = float(np.mean([
                np.linalg.norm(state["models"][model][pid] - state["observed"][pid])
                for pid in state["common_ids"]
            ]))
        for candidate in CANDIDATES:
            q5_rows[candidate].append({
                "game": row["game"], "start_id": sid,
                "individual_radial_gain_ft": radial["M0"] - radial[candidate],
                "team_spacing_loss_ft": spacing_lookup[(sid, candidate)] - spacing_lookup[(sid, "M0")],
                "common_skaters": len(state["common_ids"]),
            })

    quadrant_names = ("both_gain_and_loss_positive", "gain_only", "loss_only", "neither_positive")
    for candidate in CANDIDATES:
        rows = q5_rows[candidate]
        x = np.asarray([row["individual_radial_gain_ft"] for row in rows], dtype=np.float64)
        y = np.asarray([row["team_spacing_loss_ft"] for row in rows], dtype=np.float64)
        rho = spearman(x, y)
        by_game = {game: [row for row in rows if row["game"] == game] for game in games}
        rho_draws = []
        for draw in draws:
            sampled_x, sampled_y = [], []
            for index in draw:
                for item in by_game[games[int(index)]]:
                    sampled_x.append(item["individual_radial_gain_ft"])
                    sampled_y.append(item["team_spacing_loss_ft"])
            rho_draws.append(spearman(sampled_x, sampled_y))
        rho_interval = defined_interval(rho_draws)
        quadrant_rows = {name: [] for name in quadrant_names}
        for row in rows:
            gain_positive = row["individual_radial_gain_ft"] > 0
            loss_positive = row["team_spacing_loss_ft"] > 0
            quadrant = ("both_gain_and_loss_positive" if gain_positive and loss_positive else
                        "gain_only" if gain_positive else
                        "loss_only" if loss_positive else "neither_positive")
            for name in quadrant_names:
                quadrant_rows[name].append({"game": row["game"], "start_id": row["start_id"],
                                            "indicator": float(name == quadrant)})
        quadrant_out = {}
        for name in quadrant_names:
            indicator_rows = quadrant_rows[name]
            summary = summarize_rows(indicator_rows, "indicator", games, draws)
            summary["start_count"] = int(sum(r["indicator"] for r in indicator_rows))
            quadrant_out[name] = summary

        gain_rows = [{"game": r["game"], "start_id": r["start_id"], "value": r["individual_radial_gain_ft"]}
                     for r in rows]
        loss_rows = [{"game": r["game"], "start_id": r["start_id"], "value": r["team_spacing_loss_ft"]}
                     for r in rows]
        q5["candidates"][candidate] = {
            "individual_radial_gain_ft": summarize_rows(gain_rows, "value", games, draws),
            "team_spacing_loss_ft": summarize_rows(loss_rows, "value", games, draws),
            "spearman_per_start": {
                "rho": rho, "bootstrap_95_percentile_interval": rho_interval["interval"],
                "valid_draws": rho_interval["valid_draws"],
                "unavailable_draws": rho_interval["unavailable_draws"],
                "resampling_unit": "whole game; all starts from each draw occurrence",
                "per_start_count": len(rows),
            },
            "sign_quadrants_equal_game_weighted": quadrant_out,
            "per_start_values": sorted(rows, key=lambda r: (r["game"], r["start_id"])),
        }

    # Q6: explicit archive schema/labels only; never infer constraint touches from moved coordinates.
    activity_audit = candidate_activity_labels(archive, comparison)
    archive_player_fields = sorted({key for scenario in archive["scenarios"].values()
                                     for player in scenario.get("initial_state", {}).get("players", []) for key in player})
    result = {
        "schema_version": 1,
        "milestone": "JC-DIAG",
        "status": "descriptive attribution only; no candidate scoring, selection, policy change, or adoption",
        "base_commit": BASE_COMMIT,
        "preregistration": {"file": "docs/research/NHL-JC-ATTRIBUTION-PREREG-2026-10-23.md",
                            "commit": PREREG_COMMIT, "sha256": PREREG_SHA256},
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "source_hashes": actual_hashes,
        "provenance_gate": {
            "task_wording_scalar_count": 7,
            "enumerated_scalar_checks_run": len(checks),
            "task_wording_note": "seven scalar assertions per the authoritative task correction",
            "jc_result_sha256_expected_and_actual": JC_SHA256,
            "all_assertions_passed": True,
            "checks": checks,
            "manager_correction_before_attribution": {
                "corrected_field": "one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds.models.M2.equal_game_mean_ft",
                "initial_typo_ft": 3.1037,
                "corrected_reference_ft": 3.1045,
                "source_artifact_sha256": JC_SHA256,
                "recomputed_float_ft": computed_values["one_step_radial_M2_ft"],
                "artifact_equal_game_mean_ft": corrected_m2_artifact_value,
                "correction_timing": "manager correction received before Q1-Q6; no attribution metrics had been run",
            },
        },
        "population": {
            "games": games, "game_count": len(games), "design": "leave-one-whole-game-out development predictions",
            "rollout_starts": len(starts), "plus45_group_scored_starts": len(rows45),
            "eligible_one_skater_windows": 454983,
            "independent_tracking_population_available": False,
            "timebase": "ordinal Image Id suffix increments; not seconds",
            "adoption_boundary": "No adoption, NHL simulator, or Legendary Picks probability claim is licensed.",
        },
        "method": {
            "primary_horizons_ordinal_increments_not_seconds": list(PRIMARY_HORIZONS),
            "distribution_horizons_ordinal_increments_not_seconds": [1, 2, 45],
            "bootstrap_replicates": BOOTSTRAPS, "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_cluster": "whole game, equal game weight; common draw matrix; linear percentile endpoints",
            "pair_quantiles": list(PAIR_QUANTILES),
            "common_tracks": "reconstructed from frozen cutoff, observed target, and all three archived model XY values; asserted against JC counts",
            "future_coordinates": "evaluation labels only",
            "controller_or_policy_changed": False,
            "resimulation_performed": False,
        },
        "frozen_schema_audit": {
            "cutoff_player_fields": archive_player_fields,
            "role_label_fields_found_in_cutoff_player_records": sorted(role_keys_seen),
            "position_role_labels_found": sorted(role_labels_seen),
            "constraint_activity_audit": activity_audit,
        },
        "Q1_pair_type_and_team_decomposition": q1,
        "Q2_signed_pair_error_distribution": q2,
        "Q3_source_XY_axis_decomposition": q3,
        "Q4_plus45_loss_concentration": q4,
        "Q5_plus45_individual_group_dissociation": q5,
        "Q6_constraint_activity_mechanism_screen": activity_audit,
    }

    encoded = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(encoded)
    out_hash = hashlib.sha256(encoded).hexdigest()
    print(f"ATTRIBUTION_JSON path={args.output} sha256={out_hash} bytes={len(encoded)}")
    print(f"EVALUATOR sha256={result['evaluator_sha256']}")
    print("Q1-Q6 calculated from frozen recorded paths only; no simulation or policy changes")


if __name__ == "__main__":
    main()
