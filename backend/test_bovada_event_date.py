#!/usr/bin/env python3
"""`prop_games.date` is the local slate day, and one function decides it.

`_wc_event_date` returned the UTC date until 2026-08-19, which is where the
second convention in `prop_games.date` came from. A 9:30pm Central kickoff is
02:30Z the next day, so the board filed tonight's late games under tomorrow
while the scoreboard correctly said tonight. Two identical 9:30 kickoffs landed
on different board days purely by which ingest wrote them.

Nothing pinned this before, which is why it drifted for months and why the fix
for it kept being a backfill. These tests fail against the UTC version.
"""
import datetime as dt
import sys

sys.path.insert(0, '.')

from bovada_scraper.direct import _wc_event_date  # noqa: E402


def _stamp_ms(*args):
    """Bovada publishes startTime in epoch milliseconds."""
    return dt.datetime(*args, tzinfo=dt.timezone.utc).timestamp() * 1000


def test_a_late_kickoff_is_filed_on_the_day_it_is_played():
    # 2026-08-20T02:30Z is Houston @ Vancouver, 9:30pm Central on Aug 19.
    # ESPN returns this event on its Aug 19 board, so Aug 19 is the answer.
    prop = {"start_time": _stamp_ms(2026, 8, 20, 2, 30)}
    assert _wc_event_date(prop, "fallback", "mls") == "2026-08-19"


def test_the_same_instant_is_the_same_day_for_every_us_league():
    # The defect that made it visible: identical kickoffs on different board
    # days. Whatever the answer is, it cannot depend on the league here.
    prop = {"start_time": _stamp_ms(2026, 8, 20, 2, 30)}
    days = {lg: _wc_event_date(prop, "fallback", lg)
            for lg in ("mls", "mlb", "nfl", "nba", "nhl", "ufc")}
    assert len(set(days.values())) == 1, days
    assert set(days.values()) == {"2026-08-19"}


def test_tennis_still_buckets_by_utc():
    # Not an oversight in `_slate_day`: tennis normalization already filters
    # competitions by UTC day, so bucketing it locally would split a session.
    prop = {"start_time": _stamp_ms(2026, 8, 20, 2, 30)}
    assert _wc_event_date(prop, "fallback", "atp") == "2026-08-20"


def test_an_early_kickoff_is_unaffected():
    # 23:30Z is 7:30pm Eastern the same day. Both conventions agree here, which
    # is exactly why the split went unnoticed: most of the slate never diverges.
    prop = {"start_time": _stamp_ms(2026, 8, 19, 23, 30)}
    assert _wc_event_date(prop, "fallback", "mls") == "2026-08-19"


def test_an_unusable_stamp_falls_back_rather_than_guessing():
    for bad in (None, "", "not-a-number", {}):
        assert _wc_event_date({"start_time": bad}, "fallback", "mls") == "fallback"
    assert _wc_event_date({}, "fallback", "mls") == "fallback"


def test_seconds_and_milliseconds_are_both_understood():
    seconds = dt.datetime(2026, 8, 20, 2, 30, tzinfo=dt.timezone.utc).timestamp()
    assert _wc_event_date({"start_time": seconds}, "fb", "mls") == "2026-08-19"
    assert _wc_event_date({"start_time": seconds * 1000}, "fb", "mls") == "2026-08-19"
