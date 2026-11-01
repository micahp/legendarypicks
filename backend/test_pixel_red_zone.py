"""Red Zone adapter and director checks using captured ESPN publisher payloads."""
import json
import os
from datetime import datetime, timezone

from pixel_red_zone import (
    channel_state,
    choose_director_game,
    monotonic_event_update,
    normalize_summary,
    plays_from_summary,
)
from routers.games.pixel_red_zone import (
    get_pixel_red_zone_replay,
    list_pixel_red_zone_replays,
)


HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(
    HERE, "..", "docs", "research", "fixtures",
    "pixel-red-zone-2026-11-01", "401772829.json",
)


def load_real_summary():
    with open(FIXTURE, encoding="utf-8") as source:
        return json.load(source)


def test_redzone_exact_score_reconciliation():
    summary = load_real_summary()
    channel = normalize_summary(summary, game_id="401772829", mode="replay",
                                observed_at_utc="2026-11-01T06:57:15Z")

    assert channel["mode"] == "replay"
    assert channel["game"]["game_id"] == "401772829"
    assert len(channel["events"]) == 180
    assert len({event["source"]["event_id"] for event in channel["events"]}) == 180
    assert all(event["source"]["revision_basis"] == "canonical_raw_play_sha256"
               for event in channel["events"])
    assert all(event["source"]["observed_at_utc"] == "2026-11-01T06:57:15Z"
               for event in channel["events"])

    reversed_play = next(event for event in channel["events"]
                         if event["review_state"] == "overturned")
    assert reversed_play["event_type"] == "interception"
    assert reversed_play["is_turnover"] is True
    assert reversed_play["raw_play"]["review"]["upheld"] is False

    final_event = channel["events"][-1]
    assert final_event["after"]["score"] == channel["game"]["score"]


def test_redzone_missing_spot_remains_unknown():
    channel = normalize_summary(load_real_summary(), game_id="401772829", mode="replay")
    events_by_type = {}
    for event in channel["events"]:
        events_by_type.setdefault(event["source_event_type"], []).append(event)

    assert events_by_type["Rush"][0]["before"]["yardline_100"] is not None
    assert events_by_type["Pass Incompletion"][0]["confidence"]["field"] == "verified"
    assert events_by_type["Pass Reception"][0]["before"]["yardline_100"] is None
    assert events_by_type["Punt"][0]["before"]["yardline_100"] is None
    assert events_by_type["Penalty"][0]["before"]["yardline_100"] is None


def test_redzone_copies_only_explicit_espn_field_goal_attempt_distance():
    channel = normalize_summary(load_real_summary(), game_id="401772829", mode="replay")
    attempts = [event for event in channel["events"]
                if event["source_event_type"] in {
                    "Field Goal Good", "Field Goal Missed", "Blocked Field Goal",
                }]
    assert [event["field_goal_attempt_distance_yards"] for event in attempts] == [45, 35, 36]
    assert all(event["field_goal_distance_provenance"]["confidence"] == "verified"
               for event in attempts)
    assert all(event["field_goal_distance_provenance"]["source_field"] == "play.text"
               for event in attempts)
    assert all(event["source"]["event_id"] and event["source"]["revision"] for event in attempts)


def test_redzone_does_not_infer_field_goal_distance_from_field_position():
    summary = {
        "header": {
            "id": "distance-guard",
            "competitions": [{
                "competitors": [
                    {"id": "H", "homeAway": "home", "score": "0", "team": {"abbreviation": "H"}},
                    {"id": "A", "homeAway": "away", "score": "0", "team": {"abbreviation": "A"}},
                ],
                "status": {"type": {"state": "in"}},
            }],
        },
        "plays": [{
            "id": "fg-without-distance", "sequenceNumber": 1,
            "period": {"number": 1}, "clock": {"displayValue": "10:00"},
            "type": {"text": "Field Goal Good"}, "text": "Field goal is GOOD.",
            "start": {"down": 4, "distance": 8, "yardsToEndzone": 17, "team": {"id": "H"}},
            "awayScore": 0, "homeScore": 3,
        }],
    }
    event = normalize_summary(summary, mode="live")["events"][0]
    assert event["field_goal_attempt_distance_yards"] is None
    assert event["field_goal_distance_provenance"]["confidence"] == "unavailable"
    assert event["field_goal_distance_provenance"]["reason"] == "no_unique_published_attempt_distance"


