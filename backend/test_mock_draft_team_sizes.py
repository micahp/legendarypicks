#!/usr/bin/env python3

"""10-, 12-, and 14-team mock-draft persistence.

Covers the production bug where the pick-appender silently discarded picks
for teams 13-14 and picks > 180 because validation was hardcoded at 12/180.
Each test creates a draft of size N, appends picks past the old constants,
and confirms they persisted.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="mock-draft-teams-", suffix=".db", delete=False
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

DEVICE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _create_draft(teams: int, rounds: int = 15) -> str:
    res = client.post(
        "/api/nfl/mock-draft",
        headers={"X-Device-Id": DEVICE},
        json={
            "season": nfl_mock_draft._CURRENT_SEASON,
            "seat": teams,
            "seed": 42,
            "teams": teams,
            "rounds": rounds,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


class VariableTeamPersistenceTests(unittest.TestCase):

    def setUp(self):
        connection = nfl_mock_draft._conn()
        try:
            connection.execute("DELETE FROM nfl_mock_draft_picks")
            connection.execute("DELETE FROM nfl_mock_drafts")
            connection.commit()
        finally:
            connection.close()

    def _append(self, draft_id: str, first: int, last: int, teams: int):
        picks = [
            {"pick_no": n, "team_no": (n - 1) % teams + 1, "player_id": 1000 + n, "auto": 1}
            for n in range(first, last + 1)
        ]
        return client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            headers={"X-Device-Id": DEVICE},
            json={"picks": picks},
        )

    # ── 10-team ────────────────────────────────────────────────────────────

    def test_10_team_draft_persists_full_150_picks(self):
        expected = 10 * 15
        draft_id = _create_draft(10, 15)
        self.assertEqual(self._append(draft_id, 1, expected, 10).json()["inserted"], expected)

        body = client.get(
            f"/api/nfl/mock-draft/{draft_id}",
            headers={"X-Device-Id": DEVICE},
        ).json()
        self.assertEqual(body["total_picks"], expected)
        self.assertEqual(body["picks_expected"], expected)
        self.assertEqual(body["missing_picks"], [])

    # ── 12-team (default) ─────────────────────────────────────────────────

    def test_12_team_draft_persists_full_180_picks(self):
        expected = 12 * 15
        draft_id = _create_draft(12, 15)
        self.assertEqual(self._append(draft_id, 1, expected, 12).json()["inserted"], expected)

        body = client.get(
            f"/api/nfl/mock-draft/{draft_id}",
            headers={"X-Device-Id": DEVICE},
        ).json()
        self.assertEqual(body["total_picks"], expected)
        self.assertEqual(body["picks_expected"], expected)
        self.assertEqual(body["missing_picks"], [])

    # ── 14-team ────────────────────────────────────────────────────────────

    def test_14_team_draft_persists_picks_181_to_210(self):
        """The exact failure mode: picks beyond team 12 / pick 180 were silently dropped."""
        expected = 14 * 15
        draft_id = _create_draft(14, 15)

        # First 180 picks (the old limit)
        self._append(draft_id, 1, 180, 14)
        # The 30 picks that used to be silently dropped
        res = self._append(draft_id, 181, expected, 14)
        self.assertEqual(res.json()["inserted"], 30, f"Expected 30 picks inserted, got {res.json()}")

        body = client.get(
            f"/api/nfl/mock-draft/{draft_id}",
            headers={"X-Device-Id": DEVICE},
        ).json()
        self.assertEqual(body["total_picks"], expected)
        self.assertEqual(body["picks_expected"], expected)
        self.assertEqual(body["missing_picks"], [])

    def test_14_team_pick_at_max_rounds_persists(self):
        """Pick 210 (14*15) is the last valid pick — should persist."""
        expected = 14 * 15
        draft_id = _create_draft(14, 15)
        res = self._append(draft_id, expected, expected, 14)
        self.assertEqual(res.json()["inserted"], 1)


if __name__ == "__main__":
    unittest.main()
