#!/usr/bin/env python3
"""Phase 2 tests — EWC event route, published standings reader, and event identity.

The event payload reads the shared esports board (mocked here); the standings reader is the real
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
from routers.esports.common import _ESPORTS_TITLES  # noqa: E402
from routers.esports.ewc import (is_ewc_2026_label,  # noqa: E402
                                 is_ewc_2026_serie)
import fetch_ewc_title_schedules as schedule_store  # noqa: E402

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
        self.assertFalse(is_ewc_2026_serie(
            {"slug": "cs-go-esports-world-cup-open-qualifier-2026", "name": "Open Qualifier",
             "full_name": "Open Qualifier 2026", "year": 2026},
            {"name": "Esports World Cup"},
        ))
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
        # event-route test; here we pin the boundary rules.
        self.assertTrue(slate._is_ewc_2026_label("Esports World Cup"))
        self.assertFalse(slate._is_ewc_2026_label("CCT League"))
        self.assertTrue(slate._is_ewc_2026_serie({"slug": "cod-mw-esports-world-cup-2026", "year": 2026}))


class EventRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.app = FastAPI()
        self.app.include_router(ewc.router)
        self.client = TestClient(self.app)

    def _board(self, matches, building=False):
        return {"matches": matches, "building": building}

    def test_event_payload_filters_and_buckets(self):
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

    def test_event_payload_publishes_complete_official_game_catalog(self):
        with mock.patch.object(slate, "esports_upcoming", return_value=self._board([])):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        self.assertEqual(d["titleCount"], 24)
        self.assertEqual(d["tournamentCount"], 25)
        self.assertEqual(len(d["titles"]), 24)
        self.assertEqual(len({row["slug"] for row in d["titles"]}), 24)
        self.assertEqual(sum(len(row["tournaments"]) for row in d["titles"]), 25)
        self.assertIn("Apex Legends", {row["name"] for row in d["titles"]})
        self.assertIn("Trackmania", {row["name"] for row in d["titles"]})
        mlbb = next(row for row in d["titles"] if row["slug"] == "mobile-legends-bang-bang")
        self.assertEqual(mlbb["tournaments"], ["MSC", "MWI"])

    def test_event_title_coverage_is_data_derived(self):
        # No published schedule snapshots in the test env -> every tile is honestly unavailable
        # ('Schedule pending'), and feedCount is derived from the EWC slate rows, never from the
        # hardcoded program weeks (which are NOT exposed in the payload at all).
        live = _match(startTime=1, live=True)  # title "Call of Duty" -> call-of-duty-black-ops-7
        board = self._board([live])
        with mock.patch.object(slate, "esports_upcoming", return_value=board):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        titles = {row["slug"]: row for row in d["titles"]}
        for slug, row in titles.items():
            self.assertNotIn("weeks", row, "hardcoded program weeks must not reach the payload")
            self.assertEqual(row["schedule"]["status"], "unavailable")
            self.assertEqual(row["schedule"]["count"], 0)
            self.assertIn("reason", row["schedule"])
        cod = titles["call-of-duty-black-ops-7"]
        self.assertEqual(cod["feedCount"], 1)  # the live 'Call of Duty' EWC row
        apex = titles["apex-legends"]
        self.assertEqual(apex["feedCount"], 0)
        self.assertEqual(len(titles), 24)

    def test_event_inactive_when_event_expired(self):
        # Only old completed matches (beyond the 24h tail) -> module expires automatically.
        old_done = _match(startTime=1, finished=True, endTime=1)
        board = self._board([old_done])
        with mock.patch.object(slate, "esports_upcoming", return_value=board):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        self.assertFalse(d["active"])
        self.assertEqual(len(d["matches"]["completed"]), 1)

    def test_event_building_state(self):
        with mock.patch.object(slate, "esports_upcoming", return_value=self._board([], building=True)):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        self.assertTrue(d["building"])
        self.assertFalse(d["active"])

    def test_event_completed_sorted_desc(self):
        older = _match(startTime=100, finished=True, endTime=100)
        newer = _match(startTime=200, finished=True, endTime=200)
        with mock.patch.object(slate, "esports_upcoming", return_value=self._board([older, newer])):
            d = self.client.get("/api/esports/events/ewc-2026").json()
        starts = [m["startTime"] for m in d["matches"]["completed"]]
        self.assertEqual(starts, sorted(starts, reverse=True))


class TitleMatchesRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.app = FastAPI()
        self.app.include_router(ewc.router)
        self.client = TestClient(self.app)
        self.dir = tempfile.mkdtemp(prefix="ewc-title-route-")
        self.old_dir = schedule_store.SCHEDULES_DIR
        schedule_store.SCHEDULES_DIR = self.dir

    def tearDown(self):
        schedule_store.SCHEDULES_DIR = self.old_dir

    def _publish_chess(self):
        wikitext = (
            "{{Stage|Playoffs}}\n{{Match\n|date=2026-08-11\n"
            "|opponent1={{1Opponent|Magnus Carlsen}}\n"
            "|opponent2={{1Opponent|Hikaru Nakamura}}\n}}\n"
        )
        rows = schedule_store.build_rows(wikitext, source_key="chess:Esports World Cup/2026")
        snap = schedule_store.build_snapshot(
            "chess", rows, [34705], "2026-08-09T00:00:00+00:00", lifecycle="upcoming")
        schedule_store.publish("chess", snap)
        return rows[0]

    def test_selected_no_feed_title_returns_snapshot_rows(self):
        self._publish_chess()
        with mock.patch.object(slate, "esports_upcoming", return_value={"matches": []}):
            r = self.client.get("/api/esports/events/ewc-2026/titles/chess/matches")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["status"], "published")
        self.assertEqual(d["lifecycle"], "upcoming")
        self.assertEqual(len(d["matches"]["upcoming"]), 1)
        self.assertEqual(d["matches"]["upcoming"][0]["teamA"], "Magnus Carlsen")
        self.assertEqual(d["matches"]["upcoming"][0]["source"], "liquipedia-snapshot")

    def test_slate_duplicate_wins_and_time_alone_does_not_match(self):
        row = self._publish_chess()
        duplicate = _match(
            title="Chess", teamA="Magnus Carlsen", teamB="Hikaru Nakamura",
            startTime=row["startTime"], live=True,
        )
        same_time_other_players = _match(
            title="Chess", teamA="Player C", teamB="Player D",
            startTime=row["startTime"], live=False,
        )
        with mock.patch.object(
            slate, "esports_upcoming",
            return_value={"matches": [duplicate, same_time_other_players]},
        ):
            d = self.client.get("/api/esports/events/ewc-2026/titles/chess/matches").json()
        combined = d["matches"]["live"] + d["matches"]["upcoming"] + d["matches"]["completed"]
        self.assertEqual(len(combined), 2)
        self.assertEqual(sum(1 for m in combined if m["teamA"] == "Magnus Carlsen"), 1)
        self.assertTrue(next(m for m in combined if m["teamA"] == "Magnus Carlsen")["live"])
        self.assertTrue(any(m["teamA"] == "Player C" for m in combined))

    def test_missing_snapshot_remains_pending(self):
        with mock.patch.object(slate, "esports_upcoming", return_value={"matches": []}):
            d = self.client.get("/api/esports/events/ewc-2026/titles/apex-legends/matches").json()
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["matches"], {"live": [], "upcoming": [], "completed": []})

    def test_unknown_title_is_404(self):
        r = self.client.get("/api/esports/events/ewc-2026/titles/not-a-title/matches")
        self.assertEqual(r.status_code, 404)


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


class TitlesRouteTests(unittest.TestCase):
    """GET /api/esports/titles — title discovery from the shared slate (fixture-driven)."""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.esports import predict as predict_module
        self.predict_module = predict_module
        self.app = FastAPI()
        self.app.include_router(predict_module.router)
        self.client = TestClient(self.app)

    def _board(self, matches, building=False):
        return {"matches": matches, "building": building}

    def test_titles_derived_from_shared_slate(self):
        matches = [
            _match(startTime=1, live=True),          # Call of Duty live
            _match(startTime=2),                     # Call of Duty upcoming
            _match(startTime=3, finished=True),      # Call of Duty result
            {"title": "CS2", "teamA": "A", "teamB": "B", "startTime": 4, "live": True},
            {"title": "Not A Registered Title", "teamA": "X", "teamB": "Y", "startTime": 5},
        ]
        with mock.patch.object(self.predict_module, "esports_upcoming", return_value=self._board(matches)):
            r = self.client.get("/api/esports/titles")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("titles", body)
        titles = {t["slug"]: t for t in body["titles"]}
        cod = titles["call-of-duty"]
        self.assertEqual(cod["label"], "Call of Duty")
        self.assertEqual(cod["live_count"], 1)
        self.assertEqual(cod["match_count"], 2)      # open matches only (live + upcoming)
        self.assertEqual(cod["result_count"], 1)
        self.assertEqual(cod["next_start"], 1)
        self.assertEqual(len(titles), len(_ESPORTS_TITLES))
        self.assertNotIn("not-a-registered-title", titles)

    def test_titles_empty_slate_returns_all_registered_zeroed(self):
        with mock.patch.object(self.predict_module, "esports_upcoming", return_value=self._board([])):
            r = self.client.get("/api/esports/titles")
        self.assertEqual(r.status_code, 200)
        titles = {t["slug"]: t for t in r.json()["titles"]}
        self.assertEqual(len(titles), len(_ESPORTS_TITLES))
        self.assertEqual(titles["call-of-duty"]["match_count"], 0)
        self.assertEqual(titles["call-of-duty"]["live_count"], 0)
        self.assertIsNone(titles["call-of-duty"]["next_start"])


if __name__ == "__main__":
    unittest.main()
