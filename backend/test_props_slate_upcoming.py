#!/usr/bin/env python3
"""The slate's "still on the board" rule, pinned to instants rather than calendar dates.

The board used to filter `pg.date >= date('now')`. `pg.date` is a UTC calendar date, but the client
groups every game under the LOCAL date it derives from `start_time` -- so a match kicking off at
00:30Z was stored under today, rendered as "yesterday, 7:30 PM", and sat FINISHED at the top of the
board. Two rulers for one board. These tests assert the two properties that fix depends on, so a
future edit that reverts to a date comparison fails here instead of in the reader.
"""

import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="slate-upcoming-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import props  # noqa: E402
from espn_client.scoreboard import _slate_day  # noqa: E402


def _utc_now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class SlateUpcomingFilterTests(unittest.TestCase):
    """Run the real `_UPCOMING` predicate against rows whose times are set relative to now."""

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="slate-upcoming-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = sqlite3.connect(self.path)
        self.addCleanup(self.con.close)
        self.con.execute(
            "CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT,"
            " start_time TEXT, home TEXT, away TEXT)"
        )

    def add(self, gid, offset_hours, start_time=..., date=None):
        """Insert a game starting `offset_hours` from now (negative = already started)."""
        row = self.con.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?),"
            "       date('now', ?)", ("%+d hours" % offset_hours, "%+d hours" % offset_hours)
        ).fetchone()
        st = row[0] if start_time is ... else start_time
        self.con.execute(
            "INSERT INTO prop_games VALUES(?,?,?,?,?,?)",
            (gid, "mls", date or row[1], st, "Home %d" % gid, "Away %d" % gid),
        )

    def kept(self):
        sql = "SELECT id FROM prop_games pg WHERE " + props._UPCOMING + " ORDER BY id"
        return [r[0] for r in self.con.execute(sql)]

    def ordered(self):
        """Game ids in the order the slate serves them."""
        sql = ("SELECT id FROM prop_games pg ORDER BY " + props._KICKOFF
               + ", pg.home, pg.away")
        return [r[0] for r in self.con.execute(sql)]

    def test_the_board_is_ordered_by_kickoff_not_by_the_date_column(self):
        """Two rows can disagree about which calendar day a late kickoff belongs to.

        Measured on prod 2026-08-19: MLS rows written from the sportsbook file a 21:30 ET
        kickoff under the next UTC day, while rows written from the relay file it under
        the local day. Ordering by `pg.date` then put a 9:30pm game above a 7:00pm one.
        The kickoff instant is the same number under either convention.
        """
        # The shape that actually breaks: the LATER kickoff carries the EARLIER date, so
        # ordering by `date` first hoists it above a game that starts before it. Prod
        # 2026-08-19: Houston @ Vancouver, 9:30pm, date 08-19, sorted above St. Louis @
        # Sporting KC, 7:00pm, date 08-20.
        self.add(1, +1, date="2026-08-20")   # 7:00pm, filed under the UTC day
        self.add(2, +2, date="2026-08-19")   # 9:30pm, filed under the local day
        self.assertEqual(self.ordered(), [1, 2],
                         "the earlier kickoff must come first whatever `date` says")

    def test_a_row_with_no_start_time_still_has_a_place_in_the_order(self):
        """17 of 30 MLS rows carried no start_time on 2026-08-19."""
        self.add(1, +2)
        self.add(2, +1, start_time=None)
        self.assertEqual(sorted(self.ordered()), [1, 2])

    def test_finished_game_dated_today_is_dropped(self):
        # 00:30Z today: still `date >= date('now')`, but it kicked off hours ago and is over.
        self.add(1, -16)
        self.add(2, +5)
        self.assertEqual(self.kept(), [2], "a game that finished last night must leave the board")

    def test_game_in_progress_is_kept(self):
        # Inside the grace window -- being played right now, so it stays.
        self.add(1, -1)
        self.assertEqual(self.kept(), [1])

    def test_missing_start_time_survives_its_whole_day(self):
        # 17 of 75 upcoming MLS rows carried no start_time (2026-08-17). A bare start_time
        # comparison would have deleted them from the board with no error anywhere.
        #
        # The dates come from `_slate_day`, not `date('now')`. `pg.date` is the New York
        # slate day and `date('now')` is the UTC date; they disagree for the four hours
        # after 20:00 ET, and this test asserted the UTC answer, so it failed every night
        # from 00:00Z to 03:00Z. It was red for three hours a day and nobody saw it,
        # because the suite is rarely run in that window.
        today = _slate_day("mls", _utc_now_iso())
        yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
        older = (dt.date.fromisoformat(today) - dt.timedelta(days=3)).isoformat()
        self.add(1, 0, start_time=None, date=today)
        self.add(2, 0, start_time="", date=today)
        self.add(3, 0, start_time=None, date=older)
        self.assertEqual(self.kept(), [1, 2], "a timeless row holds for the day it is dated for")
        self.assertNotIn(3, self.kept(), "a timeless row does not hold forever")

    def test_a_timeless_row_lasts_until_its_day_actually_ends(self):
        """The fallback is the end of the NY day, not 19:59 ET on it.

        `pg.date || 'T23:59:59Z'` reads like "end of day" and, once `pg.date`
        became the New York slate day, meant 7:59pm Eastern. A timeless row
        dated today dropped off mid-evening. Fails against that expression.
        """
        today = _slate_day("mls", _utc_now_iso())
        self.add(1, 0, start_time=None, date=today)
        kickoff = self.con.execute(
            "SELECT " + props._KICKOFF + " FROM prop_games pg WHERE id=1").fetchone()[0]
        # Midnight Eastern is 04:00Z (EDT) or 05:00Z (EST); never the same calendar day.
        self.assertGreater(kickoff, today + "T23:59:59",
                           "a timeless row must survive its own evening")

    def test_both_slate_paths_share_one_rule(self):
        # The summary and fully-nested paths are separate queries; a board that filters two ways
        # is a board that disagrees with itself.
        src = open(os.path.join(HERE, "routers", "props.py")).read()
        self.assertEqual(src.count('" AND " + _UPCOMING'), 2)
        # Comments quote the old predicate deliberately (that is the record of why it changed),
        # so check the code lines only.
        code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        self.assertNotIn("pg.date >= date('now')", "\n".join(code))


if __name__ == "__main__":
    unittest.main()
