#!/usr/bin/env python3
"""A club's code learned from its squad, because names do not bridge publishers.

`league_clubs` holds both halves of the crosswalk already, FotMob names against numeric
ids and ESPN names against short codes, and joining them on the NAME reaches 2 of 11 Liga
MX clubs: ESPN files `Rayados`, `Panzas Verdes`, `La Franja`. The squad reaches all 18.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import club_crosswalk as cc


def _con():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT);
        CREATE TABLE published_roster(league TEXT, source TEXT, source_player_key TEXT,
            name TEXT, name_folded TEXT, team TEXT, position TEXT, position_group TEXT,
            updated_at TEXT, team_code TEXT, player_id INTEGER);
    """)
    return con


def _squad(con, league, club, code, count, league_of_player=None):
    """`count` people published at `club` who already carry `code` in the spine."""
    for index in range(count):
        name = "{}{}{}".format(club, code, index)
        pid = con.execute("INSERT INTO players(name,team,league) VALUES(?,?,?)",
                          (name, code, league_of_player or league)).lastrowid
        con.execute(
            "INSERT INTO published_roster(league,source,source_player_key,name,name_folded,"
            "team,updated_at,player_id) VALUES(?,?,?,?,?,?,'now',?)",
            (league, "fotmob", "{}-{}".format(code, index), name, name, club, pid))


class ItLearnsFromTheSquad(unittest.TestCase):
    def test_a_club_is_identified_by_who_plays_for_it(self):
        con = _con()
        _squad(con, "ligamx", "Chivas", "GDL", 19)
        self.assertEqual(cc.resolve("Chivas", "ligamx", cc.learn(con)), "GDL")

    def test_a_nickname_no_name_join_could_bridge(self):
        """ESPN files Pumas UNAM as UNAM; FotMob publishes `Pumas`. Folding never bridges
        `Rayados` to `Monterrey`, and the squad does not care."""
        con = _con()
        _squad(con, "ligamx", "Monterrey", "MTY", 24)
        self.assertEqual(cc.resolve("Monterrey", "ligamx", cc.learn(con)), "MTY")

    def test_the_static_map_still_wins_where_it_has_an_answer(self):
        """It is the publisher's committed vocabulary and does not depend on db state."""
        con = _con()
        _squad(con, "mls", "San Diego FC", "WRONG", 20)
        self.assertEqual(cc.resolve("San Diego FC", "mls", cc.learn(con)), "SD")

    def test_a_club_it_cannot_learn_returns_unknown_not_a_guess(self):
        self.assertEqual(cc.resolve("Some New Club", "ligamx", {}), "")

    def test_an_empty_database_teaches_nothing_and_does_not_raise(self):
        self.assertEqual(cc.learn(_con()), {})

    def test_a_database_without_the_tables_degrades(self):
        self.assertEqual(cc.learn(sqlite3.connect(":memory:")), {})


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def test_too_few_bound_players_teaches_nothing(self):
        """Two people cannot mint a club code; one mis-bound row would be half the vote."""
        con = _con()
        _squad(con, "ligamx", "Tijuana", "TIJ", cc.MIN_OVERLAP - 1)
        self.assertEqual(cc.resolve("Tijuana", "ligamx", cc.learn(con)), "")

    def test_a_split_squad_teaches_nothing(self):
        """Half at one code and half at another means the bindings are wrong, not that
        one of the two codes is right."""
        con = _con()
        _squad(con, "ligamx", "Split Club", "AAA", 10)
        _squad(con, "ligamx", "Split Club", "BBB", 10)
        self.assertEqual(cc.resolve("Split Club", "ligamx", cc.learn(con)), "")

    def test_one_code_naming_two_clubs_in_one_league_teaches_neither(self):
        con = _con()
        _squad(con, "ligamx", "Club One", "DUP", 12)
        _squad(con, "ligamx", "Club Two", "DUP", 12)
        learned = cc.learn(con)
        self.assertEqual(cc.resolve("Club One", "ligamx", learned), "")
        self.assertEqual(cc.resolve("Club Two", "ligamx", learned), "")


