#!/usr/bin/env python3
"""link_prop_games must pace its fan-out.

Measured 2026-08-24 21:00 UTC, this job fired 18 requests inside one minute alongside
settle_props' 44 and ingest_scoreboards' 30. site.web.api.espn.com refused for minutes
and 13 of the refusals landed on UVICORN, so a batch job spent the budget the live page
loads needed. It had inherited espn_client's serving-path default of min_interval=0,
because its own docstring taught the superseded model that pacing buys nothing.
"""
import os
import sqlite3
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import espn_client as espn
import link_prop_games as lpg


def _current_min_interval():
    prev = espn.set_min_interval(0)
    espn.set_min_interval(prev)
    return prev


class LinkPropGamesPacingTests(unittest.TestCase):
    def _con(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(
            """
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY AUTOINCREMENT,
              league TEXT NOT NULL, date TEXT NOT NULL, home TEXT, away TEXT,
              espn_event_id TEXT, final_home INTEGER, final_away INTEGER,
              start_time TEXT);
            """
        )
        con.execute(
            "INSERT INTO prop_games(league, date, home, away) VALUES('mlb','2026-08-01','A','B')")
        con.commit()
        return con

    def test_the_fan_out_is_paced_while_it_fetches(self):
        seen = []

        def _record(*_args, **_kwargs):
            seen.append(_current_min_interval())
            return []

        before = _current_min_interval()
        with mock.patch.object(lpg.espn, "games", side_effect=_record):
            lpg.link_existing_games(self._con(), dry_run=True, league="mlb")

        self.assertTrue(seen, "the fan-out never fetched, so this proves nothing")
        self.assertGreaterEqual(min(seen), 1.0, "the link fan-out ran unpaced")
        self.assertEqual(before, _current_min_interval(), "pacing leaked out of the run")

    def test_pacing_is_restored_when_the_run_raises(self):
        """The fetcher is process-global. A run that leaves it paced would slow every
        later caller, including the serving path.

        The raise is injected at `_scope`, not at the fetch: the per-day loop catches
        fetch errors on purpose, so a fetch that raises would never reach the caller and
        would prove nothing about unwinding."""
        before = _current_min_interval()
        with mock.patch.object(lpg, "_scope", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                lpg.link_existing_games(self._con(), dry_run=True, league="mlb")
        self.assertEqual(before, _current_min_interval())

    def test_the_docstring_no_longer_teaches_the_superseded_count_model(self):
        """The stale doctrine IS the defect: this function was left unpaced because its
        own docstring said pacing buys nothing. A comment that states a superseded
        measurement as current fact is a bug with a long fuse."""
        doc = lpg.link_existing_games.__doc__ or ""
        # The superseded claim is kept, quoted, with what replaced it. Deleting it would
        # lose why this function was unpaced for weeks; stating it unqualified is the bug.
        self.assertIn("was wrong", doc)
        self.assertIn("FLAT", doc)
        self.assertIn("min_interval=0", doc)


if __name__ == "__main__":
    unittest.main()
