"""Versioned NFL Arcade challenges, scoring and anonymous score APIs."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

import arcade_store as store
from pixel_red_zone import published_field_goal_attempt_distance, published_field_goal_challenge_id

router = APIRouter()

PHYSICS_VERSION = store.PHYSICS_VERSION
SCORING_VERSION = store.SCORING_VERSION
SCHEMA_VERSION = "lp-arcade-challenge-v2"
TRAINING_SCHEMA_VERSION = "lp-arcade-training-v1"
_REPLAY_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pixel_red_zone"
_FIELD_GOAL_ATTEMPT_TYPES = {"Field Goal Good", "Field Goal Missed", "Blocked Field Goal"}
_SOURCE_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_REAL_OUTCOME_BY_TYPE = {
    "Field Goal Good": {"status": "made", "label": "Real attempt: made"},
    "Field Goal Missed": {"status": "missed", "label": "Real attempt: missed"},
    "Blocked Field Goal": {"status": "blocked", "label": "Real attempt: blocked"},
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArcadeInput(StrictModel):
    aim: FiniteFloat = Field(..., ge=-1.0, le=1.0)
    power: FiniteFloat = Field(..., ge=0.0, le=1.0)
    release_timing: FiniteFloat = Field(..., ge=0.0, le=1.0)


class ArcadeAttempt(StrictModel):
    attempt_id: UUID
    challenge_id: str = Field(..., min_length=1, max_length=80)
    input: ArcadeInput
    share_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    drill_id: Optional[str] = Field(default=None, min_length=1, max_length=80)
    drill_run_id: Optional[UUID] = None
    drill_attempt_index: Optional[int] = Field(default=None, ge=0, le=4)


class ArcadeShareRequest(StrictModel):
    attempt_id: UUID
    challenge_id: str = Field(..., min_length=1, max_length=80)


def _config_hash(config: dict) -> str:
    return store.frozen_config_hash(config, PHYSICS_VERSION, SCORING_VERSION)


def _challenge(challenge_id: str, yards: int, target_aim: float = 0.0) -> dict:
    config = {
        "attempt_distance_yards": yards,
        "target_aim": target_aim,
        "aim_tolerance": 0.24,
        "timing_window": 0.26,
        "range_min_margin_yards": 1.5,
        "range_max_margin_yards": 8.0,
        "weather_mode": "neutral_arcade",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "challenge_id": challenge_id,
        "kind": "field_goal",
        "origin": "fictional_practice",
        "source_ref": None,
        "observed_context": None,
        "challenge_config": config,
        "physics_version": PHYSICS_VERSION,
        "scoring_version": SCORING_VERSION,
        "config_hash": _config_hash(config),
        "state": "available",
    }


_PRACTICE_CHALLENGES = {
    challenge["challenge_id"]: challenge
    for challenge in (
        _challenge("practice-fg-25-v1", 25),
        _challenge("practice-fg-35-v1", 35),
        _challenge("practice-fg-45-v1", 45),
        _challenge("practice-fg-52-v1", 52),
        _challenge("practice-fg-55-v1", 55),
    )
}

_DRILLS = [
    {
        "id": "aim-lab-v1",
        "name": "Aim Lab",
        "description": "Center, then line up two changing hash marks.",
        "medal_thresholds": {"bronze": 1500, "silver": 2200, "gold": 2700},
        "attempts": [
            {"challenge_id": "aim-lab-25-center-v1", "yards": 25, "target_aim": 0.0, "target_label": "CENTER"},
            {"challenge_id": "aim-lab-35-left-v1", "yards": 35, "target_aim": -0.34, "target_label": "LEFT HASH"},
            {"challenge_id": "aim-lab-45-right-v1", "yards": 45, "target_aim": 0.34, "target_label": "RIGHT HASH"},
        ],
    },
    {
        "id": "precision-set-v1",
        "name": "Precision Set",
        "description": "Combine aim, distance and release timing across three kicks.",
        "medal_thresholds": {"bronze": 1500, "silver": 2200, "gold": 2700},
        "attempts": [
            {"challenge_id": "precision-30-center-v1", "yards": 30, "target_aim": 0.0, "target_label": "CENTER"},
            {"challenge_id": "precision-40-left-v1", "yards": 40, "target_aim": -0.25, "target_label": "LEFT HASH"},
            {"challenge_id": "precision-50-right-v1", "yards": 50, "target_aim": 0.25, "target_label": "RIGHT HASH"},
        ],
    },
]
_DRILLS_BY_ID = {drill["id"]: drill for drill in _DRILLS}

_DRILL_CHALLENGES = {
    attempt["challenge_id"]: _challenge(attempt["challenge_id"], attempt["yards"], attempt["target_aim"])
    for drill in _DRILLS
    for attempt in drill["attempts"]
}
_CHALLENGES = {**_PRACTICE_CHALLENGES, **_DRILL_CHALLENGES}


def _resolve_challenge(challenge_id: str) -> dict | None:
    challenge = _CHALLENGES.get(challenge_id)
    if challenge is not None:
        return challenge
    if challenge_id.startswith("espn-fg-"):
        return store.live_challenge(challenge_id)
    return None


def _load_archived_challenges() -> tuple[dict[str, dict], dict[str, dict]]:
    """Build immutable challenge snapshots from the bundled, normalized ESPN archive."""
    challenges: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    for path in sorted(_REPLAY_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            replay = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        game = replay.get("game") or {}
        game_id = str(game.get("game_id") or "")
        teams = game.get("teams") or {}
        away_team = (teams.get("away") or {}).get("name")
        home_team = (teams.get("home") or {}).get("name")
        if (replay.get("schema_version") != "lp-observed-nfl-event-v1"
                or replay.get("mode") != "replay" or not game_id.isdigit() or game_id != path.stem
                or not isinstance(away_team, str) or not away_team
                or not isinstance(home_team, str) or not home_team):
            continue
        for event in replay.get("events") or []:
            event_type = event.get("source_event_type")
            if event_type not in _FIELD_GOAL_ATTEMPT_TYPES or event.get("game_id") != game_id:
                continue
            source = event.get("source") or {}
            play_id = str(source.get("play_id") or "")
            event_id = str(source.get("event_id") or "")
            revision = str(source.get("revision") or "")
            observed_at = source.get("observed_at_utc")
            if (source.get("publisher") != "ESPN" or not play_id
                    or source.get("revision_basis") != "canonical_raw_play_sha256"
                    or not _SOURCE_REVISION_RE.fullmatch(revision) or not observed_at
                    or event_id != f"{game_id}:ESPN:{play_id}"):
                continue
            distance, provenance = published_field_goal_attempt_distance(event.get("display_text"), event_type)
            if distance is None or provenance.get("confidence") != "verified":
                continue

            source_ref = {
                "publisher": "ESPN",
                "game_id": game_id,
                "play_id": play_id,
                "event_id": event_id,
                "source_revision": revision,
            }
            observed_context = {
                "away_team": away_team,
                "away_team_id": (teams.get("away") or {}).get("team_id"),
                "home_team": home_team,
                "home_team_id": (teams.get("home") or {}).get("team_id"),
                "period": event.get("period"),
                "clock": event.get("clock"),
                "game_date": game.get("date"),
                "attempt_distance_yards": distance,
            }
            challenge_id = published_field_goal_challenge_id(event_id, revision)
            challenge = _challenge(challenge_id, distance)
            challenge.update({
                "origin": "observed_nfl_play",
                "source_ref": source_ref,
                "source_verified_at_utc": observed_at,
                "observed_context": observed_context,
                "state": "archived_verified",
            })
            challenges[challenge_id] = challenge
            outcomes[challenge_id] = deepcopy(_REAL_OUTCOME_BY_TYPE[event_type])
    return challenges, outcomes


_ARCHIVED_CHALLENGES, _ARCHIVED_OUTCOMES = _load_archived_challenges()
_CHALLENGES.update(_ARCHIVED_CHALLENGES)


def training_catalog() -> dict:
    return {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "physics_version": PHYSICS_VERSION,
        "scoring_version": SCORING_VERSION,
        "origin": "fictional_practice",
        "drills": deepcopy(_DRILLS),
    }


def _drills_with_scenario_versions() -> list[dict]:
    return [
        {
            **drill,
            "scenario_versions": [
                (attempt["challenge_id"], _DRILL_CHALLENGES[attempt["challenge_id"]]["config_hash"])
                for attempt in drill["attempts"]
            ],
        }
        for drill in _DRILLS
    ]


def score_attempt(challenge: dict, attempt: ArcadeInput) -> dict:
    """Recalculate an arcade result from normalized inputs and frozen rules."""
    if not all(math.isfinite(value) for value in (attempt.aim, attempt.power, attempt.release_timing)):
        raise ValueError("arcade inputs must be finite numbers")

    config = challenge["challenge_config"]
    distance = config["attempt_distance_yards"]
    aim_error = attempt.aim - config["target_aim"]
    timing_error = attempt.release_timing - 0.5
    range_yards = 14.0 + attempt.power * 55.0
    range_error = range_yards - distance

    if aim_error < -config["aim_tolerance"]:
        feedback = "LEFT"
        coaching = "Aim right to bring the kick back toward the target."
    elif aim_error > config["aim_tolerance"]:
        feedback = "RIGHT"
        coaching = "Aim left to bring the kick back toward the target."
    elif range_yards < distance - config["range_min_margin_yards"]:
        feedback = "SHORT"
        coaching = "Add power so the kick reaches the uprights."
    elif range_yards > distance + config["range_max_margin_yards"]:
        feedback = "LONG"
        coaching = "Ease off the power to keep the kick inside the uprights."
    elif timing_error < -config["timing_window"]:
        feedback = "EARLY"
        coaching = "Release closer to the center of the timing window."
    elif timing_error > config["timing_window"]:
        feedback = "LATE"
        coaching = "Release closer to the center of the timing window."
    else:
        feedback = "GOOD"
        coaching = "Clean kick. Try to bring aim, timing and distance even closer."

    made = feedback == "GOOD"
    precision_bonus = 0
    distance_bonus = 0
    score = 0
    if made:
        aim_quality = max(0.0, 1.0 - abs(aim_error) / config["aim_tolerance"])
        timing_quality = max(0.0, 1.0 - abs(timing_error) / config["timing_window"])
        precision_bonus = round(300 * aim_quality * timing_quality)
        distance_bonus = round(100 * max(0.0, 1.0 - abs(range_error) / 10.0))
        score = 600 + precision_bonus + distance_bonus

    return {
        "attempt_id": None,
        "challenge_id": challenge["challenge_id"],
        "origin": challenge["origin"],
        "config_hash": challenge["config_hash"],
        "physics_version": challenge["physics_version"],
        "scoring_version": challenge["scoring_version"],
        "attempt_distance_yards": distance,
        "made": made,
        "feedback": feedback,
        "score": min(1000, max(0, score)),
        "score_breakdown": {
            "base": 600 if made else 0,
            "precision": precision_bonus,
            "distance_execution": distance_bonus,
        },
        "coaching": coaching,
        "estimated_arcade_range_yards": round(range_yards, 1),
        "real_game_outcome": None,
    }


@router.get("/api/arcade/training")
async def get_training():
    return training_catalog()


@router.get("/api/arcade/moments")
async def get_archived_moments():
    """List archived and freshly observed source-verified kicks without results."""
    moments = []
    for challenge in _ARCHIVED_CHALLENGES.values():
        context = challenge["observed_context"]
        moments.append({
            "challenge_id": challenge["challenge_id"],
            "origin": challenge["origin"],
            "state": challenge["state"],
            "source_ref": deepcopy(challenge["source_ref"]),
            "source_verified_at_utc": challenge["source_verified_at_utc"],
            "observed_context": deepcopy(context),
        })
    try:
        live_moments = store.recent_live_moments()
        archived_live_moments = store.recent_archived_moments()
        live_available = True
        archive_live_available = True
    except store.StoreUnavailable:
        live_moments = []
        archived_live_moments = []
        live_available = False
        archive_live_available = False
    listed_ids = {moment["challenge_id"] for moment in moments}
    moments.extend(moment for moment in archived_live_moments
                   if moment["challenge_id"] not in listed_ids)
    return {"moments": moments, "live_moments": live_moments,
            "live_available": live_available, "archive_live_available": archive_live_available}


def _store_http_error(error: Exception) -> HTTPException:
    if isinstance(error, store.InvalidClaim):
        return HTTPException(status_code=401, detail=str(error))
    if isinstance(error, store.RateLimited):
        return HTTPException(status_code=429, detail=str(error), headers={"Retry-After": "3600"})
    if isinstance(error, store.AttemptConflict):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail="Arcade scores are temporarily unavailable")


@router.post("/api/arcade/session")
async def create_anonymous_session(
    request: Request,
    x_arcade_claim: Optional[str] = Header(default=None, alias="X-Arcade-Claim"),
):
    try:
        token, created = store.issue_claim(x_arcade_claim, request.client.host if request.client else None)
    except (store.StoreUnavailable, store.InvalidClaim, store.RateLimited) as exc:
        raise _store_http_error(exc) from exc
    return JSONResponse({"claim_token": token, "created": created}, status_code=201 if created else 200)


@router.get("/api/arcade/personal-bests")
async def get_personal_bests(
    x_arcade_claim: Optional[str] = Header(default=None, alias="X-Arcade-Claim"),
):
    try:
        claim_hash = store.authorize_claim(x_arcade_claim)
        return store.personal_bests(claim_hash, _drills_with_scenario_versions())
    except (store.StoreUnavailable, store.InvalidClaim) as exc:
        raise _store_http_error(exc) from exc


@router.get("/api/arcade/leaderboard")
async def get_leaderboard(
    challenge_id: str = Query(..., min_length=1, max_length=80),
    config_hash: Optional[str] = Query(default=None, min_length=64, max_length=64),
    limit: int = Query(10, ge=1, le=50),
):
    try:
        challenge = _resolve_challenge(challenge_id)
        if challenge is None:
            return JSONResponse({"error": "challenge not found"}, status_code=404)
        if config_hash is not None and config_hash != challenge["config_hash"]:
            return JSONResponse({"error": "challenge version unavailable"}, status_code=409)
        return {"challenge_id": challenge_id, "config_hash": challenge["config_hash"],
                "entries": store.challenge_leaderboard(challenge_id, challenge["config_hash"], limit)}
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc


@router.post("/api/arcade/shares")
async def post_share(
    payload: ArcadeShareRequest,
    x_arcade_claim: Optional[str] = Header(default=None, alias="X-Arcade-Claim"),
):
    try:
        claim_hash = store.authorize_claim(x_arcade_claim)
        challenge = _resolve_challenge(payload.challenge_id)
        if challenge is None:
            return JSONResponse({"error": "challenge not found"}, status_code=404)
        share_id, score = store.create_share(
            claim_hash, str(payload.attempt_id), payload.challenge_id, challenge["config_hash"],
        )
        return {"share_id": share_id, "challenge_id": payload.challenge_id,
                "config_hash": challenge["config_hash"], "target_score": score}
    except (store.StoreUnavailable, store.InvalidClaim, store.RateLimited) as exc:
        raise _store_http_error(exc) from exc


@router.get("/api/arcade/shares/{share_id}")
async def get_share(share_id: str):
    try:
        share = store.resolve_share(share_id)
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc
    if share is None:
        return JSONResponse({"error": "share not found"}, status_code=404)
    try:
        challenge = _resolve_challenge(share["challenge_id"])
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc
    if challenge is None:
        return JSONResponse({"error": "share not found"}, status_code=404)
    if share["config_hash"] != challenge["config_hash"]:
        return JSONResponse({"error": "share version unavailable"}, status_code=410)
    return share


@router.get("/api/arcade/challenges/{challenge_id}")
async def get_challenge(challenge_id: str):
    try:
        challenge = _resolve_challenge(challenge_id)
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc
    if challenge is None:
        return JSONResponse({"error": "challenge not found"}, status_code=404)
    return deepcopy(challenge)


@router.post("/api/arcade/attempts")
async def post_attempt(
    payload: ArcadeAttempt,
    x_arcade_claim: Optional[str] = Header(default=None, alias="X-Arcade-Claim"),
):
    try:
        challenge = _resolve_challenge(payload.challenge_id)
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc
    if challenge is None:
        return JSONResponse({"error": "challenge not found"}, status_code=404)
    drill_metadata = (payload.drill_id, payload.drill_run_id, payload.drill_attempt_index)
    drill = _DRILLS_BY_ID.get(payload.drill_id) if payload.drill_id else None
    if any(value is not None for value in drill_metadata):
        if (drill is None or any(value is None for value in drill_metadata)
                or payload.drill_attempt_index is None
                or payload.drill_attempt_index >= len(drill["attempts"])
                or drill["attempts"][payload.drill_attempt_index]["challenge_id"] != payload.challenge_id):
            return JSONResponse({"error": "training scenario does not match the frozen drill"}, status_code=422)
    try:
        claim_hash = store.authorize_claim(x_arcade_claim)
    except store.InvalidClaim as exc:
        raise _store_http_error(exc) from exc
    except store.StoreUnavailable as exc:
        raise _store_http_error(exc) from exc
    result = score_attempt(challenge, payload.input)
    result["attempt_id"] = str(payload.attempt_id)
    real_outcome = _ARCHIVED_OUTCOMES.get(payload.challenge_id)
    if real_outcome is None and challenge["origin"] == "observed_nfl_play":
        try:
            real_outcome = store.live_real_outcome(payload.challenge_id)
        except store.StoreUnavailable as exc:
            raise _store_http_error(exc) from exc
    if real_outcome is not None:
        result["real_game_outcome"] = deepcopy(real_outcome)
    try:
        return store.record_attempt(
            claim_hash,
            attempt_id=str(payload.attempt_id),
            challenge_id=payload.challenge_id,
            config_hash=challenge["config_hash"],
            origin=challenge["origin"],
            input_payload=payload.input.model_dump(),
            result=result,
            drill_id=payload.drill_id,
            drill_run_id=str(payload.drill_run_id) if payload.drill_run_id else None,
            drill_attempt_index=payload.drill_attempt_index,
            drill_attempt_count=len(drill["attempts"]) if drill else None,
            drill_scenarios=[
                (item["challenge_id"], _DRILL_CHALLENGES[item["challenge_id"]]["config_hash"])
                for item in drill["attempts"]
            ] if drill else None,
            medal_thresholds=drill["medal_thresholds"] if drill else None,
            referral_share_id=payload.share_id,
        )
    except (store.StoreUnavailable, store.InvalidClaim, store.RateLimited, store.AttemptConflict) as exc:
        raise _store_http_error(exc) from exc