class OneClubIsTheSameClubEverywhere(unittest.TestCase):
    def test_leagues_cup_inherits_what_the_home_leagues_teach(self):
        """Leagues Cup had ZERO bound players on prod, and all 36 of its clubs are MLS or
        Liga MX clubs. Learning per league only would have left it unreachable forever."""
        con = _con()
        _squad(con, "ligamx", "Tijuana", "TIJ", 18)
        learned = cc.learn(con)
        self.assertEqual(cc.resolve("Tijuana", "lcup", learned), "TIJ")

    def test_two_leagues_may_each_keep_their_own_meaning_of_one_code(self):
        """ATL is Atlanta United in MLS and Atlante in Liga MX. Both are correct, and
        judging uniqueness globally threw away both."""
        con = _con()
        _squad(con, "mls", "Atlanta United", "ATL", 25)
        _squad(con, "ligamx", "Atlante", "ATL", 27)
        learned = cc.learn(con)
        self.assertEqual(cc.resolve("Atlante", "ligamx", learned), "ATL")
        self.assertEqual(cc.resolve("Atlanta United", "mls", learned), "ATL")

    def test_but_the_shared_competition_refuses_the_ambiguous_one(self):
        """In Leagues Cup, where both clubs play, ATL does not identify either."""
        con = _con()
        _squad(con, "mls", "Atlanta United", "ATL", 25)
        _squad(con, "ligamx", "Atlante", "ATL", 27)
        self.assertEqual(cc.resolve("Atlante", "lcup", cc.learn(con)), "")


class IndividualSportsNeverTeach(unittest.TestCase):
    def test_ufc_team_is_the_opponent_and_must_not_become_a_club_code(self):
        """`ingest_ufc_fight_stats/roster.py` reuses `team` to carry the opponent. On prod
        242 of 248 UFC team values are another fighter's name, 232 reciprocal."""
        con = _con()
        _squad(con, "ufc", "Some Card", "Mike Davis", 12)
        self.assertEqual(cc.learn(con), {})


if __name__ == "__main__":
    unittest.main()


