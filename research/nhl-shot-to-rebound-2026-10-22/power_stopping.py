#!/usr/bin/env python3
"""Summarize committed game-cluster bootstrap intervals; perform no refits."""

import hashlib
import json
import math
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "research/nhl-shot-to-rebound-2026-10-22/results"
SOURCE = RESULTS / "tracking_robustness_null2.json"
OUTPUT = RESULTS / "tracking_power.json"
PROTECTED = {
    "tracking_rebound_analysis.json": RESULTS / "tracking_rebound_analysis.json",
    "tracking_robustness.json": RESULTS / "tracking_robustness.json",
    "tracking_robustness_null2.json": RESULTS / "tracking_robustness_null2.json",
}
Z_975 = 1.959963985
Z_80 = 0.8416212336
T_CRIT_9DF = 2.262157


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes():
    return {name: sha256(path) for name, path in PROTECTED.items()}


def classify_read(delta, excludes_zero):
    if excludes_zero:
        return "detectable at n=10"
    if delta < 0:
        return "direction favours movement but not resolvable"
    return "underpowered at n=10"


def score_population(source_target):
    metrics = source_target["event_only"]["metrics"]
    class_calibration = metrics.get("class_calibration", [])
    class_counts = {
        row["category"]: row["n_observed"] for row in class_calibration
    }
    return {
        "event_rate": metrics.get("event_rate"),
        "positive_count": metrics.get("positive"),
        "class_counts": class_counts or None,
    }


