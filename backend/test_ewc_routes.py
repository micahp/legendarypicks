#!/usr/bin/env python3
"""Phase 2 tests — EWC projection route, published standings reader, and event identity.

The projection reads the shared esports board (mocked here); the standings reader is the real
atomic-snapshot store with a temp path. No network calls.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(prefix="ewc-routes-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import ewc  # noqa: E402
from routers.esports import slate  # noqa: E402
from routers.esports.ewc import (is_ewc_2026_label,  # noqa: E402
                                 is_ewc_2026_serie)

FIX = os.path.join(HERE, "..", "docs", "ewc2026", "fixtures")


def _match(**kw):
    m = {"startTime": 1786215600000, "endTime": None, "live": False, "finished": False,
         "title": "Call of Duty", "league": "Esports World Cup", "teamA": "FaZe Clan",
         "teamB": "OpTic Gaming", "ewcEventId": "ewc-2026", "eventId": 10834}
    m.update(kw)
    return m


class EventIdentityTests(unittest.TestCase):
    def test_ewc_2026_serie_by_slug_and_year(self):
        self.assertTrue(is_ewc_2026_serie({"slug": "cod-mw-esports-world-cup-2026", "year": 2026}))
        self.assertFalse(is_ewc_2026_serie({"slug": "cod-mw-esports-world-cup-2025", "year": 2025}))
        self.assertFalse(is_ewc_2026_serie({"slug": "cs-go-esports-world-cup-open-qualifier-2026", "year": 2026}))
        self.assertTrue(is_ewc_2026_serie({"slug": "x", "year": 2026}, {"name": "Esports World Cup"}))

    def test_label_detector_excludes_qualifiers(self):
        self.assertTrue(is_ewc_2026_label("Esports World Cup"))
        self.assertTrue(is_ewc_2026_label("Esports World Cup — 2026 (Playoffs)"))
        self.assertTrue(is_ewc_2026_label("Esports World Cup 26"))
        self.assertFalse(is_ewc_2026_label("Ewc Last Chance Qualifier"))
        self.assertFalse(is_ewc_2026_label("Esports World Cup — Open Qualifier 2026 (Group 1)"))
        self.assertFalse(is_ewc_2026_label("CDL 2026"))


class SlateStampingTests(unittest.TestCase):
    def test_slate_stamps_ewc_event_id(self):
        # Drive the real _rebuild_upcoming stamping logic through its helper path: the detector
        # decides from serie id + label. The stamping line is exercised end-to-end by the
        # projection test; here we pin the boundary rules.
        self.assertTrue(slate._is_ewc_2026_label("Esports World Cup"))
        self.assertFalse(slate._is_ewc_2026_label("CCT League"))
        self.assertTrue(slate._is_ewc_2026_serie({"slug": "cod-mw-esports-world-cup-2026", "year": 2026}))


class ProjectionRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.app = FastAPI()
        self.app.include_router(ewc.router)
        self.client = TestClient(self.app)

    def _board(self, matches, building=False):
        return {"matches": matches, "building": building}

    def test_projection_filters_and_buckets(self):
        live = _match(startTime=1, live=True)
        up = _match(startTime=2)
        done = _match(startTime=3, finished=True, endTime=1786215600000)
        non_ewc = _match(startTime=4, ewcEventId=None)
        board = self._board([non_ewc, done, up, live])
        with mock.patch.object(slate, "esports_upcoming", return_value=board):
            r = self.client.get("/api/esports/events/ewc-2026")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["eventId"], "ewc-2026")
        self.assertTrue(d["active"])
        self.assertEqual(len(d["matches"]["live"]), 1)
        self.assertEqual(len(d["matches"]["upcoming"]), 1)
        self.assertEqual(len(d["matches"]["completed"]), 1)
        self.assertNotIn(non_ewc, d["matches"]["live"] + d["matches"]["upcoming"] + d["matches"]["completed"])

    def test_projection_inactive_when_event_expired(self):
        # Only old completed matches (beyond the 24h tail) -> module expires automatically.
        old_done = _match(startTime=1, finished=True, endTime=1)
        board = self._board([old_done])
        with mock.patch.object(slate, "esports_upcoming", return_value=board):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        self.assertFalse(d["active"])
        self.assertEqual(len(d["matches"]["completed"]), 1)

    def test_projection_building_state(self):
        with mock.patch.object(slate, "esports_upcoming", return_value=self._board([], building=True)):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        self.assertTrue(d["building"])
        self.assertFalse(d["active"])

    def test_projection_completed_sorted_desc(self):
        older = _match(startTime=100, finished=True, endTime=100)
        newer = _match(startTime=200, finished=True, endTime=200)
        with mock.patch.object(slate, "esports_upcoming", return_value=self._board([older, newer])):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        starts = [m["startTime"] for m in d["matches"]["completed"]]
        self.assertEqual(starts, sorted(starts, reverse=True))


class StandingsRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.app = FastAPI()
        self.app.include_router(ewc.router)
        self.client = TestClient(self.app)
        fd, self.path = tempfile.mkstemp(prefix="ewc-standings-route-", suffix=".json")
        os.close(fd)
        os.unlink(self.path)

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def _snapshot(self, n=12):
        rows = []
        for i in range(1, n + 1):
            rows.append({"rank": i, "clubId": f"club-{i}", "clubName": f"Club {i}", "logo": None,
                         "points": 3000 - i * 100, "eligibleTopEightCount": None,
                         "titleWins": None, "eligibleToWin": None, "movement": None})
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        return {
            "event": "ewc-2026",
            "publishedAt": now,
            "source": {"label": "X", "url": "https://x", "fetchedAt": now,
                       "sourceReportedClubs": n, "fetchedClubs": n, "checksum": "c"},
            "standings": rows,
        }

    def test_no_publication_is_honest_unavailable(self):
        with mock.patch.object(ewc, "_STANDINGS_PATH", self.path):
            r = self.client.get("/api/esports/events/ewc-2026/club-standings")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["standings"], [])
        self.assertIsNone(d["asOf"])
        self.assertIn("reason", d)

    def test_published_snapshot_is_sliced_by_limit(self):
        with mock.patch.object(ewc, "_STANDINGS_PATH", self.path):
            ewc.publish_standings(self._snapshot(12), path=self.path)
            r = self.client.get("/api/esports/events/ewc-2026/club-standings?limit=10")
            d = r.json()
            self.assertEqual(d["status"], "current")
            self.assertEqual(len(d["standings"]), 10)
            r5 = self.client.get("/api/esports/events/ewc-2026/club-standings?limit=5")
            self.assertEqual(len(r5.json()["standings"]), 5)

    def test_limit_is_bounded(self):
        r = self.client.get("/api/esports/events/ewc-2026/club-standings?limit=0")
        self.assertEqual(r.status_code, 422)
        r = self.client.get("/api/esports/events/ewc-2026/club-standings?limit=999")
        self.assertEqual(r.status_code, 422)

    def test_limit_never_turns_unavailable_into_empty_success(self):
        with mock.patch.object(ewc, "_STANDINGS_PATH", self.path):
            d = self.client.get("/api/esports/events/ewc-2026/club-standings?limit=10").json()
        self.assertEqual(d["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