def test_redzone_td_requires_confirmed_result_and_keeps_try_attached():
    channel = normalize_summary(load_real_summary(), game_id="401772829", mode="replay")
    touchdown_events = [event for event in channel["events"]
                        if event["event_type"] == "touchdown"]
    assert touchdown_events
    assert any(event["point_after_attempt"] for event in touchdown_events)
    assert all(event["after"]["score"] is None or isinstance(event["after"]["score"]["home"], int)
               for event in touchdown_events)
    assert all(event["event_type"] != "try" for event in channel["events"])


def test_redzone_requires_verified_play_identity():
    summary = {
        "header": {
            "id": "fixture-game",
            "competitions": [{
                "competitors": [
                    {"id": "H", "homeAway": "home", "score": "7", "team": {"abbreviation": "H"}},
                    {"id": "A", "homeAway": "away", "score": "0", "team": {"abbreviation": "A"}},
                ],
                "status": {"type": {"state": "in"}},
            }],
        },
        "plays": [
            {"id": "one", "sequenceNumber": "100", "type": {"text": "Rush"},
             "period": {"number": 1}, "clock": {"displayValue": "10:00"},
             "start": {"down": 1, "distance": 10, "yardsToEndzone": 30, "team": {"id": "H"}},
             "awayScore": 0, "homeScore": 0},
            {"id": "one", "sequenceNumber": "100", "type": {"text": "Rush"},
             "period": {"number": 1}, "clock": {"displayValue": "10:00"},
             "start": {"down": 1, "distance": 10, "yardsToEndzone": 30, "team": {"id": "H"}},
             "awayScore": 0, "homeScore": 0},
            {"id": "one", "sequenceNumber": "100", "text": "corrected"},
            {"sequenceNumber": "200", "text": "no publisher ID"},
        ],
    }
    channel = normalize_summary(summary, mode="live")

    assert channel["coverage"]["normalized_event_count"] == 2
    assert channel["coverage"]["missing_play_ids"] == 1
    assert channel["coverage"]["duplicate_play_versions"] == 1
    assert len({event["source"]["event_id"] for event in channel["events"]}) == 1
    assert channel["events"][0]["source"]["revision"] != channel["events"][1]["source"]["revision"]


def test_redzone_two_game_director_priority():
    base = {
        "state": "in",
        "last_event": {
            "scoring_play": False,
            "event_type": "rush",
            "review_state": "none",
            "confidence": {"field": "unavailable", "score": "verified"},
            "before": {"yardline_100": 2, "down": 1, "yards_to_go": 3},
        },
    }
    games = [
        {**base, "game_id": "red-zone-unknown"},
        {**base, "game_id": "final", "state": "post"},
        {**base, "game_id": "approaching", "last_event": {
            **base["last_event"], "confidence": {"field": "verified", "score": "verified"},
            "before": {"yardline_100": 24, "down": 2, "yards_to_go": 5},
        }},
    ]

    assert choose_director_game(games) == "approaching"

    touchdown = {
        "scoring_play": True,
        "event_type": "touchdown",
        "review_state": "none",
        "source": {"event_id": "game-td"},
        "confidence": {"field": "verified", "score": "verified"},
        "before": {"yardline_100": 3, "down": 1, "yards_to_go": 2},
    }
    correction = {"game_id": "td", "state": "in", "last_event": touchdown}
    assert choose_director_game([*games, correction]) == "td"
    assert choose_director_game([*games, correction], announced_event_ids={"game-td"}) == "approaching"
    overturned = {**correction, "last_event": {**touchdown, "review_state": "overturned"}}
    assert choose_director_game([*games, overturned]) == "approaching"


def test_redzone_user_pin_dwell_and_stable_ties():
    def candidate(game_id, spot=10, order=1):
        return {
            "game_id": game_id,
            "state": "in",
            "last_play_order": order,
            "last_event": {
                "scoring_play": False,
                "event_type": "rush",
                "review_state": "none",
                "confidence": {"field": "verified", "score": "verified"},
                "before": {"yardline_100": spot, "down": 2, "yards_to_go": 4},
            },
        }

    games = [candidate("B", order=5), candidate("A", order=5)]
    assert choose_director_game(games) == "A"
    assert choose_director_game(games, pinned_game_id="B") == "B"
    assert choose_director_game(games, current_game_id="B", min_dwell_elapsed=False) == "B"
    assert choose_director_game([{**games[0], "state": "post"}]) is None