def main():
    started = time.perf_counter()
    hashes_before = protected_hashes()
    with SOURCE.open("r", encoding="utf-8") as handle:
        source = json.load(handle)

    metadata = source["metadata"]
    bootstrap = metadata["binary_cluster_bootstrap"]
    if bootstrap["unit"] != "game" or bootstrap["replicates"] != 2000:
        raise ValueError("expected the committed 2,000-replicate game-cluster bootstrap")

    game_rows = metadata["game_rows"]
    populations = {
        "rows": metadata["rows"],
        "outer_heldout_games": metadata["outer_heldout_games"],
        "event_only_parameter_count_including_intercept": metadata[
            "event_only_parameter_count_including_intercept"
        ],
        "movement_augmented_parameter_count_including_intercept": metadata[
            "movement_augmented_parameter_count_including_intercept"
        ],
        "event_rate_and_positive_count_by_target": {
            target: score_population(target_source)
            for target, target_source in source["targets"].items()
        },
        "game_rows": [{"game": game, "rows": rows} for game, rows in game_rows.items()],
    }
    if len(game_rows) != populations["outer_heldout_games"]:
        raise ValueError("game_rows count does not match outer_heldout_games")
    if sum(game_rows.values()) != populations["rows"]:
        raise ValueError("game_rows do not sum to the committed row count")

    targets = {}
    for target, target_source in source["targets"].items():
        paired = target_source["paired_uncertainty"]
        score_results = {}
        for block_name, block in paired.items():
            if not block_name.endswith("_movement_minus_event"):
                continue
            if not isinstance(block, dict) or "mean" not in block:
                raise ValueError(f"malformed paired uncertainty block: {target}/{block_name}")
            interval = block["cluster_bootstrap_95pct"]
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError(f"malformed 95% interval: {target}/{block_name}")
            low, high = interval
            if low > high:
                raise ValueError(f"reversed 95% interval: {target}/{block_name}")

            delta = block["mean"]
            se = (high - low) / (2 * Z_975)
            mde = (Z_975 + Z_80) * se
            excludes_zero = low > 0 or high < 0
            games_needed = None if delta == 0 else 10 * (mde / delta) ** 2
            score_name = block_name[: -len("_movement_minus_event")]
            score_results[score_name] = {
                "delta": delta,
                "ci95": list(interval),
                "se_from_ci": se,
                "se_method": "normal approximation to the game-level cluster bootstrap 95% interval; not a directly estimated standard error",
                "z": None if se == 0 else delta / se,
                "t_crit_9df": T_CRIT_9DF,
                "ci_excludes_zero": excludes_zero,
                "mde_at_n10_80pct": mde,
                "observed_delta_as_pct_of_mde": None if mde == 0 else 100 * delta / mde,
                "games_for_observed_delta_to_reach_mde": games_needed,
                "games_for_observed_delta_to_reach_mde_ceil": None if games_needed is None else math.ceil(games_needed),
                "read": classify_read(delta, excludes_zero),
            }
        if score_results:
            targets[target] = {"scores": score_results}

    if len(targets) != 5 or sum(len(item["scores"]) for item in targets.values()) != 10:
        raise ValueError("expected five targets and ten movement-minus-event score blocks")

    # Independent transcription checks from the task brief. These guard the
    # source mapping and arithmetic; all reported values above are computed
    # from the committed input, not copied from this table.
    checks = {
        ("recovery_within_3s", "brier"): (0.0008644, 0.0006384, 0.0017886, 42.8),
        ("recovery_within_3s", "logloss"): (0.0017685, 0.0012991, 0.0036397, 42.4),
        ("goal_from_attempt", "logloss"): (-0.0012875, 0.0004076, 0.0011418, 7.9),
        ("goal_from_attempt", "brier"): (-0.0001205, 0.0001214, 0.0003401, 79.6),
        ("recovery_team_category", "multiclass_brier"): (0.0012993, 0.0009569, 0.0026808, 42.6),
    }
    for (target, score), expected in checks.items():
        observed = targets[target]["scores"][score]
        actual = (
            observed["delta"],
            observed["se_from_ci"],
            observed["mde_at_n10_80pct"],
            observed["games_for_observed_delta_to_reach_mde"],
        )
        for label, value, target_value in zip(("delta", "SE", "MDE", "games"), actual, expected):
            # The brief rounds required game counts to one decimal; compare at
            # that displayed precision while keeping other checks at ~4 sig figs.
            matches = (
                abs(value - target_value) <= 0.05000001
                if label == "games"
                else math.isclose(value, target_value, rel_tol=0.0005, abs_tol=1e-12)
            )
            if not matches:
                raise ValueError(f"cross-check mismatch for {target}/{score} {label}: {value} vs {target_value}")

    recovery_brier = targets["recovery_within_3s"]["scores"]["brier"]["delta"]
    row_preserving_brier = source["matched_null_row_preserving"][
        "brier_movement_minus_event"
    ]["real_movement_delta"]
    if not math.isclose(recovery_brier, row_preserving_brier, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError("recovery Brier delta does not match the committed row-preserving null")

    payload = {
        "metadata": {
            "input": "results/tracking_robustness_null2.json",
            "evaluation": metadata["evaluation"],
            "bootstrap_unit": bootstrap["unit"],
            "bootstrap_replicates": bootstrap["replicates"],
            "bootstrap_seed": bootstrap["seed"],
            "power_method": "normal approximation using the committed game-cluster bootstrap interval-derived SE; MDE uses z_(0.975)+z_(0.80); projected games assume SE scales as 1/sqrt(G)",
        },
        "populations": populations,
        "targets": targets,
        "provenance": {
            "protected_sha256": {
                "before_write": hashes_before,
                # These are the expected post-write values. They are verified
                # against the files after OUTPUT has been written.
                "after_write": hashes_before,
            },
            "input_sha256": sha256(SOURCE),
            "refits_or_csv_reads": False,
        },
        "runtime_seconds": time.perf_counter() - started,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    hashes_after = protected_hashes()
    if hashes_after != hashes_before:
        raise RuntimeError("a protected JSON changed while writing the power result")

    summary = {
        "output": str(OUTPUT),
        "runtime_seconds": payload["runtime_seconds"],
        "protected_sha256_unchanged": hashes_after == hashes_before,
        "results": {
            target: {
                score: {
                    field: result[field]
                    for field in (
                        "delta", "se_from_ci", "mde_at_n10_80pct",
                        "games_for_observed_delta_to_reach_mde",
                        "games_for_observed_delta_to_reach_mde_ceil", "read",
                    )
                }
                for score, result in target_result["scores"].items()
            }
            for target, target_result in targets.items()
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
