#!/usr/bin/env python3

"""A saved draft must say how far it got, and whether what we hold is whole.

Two defects this file exists to keep fixed:

1. **Nothing ever wrote completion.** ``status`` was set to 'active' at insert
   and never updated; ``completed_at`` was never written by any code path. So
   the server could not distinguish a draft abandoned at pick 4 from one that
   ran all 180 -- and that classification is exactly what slice B's
   claim-on-sign-in inherits. The frontend compounded it by comparing against
   ``status === 'complete'``, a string nothing writes.

2. **A dropped append left an invisible hole.** Picks are
   ``INSERT OR IGNORE`` on (draft_id, pick_no) with no sequence check, so when
   the client's best-effort append failed, later batches still landed and
   neither side raised. The row kept picks [1,2,3,7,8,9] with nothing in the
   payload saying six picks never made it.

LP_DB_PATH is pointed at a tempfile BEFORE importing the router, same pattern
as test_nfl_mock_draft.py.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="mock-draft-completion-", suffix=".db", delete=False
)
_TEST_DB.close()
_ORIGINAL_LP_DB_PATH = os.environ.get("LP_DB_PATH")
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers import nfl_mock_draft  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

if _ORIGINAL_LP_DB_PATH is None:
    os.environ.pop("LP_DB_PATH", None)
else:
    os.environ["LP_DB_PATH"] = _ORIGINAL_LP_DB_PATH

app = FastAPI()
app.include_router(nfl_mock_draft.router)
client = TestClient(app)

DEVICE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DEVICE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _picks(first, last):
    return [
        {"pick_no": n, "team_no": (n - 1) % 12 + 1, "player_id": 1000 + n, "auto": 1}
        for n in range(first, last + 1)
    ]


class CompletionTests(unittest.TestCase):

    def setUp(self):
        connection = nfl_mock_draft._conn()
        try:
            connection.execute("DELETE FROM nfl_mock_draft_picks")
            connection.execute("DELETE FROM nfl_mock_drafts")
            connection.commit()
        finally:
            connection.close()

        res = client.post(
            "/api/nfl/mock-draft",
            headers={"X-Device-Id": DEVICE_A},
            json={"season": nfl_mock_draft._CURRENT_SEASON, "seat": 1, "seed": 42},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.draft_id = res.json()["id"]

    def _append(self, first, last):
        res = client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/picks",
            headers={"X-Device-Id": DEVICE_A},
            json={"picks": _picks(first, last)},
        )
        self.assertEqual(res.status_code, 200, res.text)

    # ── completion ────────────────────────────────────────────────────────

    def test_a_new_draft_is_active_and_not_completed(self):
        res = client.get(
            f"/api/nfl/mock-draft/{self.draft_id}",
            headers={"X-Device-Id": DEVICE_A},
        )
        self.assertEqual(res.json()["status"], "active")
        self.assertIsNone(res.json()["completed_at"])

    def test_complete_writes_status_and_timestamp(self):
        self._append(1, 12)
        res = client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/complete",
            headers={"X-Device-Id": DEVICE_A},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "completed")

        # The stored row, not just the response, is what slice B will read.
        stored = client.get(
            f"/api/nfl/mock-draft/{self.draft_id}",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        self.assertEqual(stored["status"], "completed")
        self.assertIsNotNone(stored["completed_at"])

    def test_complete_is_idempotent(self):
        self._append(1, 12)
        first = client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/complete",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        second = client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/complete",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        self.assertEqual(first["status"], second["status"])
        self.assertEqual(first["pick_count"], second["pick_count"])

    def test_complete_rejects_another_device(self):
        """A device must not be able to close a draft it does not own."""
        res = client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/complete",
            headers={"X-Device-Id": DEVICE_B},
        )
        self.assertEqual(res.status_code, 404)

    # ── holes ─────────────────────────────────────────────────────────────

    def test_a_contiguous_draft_reports_no_missing_picks(self):
        self._append(1, 9)
        body = client.get(
            f"/api/nfl/mock-draft/{self.draft_id}",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        self.assertEqual(body["missing_picks"], [])
        self.assertEqual(body["total_picks"], 9)
        self.assertEqual(body["picks_expected"], 180)

    def test_a_dropped_batch_shows_up_as_missing_picks(self):
        """The exact failure the swallowed `.catch(() => {})` used to hide."""
        self._append(1, 3)
        # picks 4-6 never sent -- the client's append failed and was discarded
        self._append(7, 9)

        body = client.get(
            f"/api/nfl/mock-draft/{self.draft_id}",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        self.assertEqual(body["missing_picks"], [4, 5, 6])
        self.assertEqual(body["total_picks"], 6)

    def test_an_unfinished_draft_is_not_reported_as_holed(self):
        """Incomplete and holed are different states.

        Missing picks are counted against the highest pick actually saved, not
        against 180 -- otherwise every draft in progress would report 170-odd
        'missing' picks and the field would carry no information at all.
        """
        self._append(1, 40)
        body = client.get(
            f"/api/nfl/mock-draft/{self.draft_id}",
            headers={"X-Device-Id": DEVICE_A},
        ).json()
        self.assertEqual(body["missing_picks"], [])
        self.assertEqual(body["total_picks"], 40)

    def test_list_classifies_rows_without_fetching_each_draft(self):
        self._append(1, 3)
        self._append(7, 9)
        client.post(
            f"/api/nfl/mock-draft/{self.draft_id}/complete",
            headers={"X-Device-Id": DEVICE_A},
        )
        row = client.get(
            "/api/nfl/mock-drafts", headers={"X-Device-Id": DEVICE_A}
        ).json()["drafts"][0]
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["pick_count"], 6)
        self.assertEqual(row["picks_expected"], 180)
        self.assertEqual(row["missing_pick_count"], 3)


if __name__ == "__main__":
    unittest.main()
