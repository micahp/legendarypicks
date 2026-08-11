"""Tests for the narrative-card regeneration gate.

A scheduled run used to rewrite `generated_at` for every conversation that
still cleared `_MIN_ITEMS`, whether or not anything new had actually
happened. For a curated conv_id that never drops below the floor, that's
every run forever -- the card kept re-pinning itself to the top of a feed
sorted by generated_at DESC, and a story from days ago read as "updated an
hour ago". `sources_unchanged` is the gate: no new source, no rewrite.
"""
import json

from ingest_league_narratives import sources_unchanged


def _src(url):
    return {"headline": "h", "url": url, "source": "espn"}


def test_identical_sources_are_unchanged():
    existing = json.dumps([_src("a"), _src("b")])
    new = [_src("b"), _src("a")]
    assert sources_unchanged(existing, new) is True


def test_a_new_source_is_a_change():
    existing = json.dumps([_src("a")])
    new = [_src("a"), _src("b")]
    assert sources_unchanged(existing, new) is False


def test_fewer_sources_this_run_is_still_unchanged():
    """The model citing a subset of what's already served is not new
    material -- only a source that wasn't there before counts."""
    existing = json.dumps([_src("a"), _src("b")])
    new = [_src("a")]
    assert sources_unchanged(existing, new) is True


def test_no_existing_card_has_nothing_to_compare_against():
    assert sources_unchanged("[]", [_src("a")]) is False


def test_empty_existing_field_is_treated_as_no_sources():
    assert sources_unchanged(None, [_src("a")]) is False
    assert sources_unchanged("", [_src("a")]) is False
