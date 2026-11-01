"""Published ESPN play-by-play adapter and deterministic Red Zone director.

The adapter preserves publisher records and only marks field position verified
for event classes that passed the independent historical spot comparison. It
does not infer routes, yards gained, tries, or missing source state.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "lp-observed-nfl-event-v1"
_FIELD_GOAL_ATTEMPT_TYPES = {"Field Goal Good", "Field Goal Missed", "Blocked Field Goal"}
_FIELD_GOAL_DISTANCE_RE = re.compile(r"(?<!\d)(\d{1,2})\s+yards?\s+field goal\b", re.IGNORECASE)

# These are the event classes that had no non-punt spot disagreement in the
# bounded 988-play ESPN-vs-nflfastR comparison. Pass Reception, Penalty, Punt,
# timeouts, and two-minute warnings fail closed as complete classes.
SPOT_VERIFIED_TYPES = {
    "Rush",
    "Pass Incompletion",
    "Sack",
    "Passing Touchdown",
    "Rushing Touchdown",
    "Pass Interception Return",
    "Sack Opp Fumble Recovery",
    "Fumble Recovery (Own)",
    "Fumble Recovery (Opponent)",
    "Blocked Field Goal",
    "Field Goal Good",
    "Field Goal Missed",
}

EVENT_TYPES = {
    "Rush": "rush",
    "Pass Reception": "pass_reception",
    "Pass Incompletion": "pass_incompletion",
    "Sack": "sack",
    "Pass Interception Return": "interception",
    "Sack Opp Fumble Recovery": "fumble_recovery",
    "Fumble Recovery (Own)": "fumble_recovery",
    "Fumble Recovery (Opponent)": "fumble_recovery",
    "Punt": "punt",
    "Field Goal Good": "field_goal_good",
    "Field Goal Missed": "field_goal_missed",
    "Blocked Field Goal": "blocked_field_goal",
    "Passing Touchdown": "touchdown",
    "Rushing Touchdown": "touchdown",
    "Kickoff": "kickoff",
    "Penalty": "penalty",
    "Timeout": "timeout",
    "Official Timeout": "timeout",
    "Two-minute warning": "two_minute_warning",
    "End Period": "period_end",
    "End of Half": "half_end",
    "End of Game": "game_end",
}


def canonical_raw_hash(value: dict[str, Any]) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and value != number:
        return None
    return number


def _team_id(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    team = state.get("team")
    if not isinstance(team, dict) or team.get("id") in (None, ""):
        return None
    return str(team["id"])


def _spot(state: Any, event_type: str, team_ids: set[str]) -> int | None:
    if event_type not in SPOT_VERIFIED_TYPES or not isinstance(state, dict):
        return None
    value = _int_or_none(state.get("yardsToEndzone"))
    side_team_id = _team_id(state)
    if value is None or not 0 <= value <= 100 or side_team_id not in team_ids:
        return None
    return value


def _review_state(play: dict[str, Any]) -> str:
    review = play.get("review")
    if not isinstance(review, dict):
        return "none"
    upheld = review.get("upheld")
    if upheld is True:
        return "confirmed"
    if upheld is False:
        return "overturned"
    return "pending"


def _event_type(raw_type: Any) -> tuple[str, str | None]:
    label = raw_type.get("text") if isinstance(raw_type, dict) else None
    if not isinstance(label, str):
        return "unknown", None
    return EVENT_TYPES.get(label, "unknown"), label


def _source_score(play: dict[str, Any]) -> dict[str, int] | None:
    away = _int_or_none(play.get("awayScore"))
    home = _int_or_none(play.get("homeScore"))
    if away is None or home is None or away < 0 or home < 0:
        return None
    return {"away": away, "home": home}


def published_field_goal_attempt_distance(
    publisher_text: Any,
    source_event_type: str | None,
) -> tuple[int | None, dict[str, str]]:
    """Copy only an explicit distance phrase from ESPN's published FG event text.

    A missing or ambiguous phrase remains unavailable. Field position and the
    familiar snap/hold allowance are never used as a fallback.
    """
    if source_event_type not in _FIELD_GOAL_ATTEMPT_TYPES:
        return None, {"confidence": "not_applicable", "source_field": "play.text"}
    matches = list(_FIELD_GOAL_DISTANCE_RE.finditer(publisher_text)) if isinstance(publisher_text, str) else []
    if len(matches) != 1:
        return None, {
            "confidence": "unavailable",
            "source_field": "play.text",
            "reason": "no_unique_published_attempt_distance",
        }
    distance = int(matches[0].group(1))
    if not 1 <= distance <= 70:
        return None, {
            "confidence": "unavailable",
            "source_field": "play.text",
            "reason": "published_distance_out_of_range",
        }
    return distance, {
        "confidence": "verified",
        "publisher": "ESPN",
        "source_field": "play.text",
        "basis": "explicit_field_goal_yard_phrase",
    }


def published_field_goal_challenge_id(event_id: str, revision: str) -> str:
    """Return the immutable Arcade ID for one canonical publisher event revision."""
    digest = hashlib.sha256(f"{event_id}:{revision}".encode("utf-8")).hexdigest()[:24]
    return f"espn-fg-{digest}"


def plays_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ESPN plays in publisher order for flat and NFL drive envelopes."""
    flat = summary.get("plays")
    if isinstance(flat, list):
        return [play for play in flat if isinstance(play, dict)]
    result: list[dict[str, Any]] = []
    drives = summary.get("drives") or {}
    if not isinstance(drives, dict):
        return result
    for key in ("previous", "current"):
        container = drives.get(key)
        if isinstance(container, dict):
            container = [container]
        if not isinstance(container, list):
            continue
        for drive in container:
            if not isinstance(drive, dict):
                continue
            rows = drive.get("plays")
            if isinstance(rows, list):
                result.extend(play for play in rows if isinstance(play, dict))
    return result


