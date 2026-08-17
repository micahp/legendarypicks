#!/usr/bin/env python3
"""The start_time write policy: overwrite only when the publisher disagrees.

Set by Micah 2026-08-17, replacing write-once. Write-once froze the first instant we ever
saw, so a publisher revising first pitch could never propagate -- ~20 of prod's 95
disagreements. The two properties that make the replacement safe rather than merely
different are asserted here: a same-instant re-scrape must NOT write (or every 30-minute
timer rewrites the row and "what changed?" becomes unanswerable), and a real disagreement
MUST write.
"""

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from link_prop_games import apply_start_time  # noqa: E402


class ApplyStartTimeTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.execute("CREATE TABLE prop_games(id INTEGER PRIMARY KEY, start_time TEXT)")
        self.con.execute("INSERT INTO prop_games VALUES(1, NULL)")

    def stored(self):
        return self.con.execute("SELECT start_time FROM prop_games WHERE id=1").fetchone()[0]

    def set_stored(self, value):
        self.con.execute("UPDATE prop_games SET start_time=? WHERE id=1", (value,))

    def test_backfills_when_we_have_nothing(self):
        self.assertEqual(apply_start_time(self.con, 1, "2026-08-11T01:40:00+00:00", None), "set")
        self.assertEqual(self.stored(), "2026-08-11T01:40:00+00:00")

    def test_publisher_silence_never_blanks_a_known_instant(self):
        self.set_stored("2026-08-11T01:40:00+00:00")
        self.assertEqual(apply_start_time(self.con, 1, None, "2026-08-11T01:40:00+00:00"), "skipped")
        self.assertEqual(self.stored(), "2026-08-11T01:40:00+00:00")

    def test_same_instant_in_a_different_format_is_not_a_change(self):
        # prop_games writes `+00:00`; ESPN sends `Z`. Comparing strings would rewrite this
        # row on every scrape -- last-writer-wins wearing a disguise.
        self.set_stored("2026-08-11T01:40:00+00:00")
        self.assertEqual(apply_start_time(self.con, 1, "2026-08-11T01:40Z",
                                          "2026-08-11T01:40:00+00:00"), "same")
        self.assertEqual(self.stored(), "2026-08-11T01:40:00+00:00")

    def test_a_real_disagreement_overwrites(self):
        # The +17h/+19h class: the publisher moved first pitch and write-once ignored it.
        self.set_stored("2026-08-11T01:40:00+00:00")
        self.assertEqual(apply_start_time(self.con, 1, "2026-08-11T18:40:00+00:00",
                                          "2026-08-11T01:40:00+00:00"), "moved")
        self.assertEqual(self.stored(), "2026-08-11T18:40:00+00:00")

    def test_write_once_is_actually_gone_from_every_ingest_path(self):
        # Three call sites had the identical `if published and not stored` guard. One left
        # behind is one league that still cannot follow a reschedule.
        for name in ("bovada_scraper.py", os.path.join("routers", "props.py")):
            src = open(os.path.join(HERE, name)).read()
            code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
            self.assertNotIn("not game_row[\"start_time\"]", code, name)
            self.assertNotIn("not row[\"start_time\"]", code, name)
            self.assertIn("apply_start_time", code, name)


if __name__ == "__main__":
    unittest.main()
