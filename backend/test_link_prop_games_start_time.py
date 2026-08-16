"""A prop_games row links to the ESPN event that starts at the SAME INSTANT.

The linker matched on `league + date + team abbreviation` only. That is ambiguous
for exactly the case baseball produces constantly: the same two clubs playing on
consecutive days.

`prop_games.date` is derived from a UTC first pitch, while ESPN's scoreboard is
keyed by LOCAL date. A 01:40Z start is the previous evening locally, so asking
ESPN for that UTC date returns the slate for the NEXT day -- which, in a series,
contains the same two teams. The team match then succeeds on the wrong game.

Measured on picks.dev.db 2026-08-11: **85 of 286** MLB prop_games rows with a
start_time were bound to an event that starts at a different time. Observed:

    prop_games 747  start 2026-08-11T01:40Z -> event 401816492 (starts 08-12T01:40Z)
    prop_games 764  start 2026-08-12T01:40Z -> event 401816507 (starts 08-12T19:05Z)

Each row bound to the NEXT game of the series. Two harms, not one:
  1. The finished game shows no props at all (Micah, /game/mlb/401816477).
  2. Those props can never settle -- settlement looks for a final on an event
     that has not been played, so they stay ungraded forever.

`start_time` is an exact key and was already on the row, unused.
"""
import sqlite3

import pytest

from link_prop_games import link_prop_game


def _row(**kw):
    d = {"id": 1, "league": "mlb", "date": "2026-08-11", "home": "Athletics",
         "away": "Tampa Bay Rays", "start_time": None}
    d.update(kw)
    return d


_NAMES = {"ATH": "Athletics", "TB": "Tampa Bay Rays",
          "SEA": "Seattle Mariners", "LAA": "Los Angeles Angels"}


def _espn(game_id, start, home="ATH", away="TB"):
    return {"game_id": game_id, "date": start,
            "home": {"abbrev": home, "displayName": _NAMES[home]},
            "away": {"abbrev": away, "displayName": _NAMES[away]}}


# The real series that exposed this.
SERIES = [
    _espn("401816477", "2026-08-11T01:40Z"),
    _espn("401816492", "2026-08-12T01:40Z"),
    _espn("401816507", "2026-08-12T19:05Z"),
]


def test_start_time_picks_the_right_game_of_a_series():
    """The regression, stated exactly: three games, same two clubs, consecutive
    days. Only the instant tells them apart."""
    row = _row(start_time="2026-08-11T01:40:00+00:00")
    assert link_prop_game(None, row, SERIES) == "401816477"


def test_each_game_of_the_series_resolves_to_itself():
    for start, expected in (("2026-08-11T01:40:00+00:00", "401816477"),
                            ("2026-08-12T01:40:00+00:00", "401816492"),
                            ("2026-08-12T19:05:00+00:00", "401816507")):
        assert link_prop_game(None, _row(start_time=start), SERIES) == expected


def test_it_refuses_to_guess_when_the_instant_matches_nothing():
    """Fail closed. A wrong link is strictly worse than no link: it hides the
    props from the game that was played AND stops them ever grading. An
    unlinked row is visibly missing and can be fixed."""
    row = _row(start_time="2026-08-15T18:00:00+00:00")
    assert link_prop_game(None, row, SERIES) == ""


def test_a_row_without_start_time_still_links_on_teams():
    """316 of 712 rows have no start_time. They must keep working."""
    row = _row(start_time=None)
    assert link_prop_game(None, row, SERIES) == "401816477"


def test_seconds_and_offset_spelling_do_not_break_the_match():
    """prop_games writes `+00:00`, ESPN writes `Z`, and one carries seconds."""
    row = _row(start_time="2026-08-12T01:40:00+00:00")
    espn = [_espn("401816492", "2026-08-12T01:40:00Z")]
    assert link_prop_game(None, row, espn) == "401816492"


def test_a_different_matchup_is_never_matched_on_time_alone():
    """Two unrelated games can share a first pitch. The instant disambiguates
    within a matchup; it does not replace the team check."""
    row = _row(start_time="2026-08-11T01:40:00+00:00")
    other = [_espn("999", "2026-08-11T01:40Z", home="SEA", away="LAA")]
    assert link_prop_game(None, row, other) == ""
