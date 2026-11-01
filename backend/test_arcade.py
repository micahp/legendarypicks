"""Contract tests for the NFL Arcade challenges, scores and training drills."""

from __future__ import annotations

import sys
from pathlib import Path
from copy import deepcopy
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import arcade_store  # noqa: E402
import migrate_schema  # noqa: E402
from pixel_red_zone import canonical_raw_hash, published_field_goal_challenge_id  # noqa: E402
from routers import arcade  # noqa: E402

app = FastAPI()
app.include_router(arcade.router)
client = TestClient(app)
CLAIM_HEADERS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def isolated_arcade_database(tmp_path, monkeypatch):
    database_path = tmp_path / "arcade.db"
    migrations = [item for item in migrate_schema.MIGRATIONS if item.migration_id in {
        "20261101_001_arcade_anonymous_scores",
        "20261102_001_arcade_referral_activations",
    }]
    with sqlite3.connect(database_path) as connection:
        for migration in migrations:
            connection.execute(migration.create_sql)
            for item in migration.objects:
                if item.name != migration.table:
                    connection.execute(item.sql)
    monkeypatch.setattr(arcade_store, "_DB", str(database_path))
    CLAIM_HEADERS.clear()
    claim = client.post("/api/arcade/session")
    assert claim.status_code == 201
    CLAIM_HEADERS["X-Arcade-Claim"] = claim.json()["claim_token"]
    yield
    CLAIM_HEADERS.clear()


def live_snapshot(*, game_status="in", distance=45, event_type="Field Goal Good",
                  away_team="Seattle Seahawks", observed_at=None):
    play_id = "live-play-1"
    raw_play = {
        "id": play_id,
        "type": {"text": event_type},
        "text": f"{distance} yard field goal",
    }
    revision = canonical_raw_hash(raw_play)
    event_id = f"401999001:ESPN:{play_id}"
    observed_at = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    event = {
        "schema_version": "lp-observed-nfl-event-v1",
        "mode": "live",
        "game_id": "401999001",
        "source": {
            "publisher": "ESPN", "play_id": play_id, "event_id": event_id,
            "revision": revision, "revision_basis": "canonical_raw_play_sha256",
            "observed_at_utc": observed_at,
        },
        "period": 2,
        "clock": "08:10",
        "source_event_type": event_type,
        "field_goal_attempt_distance_yards": distance,
        "field_goal_distance_provenance": {
            "confidence": "verified", "publisher": "ESPN",
            "basis": "explicit_field_goal_yard_phrase",
        },
        "arcade_challenge_id": published_field_goal_challenge_id(event_id, revision),
        "display_text": raw_play["text"],
        "raw_play": raw_play,
    }
    return {
        "schema_version": "lp-observed-nfl-event-v1",
        "mode": "live",
        "game": {
            "game_id": "401999001", "date": "2026-11-01T18:00Z", "status": game_status,
            "teams": {
                "away": {"name": away_team}, "home": {"name": "Chicago Bears"},
            },
        },
        "source": {"publisher": "ESPN", "publisher_updated_at": observed_at,
                   "observed_at_utc": observed_at},
        "events": [event] if game_status == "in" else [],
    }


def test_challenge_hash_includes_its_physics_and_scoring_versions():
    config = {"attempt_distance_yards": 45, "weather_mode": "neutral_arcade"}
    current = arcade_store.frozen_config_hash(config, "fg-physics-v2", "fg-score-v2")
    assert arcade_store.frozen_config_hash(config, "fg-physics-v1", "fg-score-v2") != current
    assert arcade_store.frozen_config_hash(config, "fg-physics-v2", "fg-score-v1") != current


def test_live_kicks_are_frozen_private_until_kicked_and_deduplicated():
    snapshot = live_snapshot()
    arcade_store.cache_live_events(snapshot)
    arcade_store.cache_live_events(snapshot)
    moments_response = client.get("/api/arcade/moments")
    assert moments_response.status_code == 200
    moments = moments_response.json()["live_moments"]
    assert len(moments) == 1
    moment = moments[0]
    assert moment["state"] == "live_observed"
    assert moment["observed_context"]["attempt_distance_yards"] == 45
    assert "event_type" not in moment and "real_game_outcome" not in moment

    challenge_id = moment["challenge_id"]
    challenge_response = client.get(f"/api/arcade/challenges/{challenge_id}")
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    assert challenge["origin"] == "observed_nfl_play"
    assert challenge["challenge_config"]["attempt_distance_yards"] == 45
    assert challenge["state"] == "observed_live"
    assert challenge["last_observed_at_utc"]
    assert "real_game_outcome" not in challenge

    result = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": "2e8d40f0-cb13-43dd-9a85-963c923b6172",
        "challenge_id": challenge_id,
        "input": {"aim": 0, "power": 0.6, "release_timing": 0.5},
    })
    assert result.status_code == 200
    assert result.json()["real_game_outcome"]["status"] == "made"