def test_plays_from_summary_handles_real_nested_nfl_and_legacy_flat_payloads():
    real = load_real_summary()
    nested = plays_from_summary(real)
    flat = [{"id": "flat"}]
    assert len(nested) == 180
    assert plays_from_summary({"plays": flat, "drives": real["drives"]}) == flat


def test_redzone_no_live_simulation_contamination():
    listing = list_pixel_red_zone_replays()
    replay = get_pixel_red_zone_replay("401772829")

    assert listing["mode"] == "replay"
    assert any(row["game_id"] == "401772829" for row in listing["replays"])
    assert replay["mode"] == "replay"
    assert replay["archive"]["raw_fixture_sha256"] == "349693297cd6f8abdabe0f4e35bc3917d20bc542f2f10ca50a5066d417390161"
    assert len(replay["events"]) == 180
    assert all("raw_play" not in event for event in replay["events"])
    assert all(event["mode"] == "replay" for event in replay["events"])


def test_redzone_no_duplicate_td_after_reconnect():
    touchdown = {
        "scoring_play": True,
        "event_type": "touchdown",
        "review_state": "none",
        "source": {"event_id": "game:ESPN:td-1"},
        "confidence": {"score": "verified", "field": "verified"},
        "before": {"yardline_100": 2, "down": 1, "yards_to_go": 2},
    }
    candidate = {"game_id": "game", "state": "in", "last_event": touchdown}
    other = {
        "game_id": "other",
        "state": "in",
        "last_event": {
            "scoring_play": False,
            "event_type": "rush",
            "review_state": "none",
            "confidence": {"score": "verified", "field": "verified"},
            "before": {"yardline_100": 12, "down": 2, "yards_to_go": 5},
        },
    }
    assert choose_director_game([candidate, other]) == "game"
    assert choose_director_game([candidate, other], announced_event_ids={"game:ESPN:td-1"}) == "other"


def test_redzone_event_sequence_rewind_guard():
    current = {"sequence": 20, "source": {"event_id": "g:p20", "revision": "r1"}}
    late = {"sequence": 19, "source": {"event_id": "g:p19", "revision": "r1"}}
    correction = {"sequence": 20, "source": {"event_id": "g:p20", "revision": "r2"}}

    result = monotonic_event_update([late], current)
    assert result["current_event"] == current
    assert result["ignored_older_events"] == 1
    corrected = monotonic_event_update([correction], current)
    assert corrected["current_event"] == current
    assert corrected["corrections"] == [correction]


def test_redzone_live_stale_and_no_games():
    now = datetime(2026, 11, 1, 18, 5, tzinfo=timezone.utc)
    live_without_pbp = [{"game_id": "g", "state": "in", "has_verified_pbp": False}]
    live_with_pbp = [{"game_id": "g", "state": "in", "has_verified_pbp": True}]

    assert channel_state([], observed_at_utc=None, now_utc=now, stale_after_seconds=30) == "off_air"
    assert channel_state([{"state": "pre"}], observed_at_utc=None,
                         now_utc=now, stale_after_seconds=30) == "scheduled"
    assert channel_state(live_without_pbp, observed_at_utc="2026-11-01T18:04:59Z",
                         now_utc=now, stale_after_seconds=30) == "waiting"
    assert channel_state(live_with_pbp, observed_at_utc="2026-11-01T18:04:59Z",
                         now_utc=now, stale_after_seconds=30) == "live"
    assert channel_state(live_with_pbp, observed_at_utc="2026-11-01T18:04:00Z",
                         now_utc=now, stale_after_seconds=30) == "stale"


def test_redzone_event_shared_with_arcade_uses_same_immutable_event_key():
    replay = get_pixel_red_zone_replay("401772829")
    for event in replay["events"]:
        assert event["source"]["event_id"] == f"{event['game_id']}:ESPN:{event['source']['play_id']}"
        assert len(event["source"]["revision"]) == 64
        assert event["source"]["revision_basis"] == "canonical_raw_play_sha256"
