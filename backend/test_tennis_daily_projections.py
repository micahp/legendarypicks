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