def test_live_publisher_correction_supersedes_listing_but_keeps_old_challenge():
    first = live_snapshot(distance=45, event_type="Field Goal Good")
    arcade_store.cache_live_events(first)
    old_id = first["events"][0]["arcade_challenge_id"]

    corrected = live_snapshot(distance=46, event_type="Field Goal Missed")
    arcade_store.cache_live_events(corrected)
    listed = client.get("/api/arcade/moments").json()["live_moments"]
    assert [moment["challenge_id"] for moment in listed] == [corrected["events"][0]["arcade_challenge_id"]]
    old_challenge = client.get(f"/api/arcade/challenges/{old_id}").json()
    assert old_challenge["challenge_config"]["attempt_distance_yards"] == 45
    assert old_challenge["state"] == "source_corrected"
    assert old_challenge["superseded_by_challenge_id"] == corrected["events"][0]["arcade_challenge_id"]

    old_attempt = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": "a0e70ac9-3903-42e4-a68a-986d03b23bcb",
        "challenge_id": old_id,
        "input": {"aim": 0, "power": 0.6, "release_timing": 0.5},
    })
    assert old_attempt.status_code == 200
    assert old_attempt.json().get("real_game_outcome") is None

    arcade_store.cache_live_events(live_snapshot(game_status="post"))
    assert client.get("/api/arcade/moments").json()["live_moments"] == []


def test_stale_live_observation_is_archived_not_advertised_as_current():
    stale_at = (datetime.now(timezone.utc) - timedelta(seconds=240)).isoformat().replace("+00:00", "Z")
    snapshot = live_snapshot(observed_at=stale_at)
    arcade_store.cache_live_events(snapshot)
    challenge_id = snapshot["events"][0]["arcade_challenge_id"]

    moments = client.get("/api/arcade/moments").json()
    assert moments["live_moments"] == []
    stale_archives = [moment for moment in moments["moments"] if moment["challenge_id"] == challenge_id]
    assert len(stale_archives) == 1
    assert stale_archives[0]["state"] == "archived_verified"
    challenge = client.get(f"/api/arcade/challenges/{challenge_id}").json()
    assert challenge["state"] == "archived_verified"


def test_final_snapshot_keeps_a_newly_observed_kick_in_the_archive_list():
    snapshot = live_snapshot()
    snapshot["game"]["status"] = "post"
    arcade_store.cache_live_events(snapshot)
    challenge_id = snapshot["events"][0]["arcade_challenge_id"]

    moments = client.get("/api/arcade/moments").json()
    assert moments["live_moments"] == []
    archived = [moment for moment in moments["moments"] if moment["challenge_id"] == challenge_id]
    assert len(archived) == 1
    assert archived[0]["state"] == "archived_verified"
    assert archived[0]["observed_context"]["attempt_distance_yards"] == 45
    assert "event_type" not in archived[0]

    challenge = client.get(f"/api/arcade/challenges/{challenge_id}").json()
    assert challenge["state"] == "archived_verified"


def test_training_catalog_is_versioned_and_contains_only_the_v1_drills():
    response = client.get("/api/arcade/training")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "lp-arcade-training-v1"
    assert [drill["id"] for drill in payload["drills"]] == ["aim-lab-v1", "precision-set-v1"]
    assert all(len(drill["attempts"]) == 3 for drill in payload["drills"])
    assert all(drill["medal_thresholds"]["gold"] > drill["medal_thresholds"]["silver"]
               > drill["medal_thresholds"]["bronze"] for drill in payload["drills"])


