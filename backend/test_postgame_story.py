"""Tests for the preview -> recap transition.

A cached story used to be final forever, so a game detail page previewed a match that had
ended hours earlier. There is no column recording which kind of story a row holds; a story
generated before kickoff is a preview by construction, and that is what these pin.
"""
from _core import _story_is_stale_preview as stale


KICKOFF = "2026-08-10T00:00Z"


def test_a_story_written_before_kickoff_is_a_preview_once_the_game_is_final():
    assert stale("2026-08-09 18:00:00", "post", KICKOFF) is True


def test_a_story_written_after_the_final_whistle_stands():
    assert stale("2026-08-10 03:00:00", "post", KICKOFF) is False


def test_a_preview_of_a_game_that_has_not_kicked_off_stands():
    """The whole point of a preview. Only 'post' makes it stale."""
    assert stale("2026-08-09 18:00:00", "pre", KICKOFF) is False
    assert stale("2026-08-09 18:00:00", "in", KICKOFF) is False


def test_utc_on_both_sides():
    """generated_at is SQLite datetime('now') — a space-separated UTC stamp. ESPN's start
    is a Zulu instant with a T. Comparing them as raw strings without normalising would
    make 'T' > ' ' decide the outcome instead of the time."""
    assert stale("2026-08-09 23:59:00", "post", "2026-08-10T00:00Z") is True
    assert stale("2026-08-10 00:01:00", "post", "2026-08-10T00:00Z") is False


def test_missing_information_never_invalidates_a_story():
    """A caller that does not know the state or the start time gets the old behaviour:
    the cache stands. Regenerating on absent evidence would burn an LLM call per view."""
    assert stale("2026-08-09 18:00:00", None, KICKOFF) is False
    assert stale("2026-08-09 18:00:00", "post", None) is False
    assert stale(None, "post", KICKOFF) is False


def test_garbage_is_not_a_reason_to_regenerate():
    assert stale("not a date", "post", KICKOFF) is False
    assert stale(12345, "post", KICKOFF) is False
