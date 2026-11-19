"""Freeze per-game SLC context separately from reusable fitted reference state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA = "lp-slc-current-streak-context-1"


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


def current_streaks_for_snapshot(snapshot, team_codes, streak_splits):
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
    required = {team_codes.to_pbp_team_code(schedule[key]) for key in ("home_team", "away_team")}
    teams = context.get("teams")
    if not isinstance(teams, dict) or not required.issubset(teams):
        raise ValueError("RUNTIME_CURRENT_STREAK_TEAMS_MISSING")
    result = {team: teams[team] for team in required}
    if any(bucket not in streak_splits.BUCKETS for bucket in result.values()):
        raise ValueError("RUNTIME_CURRENT_STREAK_BUCKET_INVALID")
    return result