def normalize_summary(
    summary: dict[str, Any],
    *,
    game_id: str | None = None,
    observed_at_utc: str | None = None,
    mode: str = "live",
) -> dict[str, Any]:
    """Normalize published ESPN state while retaining raw fields and provenance.

    `mode="replay"` is required for archived/final fixtures. In either mode,
    an event with no publisher ID is excluded and reported; prose is never used
    as an identity or a field-position fallback.
    """
    header = summary.get("header") or {}
    if not isinstance(header, dict):
        header = {}
    resolved_game_id = str(game_id or header.get("id") or "")
    if not resolved_game_id:
        raise ValueError("ESPN summary has no event ID")
    if mode not in {"live", "replay"}:
        raise ValueError("mode must be 'live' or 'replay'")

    competition = (header.get("competitions") or [{}])[0]
    if not isinstance(competition, dict):
        competition = {}
    competitors = [row for row in competition.get("competitors") or []
                   if isinstance(row, dict)]
    by_side = {row.get("homeAway"): row for row in competitors}
    teams = {}
    team_ids: set[str] = set()
    for side in ("home", "away"):
        row = by_side.get(side) or {}
        team = row.get("team") or {}
        raw_id = row.get("id") or team.get("id")
        if raw_id not in (None, ""):
            team_ids.add(str(raw_id))
        teams[side] = {
            "team_id": str(raw_id) if raw_id not in (None, "") else None,
            "abbreviation": team.get("abbreviation"),
            "name": team.get("displayName"),
        }

    source_status = (competition.get("status") or {}).get("type") or {}
    if not isinstance(source_status, dict):
        source_status = {}
    game_status = "replay" if mode == "replay" else source_status.get("state")
    rows = plays_from_summary(summary)
    raw_events: list[dict[str, Any]] = []
    missing_ids = 0
    duplicate_ids = 0
    seen: dict[str, set[str]] = {}

    for source_order, play in enumerate(rows):
        raw_play_id = play.get("id")
        if raw_play_id in (None, ""):
            missing_ids += 1
            continue
        play_id = str(raw_play_id)
        revision = canonical_raw_hash(play)
        known = seen.setdefault(play_id, set())
        if revision in known:
            duplicate_ids += 1
            continue
        known.add(revision)

        kind, source_type = _event_type(play.get("type"))
        field_goal_distance, field_goal_distance_provenance = published_field_goal_attempt_distance(
            play.get("text"), source_type,
        )
        start = play.get("start") if isinstance(play.get("start"), dict) else None
        end = play.get("end") if isinstance(play.get("end"), dict) else None
        offense_team_id = _team_id(start)
        if offense_team_id not in team_ids:
            offense_team_id = None
        defense_team_id = next((team_id for team_id in team_ids
                                if team_id != offense_team_id), None)
        field_spot = _spot(start, source_type or "", team_ids)
        down = _int_or_none(start.get("down")) if start else None
        distance = _int_or_none(start.get("distance")) if start else None
        period = play.get("period") or {}
        period_number = _int_or_none(period.get("number")) if isinstance(period, dict) else None
        sequence = _int_or_none(play.get("sequenceNumber"))
        after_score = _source_score(play)
        review_state = _review_state(play)
        scoring_play = play.get("scoringPlay") if isinstance(play.get("scoringPlay"), bool) else None
        raw_scoring_type = play.get("scoringType") or {}
        if not isinstance(raw_scoring_type, dict):
            raw_scoring_type = {}
        source_type_name = raw_scoring_type.get("name")
        event_id = f"{resolved_game_id}:ESPN:{play_id}"
        raw_event = {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "game_id": resolved_game_id,
            "source": {
                "publisher": "ESPN",
                "play_id": play_id,
                "event_id": event_id,
                "revision": revision,
                "revision_basis": "canonical_raw_play_sha256",
                "occurred_at_utc": play.get("wallclock"),
                "source_modified_at": play.get("modified"),
                "observed_at_utc": observed_at_utc,
            },
            "sequence": sequence,
            "source_order": source_order,
            "period": period_number,
            "clock": ((play.get("clock") or {}).get("displayValue")
                      if isinstance(play.get("clock"), dict) else None),
            "status": game_status,
            "offense_team_id": offense_team_id,
            "defense_team_id": defense_team_id,
            "before": {
                "down": down if down is not None and 1 <= down <= 4 else None,
                "yards_to_go": distance if distance is not None and 0 <= distance <= 99 else None,
                "yardline_100": field_spot,
                "score": None,
            },
            "after": {
                "down": (_int_or_none(end.get("down")) if end else None),
                "yards_to_go": (_int_or_none(end.get("distance")) if end else None),
                # Raw end spots are retained below; only the next independently
                # validated snap may promote one to an offense-relative spot.
                "yardline_100": None,
                "score": after_score,
            },
            "event_type": kind,
            "source_event_type": source_type,
            "field_goal_attempt_distance_yards": field_goal_distance,
            "field_goal_distance_provenance": field_goal_distance_provenance,
            "arcade_challenge_id": (published_field_goal_challenge_id(event_id, revision)
                                    if field_goal_distance is not None else None),
            "score_kind": source_type_name or ("touchdown" if kind == "touchdown" else None),
            "scoring_play": scoring_play,
            "is_turnover": play.get("isTurnover") if isinstance(play.get("isTurnover"), bool) else None,
            "review_state": review_state,
            "point_after_attempt": play.get("pointAfterAttempt"),
            "field_provenance": ({
                "confidence": "verified",
                "source_field": "start.yardsToEndzone",
                "source_team_id": _team_id(start),
                "orientation": "offense_relative_diagrammatic",
            } if field_spot is not None else {
                "confidence": "unavailable",
                "source_field": "start.yardsToEndzone",
                "reason": ("event_class_not_independently_verified" if start else "source_start_missing"),
            }),
            "confidence": {
                "identity": "verified" if offense_team_id is not None else "unavailable",
                "field": "verified" if field_spot is not None else "unavailable",
                "score": "verified" if after_score is not None else "unavailable",
            },
            "raw_start": start,
            "raw_end": end,
            "display_text": play.get("text") if isinstance(play.get("text"), str) else None,
            "raw_play": play,
        }
        raw_events.append(raw_event)

    # ESPN's score after a play is source-published. The preceding event's score
    # is the only accepted score-before value; no touchdown/PAT arithmetic is used.
    ordered = sorted(raw_events, key=lambda row: (
        row["sequence"] is None,
        row["sequence"] if row["sequence"] is not None else row["source_order"],
        row["source_order"],
    ))
    previous_score = None
    for row in ordered:
        row["before"]["score"] = previous_score
        previous_score = row["after"]["score"] or previous_score

    header_id = header.get("id")
    published_score = {}
    for side in ("away", "home"):
        score = _int_or_none((by_side.get(side) or {}).get("score"))
        published_score[side] = score

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "game": {
            "game_id": resolved_game_id,
            "publisher_event_id": str(header_id) if header_id is not None else resolved_game_id,
            "date": competition.get("date"),
            "status": game_status,
            "teams": teams,
            "score": published_score,
        },
        "source": {
            "publisher": "ESPN",
            "publisher_updated_at": ((summary.get("meta") or {}).get("lastUpdatedAt")
                                      if isinstance(summary.get("meta"), dict) else None),
            "observed_at_utc": observed_at_utc,
        },
        "events": ordered,
        "coverage": {
            "source_play_count": len(rows),
            "normalized_event_count": len(ordered),
            "missing_play_ids": missing_ids,
            "duplicate_play_versions": duplicate_ids,
            "events_with_verified_spot": sum(row["before"]["yardline_100"] is not None for row in ordered),
            "events_with_source_score": sum(row["after"]["score"] is not None for row in ordered),
        },
    }