def test_fictional_challenge_is_frozen_and_has_no_nfl_source():
    response = client.get("/api/arcade/challenges/practice-fg-35-v1")
    assert response.status_code == 200
    challenge = response.json()
    assert challenge["schema_version"] == "lp-arcade-challenge-v2"
    assert challenge["origin"] == "fictional_practice"
    assert challenge["challenge_config"]["attempt_distance_yards"] == 35
    assert challenge["source_ref"] is None
    assert challenge["config_hash"]
    assert challenge["physics_version"] == "fg-physics-v2"
    assert challenge["scoring_version"] == "fg-score-v2"


def test_archived_moments_use_verified_espn_distances_and_hide_the_real_outcome():
    response = client.get("/api/arcade/moments")
    assert response.status_code == 200
    moments = response.json()["moments"]
    target = next(moment for moment in moments
                  if moment["source_ref"]["game_id"] == "401772829"
                  and moment["source_ref"]["play_id"] == "4017728291916")
    assert target["origin"] == "observed_nfl_play"
    assert target["state"] == "archived_verified"
    assert target["observed_context"]["attempt_distance_yards"] == 45
    assert target["observed_context"]["away_team"] == "Cincinnati Bengals"
    assert target["observed_context"]["away_team_id"] == "4"
    assert target["observed_context"]["home_team"] == "Cleveland Browns"
    assert target["observed_context"]["home_team_id"] == "5"
    assert target["source_ref"]["event_id"] == "401772829:ESPN:4017728291916"
    assert target["source_ref"]["source_revision"]
    assert target["source_verified_at_utc"]
    assert "real_game_outcome" not in target


def test_archived_challenge_withholds_result_until_after_the_arcade_kick():
    moments = client.get("/api/arcade/moments").json()["moments"]
    source_moment = next(moment for moment in moments
                         if moment["source_ref"]["game_id"] == "401772829"
                         and moment["source_ref"]["play_id"] == "4017728291916")
    challenge_id = source_moment["challenge_id"]

    frozen = client.get(f"/api/arcade/challenges/{challenge_id}")
    assert frozen.status_code == 200
    challenge = frozen.json()
    assert challenge["schema_version"] == "lp-arcade-challenge-v2"
    assert challenge["origin"] == "observed_nfl_play"
    assert challenge["challenge_config"]["attempt_distance_yards"] == 45
    assert challenge["source_ref"] == source_moment["source_ref"]
    assert "real_game_outcome" not in challenge
    assert "display_text" not in challenge

    result = client.post("/api/arcade/attempts", json={
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": challenge_id,
        "input": {"aim": 0, "power": 31 / 55, "release_timing": 0.5},
    }, headers=CLAIM_HEADERS)
    assert result.status_code == 200
    assert result.json()["origin"] == "observed_nfl_play"
    assert result.json()["made"] is True
    assert result.json()["real_game_outcome"] == {"status": "made", "label": "Real attempt: made"}
    share = client.post("/api/arcade/shares", json={
        "attempt_id": result.json()["attempt_id"], "challenge_id": challenge_id,
    }, headers=CLAIM_HEADERS)
    assert share.status_code == 200
    shared_target = client.get(f"/api/arcade/shares/{share.json()['share_id']}")
    assert shared_target.json()["target_score"] == result.json()["score"]
    assert "real_game_outcome" not in shared_target.json()


def test_same_challenge_and_normalized_input_have_a_deterministic_score():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    }
    first = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS)
    second = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["made"] is True
    assert first.json()["score"] == 1000
    assert first.json()["feedback"] == "GOOD"
    assert 0 <= first.json()["score"] <= 1000


def test_long_centered_35_yard_kick_clears_the_goal_and_is_good():
    challenge = arcade._CHALLENGES["practice-fg-35-v1"]
    result = arcade.score_attempt(challenge, arcade.ArcadeInput(
        aim=0, power=0.77, release_timing=0.5,
    ))

    assert result["estimated_arcade_range_yards"] == 56.4
    assert result["made"] is True
    assert result["feedback"] == "GOOD"
    assert result["trajectory"] == {
        "range_yards": 56.35,
        "range_fraction": 1.61,
        "lateral_position": 0.0,
        "height_above_crossbar_yards": 4.281,
        "reaches_goal_line": True,
        "between_uprights": True,
        "clears_crossbar": True,
    }


