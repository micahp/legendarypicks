#!/usr/bin/env python3
"""A fixture must belong to the league claiming it, and the rule must know its own limits.

Every test here is a mistake this rule actually made before it was pinned. The first version
called 11 UFC fights foreign because a fighter is not a club; the second called 7 real NCAAF
games foreign over "Michigan (#16)" against "Michigan Wolverines"; the third let
"Atletico San Luis" pass as Atlanta United because "ATL" is a prefix of it.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import league_membership as lm


def _con(rows=(), snapshots=()):
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT,
            home TEXT, away TEXT, espn_event_id TEXT);
        CREATE TABLE scoreboard_snapshots(league TEXT, game_id TEXT, payload TEXT);
    """)
    for index, (league, home, away, espn) in enumerate(rows, start=1):
        con.execute("INSERT INTO prop_games VALUES(?,?,?,?,?,?)",
                    (index, league, "2026-09-06", home, away, espn))
    for league, payload in snapshots:
        con.execute("INSERT INTO scoreboard_snapshots VALUES(?,?,?)",
                    (league, "g", payload))
    con.commit()
    return con


def _mls(extra=()):
    clubs = ["Atlanta United", "Austin FC", "LA Galaxy", "Inter Miami CF",
             "Seattle Sounders FC", "Portland Timbers", "FC Dallas", "Toronto FC",
             "New York Red Bulls", "Los Angeles FC"]
    rows = [("mls", clubs[i], clubs[i + 1], "7617%02d" % i)
            for i in range(0, len(clubs) - 1, 2)]
    return _con(rows + list(extra))


class ItRefusesAFixtureFromAnotherCompetition(unittest.TestCase):
    def test_a_serie_a_fixture_is_not_mls(self):
        self.assertIs(lm.belongs(_mls(), "mls", "Bologna", "Sassuolo"), False)

    def test_a_liga_mx_fixture_is_not_mls(self):
        self.assertIs(lm.belongs(_mls(), "mls", "Atlético San Luis", "Guadalajara"), False)

    def test_an_abbreviation_is_too_short_to_be_a_prefix(self):
        """ATL made "Atletico San Luis" pass as Atlanta United. Three letters are not
        evidence, and this is the exact false negative that let a Liga MX fixture through."""
        con = _mls([("mls", "ATL", "AUS", "761799")])
        self.assertIs(lm.belongs(con, "mls", "Atlético San Luis", "Guadalajara"), False)


class ItAdmitsRealFixtures(unittest.TestCase):
    def test_a_real_mls_fixture_belongs(self):
        self.assertIs(lm.belongs(_mls(), "mls", "Austin FC", "LA Galaxy"), True)

    def test_one_side_on_record_is_enough(self):
        """A newly renamed or promoted side must not make a real fixture foreign."""
        self.assertIs(lm.belongs(_mls(), "mls", "Austin FC", "Some New Expansion Club"), True)

    def test_a_publishers_ranking_is_decoration_not_identity(self):
        """"Michigan (#16)" against a stored "Michigan Wolverines" is one school. Seven real
        NCAAF games were called foreign on exactly this."""
        clubs = ["Michigan Wolverines", "Ohio State Buckeyes", "Alabama Crimson Tide",
                 "Georgia Bulldogs", "Texas Longhorns", "Oregon Ducks",
                 "Penn State Nittany Lions", "Notre Dame Fighting Irish"]
        rows = [("ncaaf", clubs[i], clubs[i + 1], "4018%02d" % i)
                for i in range(0, len(clubs) - 1, 2)]
        self.assertIs(
            lm.belongs(_con(rows), "ncaaf", "Michigan (#16)", "Western Michigan"), True)

    def test_accents_do_not_make_a_club_foreign(self):
        con = _con([("mls", "CF Montréal", "Toronto FC", "761772"),
                    ("mls", "Austin FC", "LA Galaxy", "761778"),
                    ("mls", "FC Dallas", "Inter Miami CF", "761779"),
                    ("mls", "Seattle Sounders FC", "Portland Timbers", "761780"),
                    ("mls", "Atlanta United", "New York Red Bulls", "761781")])
        self.assertIs(lm.belongs(con, "mls", "CF Montreal", "Toronto"), True)


