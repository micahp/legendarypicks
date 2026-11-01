"""Contract checks for the bounded R0 live-source capture helper."""
import json
import os
from collections import defaultdict
import pytest

from capture_pixel_red_zone_r0 import (
    MIN_INTERVAL_SECONDS,
    _capture_play_versions,
    main,
    plays_from_summary,
)


HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(
    HERE, "..", "docs", "research", "fixtures",
    "pixel-red-zone-2026-11-01", "401772830.json",
)


def test_live_capture_flattens_real_espn_nfl_drives():
    with open(FIXTURE, encoding="utf-8") as source:
        summary = json.load(source)

    plays = plays_from_summary(summary)

    assert len(plays) == 187
    assert plays[0]["id"] == "40177283040"
    assert len({str(play["id"]) for play in plays}) == 187


def test_capture_deduplicates_identical_plays_and_retains_changed_versions(tmp_path):
    path = tmp_path / "play_versions.jsonl"
    versions = defaultdict(set)
    event_id = "401873026"
    original = {
        "id": "play-17", "sequenceNumber": "1700",
        "period": {"number": 1}, "clock": {"displayValue": "08:24"},
        "wallclock": "2026-11-01T18:12:00Z", "modified": "2026-11-01T18:12:00Z",
        "text": "A. Runner gains 9 yards.",
    }

    first = _capture_play_versions(event_id, [original], "2026-11-01T18:12:02Z", versions, path)
    repeated = _capture_play_versions(event_id, [original], "2026-11-01T18:12:30Z", versions, path)
    corrected = {**original, "text": "A. Runner gains 8 yards."}
    revised = _capture_play_versions(event_id, [corrected], "2026-11-01T18:13:00Z", versions, path)

    assert first["new_play_versions"] == 1
    assert repeated["new_play_versions"] == 0
    assert revised["changed_play_versions"] == 1
    assert revised["new_play_versions"] == 0
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["event_id"] == "401873026:ESPN:play-17"
    assert records[0]["observed_at_utc"] == "2026-11-01T18:12:02Z"
    assert records[1]["observed_at_utc"] == "2026-11-01T18:13:00Z"
    assert records[0]["revision_hash"] != records[1]["revision_hash"]
    assert all(record["revision_basis"] == "canonical_raw_play_sha256" for record in records)


def test_redzone_latency_and_poll_budget():
    assert MIN_INTERVAL_SECONDS == 60
    with pytest.raises(SystemExit) as error:
        main(["--date", "2026-11-01", "--duration-minutes", "1", "--interval-seconds", "59"])
    assert error.value.code == 2