@pytest.mark.parametrize(("aim", "power", "timing", "feedback"), [
    (-0.8, 0.77, 0.5, "LEFT"),
    (0.8, 0.77, 0.5, "RIGHT"),
    (0, 0.2, 0.5, "SHORT"),
])
def test_real_miss_trajectories_remain_misses(aim, power, timing, feedback):
    challenge = arcade._CHALLENGES["practice-fg-35-v1"]
    result = arcade.score_attempt(challenge, arcade.ArcadeInput(
        aim=aim, power=power, release_timing=timing,
    ))

    assert result["made"] is False
    assert result["score"] == 0
    assert result["feedback"] == feedback


def test_release_timing_changes_the_calculated_flight_path():
    challenge = arcade._CHALLENGES["practice-fg-35-v1"]
    on_time = arcade.score_attempt(challenge, arcade.ArcadeInput(
        aim=0, power=0.77, release_timing=0.5,
    ))["trajectory"]
    late = arcade.score_attempt(challenge, arcade.ArcadeInput(
        aim=0, power=0.77, release_timing=0.9,
    ))["trajectory"]

    assert late["lateral_position"] != on_time["lateral_position"]
    assert late["height_above_crossbar_yards"] < on_time["height_above_crossbar_yards"]


def test_client_cannot_submit_or_change_an_outcome():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 0.8, "release_timing": 0.5},
        "made": True,
        "score": 1000,
    }
    assert client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS).status_code == 422


def test_invalid_inputs_and_unknown_challenges_fail_closed():
    base = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 0.8, "release_timing": 0.5},
    }
    invalid = {**base, "input": {**base["input"], "aim": 1.01}}
    assert client.post("/api/arcade/attempts", json=invalid, headers=CLAIM_HEADERS).status_code == 422
    assert client.get("/api/arcade/challenges/not-a-challenge").status_code == 404
    assert client.post("/api/arcade/attempts", json={**base, "challenge_id": "unknown"},
                       headers=CLAIM_HEADERS).status_code == 404


def test_skill_failures_return_zero_competitive_score_and_specific_feedback():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": -0.8, "power": 0.1, "release_timing": 0.5},
    }
    result = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS).json()
    assert result["made"] is False
    assert result["score"] == 0
    assert result["feedback"] == "LEFT"
    assert "right" in result["coaching"].lower()


def test_attempt_requires_unpredictable_claim_token_not_client_device_id():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    }
    assert client.post("/api/arcade/attempts", json=payload,
                       headers={"X-Device-Id": "editable-device-id"}).status_code == 401


def test_anonymous_claim_token_is_random_and_only_its_hash_is_stored():
    token = CLAIM_HEADERS["X-Arcade-Claim"]
    assert len(token) >= 32
    with sqlite3.connect(arcade_store._DB) as connection:
        rows = connection.execute("SELECT token_hash FROM arcade_anonymous_claims").fetchall()
    assert (arcade_store._token_hash(token),) in rows
    assert token not in {row[0] for row in rows}


def test_anonymous_session_creation_has_a_network_rate_limit():
    for _ in range(119):
        assert client.post("/api/arcade/session").status_code == 201
    limited = client.post("/api/arcade/session")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "3600"


def test_attempt_id_is_idempotent_and_conflicting_reuse_is_rejected():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    }
    first = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS)
    retry = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS)
    changed = {**payload, "input": {**payload["input"], "aim": 0.1}}
    conflict = client.post("/api/arcade/attempts", json=changed, headers=CLAIM_HEADERS)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert conflict.status_code == 409


def test_anonymous_score_is_persisted_on_the_private_personal_board_and_public_leaderboard():
    payload = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    }
    scored = client.post("/api/arcade/attempts", json=payload, headers=CLAIM_HEADERS)
    assert scored.status_code == 200
    assert scored.json()["personal_best_score"] == 1000

    personal = client.get("/api/arcade/personal-bests", headers=CLAIM_HEADERS)
    assert personal.status_code == 200
    version_key = arcade_store.challenge_version_key(
        "practice-fg-35-v1", arcade._CHALLENGES["practice-fg-35-v1"]["config_hash"],
    )
    assert personal.json()["challenge_bests"][version_key] == 1000
    assert personal.json()["challenge_progress"][version_key] == {
        "attempts": 1, "average_score": 1000, "misses": 0,
        "scores_600_799": 0, "scores_800_plus": 1,
    }
    assert personal.json()["training_bests"]["aim-lab-v1"]["completed_sets"] == 0

    board = client.get("/api/arcade/leaderboard?challenge_id=practice-fg-35-v1")
    assert board.status_code == 200
    assert board.json()["entries"] == [{"rank": 1, "player": "Anonymous 1", "score": 1000}]
    assert "claim" not in board.text.lower()


