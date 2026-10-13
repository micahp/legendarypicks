#!/usr/bin/env python3
"""A club is a DEFINITION, not a computation.

`publish_identities` fills a blank team and never corrects a wrong one, so a transfer
updated identity and left the club stale: 24 bound players on prod 2026-09-07 disagreed
with the roster their own publisher was serving. Same defect and same argument as
`refresh_mlb_player_teams.py`, minus the request, because the squad is already stored.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import refresh_soccer_player_teams as refresh


def _con():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
            updated_at TEXT);
        CREATE TABLE published_roster(league TEXT, source TEXT, source_player_key TEXT,
            name TEXT, name_folded TEXT, team TEXT, position TEXT, position_group TEXT,
            updated_at TEXT, team_code TEXT, player_id INTEGER);
    """)
    return con


def _player(con, name, team, league="mls"):
    return con.execute("INSERT INTO players(name,team,league) VALUES(?,?,?)",
                       (name, team, league)).lastrowid


def _roster(con, player_id, code, league="mls", source="fotmob"):
    con.execute(
        "INSERT INTO published_roster(league,source,source_player_key,name,name_folded,"
        "team,updated_at,team_code,player_id) VALUES(?,?,?, 'x','x','X','now',?,?)",
        (league, source, "{}-{}".format(source, player_id), code, player_id))


class ItCopiesWhatThePublisherStates(unittest.TestCase):
    def test_a_transfer_is_copied(self):
        con = _con()
        pid = _player(con, "Jacob Jackson", "DAL")
        _roster(con, pid, "SD")
        changes, contested = refresh.plan(con)
        self.assertEqual(changes, [(pid, "Jacob Jackson", "DAL", "SD")])
        self.assertEqual(contested, 0)

    def test_a_blank_team_is_filled(self):
        con = _con()
        pid = _player(con, "New Signing", "")
        _roster(con, pid, "SD")
        self.assertEqual(refresh.plan(con)[0][0][3], "SD")

    def test_an_agreeing_club_is_left_alone(self):
        con = _con()
        pid = _player(con, "Settled Player", "SD")
        _roster(con, pid, "SD")
        self.assertEqual(refresh.plan(con)[0], [])

    def test_two_publishers_agreeing_is_one_change_not_two(self):
        con = _con()
        pid = _player(con, "Doubled Player", "DAL")
        _roster(con, pid, "SD", source="fotmob")
        _roster(con, pid, "SD", source="mlssoccer")
        self.assertEqual(len(refresh.plan(con)[0]), 1)


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def test_publishers_disagreeing_about_the_club_is_skipped(self):
        """A transfer in progress. Answering it by preferring one publisher is a guess."""
        con = _con()
        pid = _player(con, "Mid Transfer", "DAL")
        _roster(con, pid, "SD", source="fotmob")
        _roster(con, pid, "POR", source="mlssoccer")
        changes, contested = refresh.plan(con)
        self.assertEqual(changes, [])
        self.assertEqual(contested, 1)

    def test_a_roster_row_with_no_code_never_blanks_a_team(self):
        con = _con()
        pid = _player(con, "Uncoded", "DAL")
        _roster(con, pid, "")
        self.assertEqual(refresh.plan(con)[0], [])

    def test_an_unbound_roster_row_is_not_evidence(self):
        con = _con()
        _player(con, "Unbound", "DAL")
        con.execute("INSERT INTO published_roster(league,source,source_player_key,name,"
                    "name_folded,team,updated_at,team_code,player_id) "
                    "VALUES('mls','fotmob','k','x','x','X','now','SD',NULL)")
        self.assertEqual(refresh.plan(con)[0], [])

    def test_a_competition_that_owns_nobody_never_restates_a_club(self):
        """A July cup entry must not overwrite a fact that belongs to the league season."""
        con = _con()
        pid = _player(con, "Cup Entrant", "MIN")
        _roster(con, pid, "SD", league="lcup")
        self.assertEqual(refresh.plan(con)[0], [])
        self.assertNotIn("lcup", refresh.LEAGUES)


if __name__ == "__main__":
    unittest.main()
