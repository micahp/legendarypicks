"""Freeze per-game SLC context separately from reusable fitted reference state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA = "lp-slc-current-streak-context-1"
MODEL_INPUT_SCHEMA = "lp-slc-runtime-model-inputs-1"


def _utc(value):
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("CURRENT_STREAK_CUTOFF_MISSING_TIMEZONE")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def freeze_current_streak_context(path, snapshot, streak_splits, team_codes):
    """Attach cutoff-pinned current streaks to the game snapshot in engine team codes."""
    raw = Path(path).read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CURRENT_STREAK_FILE_INVALID_JSON") from exc
    schedule = snapshot["schedule"]
    if payload.get("game_id") not in (None, schedule.get("game_id")):
        raise ValueError("CURRENT_STREAK_GAME_ID_MISMATCH")
    source_cutoff = payload.get("cutoff_utc") or payload.get("as_of_utc")
    if not source_cutoff:
        raise ValueError("CURRENT_STREAK_CUTOFF_MISSING")
    source_cutoff = _utc(source_cutoff)
    snapshot_cutoff = _utc(snapshot.get("as_of"))
    if source_cutoff > snapshot_cutoff:
        raise ValueError("CURRENT_STREAK_CUTOFF_AFTER_SNAPSHOT")
    records = payload.get("teams")
    if not isinstance(records, dict):
        raise ValueError("CURRENT_STREAK_TEAMS_MISSING")
    teams = {}
    for source_team, record in records.items():
        bucket = streak_splits.bucket_from_text(record.get("streak", "") if isinstance(record, dict) else "")
        if bucket not in streak_splits.BUCKETS:
            continue
        teams[team_codes.to_pbp_team_code(source_team)] = bucket
    required = {team_codes.to_pbp_team_code(schedule[key]) for key in ("home_team", "away_team")}
    if not required.issubset(teams):
        raise ValueError("CURRENT_STREAK_REQUIRED_TEAMS_MISSING: " + ", ".join(sorted(required - teams.keys())))
    snapshot.setdefault("model_reference", {})["current_streak_context"] = {
        "schema": SCHEMA,
        "game_id": schedule["game_id"],
        "cutoff_utc": snapshot_cutoff,
        "source_cutoff_utc": source_cutoff,
        "teams": {team: teams[team] for team in sorted(required)},
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def freeze_current_streak_model_inputs(path, snapshot, streak_splits, team_codes):
    """Freeze the exact legacy streak table beside, but outside, the hashed pregame snapshot."""
    raw = Path(path).read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CURRENT_STREAK_FILE_INVALID_JSON") from exc
    context = ((snapshot.get("model_reference") or {}).get("current_streak_context"))
    if not isinstance(context, dict) or context.get("schema") != SCHEMA:
        raise ValueError("CURRENT_STREAK_CONTEXT_MISSING")
    if hashlib.sha256(raw).hexdigest() != context.get("source_sha256"):
        raise ValueError("CURRENT_STREAK_SOURCE_HASH_MISMATCH")
    records = payload.get("teams")
    if not isinstance(records, dict):
        raise ValueError("CURRENT_STREAK_TEAMS_MISSING")
    # Match the pinned loader exactly: keep original source keys and None buckets.
    teams = {team: streak_splits.bucket_from_text(
        record.get("streak", "") if isinstance(record, dict) else "")
        for team, record in records.items()}
    required = {team_codes.to_nflverse_team_code(snapshot["schedule"][key])
                for key in ("home_team", "away_team")}
    available = {team_codes.to_nflverse_team_code(team) for team in teams}
    if not required.issubset(available):
        raise ValueError("CURRENT_STREAK_REQUIRED_TEAMS_MISSING: " + ", ".join(sorted(required - available)))
    result = {"schema": MODEL_INPUT_SCHEMA, "current_streak": teams,
              "source_sha256": context["source_sha256"]}
    result["sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return result


def current_streaks_for_snapshot(snapshot, team_codes, streak_splits, model_inputs=None):
    context = ((snapshot.get("model_reference") or {}).get("current_streak_context"))
    if not isinstance(context, dict) or context.get("schema") != SCHEMA:
        raise ValueError("RUNTIME_CURRENT_STREAK_CONTEXT_MISSING")
    schedule = snapshot["schedule"]
    if context.get("game_id") != schedule.get("game_id"):
        raise ValueError("RUNTIME_CURRENT_STREAK_GAME_ID_MISMATCH")
    if _utc(context.get("cutoff_utc")) != _utc(snapshot.get("as_of")):
        raise ValueError("RUNTIME_CURRENT_STREAK_CUTOFF_MISMATCH")
    source_cutoff = context.get("source_cutoff_utc")
    if not source_cutoff or _utc(source_cutoff) > _utc(snapshot.get("as_of")):
        raise ValueError("RUNTIME_CURRENT_STREAK_SOURCE_CUTOFF_INVALID")
    if not isinstance(model_inputs, dict) or model_inputs.get("schema") != MODEL_INPUT_SCHEMA:
        raise ValueError("RUNTIME_CURRENT_STREAK_MODEL_INPUT_MISSING")
    expected_digest = model_inputs.get("sha256")
    body = {key: value for key, value in model_inputs.items() if key != "sha256"}
    actual_digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    if expected_digest != actual_digest:
        raise ValueError("RUNTIME_CURRENT_STREAK_MODEL_INPUT_HASH_MISMATCH")
    if model_inputs.get("source_sha256") != context.get("source_sha256"):
        raise ValueError("RUNTIME_CURRENT_STREAK_SOURCE_HASH_MISMATCH")
    teams = model_inputs.get("current_streak")
    if not isinstance(teams, dict):
        raise ValueError("RUNTIME_CURRENT_STREAK_TEAMS_MISSING")
    required = {team_codes.to_nflverse_team_code(schedule[key]) for key in ("home_team", "away_team")}
    if not required.issubset({team_codes.to_nflverse_team_code(team) for team in teams}):
        raise ValueError("RUNTIME_CURRENT_STREAK_TEAMS_MISSING")
    result = dict(teams)
    if any(bucket is not None and bucket not in streak_splits.BUCKETS for bucket in result.values()):
        raise ValueError("RUNTIME_CURRENT_STREAK_BUCKET_INVALID")
    return result
