#!/usr/bin/env python3
"""A live game page answers from the DATABASE, not from a publisher.

Reported 2026-08-26 on Leagues Cup 401911270: the game page showed no score and
no clock while the scoreboard snapshot in our own database said America 2 - 0
Columbus at Halftime, with period, clock and status_detail all present.

Three separate reasons, all of them "ask ESPN for something already stored":

  1. `_state_and_score_from_snapshot` extracted the score only when the state was
     'post', so a live game's score was read and thrown away.
  2. The live branch fetched from ESPN with the comment "the live score is not
     persisted" -- it is -- inside a bare `except Exception: pass`, so a 403 or a
     slow host produced NO SCORE rather than an error.
  3. The boxscore fallback then overwrote whatever was there with its own fetch,
     unconditionally.

Net effect: TWO publisher requests per page load, on the serving path, for
values on disk. Now zero.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="detail-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import _core  # noqa: E402
from routers.games import game_detail as gd  # noqa: E402


def _payload():
    return json.dumps({
        "game_id": "401911270", "date": "2026-08-27T02:45Z", "state": "in",
        "status": "Halftime", "status_detail": "HT", "period": 1, "clock": "45'+7'",
        "home": {"abbrev": "AME", "name": "América", "score": 2.0, "winner": False},
        "away": {"abbrev": "CLB", "name": "Columbus Crew", "score": 0.0, "winner": False},
    })


class ALiveGamePageAsksNoPublisher(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="detail-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        # Let _core build the schema. Hand-writing it here declares a fixture's
        # own version of a shipped table, which is the drift that had earlier
        # fixtures in this repo describing tables the code does not have -- the
        # first version of this test created only `scoreboard_snapshots` and died
        # on "no such table: team_game_stats".
        import importlib
        previous = os.environ.get("LP_DB_PATH")

        def restore():
            if previous is None:
                os.environ.pop("LP_DB_PATH", None)
            else:
                os.environ["LP_DB_PATH"] = previous
            importlib.reload(_core)

        self.addCleanup(restore)
        os.environ["LP_DB_PATH"] = self.path
        importlib.reload(_core)

        # `scoreboard_snapshots` is owned by the scoreboard ingest, not by
        # _init_db, so its DDL comes from that module rather than a copy here.
        import scoreboard_store
        con = _core._db()
        con.executescript(scoreboard_store.SCHEMA)
        con.execute("INSERT INTO scoreboard_snapshots"
                    "(league, game_date, game_id, payload, state, start_time,"
                    " fetched_at, source)"
                    " VALUES('lcup','2026-08-26','401911270',?,'in',"
                    "'2026-08-27T02:45Z','2026-08-27T03:30Z','espn')",
                    (_payload(),))
        con.commit()
        con.close()

        self.calls = []

        def refuse(*args, **kwargs):
            self.calls.append(args)
            raise AssertionError("the serving path asked a publisher")

        espn_patch = mock.patch.object(gd.espn, "game_result", side_effect=refuse)
        espn_patch.start()
        self.addCleanup(espn_patch.stop)

    def test_the_live_score_comes_from_the_snapshot(self):
        out = gd.get_game_detail("lcup", "401911270")
        self.assertEqual(out["live_score"], {"home": 2, "away": 0})
        self.assertIsNone(out["final_score"], "a live game has no final score")

    def test_state_clock_and_status_come_from_the_snapshot(self):
        out = gd.get_game_detail("lcup", "401911270")
        self.assertEqual(out["state"], "in")
        self.assertEqual(out["period"], 1)
        self.assertEqual(out["clock"], "45'+7'")
        self.assertEqual(out["status_detail"], "HT")

    def test_the_teams_come_from_the_snapshot(self):
        """`context` used to exist only as a by-product of the ESPN fallback, so
        a page cost a request purely to learn who was playing."""
        out = gd.get_game_detail("lcup", "401911270")
        self.assertEqual(out["context"]["home_team"], "América")
        self.assertEqual(out["context"]["away_team"], "Columbus Crew")

    def test_no_publisher_request_is_made_at_all(self):
        gd.get_game_detail("lcup", "401911270")
        self.assertEqual(self.calls, [], "a stored game must need no publisher")


if __name__ == "__main__":
    unittest.main()
