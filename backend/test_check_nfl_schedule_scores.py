"""Tests for check_nfl_schedule_scores.py. Temp DB, fixed clock, no network.

Each assertion was checked against a deliberately wrong implementation (kickoff read as UTC,
no grace window, scored games flagged) so it can fail.
"""
import datetime as dt
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_nfl_schedule_scores as chk  # noqa: E402


def utc(*args):
    return pytz.utc.localize(dt.datetime(*args))


class KickoffTime(unittest.TestCase):
    def test_daylight_time_is_edt(self):
        # 2026-10-08 20:15 Eastern (EDT, UTC-4) is 00:15 UTC on 10-09.
        self.assertEqual(chk.kickoff_utc("2026-10-08", "20:15"), utc(2026, 10, 9, 0, 15))

    def test_standard_time_is_est(self):
        # 2026-11-08 13:00 Eastern (EST, UTC-5) is 18:00 UTC.
        self.assertEqual(chk.kickoff_utc("2026-11-08", "13:00"), utc(2026, 11, 8, 18, 0))

    def test_missing_time_reads_as_end_of_day(self):
        self.assertEqual(chk.kickoff_utc("2026-10-11", None), utc(2026, 10, 12, 3, 59))


class OverdueRule(unittest.TestCase):
    NOW = utc(2026, 10, 11, 12, 0)  # Sunday noon UTC

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "t.db")
        self.con = sqlite3.connect(self.db)
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT, season INT, week INT, gameday TEXT, "
            "gametime TEXT, away_team TEXT, home_team TEXT, away_score INT, home_score INT)")

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def add(self, gid, gameday, gametime, away_s, home_s):
        self.con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?)",
                         (gid, 2026, 5, gameday, gametime, "AAA", "BBB", away_s, home_s))

    def overdue_ids(self):
        _, rows = chk.overdue_unscored(self.con, self.NOW)
        return sorted(r[0] for r in rows)

    def test_unscored_past_grace_is_flagged(self):
        # Thu 2026-10-08 20:15 EDT = 2026-10-09 00:15Z. Now is 2026-10-11 12:00Z, 59.75h later.
        self.add("old_unscored", "2026-10-08", "20:15", None, None)
        self.assertEqual(self.overdue_ids(), ["old_unscored"])

    def test_inside_grace_is_not_flagged(self):
        # Sat 2026-10-10 20:15 EDT = 2026-10-11 00:15Z. Now is 12:00Z, so 11.75h ago: inside 36h.
        self.add("recent_unscored", "2026-10-10", "20:15", None, None)
        self.assertEqual(self.overdue_ids(), [])

    def test_scored_old_game_is_not_flagged(self):
        self.add("old_scored", "2026-10-01", "13:00", 10, 20)
        self.assertEqual(self.overdue_ids(), [])

    def test_future_unscored_is_not_flagged(self):
        self.add("future", "2026-10-18", "13:00", None, None)
        self.assertEqual(self.overdue_ids(), [])

    def test_one_missing_score_is_still_overdue(self):
        self.add("half_scored", "2026-10-08", "20:15", 17, None)
        self.assertEqual(self.overdue_ids(), ["half_scored"])

    def test_missing_time_not_flagged_before_end_of_day_plus_grace(self):
        # Sat 10-10 with no time: read as 23:59 EDT Sat = 10-11 03:59Z, so 8h before now.
        self.add("no_time_recent", "2026-10-10", None, None, None)
        self.assertEqual(self.overdue_ids(), [])

    def test_counts_every_row_checked(self):
        self.add("a", "2026-10-01", "13:00", 1, 2)
        self.add("b", "2026-10-08", "20:15", None, None)
        checked, rows = chk.overdue_unscored(self.con, self.NOW)
        self.assertEqual(checked, 2)
        self.assertEqual([r[0] for r in rows], ["b"])


class ExitCodes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE nfl_schedule (game_id TEXT, season INT, week INT, gameday TEXT, "
                    "gametime TEXT, away_team TEXT, home_team TEXT, away_score INT, home_score INT)")
        con.commit()
        con.close()
        self._orig = chk.DB
        chk.DB = self.db

    def tearDown(self):
        chk.DB = self._orig
        self._tmp.cleanup()

    def run_main(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = chk.main([])
        return code, buf.getvalue()

    def test_clean_db_exits_zero_and_says_zero(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("0 overdue unscored", out)

    def test_overdue_exits_one_with_alert(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO nfl_schedule VALUES "
                    "('g1', 2026, 5, '2026-10-01', '13:00', 'AAA', 'BBB', NULL, NULL)")
        con.commit()
        con.close()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("ALERT nfl_schedule unscored: g1", out)

    def test_missing_db_exits_one(self):
        chk.DB = os.path.join(self._tmp.name, "nope.db")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("ALERT database missing", out)


if __name__ == "__main__":
    unittest.main()
