#!/usr/bin/env python3

"""Tests for the NFL draft-notes router.

LP_DB_PATH is pointed at a tempfile BEFORE importing the router so that the
module-level ``_DB`` resolves to a disposable database rather than a real one.
``conftest.py`` restores the env var afterwards (per its docstring)."""

import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Point LP_DB_PATH at a throwaway file BEFORE importing the router.
_TEST_DB = tempfile.NamedTemporaryFile(prefix="draft-notes-test-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers import nfl_draft_notes  # noqa: E402

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Build a minimal app that only includes the draft-notes router.
app = FastAPI()
app.include_router(nfl_draft_notes.router)
client = TestClient(app)


class TestNflDraftNotes(unittest.TestCase):

    SEASON = nfl_draft_notes._CURRENT_SEASON
    DEVICE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    DEVICE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    def setUp(self):
        """Clean the notes table between tests so counts are deterministic."""
        connection = nfl_draft_notes._conn()
        try:
            connection.execute("DELETE FROM nfl_draft_notes")
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def setUpClass(cls):
        """Create the ``players`` table and seed a few test players."""
        connection = nfl_draft_notes._conn()
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS players ("
                "  id INTEGER PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  league TEXT NOT NULL,"
                "  active INTEGER DEFAULT 1"
                ")"
            )
            connection.executemany(
                "INSERT OR IGNORE INTO players (id, name, league, active) VALUES (?, ?, ?, ?)",
                [
                    (1, "Player One", "nfl", 1),
                    (2, "Player Two (retired)", "nfl", 0),
                    (3, "NBA Guy", "nba", 1),
                    (4, "Player Four (inactive)", "nfl", 0),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    #  Helper
    # ------------------------------------------------------------------

    _MISSING = object()

    def _put(self, player_id, rank=_MISSING, watch=_MISSING, fade=_MISSING, device=None):
        body = {"season": self.SEASON, "player_id": player_id}
        if rank is not self._MISSING:
            body["rank"] = rank
        if watch is not self._MISSING:
            body["watch"] = watch
        if fade is not self._MISSING:
            body["fade"] = fade
        headers = {"X-Device-Id": device or self.DEVICE_A}
        return client.put("/api/nfl/draft-notes", json=body, headers=headers)

    def _get(self, device=None):
        headers = {"X-Device-Id": device or self.DEVICE_A}
        return client.get(f"/api/nfl/draft-notes?season={self.SEASON}", headers=headers)

    def _import(self, notes, device=None):
        headers = {"X-Device-Id": device or self.DEVICE_A}
        return client.post(
            "/api/nfl/draft-notes/import",
            json={"season": self.SEASON, "notes": notes},
            headers=headers,
        )

    # ------------------------------------------------------------------
    #  1.  Round trip: rank, watch, fade
    # ------------------------------------------------------------------

    def test_round_trip_rank_watch_fade(self):
        # Set rank on player 1
        resp = self._put(1, rank=3)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rank"], 3)
        self.assertFalse(resp.json()["watch"])
        self.assertFalse(resp.json()["fade"])

        # Toggle watch on player 1
        resp = self._put(1, watch=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["watch"])

        # Toggle fade on player 1
        resp = self._put(1, fade=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["fade"])

        # GET — all three must be present
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["contract"], "nfl-draft-notes-v1")
        self.assertEqual(body["notes"]["rank"]["1"], 3)
        self.assertEqual(body["notes"]["watch"]["1"], True)
        self.assertEqual(body["notes"]["fade"]["1"], True)
        self.assertEqual(body["note_count"], 1)
        self.assertIsNotNone(body["updated_at"])

    # ------------------------------------------------------------------
    #  2.  Device isolation
    # ------------------------------------------------------------------

    def test_device_isolation(self):
        # Device A sets a rank on player 1
        resp = self._put(1, rank=5, device=self.DEVICE_A)
        self.assertEqual(resp.status_code, 200)

        # Device B sees nothing
        resp = self._get(device=self.DEVICE_B)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["note_count"], 0)
        self.assertEqual(body["notes"]["rank"], {})
        self.assertEqual(body["notes"]["watch"], {})
        self.assertEqual(body["notes"]["fade"], {})

        # But direct query confirms Device A's row exists
        connection = nfl_draft_notes._conn()
        try:
            row = connection.execute(
                "SELECT device_id, player_id, \"rank\" FROM nfl_draft_notes"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["device_id"], self.DEVICE_A)
            self.assertEqual(row["player_id"], 1)
            self.assertEqual(row["rank"], 5)
        finally:
            connection.close()

    # ------------------------------------------------------------------
    #  3.  Import path
    # ------------------------------------------------------------------

    def test_import_notes(self):
        notes = {
            "rank": {"1": 10, "4": 7},
            "watch": {"2": True, "1": True},
            "fade": {"2": True},
        }
        resp = self._import(notes, device=self.DEVICE_A)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # All three are NFL players and should be imported
        self.assertEqual(body["imported"], 3)  # pid 1, 2, 4
        self.assertEqual(body["skipped"], 0)
        self.assertEqual(body["rejected"], 0)

        # Re-importing the same notes should be all skipped
        resp2 = self._import(notes, device=self.DEVICE_A)
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.json()
        self.assertEqual(body2["imported"], 0)
        self.assertEqual(body2["skipped"], 3)

    # ------------------------------------------------------------------
    #  4.  Delete-on-empty
    # ------------------------------------------------------------------

    def test_delete_on_empty(self):
        # Toggle watch on player 1
        resp = self._put(1, watch=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["watch"])

        # Toggle watch off — should delete the row
        resp = self._put(1, watch=False)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

        # Confirm zero rows in SQLite
        connection = nfl_draft_notes._conn()
        try:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM nfl_draft_notes "
                "WHERE device_id=? AND player_id=? AND season=?",
                (self.DEVICE_A, 1, self.SEASON),
            ).fetchone()["n"]
            self.assertEqual(count, 0)
        finally:
            connection.close()

    # ------------------------------------------------------------------
    #  5.  1,000 row cap
    # ------------------------------------------------------------------

    def test_row_cap(self):
        device = "cap-test-device"
        # Seed enough valid NFL players (including the "over-cap" test player)
        connection = nfl_draft_notes._conn()
        try:
            for pid in range(100, 1200):
                connection.execute(
                    "INSERT OR IGNORE INTO players (id, name, league) VALUES (?, ?, 'nfl')",
                    (pid, f"CapPlayer{pid}"),
                )
            # Also seed the player we'll use to test the cap
            connection.execute(
                "INSERT OR IGNORE INTO players (id, name, league) VALUES (9999, 'OverCap', 'nfl')"
            )
            connection.commit()
        finally:
            connection.close()

        imported = 0
        for pid in range(100, 1200):
            resp = self._put(pid, rank=1, device=device)
            if resp.status_code == 200:
                imported += 1
            elif resp.status_code == 409:
                break

        self.assertLessEqual(imported, 1000)

        # Try a brand-new player_id (not yet in notes) — must hit the cap
        resp = self._put(9999, rank=2, device=device)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("cap", resp.json()["error"].lower())

    # ------------------------------------------------------------------
    #  6.  Unknown player is 404
    # ------------------------------------------------------------------

    def test_unknown_player_404(self):
        resp = self._put(99999, rank=5)
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["error"].lower())

    # ------------------------------------------------------------------
    #  7.  Missing device-id is 400
    # ------------------------------------------------------------------

    def test_missing_device_id_400(self):
        # PUT without header
        resp = client.put(
            "/api/nfl/draft-notes",
            json={"season": self.SEASON, "player_id": 1, "rank": 5},
        )
        self.assertEqual(resp.status_code, 400)

        # GET without header
        resp = client.get(f"/api/nfl/draft-notes?season={self.SEASON}")
        self.assertEqual(resp.status_code, 400)

        # POST import without header
        resp = client.post(
            "/api/nfl/draft-notes/import",
            json={"season": self.SEASON, "notes": {"rank": {"1": 5}}},
        )
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  8.  Retired (active=0) players are still valid
    # ------------------------------------------------------------------

    def test_inactive_player_allowed(self):
        # Player 2 is retired (active=0) but still an NFL player
        resp = self._put(2, rank=42)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rank"], 42)

    # ------------------------------------------------------------------
    #  9.  Non-NFL player is 404
    # ------------------------------------------------------------------

    def test_non_nfl_player_404(self):
        # Player 3 is NBA
        resp = self._put(3, rank=5)
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    #  10.  Rank out of range
    # ------------------------------------------------------------------

    def test_rank_out_of_range(self):
        # rank 0 is invalid
        resp = self._put(1, rank=0)
        self.assertEqual(resp.status_code, 400)

        # rank 1000 is invalid
        resp = self._put(1, rank=1000)
        self.assertEqual(resp.status_code, 400)

        # rank 1 is valid
        resp = self._put(1, rank=1)
        self.assertEqual(resp.status_code, 200)

        # rank 999 is valid
        resp = self._put(1, rank=999)
        self.assertEqual(resp.status_code, 200)

    # ------------------------------------------------------------------
    #  11.  watch/fade null is 400
    # ------------------------------------------------------------------

    def test_watch_fade_null_400(self):
        resp = self._put(1, watch=None)
        self.assertEqual(resp.status_code, 400)

        resp = self._put(1, fade=None)
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  12.  Season validation
    # ------------------------------------------------------------------

    def test_season_validation(self):
        # Wrong season on PUT
        resp = client.put(
            "/api/nfl/draft-notes",
            json={"season": 2025, "player_id": 1, "rank": 5},
            headers={"X-Device-Id": self.DEVICE_A},
        )
        self.assertEqual(resp.status_code, 400)

        # Wrong season on GET
        resp = client.get(
            "/api/nfl/draft-notes?season=2025",
            headers={"X-Device-Id": self.DEVICE_A},
        )
        self.assertEqual(resp.status_code, 400)

        # Wrong season on import
        resp = client.post(
            "/api/nfl/draft-notes/import",
            json={"season": 2025, "notes": {"rank": {"1": 5}}},
            headers={"X-Device-Id": self.DEVICE_A},
        )
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  13.  Import entry cap
    # ------------------------------------------------------------------

    def test_import_entry_cap(self):
        big_rank = {str(i): i for i in range(1, 1002)}
        resp = self._import({"rank": big_rank})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cap", resp.json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