def test_personal_bests_and_leaderboards_are_scoped_to_the_frozen_config_version(monkeypatch):
    challenge_id = "practice-fg-35-v1"
    original = arcade._CHALLENGES[challenge_id]
    old_hash = original["config_hash"]
    first = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": "72020318-f88b-4b06-83a9-2c159927f379",
        "challenge_id": challenge_id,
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    })
    assert first.status_code == 200
    assert first.json()["score"] == 1000

    revised = deepcopy(original)
    revised["challenge_config"]["target_aim"] = 0.6
    revised["config_hash"] = arcade._config_hash(revised["challenge_config"])
    monkeypatch.setitem(arcade._CHALLENGES, challenge_id, revised)
    second = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": "91cdb9ca-d5b4-4acf-a454-43941c843c28",
        "challenge_id": challenge_id,
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    })
    assert second.status_code == 200
    assert second.json()["score"] == 700
    assert second.json()["made"] is True
    assert second.json()["personal_best_score"] == 700
    replay_old_version = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": "72020318-f88b-4b06-83a9-2c159927f379",
        "challenge_id": challenge_id,
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    })
    assert replay_old_version.status_code == 409

    current_hash = revised["config_hash"]
    current_key = arcade_store.challenge_version_key(challenge_id, current_hash)
    old_key = arcade_store.challenge_version_key(challenge_id, old_hash)
    personal = client.get("/api/arcade/personal-bests", headers=CLAIM_HEADERS).json()
    assert personal["challenge_bests"][old_key] == 1000
    assert personal["challenge_bests"][current_key] == 700
    assert arcade_store.challenge_leaderboard(challenge_id, old_hash)[0]["score"] == 1000
    assert arcade_store.challenge_leaderboard(challenge_id, current_hash)[0]["score"] == 700
    assert client.get(
        f"/api/arcade/leaderboard?challenge_id={challenge_id}&config_hash={old_hash}"
    ).status_code == 409
    assert client.get(
        f"/api/arcade/leaderboard?challenge_id={challenge_id}&config_hash={current_hash}"
    ).json()["entries"][0]["score"] == 700


def test_shared_challenge_binds_to_the_server_scored_kick():
    attempt = {
        "attempt_id": "fd7c4ff5-7e7e-4b2b-9ac0-7b17b41c06f2",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    }
    assert client.post("/api/arcade/attempts", json=attempt, headers=CLAIM_HEADERS).status_code == 200
    share = client.post("/api/arcade/shares", json={
        "attempt_id": attempt["attempt_id"], "challenge_id": attempt["challenge_id"],
    }, headers=CLAIM_HEADERS)
    assert share.status_code == 200
    resolved = client.get(f"/api/arcade/shares/{share.json()['share_id']}")
    assert resolved.status_code == 200
    assert resolved.json() == {
        "challenge_id": "practice-fg-35-v1",
        "config_hash": arcade._CHALLENGES["practice-fg-35-v1"]["config_hash"],
        "target_score": 1000,
    }


