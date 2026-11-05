"""Persistent anonymous Arcade claims, attempts, scoreboards and share links.

The schema is owned by the explicit migration in ``migrate_schema.py``. This
module never creates or alters tables at application startup.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pixel_red_zone import (
    canonical_raw_hash,
    published_field_goal_attempt_distance,
    published_field_goal_challenge_id,
)


_DB = os.environ.get("LP_DB_PATH") or str(Path(__file__).resolve().parent / "data" / "picks.db")
_WINDOW_SECONDS = 60 * 60
_SESSION_ISSUES_PER_IP = 120
_ATTEMPTS_PER_CLAIM = 40
_SHARES_PER_CLAIM = 30
PHYSICS_VERSION = "fg-physics-v2"
SCORING_VERSION = "fg-score-v2"


def frozen_config_hash(
    challenge_config: dict[str, Any], physics_version: str, scoring_version: str,
) -> str:
    payload = json.dumps({
        "challenge_config": challenge_config,
        "physics_version": physics_version,
        "scoring_version": scoring_version,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def challenge_version_key(challenge_id: str, config_hash: str) -> str:
    return f"{challenge_id}:{config_hash}"


class StoreUnavailable(RuntimeError):
    pass


class InvalidClaim(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class AttemptConflict(RuntimeError):
    pass


def _connect() -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(_DB, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_fresh_observation(value: str | None, max_age_seconds: int = 180) -> bool:
    if not value:
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        return -60 <= age <= max_age_seconds
    except (TypeError, ValueError):
        return False


def _rate_limit(connection: sqlite3.Connection, bucket: str, now: int, limit: int) -> bool:
    connection.execute(
        "DELETE FROM arcade_rate_limits WHERE window_started_at<?", (now - 24 * _WINDOW_SECONDS,)
    )
    bucket_hash = hashlib.sha256(bucket.encode("utf-8")).hexdigest()
    row = connection.execute(
        "SELECT window_started_at,request_count FROM arcade_rate_limits WHERE bucket_hash=?",
        (bucket_hash,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO arcade_rate_limits(bucket_hash,window_started_at,request_count) VALUES(?,?,1)",
            (bucket_hash, now),
        )
        return True
    if now - row["window_started_at"] >= _WINDOW_SECONDS:
        connection.execute(
            "UPDATE arcade_rate_limits SET window_started_at=?,request_count=1 WHERE bucket_hash=?",
            (now, bucket_hash),
        )
        return True
    if row["request_count"] >= limit:
        return False
    connection.execute(
        "UPDATE arcade_rate_limits SET request_count=request_count+1 WHERE bucket_hash=?",
        (bucket_hash,),
    )
    return True


def _ip_fingerprint(connection: sqlite3.Connection, ip_address: str | None) -> str:
    row = connection.execute(
        "SELECT ip_hash_secret FROM arcade_service_state WHERE id=1"
    ).fetchone()
    if row is None:
        secret = secrets.token_hex(32)
        connection.execute(
            "INSERT INTO arcade_service_state(id,ip_hash_secret) VALUES(1,?)", (secret,)
        )
    else:
        secret = row["ip_hash_secret"]
    address = (ip_address or "unknown").encode("utf-8")
    return hmac.new(secret.encode("utf-8"), address, hashlib.sha256).hexdigest()


def issue_claim(existing_token: str | None, ip_address: str | None) -> tuple[str, bool]:
    connection = _connect()
    try:
        now = int(time.time())
        if existing_token is not None:
            if len(existing_token) > 128:
                raise InvalidClaim("Arcade claim is invalid")
            digest = _token_hash(existing_token)
            row = connection.execute(
                "SELECT 1 FROM arcade_anonymous_claims WHERE token_hash=?", (digest,)
            ).fetchone()
            if row is None:
                raise InvalidClaim("Arcade claim is invalid")
            connection.execute(
                "UPDATE arcade_anonymous_claims SET last_seen_at=? WHERE token_hash=?",
                (now, digest),
            )
            connection.commit()
            return existing_token, False

        connection.execute("BEGIN IMMEDIATE")
        ip_fingerprint = _ip_fingerprint(connection, ip_address)
        if not _rate_limit(connection, f"session:{ip_fingerprint}", now, _SESSION_ISSUES_PER_IP):
            connection.rollback()
            raise RateLimited("Too many anonymous Arcade sessions from this network. Try again later.")
        token = secrets.token_urlsafe(32)
        digest = _token_hash(token)
        connection.execute(
            "INSERT INTO arcade_anonymous_claims(token_hash,created_at,last_seen_at) VALUES(?,?,?)",
            (digest, now, now),
        )
        connection.commit()
        return token, True
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def authorize_claim(token: str | None) -> str:
    if not token or len(token) > 128:
        raise InvalidClaim("A valid Arcade claim token is required")
    digest = _token_hash(token)
    connection = _connect()
    try:
        cursor = connection.execute(
            "UPDATE arcade_anonymous_claims SET last_seen_at=? WHERE token_hash=?",
            (int(time.time()), digest),
        )
        connection.commit()
        if cursor.rowcount != 1:
            raise InvalidClaim("A valid Arcade claim token is required")
        return digest
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def record_attempt(
    claim_hash: str,
    *,
    attempt_id: str,
    challenge_id: str,
    config_hash: str,
    origin: str,
    input_payload: dict[str, float],
    result: dict[str, Any],
    drill_id: str | None = None,
    drill_run_id: str | None = None,
    drill_attempt_index: int | None = None,
    drill_attempt_count: int | None = None,
    drill_scenarios: list[tuple[str, str]] | None = None,
    medal_thresholds: dict[str, int] | None = None,
    referral_share_id: str | None = None,
) -> dict[str, Any]:
    referral_share_hash = _token_hash(referral_share_id) if referral_share_id else None
    input_json = json.dumps({
        "input": input_payload,
        "drill_id": drill_id,
        "drill_run_id": drill_run_id,
        "drill_attempt_index": drill_attempt_index,
        "referral_share_hash": referral_share_hash,
    }, sort_keys=True, separators=(",", ":"))
    connection = _connect()
    now = int(time.time())
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT challenge_id,config_hash,input_json,result_json FROM arcade_attempts "
            "WHERE claim_hash=? AND attempt_id=?",
            (claim_hash, attempt_id),
        ).fetchone()
        if existing is not None:
            if (existing["challenge_id"] != challenge_id or existing["config_hash"] != config_hash
                    or existing["input_json"] != input_json):
                connection.rollback()
                raise AttemptConflict("This attempt ID was already used for different kick input")
            connection.commit()
            return json.loads(existing["result_json"])

        if not _rate_limit(connection, f"attempt:{claim_hash}", now, _ATTEMPTS_PER_CLAIM):
            connection.rollback()
            raise RateLimited("Kick limit reached for this Arcade claim. Try again later.")

        result = dict(result)
        result["personal_best_score"] = None
        result["training_set"] = None
        result["qualified_referral_activation"] = False
        connection.execute(
            "INSERT INTO arcade_attempts("
            "claim_hash,attempt_id,challenge_id,config_hash,origin,input_json,score,made,result_json,"
            "drill_id,drill_run_id,drill_attempt_index,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (claim_hash, attempt_id, challenge_id, config_hash, origin, input_json,
             int(result["score"]), int(bool(result["made"])), "{}", drill_id,
             drill_run_id, drill_attempt_index, now),
        )
        if referral_share_hash:
            share = connection.execute(
                "SELECT claim_hash,challenge_id,config_hash FROM arcade_shares WHERE share_hash=?",
                (referral_share_hash,),
            ).fetchone()
            if (share is not None and share["claim_hash"] != claim_hash
                    and share["challenge_id"] == challenge_id
                    and share["config_hash"] == config_hash):
                activation = connection.execute(
                    "INSERT OR IGNORE INTO arcade_referral_activations("
                    "sharer_hash,recipient_hash,share_hash,challenge_id,attempt_id,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (share["claim_hash"], claim_hash, referral_share_hash,
                     challenge_id, attempt_id, now),
                )
                result["qualified_referral_activation"] = activation.rowcount == 1
        best = connection.execute(
            "SELECT MAX(score) AS score FROM arcade_attempts "
            "WHERE claim_hash=? AND challenge_id=? AND config_hash=?",
            (claim_hash, challenge_id, config_hash),
        ).fetchone()["score"]
        result["personal_best_score"] = int(best or 0)

        if (drill_id and drill_run_id is not None and drill_attempt_count and medal_thresholds
                and drill_scenarios and len(drill_scenarios) == drill_attempt_count):
            run_scores = _completed_training_run_scores(connection, claim_hash, drill_id, drill_scenarios)
            if drill_run_id in run_scores:
                total = run_scores[drill_run_id]
                previous = max(run_scores.values(), default=0)
                result["training_set"] = {
                    "drill_id": drill_id,
                    "score": total,
                    "personal_best_score": int(max(total, previous or 0)),
                    "medal": "gold" if total >= medal_thresholds["gold"]
                    else "silver" if total >= medal_thresholds["silver"]
                    else "bronze" if total >= medal_thresholds["bronze"] else None,
                }

        result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "UPDATE arcade_attempts SET result_json=? WHERE claim_hash=? AND attempt_id=?",
            (result_json, claim_hash, attempt_id),
        )
        connection.commit()
        return result
    except (AttemptConflict, RateLimited):
        if connection.in_transaction:
            connection.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise AttemptConflict("This drill attempt slot has already been recorded") from exc
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def _completed_training_run_scores(
    connection: sqlite3.Connection,
    claim_hash: str,
    drill_id: str,
    expected_scenarios: list[tuple[str, str]],
) -> dict[str, int]:
    rows = connection.execute(
        "SELECT drill_run_id,drill_attempt_index,challenge_id,config_hash,score "
        "FROM arcade_attempts WHERE claim_hash=? AND drill_id=? AND drill_run_id IS NOT NULL",
        (claim_hash, drill_id),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["drill_run_id"], []).append(row)

    complete: dict[str, int] = {}
    for run_id, attempts in grouped.items():
        ordered = sorted(attempts, key=lambda row: row["drill_attempt_index"])
        if len(ordered) != len(expected_scenarios):
            continue
        if any(
            row["drill_attempt_index"] != index
            or (row["challenge_id"], row["config_hash"]) != expected_scenarios[index]
            for index, row in enumerate(ordered)
        ):
            continue
        complete[run_id] = sum(row["score"] for row in ordered)
    return complete


def personal_bests(claim_hash: str, drills: list[dict]) -> dict[str, Any]:
    connection = _connect()
    try:
        challenge_bests = {
            challenge_version_key(row["challenge_id"], row["config_hash"]): row["score"]
            for row in connection.execute(
                "SELECT challenge_id,config_hash,MAX(score) AS score FROM arcade_attempts "
                "WHERE claim_hash=? GROUP BY challenge_id,config_hash",
                (claim_hash,),
            )
        }
        challenge_progress: dict[str, dict[str, int]] = {}
        for row in connection.execute(
            "SELECT challenge_id,config_hash,COUNT(*) AS attempts,AVG(score) AS average_score,"
            "SUM(CASE WHEN score=0 THEN 1 ELSE 0 END) AS misses,"
            "SUM(CASE WHEN score BETWEEN 600 AND 799 THEN 1 ELSE 0 END) AS scores_600_799,"
            "SUM(CASE WHEN score>=800 THEN 1 ELSE 0 END) AS scores_800_plus "
            "FROM arcade_attempts WHERE claim_hash=? GROUP BY challenge_id,config_hash",
            (claim_hash,),
        ):
            key = challenge_version_key(row["challenge_id"], row["config_hash"])
            challenge_progress[key] = {
                "attempts": row["attempts"],
                "average_score": int(round(row["average_score"] or 0)),
                "misses": row["misses"] or 0,
                "scores_600_799": row["scores_600_799"] or 0,
                "scores_800_plus": row["scores_800_plus"] or 0,
            }
        training_bests: dict[str, dict[str, Any]] = {}
        for drill in drills:
            expected_scenarios = drill.get("scenario_versions") or []
            complete_scores = _completed_training_run_scores(
                connection, claim_hash, drill["id"], expected_scenarios,
            )
            complete = list(complete_scores.values())
            best = max(complete) if complete else 0
            thresholds = drill["medal_thresholds"]
            medal = "gold" if best >= thresholds["gold"] else \
                "silver" if best >= thresholds["silver"] else \
                "bronze" if best >= thresholds["bronze"] else None
            training_bests_distribution = {
                "completed_sets": len(complete),
                "average_score": int(round(sum(complete) / len(complete))) if complete else 0,
                "below_bronze": sum(score < thresholds["bronze"] for score in complete),
                "bronze": sum(thresholds["bronze"] <= score < thresholds["silver"] for score in complete),
                "silver": sum(thresholds["silver"] <= score < thresholds["gold"] for score in complete),
                "gold": sum(score >= thresholds["gold"] for score in complete),
            }
            training_bests[drill["id"]] = {
                "score": best,
                "medal": medal,
                "completed_sets": len(complete),
                "score_distribution": training_bests_distribution,
            }
        return {"challenge_bests": challenge_bests, "challenge_progress": challenge_progress,
                "training_bests": training_bests}
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def challenge_leaderboard(challenge_id: str, config_hash: str, limit: int = 10) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        rows = connection.execute(
            "WITH ranked_attempts AS ("
            "SELECT claim_hash,score,created_at,ROW_NUMBER() OVER ("
            "PARTITION BY claim_hash ORDER BY score DESC,created_at ASC,attempt_id ASC) AS owner_rank "
            "FROM arcade_attempts WHERE challenge_id=? AND config_hash=?) "
            "SELECT claim_hash,score,created_at FROM ranked_attempts WHERE owner_rank=1 "
            "ORDER BY score DESC,created_at ASC,claim_hash ASC LIMIT ?",
            (challenge_id, config_hash, max(1, min(50, limit))),
        ).fetchall()
        return [{"rank": index + 1, "player": f"Anonymous {index + 1}", "score": row["score"]}
                for index, row in enumerate(rows)]
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def qualified_referral_activations(sharer_hash: str) -> int:
    """Count distinct anonymous recipients who completed a verified shared kick."""
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS completions FROM arcade_referral_activations WHERE sharer_hash=?",
            (sharer_hash,),
        ).fetchone()
        return int(row["completions"] or 0)
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def create_share(claim_hash: str, attempt_id: str, challenge_id: str, config_hash: str) -> tuple[str, int]:
    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if not _rate_limit(connection, f"share:{claim_hash}", int(time.time()), _SHARES_PER_CLAIM):
            connection.rollback()
            raise RateLimited("Share limit reached for this Arcade claim. Try again later.")
        attempt = connection.execute(
            "SELECT score,challenge_id,config_hash FROM arcade_attempts "
            "WHERE claim_hash=? AND attempt_id=?",
            (claim_hash, attempt_id),
        ).fetchone()
        if (attempt is None or attempt["challenge_id"] != challenge_id
                or attempt["config_hash"] != config_hash):
            connection.rollback()
            raise InvalidClaim("A verified kick for this challenge is required to share it")
        share_id = secrets.token_urlsafe(24)
        connection.execute(
            "INSERT INTO arcade_shares(share_hash,claim_hash,attempt_id,challenge_id,config_hash,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (_token_hash(share_id), claim_hash, attempt_id, challenge_id, config_hash, int(time.time())),
        )
        connection.commit()
        return share_id, int(attempt["score"])
    except (InvalidClaim, RateLimited):
        if connection.in_transaction:
            connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def resolve_share(share_id: str) -> dict[str, Any] | None:
    if not share_id or len(share_id) > 128:
        return None
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT s.challenge_id,s.config_hash,a.score FROM arcade_shares AS s "
            "JOIN arcade_attempts AS a ON a.claim_hash=s.claim_hash AND a.attempt_id=s.attempt_id "
            "WHERE s.share_hash=?",
            (_token_hash(share_id),),
        ).fetchone()
        if row is None:
            return None
        return {"challenge_id": row["challenge_id"], "config_hash": row["config_hash"],
                "target_score": row["score"]}
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def cache_live_events(normalized: dict[str, Any]) -> None:
    """Persist immutable, source-verified live field-goal challenge snapshots."""
    game = normalized.get("game") or {}
    game_id = str(game.get("game_id") or "")
    status = game.get("status")
    source = normalized.get("source") or {}
    teams = game.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    away_team = away.get("name")
    home_team = home.get("name")
    if (normalized.get("schema_version") != "lp-observed-nfl-event-v1"
            or normalized.get("mode") != "live"
            or source.get("publisher") != "ESPN"
            or not game_id.isdigit()
            or not isinstance(away_team, str) or not away_team.strip()
            or not isinstance(home_team, str) or not home_team.strip()
            or status not in {"in", "post"}):
        return

    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE arcade_observed_events SET game_status=?,publisher_updated_at=? "
            "WHERE game_id=?",
            (status, source.get("publisher_updated_at"), game_id),
        )
        if status in {"in", "post"}:
            for event in normalized.get("events") or []:
                source_event = event.get("source") or {}
                event_id = str(source_event.get("event_id") or "")
                play_id = str(source_event.get("play_id") or "")
                revision = str(source_event.get("revision") or "")
                if not event_id or not play_id or not revision:
                    continue
                if event_id != f"{game_id}:ESPN:{play_id}" or source_event.get("publisher") != "ESPN":
                    continue

                event_type = event.get("source_event_type")
                distance, provenance = published_field_goal_attempt_distance(
                    event.get("display_text"), event_type,
                )
                verified = (
                    event.get("mode") == "live"
                    and event_type in {"Field Goal Good", "Field Goal Missed", "Blocked Field Goal"}
                    and len(revision) == 64
                    and all(character in "0123456789abcdef" for character in revision)
                    and source_event.get("revision_basis") == "canonical_raw_play_sha256"
                    and isinstance(event.get("raw_play"), dict)
                    and canonical_raw_hash(event["raw_play"]) == revision
                    and source_event.get("observed_at_utc")
                    and event.get("arcade_challenge_id") == published_field_goal_challenge_id(event_id, revision)
                    and distance is not None
                    and provenance.get("confidence") == "verified"
                    and provenance.get("publisher") == "ESPN"
                    and provenance.get("basis") == "explicit_field_goal_yard_phrase"
                )
                if not verified:
                    # A publisher correction may turn a previously eligible kick into
                    # another event type. Retire its prior challenge immediately.
                    connection.execute(
                        "UPDATE arcade_observed_events SET superseded_by=? "
                        "WHERE event_id=? AND superseded_by IS NULL",
                        ("publisher-correction-unavailable", event_id),
                    )
                    continue

                challenge_id = published_field_goal_challenge_id(event_id, revision)
                observed_at = str(source_event["observed_at_utc"])
                source_ref = {
                    "publisher": "ESPN",
                    "game_id": game_id,
                    "play_id": play_id,
                    "event_id": event_id,
                    "source_revision": revision,
                }
                context = {
                    "away_team": away_team,
                    "away_team_id": away.get("team_id"),
                    "home_team": home_team,
                    "home_team_id": home.get("team_id"),
                    "period": event.get("period"),
                    "clock": event.get("clock"),
                    "game_date": game.get("date"),
                    "attempt_distance_yards": distance,
                }
                connection.execute(
                    "UPDATE arcade_observed_events SET superseded_by=? "
                    "WHERE event_id=? AND challenge_id<>? AND superseded_by IS NULL",
                    (challenge_id, event_id, challenge_id),
                )
                connection.execute(
                    "INSERT INTO arcade_observed_events(" 
                    "challenge_id,game_id,play_id,event_id,source_revision,game_date,away_team,home_team," 
                    "period,clock,attempt_distance_yards,event_type,game_status,publisher_updated_at," 
                    "first_observed_at_utc,last_observed_at_utc,source_ref_json,observed_context_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(challenge_id) DO UPDATE SET "
                    "game_status=excluded.game_status,publisher_updated_at=excluded.publisher_updated_at," 
                    "last_observed_at_utc=excluded.last_observed_at_utc",
                    (challenge_id, game_id, play_id, event_id, revision, game.get("date"),
                     away_team, home_team, event.get("period"), event.get("clock"), distance,
                     event_type, status, source.get("publisher_updated_at"), observed_at, observed_at,
                     json.dumps(source_ref, sort_keys=True, separators=(",", ":")),
                     json.dumps(context, sort_keys=True, separators=(",", ":"))),
                )
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def live_challenge(challenge_id: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT * FROM arcade_observed_events WHERE challenge_id=?", (challenge_id,),
        ).fetchone()
        if row is None:
            return None
        context = json.loads(row["observed_context_json"])
        config = {
            "attempt_distance_yards": row["attempt_distance_yards"],
            "target_aim": 0.0,
            "aim_tolerance": 0.24,
            "goal_half_width": 0.36,
            "timing_window": 0.26,
            "timing_lateral_coupling": 0.2,
            "base_crossbar_clearance_yards": 3.0,
            "timing_clearance_penalty_yards": 4.0,
            "range_clearance_gain": 0.06,
            "weather_mode": "neutral_arcade",
        }
        config_hash = frozen_config_hash(config, PHYSICS_VERSION, SCORING_VERSION)
        return {
            "schema_version": "lp-arcade-challenge-v2",
            "challenge_id": challenge_id,
            "kind": "field_goal",
            "origin": "observed_nfl_play",
            "source_ref": json.loads(row["source_ref_json"]),
            "observed_context": context,
            "source_verified_at_utc": row["first_observed_at_utc"],
            "last_observed_at_utc": row["last_observed_at_utc"],
            "publisher_updated_at": row["publisher_updated_at"],
            "challenge_config": config,
            "physics_version": PHYSICS_VERSION,
            "scoring_version": SCORING_VERSION,
            "config_hash": config_hash,
            "state": "source_corrected" if row["superseded_by"] else (
                "observed_live" if row["game_status"] == "in"
                and _is_fresh_observation(row["last_observed_at_utc"])
                else "archived_verified"
            ),
            "superseded_by_challenge_id": (
                row["superseded_by"]
                if row["superseded_by"] and row["superseded_by"].startswith("espn-fg-")
                else None
            ),
        }
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def live_real_outcome(challenge_id: str) -> dict[str, str] | None:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT event_type,superseded_by FROM arcade_observed_events WHERE challenge_id=?", (challenge_id,),
        ).fetchone()
        if row is None or row["superseded_by"] is not None:
            return None
        return {
            "Field Goal Good": {"status": "made", "label": "Real attempt: made"},
            "Field Goal Missed": {"status": "missed", "label": "Real attempt: missed"},
            "Blocked Field Goal": {"status": "blocked", "label": "Real attempt: blocked"},
        }.get(row["event_type"])
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def recent_live_moments(max_age_seconds: int = 180) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT challenge_id,game_id,play_id,source_ref_json,observed_context_json," 
            "first_observed_at_utc,last_observed_at_utc,publisher_updated_at "
            "FROM arcade_observed_events WHERE game_status='in' AND superseded_by IS NULL "
            "AND julianday(last_observed_at_utc)>=julianday('now')-?/86400.0 "
            "AND julianday(last_observed_at_utc)<=julianday('now')+60.0/86400.0 "
            "ORDER BY last_observed_at_utc DESC LIMIT 20",
            (max(1, min(600, max_age_seconds)),),
        ).fetchall()
        moments = []
        for row in rows:
            moments.append({
                "challenge_id": row["challenge_id"],
                "origin": "observed_nfl_play",
                "state": "live_observed",
                "source_ref": json.loads(row["source_ref_json"]),
                "source_verified_at_utc": row["first_observed_at_utc"],
                "last_observed_at_utc": row["last_observed_at_utc"],
                "publisher_updated_at": row["publisher_updated_at"],
                "observed_context": json.loads(row["observed_context_json"]),
            })
        return moments
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()


def recent_archived_moments(limit: int = 20, max_age_seconds: int = 180) -> list[dict[str, Any]]:
    """List recently finalized or expired live captures as historical challenges."""
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT challenge_id,game_id,play_id,source_ref_json,observed_context_json,"
            "first_observed_at_utc,last_observed_at_utc,publisher_updated_at "
            "FROM arcade_observed_events WHERE superseded_by IS NULL AND (game_status='post' "
            "OR (game_status='in' AND julianday(last_observed_at_utc)<julianday('now')-?/86400.0)) "
            "ORDER BY last_observed_at_utc DESC LIMIT ?",
            (max(1, min(600, max_age_seconds)), max(1, min(50, limit))),
        ).fetchall()
        return [{
            "challenge_id": row["challenge_id"],
            "origin": "observed_nfl_play",
            "state": "archived_verified",
            "source_ref": json.loads(row["source_ref_json"]),
            "source_verified_at_utc": row["first_observed_at_utc"],
            "last_observed_at_utc": row["last_observed_at_utc"],
            "publisher_updated_at": row["publisher_updated_at"],
            "observed_context": json.loads(row["observed_context_json"]),
        } for row in rows]
    except sqlite3.Error as exc:
        raise StoreUnavailable("Arcade storage is unavailable") from exc
    finally:
        connection.close()
