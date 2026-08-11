"""The gamePk comes from the published first pitch, and never from a game that
has not been played.

Measured live on 2026-08-11, one hour after the props timer ran:

    _fetch_mlb_gamepk('2026-08-11', 'Arizona Diamondbacks', 'Colorado Rockies')
      -> 825046  =  2026-08-12T01:40Z, status "Pre-Game"

The game that actually happened was `2026-08-11T01:40Z` — the same matchup one
day earlier in UTC, already Final 9-0. `prop_games.start_time` held
`2026-08-11T01:40:00+00:00`, the exact key, unused: the lookup searched
day-1/day/day+1 on TEAMS ONLY and returned the first match, which for a series is
a different game between the same two clubs.

The consequence is not a missing grade. The unplayed game publishes a lineup with
zeroed batting lines, so every player resolves, every stat reads 0, and every
prop grades — **every UNDER cashed and every OVER lost**. 7,857 props across 6
games settled that way at 21:00Z, and 4,078 more sit on 11 games ESPN reports as
Postponed.

Two independent guards, because either alone leaves the other hole open:

1. **Pick by the instant.** `start_time` is on the same row; the MLB schedule
   publishes `gameDate` on the same object. Matching instants removes the guess.
2. **Refuse a game that is not Final.** Even the right gamePk must not grade a
   game in progress or not yet started — a box score is not a result. This is the
   settlement-side twin of the `completed` gate in
   test_finality_gate_completed.
"""
import pytest

import settlement


def _game(pk, iso, home, away, state="Final"):
    return {"gamePk": pk, "gameDate": iso,
            "status": {"abstractGameState": state},
            "teams": {"home": {"team": {"name": home, "abbreviation": home[:3].upper()}},
                      "away": {"team": {"name": away, "abbreviation": away[:3].upper()}}}}


ARI, COL = "Arizona Diamondbacks", "Colorado Rockies"

# The real 2026-08-11 shape: the played game sits on the previous UTC day, and the
# same matchup recurs the next day, unplayed.
_PLAYED = _game(825045, "2026-08-11T01:40:00Z", ARI, COL)
_NOT_YET = _game(825046, "2026-08-12T01:40:00Z", ARI, COL, state="Preview")


@pytest.fixture
def schedule(monkeypatch):
    def use(by_day):
        monkeypatch.setattr(settlement, "_mlb_schedule",
                            lambda day: {"dates": [{"games": by_day.get(day, [])}]})
    return use


def test_the_instant_decides_which_game_of_the_series(schedule):
    schedule({"2026-08-11": [_PLAYED], "2026-08-12": [_NOT_YET]})
    pk = settlement._fetch_mlb_gamepk("2026-08-11", ARI, COL,
                                      start_time="2026-08-11T01:40:00+00:00")
    assert pk == 825045, "the game that was actually played, not the next one"


def test_without_the_instant_an_unplayed_game_is_still_refused(schedule):
    """The historical rows have no start_time. They must not grade against a
    game that has not happened, key or no key."""
    schedule({"2026-08-12": [_NOT_YET]})
    assert settlement._fetch_mlb_gamepk("2026-08-12", ARI, COL) is None


def test_a_doubleheader_resolves_by_instant_instead_of_taking_the_first(schedule):
    first = _game(824912, "2026-06-17T18:00:00Z", "Atlanta Braves", "San Francisco Giants")
    second = _game(824913, "2026-06-17T23:15:00Z", "Atlanta Braves", "San Francisco Giants")
    schedule({"2026-06-17": [first, second]})
    pk = settlement._fetch_mlb_gamepk("2026-06-17", "Atlanta Braves", "San Francisco Giants",
                                      start_time="2026-06-17T23:15:00+00:00")
    assert pk == 824913, "the docstring conceded the doubleheader half; the instant settles it"


def test_an_ambiguous_lookup_without_an_instant_fails_closed(schedule):
    """Two candidates and no way to tell them apart: refuse. An unsettled prop is
    recoverable; a prop graded against the wrong game is not."""
    first = _game(824912, "2026-06-17T18:00:00Z", "Atlanta Braves", "San Francisco Giants")
    second = _game(824913, "2026-06-17T23:15:00Z", "Atlanta Braves", "San Francisco Giants")
    schedule({"2026-06-17": [first, second]})
    assert settlement._fetch_mlb_gamepk("2026-06-17", "Atlanta Braves",
                                        "San Francisco Giants") is None


def test_a_postponed_game_is_never_the_answer(schedule):
    pp = _game(824911, "2026-06-18T23:15:00Z", "Atlanta Braves", "San Francisco Giants",
               state="Preview")
    schedule({"2026-06-18": [pp]})
    assert settlement._fetch_mlb_gamepk("2026-06-18", "Atlanta Braves",
                                        "San Francisco Giants",
                                        start_time="2026-06-18T23:15:00+00:00") is None


def test_an_unambiguous_day_still_resolves_without_an_instant(schedule):
    """Don't break the 396 historical rows that have no start_time and no rival."""
    schedule({"2026-08-11": [_PLAYED]})
    assert settlement._fetch_mlb_gamepk("2026-08-11", ARI, COL) == 825045


def test_the_instant_must_actually_match(schedule):
    """A start_time that matches nothing is a link problem, not a licence to guess."""
    schedule({"2026-08-11": [_PLAYED]})
    assert settlement._fetch_mlb_gamepk("2026-08-11", ARI, COL,
                                        start_time="2026-08-11T18:05:00+00:00") is None


def test_a_small_clock_drift_still_matches(schedule):
    """Published first pitch moves by a few minutes; that is not a different game."""
    schedule({"2026-08-11": [_PLAYED]})
    assert settlement._fetch_mlb_gamepk("2026-08-11", ARI, COL,
                                        start_time="2026-08-11T01:47:00+00:00") == 825045


def test_settle_passes_the_start_time_it_already_has(monkeypatch):
    """The key was on the row the whole time. Regression pin on the plumbing."""
    seen = {}

    def fake(date_str, home, away, start_time=None):
        seen.update(date=date_str, start_time=start_time)
        return None

    monkeypatch.setattr(settlement, "_fetch_mlb_gamepk", fake)
    row = {"date": "2026-08-11", "home": ARI, "away": COL,
           "start_time": "2026-08-11T01:40:00+00:00"}
    settlement._settle_mlb_props(None, row, [])
    assert seen["start_time"] == "2026-08-11T01:40:00+00:00"