class ACompetitionDoesNotOwnItsPlayers(unittest.TestCase):
    """The crosswalk is what makes this dangerous, so the guard belongs beside it.

    Before `club_crosswalk`, every Leagues Cup roster row failed on `missing_team` and no
    identity was ever created for it. Filling `team_code` removes that accidental
    protection: measured on a clone of prod 2026-09-07, publishing lcup identities then
    inserted 1,004 players of whom 997 already existed in mls or ligamx.
    """

    def setUp(self):
        import published_roster as pr
        self.pr = pr
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT,
                league TEXT, team TEXT, game_date TEXT);
        """)
        pr.ensure(self.con)

    def _publish(self, league):
        self.con.execute(
            "INSERT INTO published_roster(league,source,source_player_key,name,name_folded,"
            "team,position,position_group,updated_at,team_code) "
            "VALUES(?, 'fotmob','F1','Elias Achouri',?, 'San Diego FC','M','Midfielder',"
            "'now','SD')", (league, self.pr.fold("Elias Achouri")))
        return self.pr.publish_identities(self.con, league, "now")

    def test_leagues_cup_refuses_to_create_a_person(self):
        stats = self._publish("lcup")
        self.assertEqual(stats["owned_elsewhere"], 1)
        self.assertEqual(stats.get("inserted", 0), 0)
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)

    def test_a_home_league_still_creates_normally(self):
        stats = self._publish("mls")
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats.get("owned_elsewhere", 0), 0)


class ACompetitionBorrowsItsPeople(unittest.TestCase):
    """Leagues Cup binds to the person who already owns that publisher id.

    FotMob does not renumber a player because he entered a second competition, so this is
    an exact join on the publisher's own id with no name matching. Measured on prod
    2026-09-07: all 1,035 lcup roster rows share a FotMob id with an mls or ligamx row.
    """

    def setUp(self):
        import published_roster as pr
        self.pr = pr
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT,
                league TEXT, team TEXT, game_date TEXT);
        """)
        pr.ensure(self.con)

    def _home_player(self, name, league, team, key="F1"):
        pid = self.con.execute(
            "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
            "VALUES(?,?,?,'M','Midfielder',1,'old')", (name, team, league)).lastrowid
        self.con.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,player_id,"
            "first_seen,last_seen) VALUES('fotmob',?,?,?,'old','old')", (league, key, pid))
        return pid

    def _cup_row(self, name, key="F1", club="Minnesota United", code="MIN"):
        self.con.execute(
            "INSERT INTO published_roster(league,source,source_player_key,name,name_folded,"
            "team,position,position_group,updated_at,team_code) "
            "VALUES('lcup','fotmob',?,?,?,?,'M','Midfielder','now',?)",
            (key, name, self.pr.fold(name), club, code))

    def test_it_binds_to_the_home_league_person_and_creates_nobody(self):
        pid = self._home_player("Elias Achouri", "mls", "SD")
        self._cup_row("Elias Achouri")
        stats = self.pr.publish_identities(self.con, "lcup", "now")
        self.assertEqual(stats["bound_from_home_league"], 1)
        self.assertEqual(stats.get("inserted", 0), 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
        self.assertEqual(self.con.execute(
            "SELECT player_id FROM published_roster WHERE league='lcup'").fetchone()[0], pid)

    def test_the_publisher_id_wins_over_the_spelling(self):
        """All three publisher rows said `Darius Randell` while players.name said
        `Alisa Randell`. The id is the identity; the stored name being wrong is a separate
        defect and must not stop the binding."""
        pid = self._home_player("Alisa Randell", "mls", "MIN")
        self._cup_row("Darius Randell")
        self.pr.publish_identities(self.con, "lcup", "now")
        self.assertEqual(self.con.execute(
            "SELECT player_id FROM published_roster WHERE league='lcup'").fetchone()[0], pid)

    def test_it_does_not_restate_their_club_or_reactivate_them(self):
        """Their club is a fact about their home league; a cup entry must not overwrite it."""
        pid = self._home_player("Someone Else", "ligamx", "TIJ")
        self.con.execute("UPDATE players SET active=0 WHERE id=?", (pid,))
        self._cup_row("Someone Else")
        self.pr.publish_identities(self.con, "lcup", "now")
        row = self.con.execute("SELECT team, active FROM players WHERE id=?", (pid,)).fetchone()
        self.assertEqual(row["team"], "TIJ")
        self.assertEqual(row["active"], 0)

    def test_a_second_run_changes_nothing(self):
        """The first version bound 1,035 rows then refused all 1,035 as conflicts, because
        the owner arrived through source_owners and a league-scoped existence check cannot
        see a person who lives in another league."""
        self._home_player("Elias Achouri", "mls", "SD")
        self._cup_row("Elias Achouri")
        self.pr.publish_identities(self.con, "lcup", "now")
        stats = self.pr.publish_identities(self.con, "lcup", "later")
        self.assertEqual(stats.get("conflicts", 0), 0)
        self.assertEqual(stats.get("inserted", 0), 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)

    def test_an_id_owned_by_two_people_is_refused(self):
        self._home_player("Twin One", "mls", "SD", key="F1")
        self._home_player("Twin Two", "ligamx", "TIJ", key="F1")
        self._cup_row("Twin One")
        stats = self.pr.publish_identities(self.con, "lcup", "now")
        self.assertEqual(stats.get("bound_from_home_league", 0), 0)
        self.assertEqual(stats["owned_elsewhere"], 1)

    def test_an_id_nobody_owns_is_still_refused_not_created(self):
        self._cup_row("Unknown Person", key="NOBODY")
        stats = self.pr.publish_identities(self.con, "lcup", "now")
        self.assertEqual(stats["owned_elsewhere"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)

    def test_the_request_path_returns_the_borrowed_identity(self):
        """lookup_player joined p.league = r.league, which would have hidden every
        identity this binds."""
        pid = self._home_player("Elias Achouri", "mls", "SD")
        self._cup_row("Elias Achouri")
        self.pr.publish_identities(self.con, "lcup", "now")
        self.assertEqual(self.pr.lookup_player(self.con, "lcup", "Elias Achouri"), pid)