class ItKnowsWhatItCannotJudge(unittest.TestCase):
    def test_an_individual_sport_is_never_judged(self):
        """A fighter is not a club, so every debut would read as foreign. Asking the
        question at all is a category error; 11 UFC fights were flagged this way."""
        rows = [("ufc", "Fighter %d" % i, "Fighter %d" % (i + 1), "e%d" % i)
                for i in range(0, 20, 2)]
        self.assertIsNone(lm.belongs(_con(rows), "ufc", "Debut Guy", "Other Debut"))

    def test_a_sparsely_covered_league_is_not_judged(self):
        """An absence in a league we barely cover says more about us than the fixture."""
        self.assertIsNone(
            lm.belongs(_con([("nhl", "A", "B", "1")]), "nhl", "Anything", "At All"))

    def test_an_unlinked_game_does_not_vote_itself_legitimate(self):
        """The rows this check exists to doubt must not become the evidence for it."""
        con = _mls([("mls", "Bologna", "Sassuolo", "")])
        self.assertNotIn("bologna", lm.known_clubs(con, "mls"))
        self.assertIs(lm.belongs(con, "mls", "Bologna", "Sassuolo"), False)


if __name__ == "__main__":
    unittest.main()


class ThePublishedClubListIsWhatMakesItStrict(unittest.TestCase):
    """Without league_clubs the record is whatever happened to appear, and a strict check
    on an incomplete record refuses real fixtures. Texas State @ Texas, Oklahoma State @
    Tulsa and UNLV @ Hawaii all read as foreign until the publisher's own list was stored."""

    def _ncaaf(self, published=()):
        con = _con([("ncaaf", "Michigan Wolverines", "Ohio State Buckeyes", "1"),
                    ("ncaaf", "Alabama Crimson Tide", "Georgia Bulldogs", "2"),
                    ("ncaaf", "Texas Longhorns", "Oregon Ducks", "3"),
                    ("ncaaf", "Penn State Nittany Lions", "Notre Dame Fighting Irish", "4")])
        con.executescript("""
            CREATE TABLE league_clubs(league TEXT, name TEXT, code TEXT, source TEXT,
                updated_at TEXT, PRIMARY KEY(league,name));
        """)
        for name in published:
            con.execute("INSERT INTO league_clubs VALUES('ncaaf',?,NULL,'cfbd','now')",
                        (name,))
        con.commit()
        return con

    def test_without_the_published_list_a_real_fixture_reads_as_foreign(self):
        con = self._ncaaf()
        self.assertIs(lm.belongs(con, "ncaaf", "Texas (#5)", "Texas State", strict=True),
                      False)

    def test_with_it_the_same_fixture_belongs(self):
        con = self._ncaaf(published=["Texas", "Texas State"])
        self.assertIs(lm.belongs(con, "ncaaf", "Texas (#5)", "Texas State", strict=True),
                      True)

    def test_a_squashed_spelling_still_matches(self):
        """CFBD publishes "Hawai'i"; the book says "Hawaii". Folding turns the apostrophe
        into a space, so the two differ by a character that means nothing."""
        con = self._ncaaf(published=["Hawai'i", "UNLV", "Texas", "Texas State"])
        self.assertIs(lm.belongs(con, "ncaaf", "Hawaii", "UNLV", strict=True), True)

    def test_a_foreign_club_is_still_refused_with_the_list_present(self):
        con = self._ncaaf(published=["Texas", "Texas State", "Hawai'i", "UNLV"])
        self.assertIs(lm.belongs(con, "ncaaf", "Bologna", "Sassuolo", strict=True), False)
