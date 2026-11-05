"""End-to-end ESPN play-by-play to Arcade source handoff contract."""

from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import arcade_store  # noqa: E402
import migrate_schema  # noqa: E402
from pixel_red_zone import plays_from_summary  # noqa: E402
from routers import arcade  # noqa: E402
from routers.games import game_detail  # noqa: E402


app = FastAPI()
app.include_router(game_detail.router)
app.include_router(arcade.router)
client = TestClient(app)


@pytest.fixture
def isolated_arcade_database(tmp_path, monkeypatch):
    database_path = tmp_path / "arcade-redzone-handoff.db"
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


def _in_progress_summary() -> dict:
    fixture = ROOT / "docs/research/fixtures/pixel-red-zone-2026-11-01/401772829.json"
    summary = json.loads(fixture.read_text(encoding="utf-8"))
    summary["header"]["id"] = "401999001"
    competition = summary["header"]["competitions"][0]
    competition["date"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    competition["status"]["type"].update({
        "state": "in",
        "name": "STATUS_IN_PROGRESS",
        "description": "In Progress",
        "shortDetail": "Q4 2:00",
    })
    return summary


def _correct_attempt_distance(summary: dict) -> None:
    play = next(play for play in plays_from_summary(summary)
                if str(play.get("id")) == "4017728291916")
    assert "45 yard field goal" in play["text"]
    play["text"] = play["text"].replace("45 yard field goal", "46 yard field goal", 1)


def test_game_detail_snapshot_and_source_correction_flow_into_arcade(isolated_arcade_database, monkeypatch):
    original = _in_progress_summary()
    corrected = deepcopy(original)
    _correct_attempt_distance(corrected)
    monkeypatch.setattr(game_detail.espn, "summary", Mock(side_effect=[original, corrected]))

    red_zone_response = client.get("/api/nfl/game/401999001/playbyplay")
    assert red_zone_response.status_code == 200
    red_zone_events = red_zone_response.json()["pixel_red_zone"]["events"]
    original_event = next(event for event in red_zone_events
                          if event["source"]["play_id"] == "4017728291916")
    assert original_event["field_goal_attempt_distance_yards"] == 45

    moments_response = client.get("/api/arcade/moments")
    assert moments_response.status_code == 200
    original_moment = next(moment for moment in moments_response.json()["live_moments"]
                           if moment["source_ref"]["play_id"] == "4017728291916")
    assert original_moment["source_ref"]["event_id"] == original_event["source"]["event_id"]
    assert original_moment["source_ref"]["source_revision"] == original_event["source"]["revision"]
    assert original_moment["observed_context"]["attempt_distance_yards"] == 45

    original_challenge = client.get(
        f"/api/arcade/challenges/{original_moment['challenge_id']}"
    ).json()
    assert original_challenge["source_ref"]["event_id"] == original_event["source"]["event_id"]
    assert original_challenge["source_ref"]["source_revision"] == original_event["source"]["revision"]
    assert original_challenge["challenge_config"]["attempt_distance_yards"] == 45

    corrected_response = client.get("/api/nfl/game/401999001/playbyplay")
    assert corrected_response.status_code == 200
    corrected_event = next(event for event in corrected_response.json()["pixel_red_zone"]["events"]
                           if event["source"]["play_id"] == "4017728291916")
    assert corrected_event["field_goal_attempt_distance_yards"] == 46
    assert corrected_event["source"]["event_id"] == original_event["source"]["event_id"]
    assert corrected_event["source"]["revision"] != original_event["source"]["revision"]

    corrected_moments = client.get("/api/arcade/moments").json()["live_moments"]
    corrected_play_moments = [moment for moment in corrected_moments
                              if moment["source_ref"]["play_id"] == "4017728291916"]
    assert len(corrected_play_moments) == 1
    corrected_moment = corrected_play_moments[0]
    assert corrected_moment["source_ref"]["event_id"] == corrected_event["source"]["event_id"]
    assert corrected_moment["source_ref"]["source_revision"] == corrected_event["source"]["revision"]
    assert corrected_moment["observed_context"]["attempt_distance_yards"] == 46

    frozen_original = client.get(
        f"/api/arcade/challenges/{original_moment['challenge_id']}"
    ).json()
    assert frozen_original["state"] == "source_corrected"
    assert frozen_original["challenge_config"]["attempt_distance_yards"] == 45
    assert frozen_original["superseded_by_challenge_id"] == corrected_moment["challenge_id"]
