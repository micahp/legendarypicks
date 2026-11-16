"""The health check reads the identity blockers the last published-rosters run recorded."""
import sqlite3
import unittest

import identity_status


def _runs(*rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ingest_runs (id INTEGER PRIMARY KEY, provider TEXT, finished_at TEXT, detail TEXT)")
    con.executemany("INSERT INTO ingest_runs(provider, finished_at, detail) VALUES (?,?,?)", rows)
    return con


class LastRunTests(unittest.TestCase):
    def test_the_latest_published_rosters_run_gives_the_count_and_when_it_ran(self):
        con = _runs(
            ("published_rosters", "2026-10-27T01:39:40+00:00", "UNDECIDED: 0 ambiguous\n  identity_blockers=5\n"),
            ("published_rosters", "2026-10-27T02:09:13+00:00", "UNDECIDED: 0 ambiguous\n  identity_blockers=4\n"),
        )
        self.assertEqual(identity_status.last_run(con), (4, "2026-10-27T02:09:13+00:00"))

    def test_no_recorded_run_gives_nothing(self):
        con = _runs(("mlb_schedule", "2026-10-27T02:09:13+00:00", "identity_blockers=9\n"))
        self.assertEqual(identity_status.last_run(con), (None, None))

    def test_a_latest_run_that_printed_no_count_says_when_it_ran_and_no_count(self):
        con = _runs(
            ("published_rosters", "2026-10-27T01:00:00+00:00", "identity_blockers=2\n"),
            ("published_rosters", "2026-10-27T02:00:00+00:00", "Traceback (most recent call last):\n"),
        )
        self.assertEqual(identity_status.last_run(con), (None, "2026-10-27T02:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
