"""Regression coverage for ESPN's nested NFL summary play shape."""
import json
import os
from unittest import mock

from routers.games import game_detail


HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(
    HERE, "..", "docs", "research", "fixtures",
    "pixel-red-zone-2026-11-01", "401772830.json",
)


def test_nfl_summary_drives_are_returned_with_source_fields():
    with open(FIXTURE, encoding="utf-8") as source:
        summary = json.load(source)

    with mock.patch.object(game_detail.espn, "summary", return_value=summary):
        result = game_detail.get_game_playbyplay("nfl", "401772830")

    assert result["available"] is True
    assert result["publisher"] == "ESPN"
    assert result["eventId"] == "401772830"
    assert result["publisherUpdatedAt"] == "2025-09-07T20:27:04Z"
    plays = [play for period in result["periods"] for play in period["plays"]]
    assert len(plays) == 187
    assert len({play["playId"] for play in plays}) == len(plays)

    first = plays[0]
    assert first["playId"] == "40177283040"
    assert first["period"] == 1
    assert first["clock"] == "15:00"
    assert first["type"] == "Kickoff"
    assert first["start"]["yardsToEndzone"] == 65
    assert first["end"]["yardsToEndzone"] == 65
    assert first["wallclock"] == "2025-09-07T17:02:59Z"

    touchdown = next(play for play in plays if play["pointAfterAttempt"])
    assert touchdown["pointAfterAttempt"]["text"] == "Extra Point Good"
    assert touchdown["scoringType"] == "touchdown"

    reviewed = [play for play in plays if play["review"]]
    assert len(reviewed) == 4
    assert {play["review"]["type"] for play in reviewed} == {"CHALLENGE", "OFFICIAL"}


def test_flat_summary_play_shape_remains_supported():
    summary = {
        "header": {"id": "game-flat"},
        "plays": [{
            "id": "play-1",
            "period": {"number": 1, "displayValue": "1st"},
            "clock": {"displayValue": "12:34"},
            "type": {"text": "Run"},
            "text": "A. Runner gains 4 yards.",
            "homeScore": 0,
            "awayScore": 0,
        }],
    }

    with mock.patch.object(game_detail.espn, "summary", return_value=summary):
        result = game_detail.get_game_playbyplay("nba", "game-flat")

    assert result["available"] is True
    assert result["eventId"] == "game-flat"
    assert result["periods"][0]["label"] == "1st"
    assert result["periods"][0]["plays"][0]["playId"] == "play-1"
