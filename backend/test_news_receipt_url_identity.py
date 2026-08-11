"""A news receipt is matched on the whole URL, because ESPN puts the identity in
the query string.

`_norm_url` normalised a cited URL by stripping the query — `.split("?")[0]` —
so that a trailing slash would not cause a miss. But ESPN's recap, preview and
clip URLs differ ONLY there:

    http://www.espn.com/mlb/recap?gameId=401816477
    http://www.espn.com/mlb/recap?gameId=401816490

Measured on the dev DB, 2026-08-11: **65 news_items collapse onto 3 keys** — 35
previews, 21 recaps, 9 clips (667 URLs carry a query; 605 survive stripping).
`by_norm` is a plain dict, so it keeps whichever landed last, and a near-miss
citation could attach a DIFFERENT game's recap to a card as its receipt. A wrong
receipt is worse than no receipt: it is a citation the reader will trust.

What the normaliser is actually for is trailing-slash and case-of-host drift.
Those are safe to fold. Query identity is not, and neither is path case — some
publishers serve case-sensitive paths.
"""
from ingest_league_narratives import _norm_url


def test_two_recaps_that_differ_only_in_the_query_stay_distinct():
    a = "http://www.espn.com/mlb/recap?gameId=401816477"
    b = "http://www.espn.com/mlb/recap?gameId=401816490"
    assert _norm_url(a) != _norm_url(b)


def test_a_trailing_slash_is_still_not_a_miss():
    assert _norm_url("https://example.com/a/b/") == _norm_url("https://example.com/a/b")


def test_host_case_is_folded():
    assert _norm_url("HTTPS://WWW.ESPN.COM/mlb/recap?gameId=1") == \
           _norm_url("https://www.espn.com/mlb/recap?gameId=1")


def test_path_case_is_preserved():
    """Folding the whole URL made two distinct paths one key for no benefit."""
    assert _norm_url("https://example.com/Story") != _norm_url("https://example.com/story")


def test_tracking_parameters_do_not_create_a_second_identity():
    """utm_* is decoration, not identity — the one part of the query worth dropping."""
    assert _norm_url("https://www.espn.com/mlb/recap?gameId=1&utm_source=x") == \
           _norm_url("https://www.espn.com/mlb/recap?gameId=1")


def test_query_parameter_order_does_not_matter():
    assert _norm_url("https://x.com/a?b=1&c=2") == _norm_url("https://x.com/a?c=2&b=1")


def test_an_empty_url_is_handled():
    assert _norm_url(None) == ""
    assert _norm_url("") == ""
