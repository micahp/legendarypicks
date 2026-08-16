"""link_prop_games — matching a prop_game to its ESPN event.

Fixtures are the REAL shape of an MLS scoreboard response, captured 2026-08-11
from espn_client.games('mls', '2026-08-16'). The team objects carry
abbrev/name/nickname/score/winner and NO displayName — which is the whole bug:
the name fallback read displayName, got None for every game, and MLS linked 2 of
15 prop_games. Their props then never reached the game page, because
/api/game/{league}/{id}/props joins on prop_games.espn_event_id.
"""
import sqlite3

import pytest

from link_prop_games import _norm_team, link_prop_game


def _espn_game(gid, home_abbrev, home_name, away_abbrev, away_name, date):
    """An ESPN scoreboard game, shaped exactly as espn_client.games() returns it."""
    return {
        "game_id": gid,
        "date": date,
        "home": {"abbrev": home_abbrev, "name": home_name,
                 "nickname": home_name, "score": 0.0, "winner": False},
        "away": {"abbrev": away_abbrev, "name": away_name,
                 "nickname": away_name, "score": 0.0, "winner": False},
    }


MLS_SLATE = [
    _espn_game("727001", "CHI", "Chicago Fire FC", "POR", "Portland Timbers",
               "2026-08-16T22:00Z"),
    _espn_game("727002", "NYC", "New York City FC", "PHI", "Philadelphia Union",
               "2026-08-16T22:00Z"),
    _espn_game("727003", "ATX", "Austin FC", "DAL", "FC Dallas",
               "2026-08-17T00:30Z"),
]


def _prop_game(**kw):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE prop_games(id,league,date,home,away,start_time)")
    con.execute(
        "INSERT INTO prop_games VALUES(?,?,?,?,?,?)",
        (kw.get("id", 716), kw.get("league", "mls"), kw.get("date", "2026-08-16"),
         kw["home"], kw["away"], kw.get("start_time")),
    )
    return con, con.execute("SELECT * FROM prop_games").fetchone()


class TestMLSLinksOnThePublishedName:
    def test_links_when_only_name_is_published(self):
        # The regression: these are the exact strings prop_games holds for
        # game 716, against the exact payload ESPN returns.
        con, row = _prop_game(home="New York City FC", away="Philadelphia Union",
                              start_time="2026-08-16T22:00:00+00:00")
        assert link_prop_game(con, row, MLS_SLATE) == "727002"

    def test_links_without_a_start_time(self):
        con, row = _prop_game(home="Austin FC", away="FC Dallas")
        assert link_prop_game(con, row, MLS_SLATE) == "727003"

    def test_unknown_matchup_still_returns_nothing(self):
        con, row = _prop_game(home="Inter Miami", away="Nashville SC")
        assert link_prop_game(con, row, MLS_SLATE) == ""

    def test_reversed_fixture_is_not_a_match(self):
        # Home and away are not interchangeable; a swapped pair is a different
        # game, and matching it would bind props to the wrong side's page.
        con, row = _prop_game(home="Philadelphia Union", away="New York City FC")
        assert link_prop_game(con, row, MLS_SLATE) == ""


class TestNoGuessedAbbreviationsForUnmappedLeagues:
    def test_the_san_collision_is_impossible(self):
        # "San Diego FC" and "San Jose Earthquakes" both used to normalise to SAN,
        # so either could match a game belonging to the other. This asserted both
        # were "" back when MLS had no map at all — the only way to be safe then.
        # MLS now carries the publisher's recorded club list, so the guarantee gets
        # stronger rather than weaker: both resolve, and they resolve DIFFERENTLY.
        # Keep the inequality, not just the two values: a future map edit that
        # collapsed them would still satisfy two separate equality checks.
        sd, sj = _norm_team("San Diego FC", "mls"), _norm_team("San Jose Earthquakes", "mls")
        assert (sd, sj) == ("SD", "SJ")
        assert sd != sj

    def test_a_club_outside_the_recorded_list_is_still_unknown(self):
        # The prefix fallback stays refused for MLS. An unrecognised club name must
        # not become three letters that read like an answer.
        assert _norm_team("Zzz Unknown Club", "mls") == ""

    def test_an_ambiguous_substring_refuses_rather_than_picks(self):
        # "new york" is inside both "new york city fc" and "new york red bulls".
        # Dict order deciding which club gets the props is a mislink that looks
        # exactly like a successful one.
        assert _norm_team("New York", "mls") == ""

    def test_the_spellings_that_were_actually_missing_now_resolve(self):
        # The eight games that stayed unlinked after the 08-11 fix, by the shape of
        # the disagreement. Measured against ESPN's published names 2026-08-15/16.
        assert _norm_team("New York Red Bulls", "mls") == "RBNY"   # word order
        assert _norm_team("DC United", "mls") == "DC"              # punctuation
        assert _norm_team("Los Angeles FC", "mls") == "LAFC"       # contraction
        assert _norm_team("Inter Miami", "mls") == "MIA"           # dropped CF
        assert _norm_team("Orlando City", "mls") == "ORL"          # dropped SC
        assert _norm_team("Minnesota United", "mls") == "MIN"      # dropped FC
        # ...and the LA pair the contraction sits next to.
        assert _norm_team("LA Galaxy", "mls") == "LA"

    def test_mapped_league_behaviour_is_unchanged(self):
        assert _norm_team("Philadelphia Phillies", "mlb") == "PHI"
        assert _norm_team("PHI", "mlb") == "PHI"
        # Still falls back to a prefix inside a league we do have a map for.
        assert _norm_team("Zzz Unknown Club", "mlb") == "ZZZ"

    def test_empty_norms_do_not_match_every_game(self):
        # Both sides normalise to "" for MLS; if the abbrev branch ran, ""==""
        # would call the first game on the slate a match.
        con, row = _prop_game(home="Nowhere United", away="Elsewhere City")
        assert link_prop_game(con, row, MLS_SLATE) == ""


class TestStartTimeStaysDecisive:
    def test_wrong_instant_fails_closed(self):
        # The MLB series bug: right matchup, wrong game. A known instant that
        # matches nothing must return '' rather than picking a candidate.
        con, row = _prop_game(home="New York City FC", away="Philadelphia Union",
                              start_time="2026-08-17T22:00:00+00:00")
        assert link_prop_game(con, row, MLS_SLATE) == ""
