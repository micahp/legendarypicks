#!/usr/bin/env python3
"""Cross-fitted PBP-only snap-to-next-play clock model for 2022 weeks 1-5.

This builder reads only the LP dev nfl_pbp table and never opens tracking or
nflverse inputs. Week 6 and later are rejected before database access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

BASE_COMMIT = "4e18cb9f9e5b29ae9e105cbed37f90dc915c83da"
SCHEMA = "lp.e3.pbp_conditional_clock.v1"
ALLOWED_WEEKS = frozenset(range(1, 6))
DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
INPUT_FIELDS = (
    "game_id", "play_id", "season", "week", "qtr", "down", "ydstogo",
    "game_seconds_remaining", "play_type", "complete_pass", "touchdown",
    "interception", "fumble_lost", "sack", "penalty", "two_point_attempt",
    "series_result",
)

# Fixed backoff hierarchy; the support floors were set before this run and are
# not tuned on the evaluation folds.
BACKOFF = (
    ("play_type_outcome_late_half_down", 25),
    ("play_type_outcome_late_half", 25),
    ("play_type_outcome", 30),
    ("play_type", 30),
    ("global", 1),
)


def validate_weeks(weeks: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    values = tuple(sorted(set(int(week) for week in weeks)))
    if not values:
        raise ValueError("select at least one development week")
    outside = [week for week in values if week not in ALLOWED_WEEKS]
    if outside:
        raise ValueError(f"week {outside[0]} is outside the allowed development scope 1-5; weeks 6-9 are reserved")
    return values


def load_pbp(db_path: Path, weeks: tuple[int, ...]) -> tuple[list[dict], str]:
    weeks = validate_weeks(weeks)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(nfl_pbp)")}
        missing = sorted(set(INPUT_FIELDS) - columns)
        if missing:
            raise RuntimeError(f"nfl_pbp source is missing required columns: {', '.join(missing)}")
        placeholders = ",".join("?" for _ in weeks)
        sql = (
            f"SELECT {', '.join(INPUT_FIELDS)} FROM nfl_pbp "
            f"WHERE season=2022 AND week IN ({placeholders}) AND play_type IS NOT NULL "
            "ORDER BY game_id, play_id"
        )
        records = [dict(row) for row in connection.execute(sql, weeks)]
    finally:
        connection.close()
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return records, hashlib.sha256(encoded).hexdigest()


def _present(value) -> bool:
    return value is not None and value != ""


def _true(value) -> bool:
    return value is True or value == 1


def _flag_label(value, source_field: str) -> dict:
    if value is None:
        return {"value": None, "label": "unresolvable", "rule": f"nfl_pbp.{source_field} is null"}
    if value not in (0, 1, 0.0, 1.0, False, True):
        return {"value": None, "label": "unresolvable", "rule": f"nfl_pbp.{source_field} is not a binary source flag"}
    return {"value": bool(value), "label": "observed", "rule": f"PBP {source_field} flag"}


def outcome_family(row: dict) -> tuple[str, str]:
    play_type = row.get("play_type") or "unknown"
    event_flags = (row.get("touchdown"), row.get("interception"), row.get("fumble_lost"), row.get("sack"))
    if all(value is None for value in event_flags):
        return "terminal_outcome_unknown", "R7u terminal outcome flags are null; play_type alone does not resolve the event family"
    if _true(row.get("touchdown")):
        return "touchdown", "R7 observed from nfl_pbp.touchdown"
    if _true(row.get("interception")):
        return "interception", "R7 observed from nfl_pbp.interception"
    if _true(row.get("fumble_lost")):
        return "fumble_lost", "R7 observed from nfl_pbp.fumble_lost"
    if _true(row.get("sack")):
        return "sack", "R7 observed from nfl_pbp.sack"
    if play_type == "pass":
        if row.get("complete_pass") == 1:
            return "pass_complete", "R7 observed from nfl_pbp.play_type and complete_pass"
        if row.get("complete_pass") == 0:
            return "pass_incomplete", "R7 observed from nfl_pbp.play_type and complete_pass"
        return "pass_result_unknown", "R7 unresolvable: complete_pass is absent"
    return str(play_type), "R7 observed from nfl_pbp.play_type"


def stoppage_context(row: dict, family: str) -> dict:
    if row.get("penalty") is None:
        return {
            "value": None,
            "label": "unresolvable",
            "rule": "PBP penalty flag is null; cannot rule out a penalty clock override",
        }
    if _true(row.get("penalty")):
        return {
            "value": None,
            "label": "unresolvable",
            "rule": "PBP penalty is observed, but enforcement and its game-clock effect are not supplied",
        }
    if family == "pass_incomplete":
        return {
            "value": "incomplete_pass_clock_stop",
            "label": "inferred",
            "rule": "PBP incomplete-pass result implies a play-end clock stop; penalty override is absent",
        }
    if row.get("play_type") == "qb_spike":
        return {
            "value": "quarterback_spike_clock_stop",
            "label": "inferred",
            "rule": "PBP qb_spike play type implies a play-end clock stop",
        }
    if family == "touchdown":
        return {
            "value": "score_transition",
            "label": "inferred",
            "rule": "PBP touchdown result identifies a scoring transition; exact dead-time duration is unavailable",
        }
    return {
        "value": None,
        "label": "unresolvable",
        "rule": "nfl_pbp has no out_of_bounds or timeout field, and other terminal clock stoppages are not identifiable",
    }


def _clock_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _observed_pbp_value(value, field: str) -> dict:
    if value is None or value == "":
        return {"value": None, "label": "unresolvable", "rule": f"nfl_pbp.{field} is null"}
    return {"value": value, "label": "observed", "rule": f"nfl_pbp.{field}"}


def actual_clock_delta(current: dict, following: dict | None) -> dict:
    if following is None:
        return {"value": None, "label": "unresolvable", "rule": "R4u1 no next PBP play row"}
    if current.get("qtr") is None or following.get("qtr") is None:
        return {"value": None, "label": "unresolvable", "rule": "R4u4 quarter value missing in PBP"}
    if current["qtr"] != following["qtr"]:
        return {"value": None, "label": "unresolvable", "rule": "R4u2 next PBP play is in another quarter; runoff is censored at the boundary"}
    now = _clock_number(current.get("game_seconds_remaining"))
    next_clock = _clock_number(following.get("game_seconds_remaining"))
    if now is None or next_clock is None:
        return {"value": None, "label": "unresolvable", "rule": "R4u4 a PBP game_seconds_remaining stamp is missing"}
    delta = now - next_clock
    if delta < 0:
        return {"value": None, "label": "unresolvable", "rule": "R4u3 PBP clock delta is negative"}
    return {
        "value": round(delta, 3),
        "label": "inferred",
        "rule": "R4 inferred: current PBP game_seconds_remaining minus next same-quarter PBP play stamp",
    }


def _late_half(row: dict) -> str:
    clock = _clock_number(row.get("game_seconds_remaining"))
    if row.get("qtr") in (2, 4) and clock is not None and clock <= 120:
        return "late_half"
    if row.get("qtr") in (1, 2, 3, 4) and clock is not None:
        return "not_late_half"
    return "unknown"


def _down_band(row: dict) -> str:
    try:
        down = int(row["down"])
    except (KeyError, TypeError, ValueError):
        return "unknown"
    if down in (1, 2):
        return "down_1_2"
    if down in (3, 4):
        return "down_3_4"
    return "unknown"


def make_features(row: dict) -> dict:
    family, family_rule = outcome_family(row)
    return {
        "play_type": str(row.get("play_type") or "unknown"),
        "outcome_family": family,
        "late_half": _late_half(row),
        "down_band": _down_band(row),
        "outcome_rule": family_rule,
    }


def labelled_features(row: dict) -> dict:
    features = row["features"]
    family_label = "unresolvable" if features["outcome_family"] in ("terminal_outcome_unknown", "pass_result_unknown") else "observed"
    return {
        "play_type": {"value": features["play_type"], "label": "observed", "rule": "nfl_pbp.play_type"},
        "outcome_family": {"value": features["outcome_family"] if family_label == "observed" else None,
                           "label": family_label, "rule": features["outcome_rule"]},
        "late_half": {"value": features["late_half"] if features["late_half"] != "unknown" else None,
                      "label": "inferred" if features["late_half"] != "unknown" else "unresolvable",
                      "rule": "inferred from qtr in {2,4} and PBP game_seconds_remaining <= 120"},
        "down_band": {"value": features["down_band"] if features["down_band"] != "unknown" else None,
                      "label": "inferred" if features["down_band"] != "unknown" else "unresolvable",
                      "rule": "inferred from PBP down: 1-2 or 3-4"},
    }


def _key(level: str, features: dict) -> tuple:
    if level == "play_type_outcome_late_half_down":
        return (features["play_type"], features["outcome_family"], features["late_half"], features["down_band"])
    if level == "play_type_outcome_late_half":
        return (features["play_type"], features["outcome_family"], features["late_half"])
    if level == "play_type_outcome":
        return (features["play_type"], features["outcome_family"])
    if level == "play_type":
        return (features["play_type"],)
    return ()


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _target_value(row: dict):
    target = row["actual_game_clock_delta_s"]
    return target["value"] if target["label"] == "inferred" else None


def train_fold(rows: list[dict], held_week: int) -> dict:
    training = [row for row in rows if row["week"] != held_week and _target_value(row) is not None]
    buckets: dict[tuple, list[float]] = defaultdict(list)
    values = []
    for row in training:
        value = _target_value(row)
        values.append(value)
        features = row["features"]
        for level, _minimum in BACKOFF[:-1]:
            buckets[(level, _key(level, features))].append(value)
        buckets[("global", ())].append(value)
    if not values:
        raise RuntimeError(f"no PBP clock-delta training rows outside held week {held_week}")
    return {"held_week": held_week, "training": training, "buckets": buckets, "global": values}


def predict(fold: dict, features: dict) -> dict:
    for level, minimum in BACKOFF:
        values = fold["buckets"].get((level, _key(level, features)), [])
        if len(values) >= minimum:
            selected_level = level
            break
    else:  # global always exists for a valid fold
        values = fold["global"]
        selected_level = "global"
    return {
        "p10_s": round(_quantile(values, 0.10), 3),
        "p50_s": round(statistics.median(values), 3),
        "p90_s": round(_quantile(values, 0.90), 3),
        "probability_clock_delta_positive": round(sum(value > 0 for value in values) / len(values), 6),
        "probability_clock_delta_zero": round(sum(value == 0 for value in values) / len(values), 6),
        "label": "inferred",
        "rule": "PBP-only conditional empirical quantiles; week-held-out training; no tracking-derived features",
        "backoff_level": selected_level,
        "training_rows": len(values),
        "training_weeks": [week for week in sorted(ALLOWED_WEEKS) if week != fold["held_week"]],
    }


def _runoff_behavior(delta: dict) -> dict:
    value = delta["value"]
    if value is None:
        return {"value": None, "label": "unresolvable", "rule": delta["rule"]}
    behavior = "no_displayed_clock_decrease" if value == 0 else "clock_decreased_between_PBP_stamps"
    return {"value": behavior, "label": "inferred", "rule": "derived from the two observed PBP game-clock stamps"}


def _pair_records(records: list[dict]) -> list[dict]:
    ordered = sorted(records, key=lambda row: (str(row["game_id"]), int(row["play_id"])))
    seen = set()
    for row in ordered:
        key = (row["game_id"], int(row["play_id"]))
        if key in seen:
            raise RuntimeError(f"duplicate LP nfl_pbp key {key[0]}/{key[1]}")
        seen.add(key)
    output = []
    for index, row in enumerate(ordered):
        following = None
        if index + 1 < len(ordered) and ordered[index + 1]["game_id"] == row["game_id"]:
            following = ordered[index + 1]
        delta = actual_clock_delta(row, following)
        family, family_rule = outcome_family(row)
        clock_value = _clock_number(row.get("game_seconds_remaining"))
        output.append({
            "game_id": row["game_id"],
            "play_id": int(row["play_id"]),
            "week": int(row["week"]),
            "source_context": {
                "quarter": _observed_pbp_value(row.get("qtr"), "qtr"),
                "down": _observed_pbp_value(row.get("down"), "down"),
                "distance": _observed_pbp_value(row.get("ydstogo"), "ydstogo"),
                "play_type": _observed_pbp_value(row.get("play_type"), "play_type"),
            },
            "features": make_features(row),
            "terminal_event_family": {
                "value": family if family not in ("terminal_outcome_unknown", "pass_result_unknown") else None,
                "label": "unresolvable" if family in ("terminal_outcome_unknown", "pass_result_unknown") else "observed",
                "rule": family_rule,
            },
            "observed_game_clock_seconds_remaining": {
                "value": clock_value,
                "label": "observed" if clock_value is not None else "unresolvable",
                "rule": "PBP game_seconds_remaining at this play row",
            },
            "actual_game_clock_delta_s": delta,
            "actual_clock_runoff_s": dict(delta),
            "actual_runoff_behavior": _runoff_behavior(delta),
            "in_play_duration_s": {
                "value": None,
                "label": "unresolvable",
                "rule": "PBP-only source has no terminal timestamp or live-play duration",
            },
            "between_play_dead_time_s": {
                "value": None,
                "label": "unresolvable",
                "rule": "cannot separate PBP clock delta into live-play duration and dead time without a terminal timestamp",
            },
            "stoppage_context": stoppage_context(row, family),
            "source_evidence": {
                "penalty_present": _flag_label(row.get("penalty"), "penalty"),
                "out_of_bounds": {"value": None, "label": "unresolvable", "rule": "no out_of_bounds column in LP nfl_pbp"},
                "timeout": {"value": None, "label": "unresolvable", "rule": "no timeout column in LP nfl_pbp"},
            },
        })
    return output


def _metric_summary(scored: list[tuple[dict, dict]]) -> dict:
    if not scored:
        return {"n": 0, "mae_conditional_s": None, "mae_global_median_s": None, "p10_p90_coverage": None}
    errors = [abs(row["actual_game_clock_delta_s"]["value"] - prediction["p50_s"]) for row, prediction in scored]
    baseline_errors = [abs(row["actual_game_clock_delta_s"]["value"] - prediction["global_baseline_p50_s"]) for row, prediction in scored]
    covered = [prediction["p10_s"] <= row["actual_game_clock_delta_s"]["value"] <= prediction["p90_s"] for row, prediction in scored]
    brier = [(prediction["probability_clock_delta_positive"] - float(row["actual_game_clock_delta_s"]["value"] > 0)) ** 2 for row, prediction in scored]
    return {
        "n": len(scored),
        "mae_conditional_s": round(statistics.mean(errors), 4),
        "mae_global_median_s": round(statistics.mean(baseline_errors), 4),
        "mae_change_vs_global_s": round(statistics.mean(errors) - statistics.mean(baseline_errors), 4),
        "p10_p90_coverage": round(sum(covered) / len(covered), 6),
        "brier_clock_delta_positive": round(statistics.mean(brier), 6),
    }


def build_artifact(records: list[dict], input_sha256: str, weeks: tuple[int, ...]) -> dict:
    weeks = validate_weeks(weeks)
    paired = _pair_records(records)
    by_week: dict[int, list[dict]] = defaultdict(list)
    for row in paired:
        by_week[row["week"]].append(row)
    for week in weeks:
        if not by_week[week]:
            raise RuntimeError(f"week {week} has no PBP play rows in the source slice")

    predictions_for_metrics: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
    for held_week in weeks:
        fold = train_fold(paired, held_week)
        global_median = round(statistics.median(fold["global"]), 3)
        for row in by_week[held_week]:
            prediction = predict(fold, row["features"])
            prediction["global_baseline_p50_s"] = global_median
            row["prediction"] = {
                "game_clock_delta_s": prediction,
                "clock_runoff_s": {
                    "p10_s": prediction["p10_s"],
                    "p50_s": prediction["p50_s"],
                    "p90_s": prediction["p90_s"],
                    "label": "inferred",
                    "rule": prediction["rule"],
                },
                "stoppage_context": dict(row["stoppage_context"]),
            }
            if row["actual_game_clock_delta_s"]["label"] == "inferred":
                predictions_for_metrics[held_week].append((row, prediction))

    for row in paired:
        row["model_inputs"] = labelled_features(row)
        del row["features"]

    coverage = {}
    per_week_metrics = {}
    for week in weeks:
        labels = Counter(row["actual_game_clock_delta_s"]["label"] for row in by_week[week])
        reasons = Counter(
            row["actual_game_clock_delta_s"]["rule"].split()[0]
            for row in by_week[week]
            if row["actual_game_clock_delta_s"]["label"] == "unresolvable"
        )
        coverage[str(week)] = {
            "plays": len(by_week[week]),
            "game_clock_delta_labels": dict(sorted(labels.items())),
            "unresolvable_reasons": dict(sorted(reasons.items())),
            "stoppage_context_labels": dict(sorted(Counter(row["stoppage_context"]["label"] for row in by_week[week]).items())),
        }
        per_week_metrics[str(week)] = _metric_summary(predictions_for_metrics[week])

    all_scored = [pair for week in weeks for pair in predictions_for_metrics[week]]
    week5 = predictions_for_metrics.get(5, [])
    fields = {
        "all_rows": len(paired),
        "season": 2022,
        "weeks": list(weeks),
        "queried_week_filter": "season=2022 AND week IN (1,2,3,4,5) AND play_type IS NOT NULL",
        "pbp_only": True,
        "tracking_inputs": [],
        "forbidden_weeks_read": [],
        "record_count_by_week": {str(week): len(by_week[week]) for week in weeks},
    }
    return {
        "schema": SCHEMA,
        "source": {
            "repository": "legendarypicks",
            "base_commit": BASE_COMMIT,
            "database_file": "backend/data/picks.dev.db (local dev snapshot, opened read-only)",
            "database_table": "nfl_pbp (read-only)",
            "database_note": "dev database file hash is environment-specific; input_slice_sha256 pins selected PBP rows",
            "input_fields": list(INPUT_FIELDS),
            "input_slice_sha256": input_sha256,
            "producer_script": "scripts/bdb/e3_pbp_conditional_clock_model.py",
            "producer_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "excluded_source_columns": {
                "out_of_bounds": "not present in nfl_pbp schema",
                "timeout": "not present in nfl_pbp schema",
                "terminal_timestamp": "not present in nfl_pbp schema",
            },
        },
        "scope": fields,
        "model": {
            "name": "PBP-only hierarchical conditional median",
            "prediction_unit": "one LP nfl_pbp play row",
            "prediction_target": "same-quarter current play game_seconds_remaining minus next PBP play game_seconds_remaining",
            "folding": "leave-one-week-out; week 5 trains on weeks 1-4 only",
            "input_fields": ["play_type", "outcome_family", "late_half", "down_band"],
            "target_labels": ["observed", "inferred", "unresolvable"],
            "minimum_support_and_backoff": [
                {"level": level, "minimum_rows": count} for level, count in BACKOFF
            ],
            "not_tuned_on_evaluation_weeks": True,
        },
        "coverage": coverage,
        "evaluation": {
            "cross_fitted_weeks_1_5": _metric_summary(all_scored),
            "forward_week_5_holdout": _metric_summary(week5),
            "per_week": per_week_metrics,
            "interpretation": "PBP-only retrospective clock-delta estimate; not a pre-snap forecast, physical play duration, or stoppage adjudication.",
        },
        "unresolvable_policy": {
            "label_set": ["observed", "inferred", "unresolvable"],
            "null_rule": "unresolvable values have null value and retain a rule; no fallback or proxy is substituted",
            "live_duration": "unresolvable for every row without tracking terminal timestamps",
            "between_play_dead_time": "unresolvable for every row because PBP delta cannot be decomposed without live duration",
            "out_of_bounds_and_timeout": "unresolvable from nfl_pbp alone; do not copy nflverse flags or tracking labels",
            "penalty_clock_effect": "unresolvable from a penalty flag alone",
        },
        "plays": paired,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weeks", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    args = parser.parse_args(argv)
    try:
        weeks = validate_weeks(args.weeks)
        records, input_sha256 = load_pbp(args.db, weeks)
        artifact = build_artifact(records, input_sha256, weeks)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"PBP source rows: {len(records)}; week coverage: {artifact['scope']['record_count_by_week']}")
    print(f"Input slice SHA-256: {input_sha256}")
    print(f"Resolved targets: {sum(item['game_clock_delta_labels'].get('inferred', 0) for item in artifact['coverage'].values())}")
    print(f"Unresolvable targets: {sum(item['game_clock_delta_labels'].get('unresolvable', 0) for item in artifact['coverage'].values())}")
    print(f"Cross-fitted MAE: {artifact['evaluation']['cross_fitted_weeks_1_5']['mae_conditional_s']} s; global baseline {artifact['evaluation']['cross_fitted_weeks_1_5']['mae_global_median_s']} s")
    print(f"Week-5 forward MAE: {artifact['evaluation']['forward_week_5_holdout']['mae_conditional_s']} s; global baseline {artifact['evaluation']['forward_week_5_holdout']['mae_global_median_s']} s")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
