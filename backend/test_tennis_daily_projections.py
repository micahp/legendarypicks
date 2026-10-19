"""Projection caches refresh when tennis-spine identities change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tennis_daily_projections import needs_projection_refresh  # noqa: E402


def _match(home_id="100", away_id="200"):
    return {
        "gameId": "match-1",
        "identity": {
            "home": {"sackmann_player_id": home_id},
            "away": {"sackmann_player_id": away_id},
        },
    }


def _projection(home_id=None, away_id=None):
    return {
        "homeDoubleFaults": None,
        "awayDoubleFaults": None,
        "unavailableReason": "One or both player IDs are not mapped through the tennis spine.",
        "_sackmannPlayerIds": {"home": home_id, "away": away_id},
    }


def test_old_unmapped_cache_refreshes_after_players_resolve():
    stored = {"match-1": _projection()}
    assert needs_projection_refresh(stored, [_match("100", "200")])


def test_cache_refreshes_when_a_resolved_player_mapping_changes():
    stored = {"match-1": _projection("100", "200")}
    assert needs_projection_refresh(stored, [_match("100", "300")])


def test_current_unmapped_cache_does_not_refresh_repeatedly():
    stored = {"match-1": _projection()}
    assert not needs_projection_refresh(stored, [_match(None, None)])


def test_cache_without_double_fault_fields_refreshes():
    stored = {"match-1": {"_sackmannPlayerIds": {"home": "100", "away": "200"}}}
    assert needs_projection_refresh(stored, [_match()])


# --- coverage drives surfaces -------------------------------------------------
# The surface map used to be keyed only on ESPN tournament ids we had happened to
# see (Shanghai and Wuhan), so every other tracked event silently had no surface
# and therefore no surface-dependent output at all. These pin the invariant that
# keeps that from returning: every event the coverage rule tracks must resolve to
# a surface without needing an ESPN id.

from espn_client.scoreboard import _ATP_MAJORS, _WTA_MAJORS, major_for_event  # noqa: E402
import tennis_daily_projections as proj  # noqa: E402


def test_every_tracked_major_has_a_surface():
    missing = [
        (tour, canonical)
        for tour, majors in (("atp", _ATP_MAJORS), ("wta", _WTA_MAJORS))
        for canonical, _aliases in majors
        if canonical not in proj.SURFACE_BY_MAJOR
    ]
    assert missing == []


def test_event_name_resolves_a_surface_without_an_espn_id():
    for tour, event_name, expected in (
        ("atp", "Rolex Paris Masters", "Hard"),
        ("atp", "Wimbledon", "Grass"),
        ("atp", "Roland Garros", "Clay"),
        ("atp", "Rolex Shanghai Masters", "Hard"),
        ("wta", "Qatar TotalEnergies Open", "Hard"),
        ("wta", "Dongfeng Voyah Wuhan Open", "Hard"),
        ("wta", "Mutua Madrid Open", "Clay"),
    ):
        major = major_for_event(tour, event_name)
        assert major is not None, f"{event_name} is tracked but has no canonical major"
        assert proj.SURFACE_BY_MAJOR[major] == expected, f"{event_name} -> {expected}"


def test_mens_grand_slams_are_best_of_five_and_everything_else_three():
    for tour, event_name in (
        ("atp", "Wimbledon"), ("atp", "Roland Garros"),
        ("atp", "US Open"), ("atp", "Australian Open"),
    ):
        assert major_for_event(tour, event_name) in proj.FIVE_SET_MAJORS
    for tour, event_name in (
        ("wta", "Wimbledon"), ("wta", "Roland Garros"),
        ("atp", "Rolex Paris Masters"), ("atp", "ATP Finals"),
        ("wta", "WTA Finals"), ("atp", "China Open"),
    ):
        major = major_for_event(tour, event_name)
        assert not (tour == "atp" and major in proj.FIVE_SET_MAJORS)


def test_untracked_event_is_not_given_a_surface():
    assert major_for_event("atp", "Vienna Open") is None
    assert major_for_event("atp", "Some Challenger") is None