def choose_director_game(
    candidates: list[dict[str, Any]],
    *,
    pinned_game_id: str | None = None,
    current_game_id: str | None = None,
    min_dwell_elapsed: bool = True,
    announced_event_ids: set[str] | None = None,
) -> str | None:
    """Choose a live game deterministically from verified publisher snapshots.

    Candidate fields are publisher-derived: `state`, `game_id`, `last_event`,
    and `last_play_order`. Unknown field spots never enter red-zone priority.
    """
    live = [game for game in candidates
            if game.get("state") == "in" and game.get("game_id")]
    by_id = {str(game["game_id"]): game for game in live}
    if pinned_game_id is not None and str(pinned_game_id) in by_id:
        return str(pinned_game_id)
    if not live:
        return None

    announced_event_ids = announced_event_ids or set()
    scoring = []
    for game in live:
        event = game.get("last_event") or {}
        source = event.get("source") or {}
        event_key = source.get("event_id")
        confirmed = (
            event.get("scoring_play") is True
            and event.get("event_type") == "touchdown"
            and event.get("review_state") in {"none", "confirmed"}
            and event.get("confidence", {}).get("score") == "verified"
            and bool(event_key)
            and event_key not in announced_event_ids
        )
        if confirmed:
            scoring.append((str(event_key), str(game["game_id"]), game))
    if scoring:
        # Stable event ID is the final tie break, independent of input order.
        return min(scoring, key=lambda item: item[0])[1]

    if current_game_id is not None and not min_dwell_elapsed and str(current_game_id) in by_id:
        return str(current_game_id)

    def priority(game: dict[str, Any]) -> tuple[Any, ...]:
        event = game.get("last_event") or {}
        before = event.get("before") or {}
        confidence = event.get("confidence") or {}
        # A touchdown's `before` location is the scoring play's starting spot,
        # not the game's current post-score location. Keep it out of red-zone
        # ranking after its one confirmed highlight has been announced.
        spot = (before.get("yardline_100")
                if confidence.get("field") == "verified" and event.get("scoring_play") is not True
                else None)
        down = before.get("down")
        distance = before.get("yards_to_go")
        if isinstance(spot, int) and 0 <= spot < 20:
            band = 0
            goal_to_go = 0 if event.get("goal_to_go") is True else 1
            spot_key = spot
        elif isinstance(spot, int) and 20 <= spot <= 30:
            band = 1
            goal_to_go = 1
            spot_key = spot
        else:
            band = 2
            goal_to_go = 1
            spot_key = 101
        return (
            band,
            goal_to_go,
            spot_key,
            down if isinstance(down, int) else 5,
            distance if isinstance(distance, int) else 100,
            -_int_or_zero(game.get("last_play_order")),
            str(game["game_id"]),
        )

    return str(min(live, key=priority)["game_id"])


