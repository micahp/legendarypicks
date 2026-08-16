"""A card is dated by when its STORY moved, not by when the writer last ran.

The generator regenerates every conversation that still clears its source
floor -- for a curated conv_id, that is every scheduled run forever. Dating
cards by `generated_at` meant a days-old story re-stamped itself hourly and
re-pinned itself above genuinely newer cards (Micah, 2026-08-11).

Fixing this by suppressing the write was the wrong lever: it silently
discarded editor-corrected cards and skipped the run-history append that
`news_narratives_runs` exists to keep. The write stays unconditional; what
changed is which timestamp the page reads and sorts on.
"""
from routers.news import _story_time


def _src(published):
    return {"headline": "h", "url": "u%s" % published, "source": "espn",
            "published": published}


def test_story_time_is_the_newest_receipt():
    sources = [_src("2026-08-05T12:00:00Z"), _src("2026-08-09T09:30:00Z"),
               _src("2026-08-07T00:00:00Z")]
    assert _story_time(sources, "2026-08-11T14:00:00Z") == "2026-08-09T09:30:00Z"


def test_regenerating_an_unchanged_story_does_not_move_its_date():
    """The reported bug, stated as a test: same receipts, later run, same date."""
    sources = [_src("2026-08-05T12:00:00Z")]
    first = _story_time(sources, "2026-08-05T13:00:00Z")
    later = _story_time(sources, "2026-08-11T14:00:00Z")
    assert first == later == "2026-08-05T12:00:00Z"


def test_a_genuinely_new_receipt_does_move_the_date():
    old = _story_time([_src("2026-08-05T12:00:00Z")], "2026-08-05T13:00:00Z")
    new = _story_time([_src("2026-08-05T12:00:00Z"), _src("2026-08-11T08:00:00Z")],
                      "2026-08-11T14:00:00Z")
    assert new > old


def test_a_card_written_before_receipts_carried_a_date_keeps_its_position():
    """Old rows have no `published` on their sources. Falling back to
    generated_at keeps them where they were rather than sorting them to the
    bottom of the feed behind everything."""
    sources = [{"headline": "h", "url": "u", "source": "espn"}]
    assert _story_time(sources, "2026-08-09T00:31:56") == "2026-08-09T00:31:56Z"


def test_no_sources_at_all_falls_back_rather_than_returning_empty():
    """An empty string would sort last and render as no date at all."""
    assert _story_time([], "2026-08-09T00:31:56") == "2026-08-09T00:31:56Z"


def test_naive_and_offset_receipts_compare_on_the_same_ruler():
    """news_items carries both shapes. Comparing the raw strings would rank
    '2026-08-09 00:31:56' below '2026-08-08T23:00:00Z' -- _utc_iso normalises
    both before they are compared."""
    sources = [{"headline": "h", "url": "a", "source": "espn",
                "published": "2026-08-09 00:31:56"},
               {"headline": "h", "url": "b", "source": "espn",
                "published": "2026-08-08T23:00:00Z"}]
    assert _story_time(sources, "") == "2026-08-09T00:31:56Z"


def test_a_card_that_cited_nothing_is_dated_by_its_conversation_pool():
    """5 of 13 dev cards cite no receipts. Without a pool fallback they keep
    re-pinning on every run -- the original bug surviving in exactly the rows
    least able to justify a top slot."""
    got = _story_time([], "2026-08-11T08:40:34Z",
                      pool_published="2026-08-07T09:32:22Z")
    assert got == "2026-08-07T09:32:22Z"


def test_a_cited_receipt_still_beats_the_pool():
    """The pool is a fallback, not a competitor: what the card actually cites
    is the better statement about what it is dated by."""
    got = _story_time([_src("2026-08-09T10:00:00Z")], "2026-08-11T08:40:34Z",
                      pool_published="2026-08-10T23:00:00Z")
    assert got == "2026-08-09T10:00:00Z"


def test_generation_time_is_the_last_resort_only():
    assert _story_time([], "2026-08-11T08:40:34Z", pool_published=None) \
        == "2026-08-11T08:40:34Z"
