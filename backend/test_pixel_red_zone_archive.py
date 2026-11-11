"""Source and identity checks for the compact historical replay archive."""

import hashlib
import json
from pathlib import Path

from build_pixel_red_zone_replays import SOURCE_DIR, build


def test_archive_fixtures_reconcile_to_the_frozen_espn_source_set():
    manifest = json.loads((SOURCE_DIR / "capture_manifest.json").read_text())
    fixtures, catalog = build()

    assert len(fixtures) == len(manifest["fixtures"]) == 8
    assert sum(len(row["payload"]["events"]) for row in fixtures) == 1464
    assert [row["game_id"] for row in catalog] == [row["game_id"] for row in sorted(
        catalog, key=lambda row: (row["date"] or "", row["game_id"]),
    )]

    captures = {str(row["event_id"]): row for row in manifest["fixtures"]}
    for fixture in fixtures:
        game_id = fixture["game_id"]
        payload = fixture["payload"]
        captured = captures[game_id]
        source_path = SOURCE_DIR / captured["file"]
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == payload["archive"]["raw_fixture_sha256"]
        assert payload["mode"] == "replay"
        assert payload["game"]["game_id"] == game_id
        assert payload["game"]["score"] == captured["score_reconciliation"]["independent_scoreboard"]
        assert payload["archive"]["score_reconciled_to_independent_espn_scoreboard"] is True

        events = payload["events"]
        event_ids = [event["source"]["event_id"] for event in events]
        assert len(event_ids) == len(set(event_ids)) == captured["unique_play_ids"]
        assert all(event["source"]["play_id"] for event in events)
        assert not any({"raw_play", "raw_start", "raw_end"} & event.keys() for event in events)