def test_referral_activation_counts_only_distinct_verified_recipient_completions():
    sharer_hash = arcade_store.authorize_claim(CLAIM_HEADERS["X-Arcade-Claim"])
    attempt_id = "5b4c85d8-d7ba-4e63-9e43-1aa79bd95b13"
    first_attempt = client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json={
        "attempt_id": attempt_id,
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
    })
    assert first_attempt.status_code == 200
    share_response = client.post("/api/arcade/shares", headers=CLAIM_HEADERS, json={
        "attempt_id": attempt_id,
        "challenge_id": "practice-fg-35-v1",
    })
    assert share_response.status_code == 200
    share_id = share_response.json()["share_id"]
    assert arcade_store.qualified_referral_activations(sharer_hash) == 0

    # Opening the score-linked URL is not a qualified activation.
    assert client.get(f"/api/arcade/shares/{share_id}").status_code == 200
    assert arcade_store.qualified_referral_activations(sharer_hash) == 0

    recipient_token = client.post("/api/arcade/session").json()["claim_token"]
    recipient_headers = {"X-Arcade-Claim": recipient_token}
    recipient_hash = arcade_store.authorize_claim(recipient_token)
    recipient_attempt = {
        "attempt_id": "b9def93f-7707-4fe2-a774-3cfbdff4ad8c",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
        "share_id": share_id,
    }
    completed = client.post("/api/arcade/attempts", headers=recipient_headers, json=recipient_attempt)
    assert completed.status_code == 200
    assert completed.json()["qualified_referral_activation"] is True
    assert arcade_store.qualified_referral_activations(sharer_hash) == 1

    # Further plays from that recipient and the sharer opening their own link do not add referrals.
    recipient_attempt["attempt_id"] = "f80e64fd-6b20-4eae-8c1d-8aa788cd552e"
    repeat = client.post("/api/arcade/attempts", headers=recipient_headers, json=recipient_attempt)
    assert repeat.status_code == 200
    assert repeat.json()["qualified_referral_activation"] is False
    own_attempt = {
        "attempt_id": "51a2ba16-1a22-474c-84f4-bf8ec1095fea",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
        "share_id": share_id,
    }
    assert client.post("/api/arcade/attempts", headers=CLAIM_HEADERS, json=own_attempt).status_code == 200
    assert arcade_store.qualified_referral_activations(sharer_hash) == 1
    assert arcade_store.qualified_referral_activations(recipient_hash) == 0

    second_recipient = client.post("/api/arcade/session").json()["claim_token"]
    second_completion = client.post("/api/arcade/attempts", headers={"X-Arcade-Claim": second_recipient}, json={
        "attempt_id": "af0799ce-ecb5-458a-8a64-0e3610ca8783",
        "challenge_id": "practice-fg-35-v1",
        "input": {"aim": 0, "power": 21 / 55, "release_timing": 0.5},
        "share_id": share_id,
    })
    assert second_completion.status_code == 200
    assert second_completion.json()["qualified_referral_activation"] is True
    assert arcade_store.qualified_referral_activations(sharer_hash) == 2


def test_training_set_medal_and_best_are_calculated_from_all_server_scored_reps(monkeypatch):
    run_id = "a1c4f6b8-0040-4b7b-99b6-d5034d957bdc"
    drill = arcade._DRILLS[0]
    responses = []
    for index, scenario in enumerate(drill["attempts"]):
        response = client.post("/api/arcade/attempts", json={
            "attempt_id": f"{index + 1:08d}-7e7e-4b2b-9ac0-7b17b41c06f2",
            "challenge_id": scenario["challenge_id"],
            "input": {"aim": scenario["target_aim"],
                      "power": (scenario["yards"] - 14) / 55,
                      "release_timing": 0.5},
            "drill_id": drill["id"],
            "drill_run_id": run_id,
            "drill_attempt_index": index,
        }, headers=CLAIM_HEADERS)
        assert response.status_code == 200
        responses.append(response.json())

    assert responses[-1]["training_set"] == {
        "drill_id": "aim-lab-v1", "score": 3000,
        "personal_best_score": 3000, "medal": "gold",
    }
    assert client.get("/api/arcade/personal-bests", headers=CLAIM_HEADERS).json()
    assert client.get("/api/arcade/personal-bests", headers=CLAIM_HEADERS).json()["training_bests"]["aim-lab-v1"] == {
        "score": 3000, "medal": "gold", "completed_sets": 1,
        "score_distribution": {
            "completed_sets": 1, "average_score": 3000,
            "below_bronze": 0, "bronze": 0, "silver": 0, "gold": 1,
        },
    }

    revised = deepcopy(arcade._DRILL_CHALLENGES[drill["attempts"][0]["challenge_id"]])
    revised["challenge_config"]["target_aim"] = 0.2
    revised["config_hash"] = arcade._config_hash(revised["challenge_config"])
    monkeypatch.setitem(arcade._DRILL_CHALLENGES, revised["challenge_id"], revised)
    monkeypatch.setitem(arcade._CHALLENGES, revised["challenge_id"], revised)
    updated_progress = client.get("/api/arcade/personal-bests", headers=CLAIM_HEADERS).json()
    assert updated_progress["training_bests"]["aim-lab-v1"]["completed_sets"] == 0
    assert updated_progress["training_bests"]["aim-lab-v1"]["score"] == 0