def channel_state(
    games: list[dict[str, Any]],
    *,
    observed_at_utc: str | None,
    now_utc: datetime,
    stale_after_seconds: float,
) -> str:
    """Classify the channel without guessing a freshness threshold.

    `stale_after_seconds` must come from the measured source distribution. A
    missing or invalid observation timestamp fails closed to `stale` whenever
    a game is live.
    """
    if not games:
        return "off_air"
    live = [game for game in games if game.get("state") == "in"]
    if not live:
        if all(game.get("state") in {"post", "final"} for game in games):
            return "final"
        return "scheduled"
    try:
        observed = datetime.fromisoformat((observed_at_utc or "").replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return "stale"
        age = (now_utc.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return "stale"
    if age < 0 or age > stale_after_seconds:
        return "stale"
    if not any(game.get("has_verified_pbp") is True for game in live):
        return "waiting"
    return "live"


def monotonic_event_update(
    incoming_events: list[dict[str, Any]],
    current_event: dict[str, Any] | None,
) -> dict[str, Any]:
    """Advance by validated sequence while surfacing late revisions explicitly."""
    current_sequence = _int_or_none(current_event.get("sequence")) if current_event else None
    current_source = current_event.get("source") or {} if current_event else {}
    current_event_id = current_source.get("event_id")
    current_revision = current_source.get("revision")
    eligible = [event for event in incoming_events
                if _int_or_none(event.get("sequence")) is not None
                and (event.get("source") or {}).get("event_id")]
    eligible.sort(key=lambda event: (
        _int_or_none(event.get("sequence")),
        str((event.get("source") or {}).get("event_id")),
        str((event.get("source") or {}).get("revision")),
    ))
    newer = [event for event in eligible
             if current_sequence is None or _int_or_none(event.get("sequence")) > current_sequence]
    corrections = [event for event in eligible
                   if current_event_id
                   and (event.get("source") or {}).get("event_id") == current_event_id
                   and (event.get("source") or {}).get("revision") != current_revision]
    return {
        "current_event": newer[-1] if newer else current_event,
        "corrections": corrections,
        "ignored_older_events": sum(
            current_sequence is not None and _int_or_none(event.get("sequence")) < current_sequence
            and event not in corrections for event in eligible
        ),
    }


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0
