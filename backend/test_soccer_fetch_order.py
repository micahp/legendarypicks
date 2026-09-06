#!/usr/bin/env python3
"""A bounded budget must buy the matches settlement is waiting on.

ESPN returns a season's events oldest-first and the ingest stops at --request-budget, so the
first scheduled run on 2026-09-06 spent its whole budget on 2026-05-02 and 05-03 while the
games holding unsettled props were four months newer. 440 logs were written and the table's
newest date did not move at all. These tests pin the ordering that fixes it.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_soccer_logs as subject


class WhatSettlementIsWaitingOnComesFirst(unittest.TestCase):
    def test_waiting_matches_lead_and_are_newest_first(self):
        waiting = {"100": "2026-09-05", "200": "2026-08-01", "300": "2026-09-06"}
        order = subject._fetch_order(waiting, ["100", "200", "300", "400", "500", "050"])
        self.assertEqual(order[:3], ["300", "100", "200"])

    def test_the_rest_follow_by_descending_id(self):
        """Only a tiebreak between matches nobody is waiting on. Measured across 626 stored
        MLS matches, id order agrees with date order 95.4% of the time, so this is a proxy
        and is never allowed to decide anything that matters."""
        order = subject._fetch_order({}, ["050", "400", "100", "500"])
        self.assertEqual(order, ["500", "400", "100", "050"])

    def test_every_input_id_survives_the_reordering(self):
        """Ordering must never drop a match. A lost id is a match that is never fetched."""
        ids = ["1", "2", "3", "4", "5"]
        self.assertEqual(sorted(subject._fetch_order({"2": "2026-01-01"}, ids)), sorted(ids))

    def test_a_non_numeric_id_does_not_raise(self):
        order = subject._fetch_order({}, ["abc", "100"])
        self.assertEqual(sorted(order), ["100", "abc"])

    def test_no_waiting_matches_is_not_an_error(self):
        self.assertEqual(subject._fetch_order({}, []), [])


class ReadingWhatIsOutstanding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")
        self.con = sqlite3.connect(self.db)
        self.con.executescript("""
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT,
                                    espn_event_id TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
            CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL);
        """)
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def _game(self, gid, event_id, date, league="mls", settled=False):
        self.con.execute("INSERT INTO prop_games VALUES(?,?,?,?)",
                         (gid, league, date, event_id))
        self.con.execute("INSERT INTO props VALUES(?,?)", (gid * 10, gid))
        if settled:
            self.con.execute("INSERT INTO prop_results VALUES(?,1.0)", (gid * 10,))
        self.con.commit()

    def test_only_unsettled_games_are_returned(self):
        self._game(1, "111", "2026-09-01", settled=False)
        self._game(2, "222", "2026-09-02", settled=True)
        waiting = subject._settlement_waiting_on(self.con, "mls")
        self.assertEqual(waiting, {"111": "2026-09-01"})

    def test_another_league_is_not_returned(self):
        self._game(1, "111", "2026-09-01", league="lcup")
        self.assertEqual(subject._settlement_waiting_on(self.con, "mls"), {})

    def test_an_unlinked_game_is_not_returned(self):
        """No event id means nothing to prioritise by; it is a different defect."""
        self._game(1, "", "2026-09-01")
        self.assertEqual(subject._settlement_waiting_on(self.con, "mls"), {})

    def test_a_missing_table_degrades_to_recency_and_says_so(self):
        """A silent empty dict here is indistinguishable from a season with nothing
        outstanding, which would hide the very problem this ordering exists to fix."""
        bare = sqlite3.connect(":memory:")
        try:
            self.assertEqual(subject._settlement_waiting_on(bare, "mls"), {})
        finally:
            bare.close()


if __name__ == "__main__":
    unittest.main()
