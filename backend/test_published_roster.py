#!/usr/bin/env python3
"""The resolver's fifth step: consult the publisher's own roster before giving up.

Giving up used to mean dropping every prop for a real player. Measured on prod 2026-09-06:
1,254 names and 873,559 attempts from bovada alone, plus 254 from espn_roster, which is proof
the spine is missing people ESPN itself names rather than that a sportsbook spells oddly.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster as pr


def _con(rows=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    pr.ensure(con)
    for league, key, name, team, position, group in rows:
        con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?, 'now')",
            (league, "fotmob", key, name, pr.fold(name), team, position, group))
    con.commit()
    return con


class ItResolvesWhatThePublisherNames(unittest.TestCase):
    def test_a_single_match_resolves(self):
        con = _con([("mls", "1", "Lautaro Giaccone", "Columbus", "M", "Midfielder")])
        self.assertEqual(pr.lookup(con, "mls", "Lautaro Giaccone"),
                         ("fotmob", "1", "M", "Midfielder", "Lautaro Giaccone"))

    def test_accents_and_punctuation_do_not_prevent_a_match(self):
        """`Djé D'Avilla` reaches us from a sportsbook in several spellings."""
        con = _con([("mls", "1", "Djé D'Avilla", "Chicago", "M", "Midfielder")])
        for spelling in ("Dje DAvilla", "DJE D'AVILLA", "Djé D`Avilla"):
            with self.subTest(spelling=spelling):
                self.assertIsNotNone(pr.lookup(con, "mls", spelling))

    def test_a_league_it_has_never_heard_of_is_not_a_match(self):
        con = _con([("mls", "1", "Someone", "Chicago", "M", "Midfielder")])
        self.assertIsNone(pr.lookup(con, "nfl", "Someone"))


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def test_two_players_of_the_same_name_resolve_to_neither(self):
        """Guessing between them is how 124 of 317 MLB duplicate groups became two people."""
        con = _con([("mls", "1", "Common Name", "Chicago", "M", "Midfielder"),
                    ("mls", "2", "Common Name", "Austin", "D", "Defender")])
        self.assertIsNone(pr.lookup(con, "mls", "Common Name"))

    def test_a_team_narrows_an_otherwise_ambiguous_name(self):
        con = _con([("mls", "1", "Common Name", "Chicago", "M", "Midfielder"),
                    ("mls", "2", "Common Name", "Austin", "D", "Defender")])
        self.assertEqual(pr.lookup(con, "mls", "Common Name", team="Austin")[1], "2")

    def test_it_returns_the_PUBLISHERS_spelling_not_the_callers(self):
        """We resolve BY the publisher's identity, so their rendering of the name is the
        fact and a sportsbook's is a display artifact."""
        con = _con([("mls", "1", "Dj\u00e9 D'Avilla", "Chicago", "M", "Midfielder")])
        self.assertEqual(pr.lookup(con, "mls", "Dje DAvilla")[4], "Dj\u00e9 D'Avilla")

    def test_a_wrong_team_does_not_exclude_the_only_candidate(self):
        """A sportsbook's team string is often absent or in its own vocabulary; requiring it
        would refuse real players for a reason about the publisher, not the person."""
        con = _con([("mls", "1", "Only One", "Chicago", "M", "Midfielder")])
        self.assertIsNotNone(pr.lookup(con, "mls", "Only One", team="NOT-A-CLUB"))

    def test_an_empty_name_is_never_a_match(self):
        con = _con([("mls", "1", "Someone", "Chicago", "M", "Midfielder")])
        for empty in ("", "   ", None, "!!!"):
            with self.subTest(name=empty):
                self.assertIsNone(pr.lookup(con, "mls", empty))

    def test_a_database_without_the_table_does_not_raise(self):
        """The resolver runs on the serving path; a missing table must degrade, not 500."""
        bare = sqlite3.connect(":memory:")
        bare.row_factory = sqlite3.Row
        self.assertIsNone(pr.lookup(bare, "mls", "Anyone"))


class TheResolverUsesIt(unittest.TestCase):
    """End to end through _core, which is what /api/props/ingest actually calls."""

    def _db(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE unresolved_players(id INTEGER PRIMARY KEY, source TEXT,
                raw_name TEXT, league TEXT, team TEXT, first_seen TEXT, count INT);
            CREATE TABLE name_alias(player_id INT, alias_norm TEXT);
        """)
        pr.ensure(con)
        con.commit()
        return con

    def test_a_published_player_is_created_carrying_their_identity(self):
        import _core
        con = self._db()
        con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES('mls','fotmob','999','Lautaro Giaccone',?,'Columbus','M','Midfielder','now')",
            (pr.fold("Lautaro Giaccone"),))
        con.commit()
        player_id, confidence = _core._resolve_player_for_ingest(
            con, "Lautaro Giaccone", "CLB", "mls", source="bovada")
        self.assertIsNotNone(player_id)
        self.assertEqual(confidence, "high")
        row = con.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        self.assertEqual((row["position"], row["position_group"]), ("M", "Midfielder"))
        self.assertEqual(row["name"], "Lautaro Giaccone",
                         "the row must carry the publisher's spelling")
        self.assertEqual(
            con.execute("SELECT source_player_key FROM player_source_ids WHERE player_id=?",
                        (player_id,)).fetchone()[0], "999")
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM unresolved_players").fetchone()[0], 0)

    def test_the_second_prop_for_that_player_reuses_the_row(self):
        """Otherwise the fix would mint a duplicate on every single prop."""
        import _core
        con = self._db()
        con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES('mls','fotmob','999','Lautaro Giaccone',?,'Columbus','M','Midfielder','now')",
            (pr.fold("Lautaro Giaccone"),))
        con.commit()
        first, _ = _core._resolve_player_for_ingest(con, "Lautaro Giaccone", "CLB", "mls")
        second, _ = _core._resolve_player_for_ingest(con, "Lautaro Giaccone", "CLB", "mls")
        self.assertEqual(first, second)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)

    def test_an_unpublished_name_still_goes_to_the_review_queue(self):
        """The queue keeps its job: only names no publisher confirms."""
        import _core
        con = self._db()
        player_id, _ = _core._resolve_player_for_ingest(
            con, "Nobody Published", "CLB", "mls", source="bovada")
        self.assertIsNone(player_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)
        self.assertEqual(
            con.execute("SELECT raw_name FROM unresolved_players").fetchone()[0],
            "Nobody Published")

    def test_an_ambiguous_published_name_is_queued_not_guessed(self):
        import _core
        con = self._db()
        for key, team, position in (("1", "Chicago", "M"), ("2", "Austin", "D")):
            con.execute(
                "INSERT INTO published_roster(league, source, source_player_key, name, "
                "name_folded, team, position, position_group, updated_at) "
                "VALUES('mls','fotmob',?,'Common Name',?,?,?,'X','now')",
                (key, pr.fold("Common Name"), team, position))
        con.commit()
        player_id, _ = _core._resolve_player_for_ingest(con, "Common Name", None, "mls")
        self.assertIsNone(player_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
