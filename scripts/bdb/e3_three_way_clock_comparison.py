#!/usr/bin/env python3
"""Paired E1-sampled, PBP-conditional, and tracking-informed clock comparison.

All fitting and scoring is restricted to 2022 weeks 1-5. Each week is held
out as a fold; week 5 is the only forward fold (train weeks 1-4). Weeks 6-9
are never queried or used by this program.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e3_pbp_conditional_clock_model import BACKOFF, _key, make_features, validate_weeks

BASE_COMMIT = "4e18cb9f9e5b29ae9e105cbed37f90dc915c83da"
E1_COMMIT = "2248f7e1f9710daa3092104526ab6003a0fc3b18"
E1_SCRIPT_SHA256 = "b2a36750c6ed66d31297eaa317b9ab95367ae0a574d50f9ed06434a7f5ead95f"
E0_BUCKETS_SHA256 = "b4ee37588b871f3406f61d35060d625d84634d2339fe5db2420f739a08fdcf02"
PBP_MODEL_SHA256 = "0863a38c022d01a27547f7bcc1ad624bd4f37a90a1d7a16ef684a5c67f2dcf8d"
TRACKING_TIMING_SHA256 = "e885fd20be7fe54f429c31f98dff11425538d331e383c90527141dd78754a63b"
TRACKING_BRANCH_HEAD = "7ee6703efdc11468d4fec373f18496a6ef6d188b"
WEEKS = (1, 2, 3, 4, 5)
E1_MIN_POOL = 50
SAMPLE_DRAWS = 100
DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
DEFAULT_PBP_MODEL = HERE.parents[1] / "docs/evidence/e3/pbp-conditional-clock-model-weeks1-5-2026-10-24.json"
PBP_FIELDS = (
    "game_id", "play_id", "season", "week", "posteam", "defteam", "qtr", "down", "ydstogo",
    "yardline_100", "game_seconds_remaining", "play_type", "yards_gained", "touchdown", "interception",
    "fumble_lost", "sack", "complete_pass", "qb_scramble", "penalty", "two_point_attempt", "drive",
)
E1_EVENTS = ("run", "pass_complete", "pass_incomplete", "sack", "interception", "fumble_lost", "punt", "field_goal_attempt")
E1_PLAY_TYPES = ("run", "pass", "punt", "field_goal")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pbp(db_path: Path) -> tuple[list[dict], str]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in WEEKS)
        query = (
            f"SELECT {', '.join(PBP_FIELDS)} FROM nfl_pbp "
            f"WHERE season=2022 AND week IN ({placeholders}) ORDER BY game_id, play_id"
        )
        rows = [dict(row) for row in connection.execute(query, WEEKS)]
    finally:
        connection.close()
    canonical = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return rows, hashlib.sha256(canonical).hexdigest()


def key_of(row: dict) -> tuple[str, int]:
    return (str(row["game_id"]), int(row["play_id"]))


def group_next(rows: list[dict]) -> dict[tuple[str, int], dict | None]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row["game_id"])].append(row)
    result = {}
    for plays in groups.values():
        plays.sort(key=lambda row: int(row["play_id"]))
        for index, row in enumerate(plays):
            result[key_of(row)] = plays[index + 1] if index + 1 < len(plays) else None
    return result


def play_target_rows(rows: list[dict], b_artifact: dict) -> tuple[list[dict], dict]:
    b_by_key = {(str(row["game_id"]), int(row["play_id"])): row for row in b_artifact["plays"]}
    eligible = [row for row in rows if row.get("play_type") is not None]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in eligible:
        groups[str(row["game_id"])].append(row)
    expected = {}
    for plays in groups.values():
        plays.sort(key=lambda row: int(row["play_id"]))
        for index, row in enumerate(plays):
            following = plays[index + 1] if index + 1 < len(plays) else None
            current = row.get("game_seconds_remaining")
            next_clock = following.get("game_seconds_remaining") if following else None
            if following is None:
                value, label, rule = None, "unresolvable", "R4u1 no next PBP play row"
            elif row.get("qtr") is None or following.get("qtr") is None:
                value, label, rule = None, "unresolvable", "R4u4 quarter value missing in PBP"
            elif row["qtr"] != following["qtr"]:
                value, label, rule = None, "unresolvable", "R4u2 next PBP play is in another quarter; runoff is censored at the boundary"
            elif current is None or next_clock is None:
                value, label, rule = None, "unresolvable", "R4u4 a PBP game_seconds_remaining stamp is missing"
            else:
                value = float(current) - float(next_clock)
                if value < 0:
                    value, label, rule = None, "unresolvable", "R4u3 PBP clock delta is negative"
                else:
                    value, label, rule = round(value, 3), "inferred", "R4 inferred: current PBP clock minus next same-quarter PBP play stamp"
            key = key_of(row)
            expected[key] = {"value": value, "label": label, "rule": rule}
            b_row = b_by_key.get(key)
            if b_row is None:
                raise RuntimeError(f"PBP model artifact omits play {key}")
            actual = b_row["actual_game_clock_delta_s"]
            if actual.get("label") != expected[key]["label"] or actual.get("value") != expected[key]["value"]:
                raise RuntimeError(f"PBP model target disagrees with independent target construction at {key}")
    if set(expected) != set(b_by_key):
        raise RuntimeError("PBP model artifact play keys differ from the 2022 weeks 1-5 PBP play rows")
    return eligible, expected


def ydstogo_bucket(distance) -> str:
    return "1-3" if distance <= 3 else "4-6" if distance <= 6 else "7-10" if distance <= 10 else "11+"


def yardline_bucket(yardline) -> str:
    return "1-9" if yardline <= 9 else "10-19" if yardline <= 19 else "20-49" if yardline <= 49 else "50-79" if yardline <= 79 else "80-99"


def e1_classify(row: dict, following: dict | None):
    """Mirror E1 e1_drive.classify for its observed-play clock donor pool."""
    if row.get("penalty") == 1 or row.get("two_point_attempt") == 1 or row.get("qb_scramble") == 1:
        return None
    if row.get("down") is None or row.get("ydstogo") is None or row.get("yardline_100") is None:
        return None
    if (following is None or str(following["game_id"]) != str(row["game_id"])
            or following.get("qtr") != row.get("qtr") or following.get("game_seconds_remaining") is None
            or row.get("game_seconds_remaining") is None):
        return None
    runoff = int(round(float(row["game_seconds_remaining"]) - float(following["game_seconds_remaining"])))
    if runoff < 0:
        return None
    if row.get("play_type") == "field_goal":
        return "field_goal_attempt", runoff
    if row.get("play_type") == "punt":
        if (following.get("posteam") != row.get("defteam") or following.get("play_type") not in ("run", "pass")
                or following.get("yardline_100") is None):
            return None
        return "punt", runoff
    if row.get("yards_gained") is None:
        return None
    if row.get("interception") == 1 or row.get("fumble_lost") == 1:
        if row.get("touchdown") == 1:
            return None
        if (following.get("posteam") != row.get("defteam") or following.get("play_type") not in ("run", "pass")
                or following.get("yardline_100") is None):
            return None
        return ("interception" if row.get("interception") == 1 else "fumble_lost"), runoff
    if row.get("sack") == 1:
        return "sack", runoff
    if row.get("play_type") == "run":
        return "run", runoff
    if row.get("play_type") == "pass" and row.get("complete_pass") == 1:
        return "pass_complete", runoff
    if row.get("play_type") == "pass" and row.get("complete_pass") == 0:
        return "pass_incomplete", runoff
    return None


def e1_cell(row: dict):
    try:
        down = int(row["down"])
        distance = int(row["ydstogo"])
        yardline = int(row["yardline_100"])
    except (TypeError, ValueError):
        return None
    if not 1 <= down <= 4 or not 1 <= yardline <= 99:
        return None
    return down, ydstogo_bucket(distance), yardline_bucket(yardline)


def build_e1_pools(training_rows: list[dict], following_by_key: dict) -> dict:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in training_rows:
        by_game[str(row["game_id"])].append(row)
    pool: dict[tuple, list[dict]] = defaultdict(list)
    for plays in by_game.values():
        plays.sort(key=lambda row: int(row["play_id"]))
        for row in plays:
            if row.get("play_type") not in E1_PLAY_TYPES or row.get("down") is None or not 1 <= row["down"] <= 4:
                continue
            hit = e1_classify(row, following_by_key.get(key_of(row)))
            cell = e1_cell(row)
            if hit is None or cell is None:
                continue
            event, runoff = hit
            pool[cell].append({"event": event, "runoff_s": runoff, "key": key_of(row)})
    for values in pool.values():
        values.sort(key=lambda row: row["key"])
    return dict(pool)


def sample_draws(values: list[dict], target_key: tuple[str, int], held_week: int, draws: int) -> list[float]:
    runoffs = [row["runoff_s"] for row in values]
    output = []
    for draw in range(draws):
        token = f"e1-sampled-v0|{held_week}|{target_key[0]}|{target_key[1]}|{draw}".encode()
        index = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % len(runoffs)
        output.append(float(runoffs[index]))
    return output


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _residual_stats(values: list[float]) -> dict:
    return {
        "p10_s": _quantile(values, 0.1),
        "p50_s": statistics.median(values),
        "p90_s": _quantile(values, 0.9),
        "training_rows": len(values),
    }


def build_residual_model(training: list[dict]) -> dict:
    buckets: dict[tuple, list[float]] = defaultdict(list)
    for item in training:
        residual = item["residual_s"]
        for level, _minimum in BACKOFF[:-1]:
            buckets[(level, _key(level, item["features"]))].append(residual)
        buckets[("global", ())].append(residual)
    return {key: _residual_stats(values) for key, values in buckets.items()}


def residual_prediction(model: dict, features: dict) -> dict | None:
    selected = None
    for level, minimum in BACKOFF:
        summary = model.get((level, _key(level, features)))
        if summary is not None and summary["training_rows"] >= minimum:
            selected = {"level": level, **summary}
            break
    if selected is None:
        return None
    selected["backoff_level"] = selected.pop("level")
    return selected


def load_tracking(path: Path) -> tuple[dict, str]:
    actual = sha256_file(path)
    if actual != TRACKING_TIMING_SHA256:
        raise RuntimeError(f"physical-timing input hash mismatch: {actual}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "gridiron.bdb2025.snap_physical_timing.v2":
        raise RuntimeError("unexpected physical-timing source schema")
    by_key = {}
    for row in document.get("plays", []):
        if row.get("week") not in WEEKS or row.get("lp_join_status") != "matched" or row.get("timing_status") != "resolved":
            continue
        elapsed = row.get("elapsed_seconds")
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or not math.isfinite(elapsed):
            continue
        key = (str(row["lp_game_id"]), int(row["lp_play_id"]))
        if key in by_key:
            raise RuntimeError(f"duplicate tracking LP key {key}")
        by_key[key] = {"elapsed_seconds": float(elapsed), "week": int(row["week"])}
    return by_key, actual


def _drive_key(row: dict):
    drive = row.get("drive")
    if drive is None:
        return None
    return str(row["game_id"]), int(drive)


def _error_summary(errors: list[float]) -> dict:
    return {"n": len(errors), "mae_s": round(statistics.mean(errors), 4) if errors else None}


def build_comparison(db_rows: list[dict], pbp_sha: str, b_artifact: dict, tracking: dict, tracking_sha: str) -> dict:
    if b_artifact.get("source", {}).get("input_slice_sha256") is None:
        raise RuntimeError("PBP-only model output is missing its input rowset hash")
    if b_artifact.get("source", {}).get("base_commit") != BASE_COMMIT:
        raise RuntimeError("PBP-only model artifact is not pinned to LP commit 4e18cb9f")
    b_path_sha = PBP_MODEL_SHA256
    b_by_key = {(str(row["game_id"]), int(row["play_id"])): row for row in b_artifact["plays"]}
    if len(b_by_key) != len(b_artifact["plays"]):
        raise RuntimeError("duplicate key in PBP-only model artifact")
    all_next = group_next(db_rows)
    play_rows, targets = play_target_rows(db_rows, b_artifact)
    raw_by_key = {key_of(row): row for row in play_rows}
    week_rows: dict[int, list[dict]] = {week: [] for week in WEEKS}
    for row in play_rows:
        week_rows[int(row["week"])].append(row)

    output_by_key = {}
    metrics_by_week = {}
    native_counts = {"A_e1_sampled": Counter(), "B_pbp_conditional": Counter(), "C_tracking_informed": Counter()}
    native_drives = {name: defaultdict(set) for name in native_counts}
    common_by_week: dict[int, list[dict]] = {week: [] for week in WEEKS}

    for held_week in WEEKS:
        train_rows = [row for row in db_rows if int(row["week"]) != held_week]
        e1_pool = build_e1_pools(train_rows, group_next(train_rows))

        residual_train = []
        for row in play_rows:
            if int(row["week"]) == held_week:
                continue
            key = key_of(row)
            target = targets[key]
            tracked = tracking.get(key)
            if target["label"] != "inferred" or tracked is None:
                continue
            residual_train.append({
                "residual_s": float(target["value"]) - tracked["elapsed_seconds"],
                "features": make_features(row),
            })
        residual_model = build_residual_model(residual_train)

        for row in week_rows[held_week]:
            key = key_of(row)
            target = targets[key]
            b_row = b_by_key[key]
            b_prediction = b_row["prediction"]["game_clock_delta_s"]
            if set(b_prediction["training_weeks"]) != set(WEEKS) - {held_week}:
                raise RuntimeError(f"PBP conditional training weeks mismatch for held week {held_week} at {key}")
            if b_prediction.get("label") != "inferred":
                raise RuntimeError(f"PBP conditional model missing prediction at {key}")
            feature = make_features(row)
            following = all_next.get(key)
            e1_hit = e1_classify(row, following)
            cell = e1_cell(row)
            a_values = None
            a_context = None
            if e1_hit is not None and cell is not None:
                event = e1_hit[0]
                candidates = [item for item in e1_pool.get(cell, []) if item["event"] == event]
                cell_size = len(e1_pool.get(cell, []))
                if cell_size >= E1_MIN_POOL and candidates:
                    a_values = sample_draws(candidates, key, held_week, SAMPLE_DRAWS)
                    a_context = {"cell": list(cell), "cell_rows": cell_size, "event_donor_rows": len(candidates)}

            tracked = tracking.get(key)
            c_prediction = None
            if tracked is not None and target["label"] == "inferred":
                residual = residual_prediction(residual_model, feature)
                if residual is not None:
                    elapsed = tracked["elapsed_seconds"]
                    c_prediction = {
                        "p10_s": round(elapsed + residual["p10_s"], 3),
                        "p50_s": round(elapsed + residual["p50_s"], 3),
                        "p90_s": round(elapsed + residual["p90_s"], 3),
                        "label": "inferred",
                        "rule": "tracking terminal-minus-snap duration plus week-held-out PBP conditional residual; retrospective input",
                        "tracking_in_play_s": {"value": round(elapsed, 3), "label": "inferred", "rule": "10 Hz tracking terminal timestamp minus snap timestamp"},
                        "residual_backoff_level": residual["backoff_level"],
                        "residual_training_rows": residual["training_rows"],
                    }

            model_a = None
            if a_values is not None:
                model_a = {
                    "sample_count": len(a_values),
                    "draw_p10_s": round(_quantile(a_values, 0.1), 3),
                    "draw_p50_s": round(statistics.median(a_values), 3),
                    "draw_p90_s": round(_quantile(a_values, 0.9), 3),
                    "expected_absolute_error_s": round(statistics.mean(abs(float(target["value"]) - value) for value in a_values), 4)
                    if target["label"] == "inferred" else None,
                    "label": "inferred",
                    "rule": "E1 event-conditioned sample of a training-fold observed clock-runoff donor",
                    "training_cell": a_context,
                }

            b_value = round(float(b_prediction["p50_s"]), 3)
            b_out = {
                "p10_s": b_prediction["p10_s"], "p50_s": b_value, "p90_s": b_prediction["p90_s"],
                "label": "inferred", "rule": b_prediction["rule"],
                "backoff_level": b_prediction["backoff_level"], "training_rows": b_prediction["training_rows"],
            }

            model_predictions = {"A_e1_sampled": model_a, "B_pbp_conditional": b_out, "C_tracking_informed": c_prediction}
            target_resolved = target["label"] == "inferred"
            for model, prediction in model_predictions.items():
                if prediction is not None:
                    native_counts[model]["predicted"] += 1
                    drive_key = _drive_key(row)
                    if drive_key is not None:
                        native_drives[model][held_week].add(drive_key)
                    if target_resolved:
                        native_counts[model]["scorable"] += 1
            common = target_resolved and all(model_predictions[name] is not None for name in model_predictions)
            errors = None
            if common:
                truth = float(target["value"])
                errors = {
                    "A_e1_sampled_expected_abs_s": model_a["expected_absolute_error_s"],
                    "B_pbp_conditional_abs_s": round(abs(truth - b_value), 4),
                    "C_tracking_informed_abs_s": round(abs(truth - float(c_prediction["p50_s"])), 4),
                }
                common_by_week[held_week].append({"truth": truth, "errors": errors, "drive": _drive_key(row)})

            output_by_key[key] = {
                "game_id": row["game_id"], "play_id": int(row["play_id"]), "week": held_week,
                "drive": row.get("drive"),
                "target": dict(target),
                "e1_event": {"value": e1_hit[0], "label": "observed", "rule": "E1 terminal event classified from PBP"} if e1_hit else
                            {"value": None, "label": "unresolvable", "rule": "play is outside E1's sampled event vocabulary/eligibility"},
                "predictions": model_predictions,
                "common_evaluation_row": bool(common),
                "paired_absolute_errors_s": errors,
            }

    common_rows = [row for week in WEEKS for row in common_by_week[week]]
    common_n = len(common_rows)
    common_drive_keys = {row["drive"] for row in common_rows if row["drive"] is not None}
    comparison_mae = {
        "A_e1_sampled_expected_mae": _error_summary([row["errors"]["A_e1_sampled_expected_abs_s"] for row in common_rows]),
        "B_pbp_conditional_mae": _error_summary([row["errors"]["B_pbp_conditional_abs_s"] for row in common_rows]),
        "C_tracking_informed_mae": _error_summary([row["errors"]["C_tracking_informed_abs_s"] for row in common_rows]),
    }
    paired_comparisons = {}
    error_names = {
        "A_e1_sampled": "A_e1_sampled_expected_abs_s",
        "B_pbp_conditional": "B_pbp_conditional_abs_s",
        "C_tracking_informed": "C_tracking_informed_abs_s",
    }
    for left, right in (("A_e1_sampled", "B_pbp_conditional"),
                        ("A_e1_sampled", "C_tracking_informed"),
                        ("B_pbp_conditional", "C_tracking_informed")):
        deltas = [row["errors"][error_names[left]] - row["errors"][error_names[right]] for row in common_rows]
        paired_comparisons[f"{left}_minus_{right}"] = {
            "mean_absolute_error_difference_s": round(statistics.mean(deltas), 4),
            "left_lower_error_rows": sum(value < 0 for value in deltas),
            "right_lower_error_rows": sum(value > 0 for value in deltas),
            "ties": sum(value == 0 for value in deltas),
        }
    for week in WEEKS:
        group = common_by_week[week]
        drives = {row["drive"] for row in group if row["drive"] is not None}
        metrics_by_week[str(week)] = {
            "common_rows": len(group),
            "common_drives": len(drives),
            "A_mae_expected_s": _error_summary([row["errors"]["A_e1_sampled_expected_abs_s"] for row in group])["mae_s"],
            "B_mae_s": _error_summary([row["errors"]["B_pbp_conditional_abs_s"] for row in group])["mae_s"],
            "C_mae_s": _error_summary([row["errors"]["C_tracking_informed_abs_s"] for row in group])["mae_s"],
        }

    total_target = sum(target["label"] == "inferred" for target in targets.values())
    total_target_drives = {_drive_key(row) for row in play_rows if targets[key_of(row)]["label"] == "inferred" and _drive_key(row) is not None}
    coverage = {
        "PBP_play_rows": len(play_rows),
        "PBP_delta_resolved_rows": total_target,
        "PBP_delta_resolved_drives": len(total_target_drives),
        "tracking_inplay_joinable_rows": sum(key in tracking for key in targets),
        "common_evaluation_rows": common_n,
        "common_evaluation_drives": len(common_drive_keys),
        "per_model_native": {},
    }
    for name in native_counts:
        rows_with_pred = [record for record in output_by_key.values() if record["predictions"][name] is not None]
        drives = {(str(record["game_id"]), int(record["drive"])) for record in rows_with_pred if record["drive"] is not None}
        coverage["per_model_native"][name] = {
            "rows_with_prediction": native_counts[name]["predicted"],
            "resolved_target_rows": native_counts[name]["scorable"],
            "drives_with_prediction": len(drives),
        }

    if common_n == 0:
        raise RuntimeError("the three models have no identical resolved target rows")
    return {
        "schema": "lp.e3.three_way_clock_comparison.v1",
        "source": {
            "LP_base_commit": BASE_COMMIT,
            "E1_sampled_runoff_source_commit": E1_COMMIT,
            "E1_e1_drive_py_sha256": E1_SCRIPT_SHA256,
            "E1_e0_bucket_source_sha256": E0_BUCKETS_SHA256,
            "B_PBP_model_artifact_sha256": b_path_sha,
            "tracking_timing_artifact_sha256": tracking_sha,
            "tracking_timing_branch_head": TRACKING_BRANCH_HEAD,
            "PBP_slice_sha256": pbp_sha,
        },
        "scope": {
            "season": 2022,
            "weeks": list(WEEKS),
            "query_week_filter": "season=2022 AND week IN (1,2,3,4,5)",
            "target": "current PBP game_seconds_remaining minus next play_type-nonnull PBP row in the same quarter",
            "target_label": "inferred",
            "holdout_status": "NOT HOLDOUT-VALIDATED: weeks 6-9 were already examined in prior E3 work; weeks 1-5 are development comparisons only",
            "folding": "leave-one-week-out for all models; week 5 trains only on weeks 1-4",
            "PBP_rows": len(play_rows),
            "target_resolved_rows": total_target,
            "drive_count_for_resolved_targets": len(total_target_drives),
            "same_target_and_common_rows_for_MAE": common_n,
            "same_drive_count_for_three_model_MAE": len(common_drive_keys),
            "stochastic_A_draws_per_row": SAMPLE_DRAWS,
        },
        "models": {
            "A_e1_sampled": "E1's empirical clock-runoff donor mechanism; refit to each fold's weeks 1-5 training pool, with the held-out PBP event/cell fixed and 100 deterministic draws from eligible event donors. This is a stochastic baseline, so its MAE is mean per-play expected absolute error over those draws.",
            "B_pbp_conditional": "Pinned PBP-only hierarchical conditional median model; uses the existing week-held-out predictions.",
            "C_tracking_informed": "Observed tracking terminal-minus-snap duration plus a same-fold PBP-conditional median residual (PBP delta minus tracking duration). This uses terminal future tracking and is retrospective, not prospective.",
        },
        "coverage": coverage,
        "common_rows_metrics": comparison_mae,
        "paired_model_differences": paired_comparisons,
        "common_rows_by_week": metrics_by_week,
        "per_play": [output_by_key[key] for key in sorted(output_by_key)],
        "limitations": [
            "Weeks 6-9 were already examined; none of these weeks 1-5 comparisons are holdout-validated.",
            "A is stochastic and is reported as expected per-play MAE over 100 fixed donor draws; it is not a deterministic point forecast.",
            "C uses terminal tracking duration from the same play, a post-play future label. Its MAE is retrospective decomposition skill and not a pre-snap prediction result.",
            "PBP clock delta is a same-quarter play-row clock difference, not an official whistle timestamp or adjudicated stoppage duration.",
            "PBP-only timeout, out-of-bounds, and penalty clock effects remain unresolvable where the source does not identify them.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--pbp-model", type=Path, default=DEFAULT_PBP_MODEL)
    parser.add_argument("--tracking-timing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_weeks(WEEKS)
        b_sha = sha256_file(args.pbp_model)
        if b_sha != PBP_MODEL_SHA256:
            raise RuntimeError(f"PBP-only model artifact hash mismatch: {b_sha}")
        b_artifact = json.loads(args.pbp_model.read_text(encoding="utf-8"))
        pbp_rows, pbp_sha = load_pbp(args.db)
        tracking, tracking_sha = load_tracking(args.tracking_timing)
        result = build_comparison(pbp_rows, pbp_sha, b_artifact, tracking, tracking_sha)
    except (OSError, sqlite3.Error, ValueError, RuntimeError, KeyError) as error:
        parser.error(str(error))
    result["source"]["B_PBP_model_artifact_sha256"] = b_sha
    result["source"]["comparison_script_sha256"] = sha256_file(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"PBP plays={result['scope']['PBP_rows']}; resolved target={result['scope']['target_resolved_rows']}; common A/B/C rows={result['scope']['same_target_and_common_rows_for_MAE']}")
    print(f"Common drives={result['scope']['same_drive_count_for_three_model_MAE']}; tracking-joined plays={result['coverage']['tracking_inplay_joinable_rows']}")
    print(f"MAE A sampled={result['common_rows_metrics']['A_e1_sampled_expected_mae']['mae_s']} s; B PBP={result['common_rows_metrics']['B_pbp_conditional_mae']['mae_s']} s; C tracking={result['common_rows_metrics']['C_tracking_informed_mae']['mae_s']} s")
    print(f"Week-5 common rows={result['common_rows_by_week']['5']['common_rows']}; holdout status: NOT HOLDOUT-VALIDATED")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
