#!/usr/bin/env python3

"""Tests for the NFL mock-draft router.

LP_DB_PATH is pointed at a tempfile BEFORE importing the router so that the
module-level ``_DB`` resolves to a disposable database rather than a real one.
Same pattern as ``test_nfl_draft_notes.py``.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Point LP_DB_PATH at a throwaway file BEFORE importing the router.
_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="mock-draft-test-", suffix=".db", delete=False
)
_TEST_DB.close()
_ORIGINAL_LP_DB_PATH = os.environ.get("LP_DB_PATH")
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers import nfl_mock_draft  # noqa: E402

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Do not poison later real-DB suites in the same unittest process. The router
# has already bound its own _DB to the tempfile; the shared environment belongs
# to the caller's test run.
if _ORIGINAL_LP_DB_PATH is None:
    os.environ.pop("LP_DB_PATH", None)
else:
    os.environ["LP_DB_PATH"] = _ORIGINAL_LP_DB_PATH

# Build a minimal app that only includes the mock-draft router.
app = FastAPI()
app.include_router(nfl_mock_draft.router)
client = TestClient(app)


class TestNflMockDraft(unittest.TestCase):

    SEASON = nfl_mock_draft._CURRENT_SEASON
    DEVICE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    DEVICE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    def setUp(self):
        """Clean draft tables between tests so counts are deterministic."""
        connection = nfl_mock_draft._conn()
        try:
            connection.execute("DELETE FROM nfl_mock_draft_picks")
            connection.execute("DELETE FROM nfl_mock_drafts")
            connection.commit()
        finally:
            connection.close()

    @classmethod
    def setUpClass(cls):
        """Seed the tables needed for pool queries."""
        connection = nfl_mock_draft._conn()
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    position TEXT,
                    team TEXT,
                    league TEXT NOT NULL,
                    active INTEGER DEFAULT 1
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS nfl_adp (
                    player_id INTEGER,
                    season INTEGER,
                    adp REAL,
                    percent_owned REAL,
                    espn_ppr_rank INTEGER,
                    active INTEGER DEFAULT 1
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS nfl_player_projections (
                    player_id INTEGER,
                    season INTEGER,
                    lp_ppr_projected_points REAL,
                    PRIMARY KEY (player_id, season)
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS player_game_logs (
                    player_id INTEGER,
                    league TEXT,
                    season INTEGER,
                    game_no TEXT,
                    team TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS player_stats (
                    player_id INTEGER,
                    league TEXT,
                    stat_type TEXT,
                    season INTEGER,
                    pass_yds_g REAL,
                    pass_td INTEGER,
                    interceptions INTEGER,
                    cmp_g REAL,
                    carries_g REAL,
                    rush_yds_g REAL,
                    rec_yds_g REAL,
                    targets INTEGER,
                    receptions INTEGER,
                    fantasy_ppr_g REAL
                )"""
            )
            # Seed players — all NFL, all active, covering the five draftable positions.
            connection.executemany(
                "INSERT OR IGNORE INTO players (id, name, position, team, league, active) "
                "VALUES (?, ?, ?, ?, 'nfl', 1)",
                [
                    (1, "Alpha RB", "RB", "KC"),
                    (2, "Beta WR", "WR", "MIN"),
                    (3, "Gamma QB", "QB", "BUF"),
                    (4, "Delta TE", "TE", "SF"),
                    (5, "Epsilon PK", "PK", "BAL"),
                    (6, "Zeta RB", "RB", "DAL"),
                    (7, "Eta WR", "WR", "LAR"),
                    (8, "Theta PK", "PK", "GB"),    # no ADP or ownership → excluded
                    (9, "Team Quarterback", "TQB", "KC"),
                ],
            )
            # Seed ADP rows.
            connection.executemany(
                "INSERT OR IGNORE INTO nfl_adp "
                "(player_id, season, adp, percent_owned, espn_ppr_rank, active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                [
                    (1, 2026, 1.5, 99.0, 1),
                    (2, 2026, 5.2, 97.0, 3),
                    (3, 2026, 15.0, 95.0, 5),
                    (4, 2026, 50.0, 80.0, 6),
                    (5, 2026, 170.0, 10.0, 7),   # copied published ADP
                    (6, 2026, 2.0, 98.0, 2),
                    (7, 2026, 10.0, 92.0, 4),
                    (8, 2026, None, 0.0, None),  # no published rank or ADP
                    (9, 2026, 25.0, 50.0, 8),   # aggregate slot, not a player
                ],
            )
            connection.executemany(
                "INSERT OR IGNORE INTO nfl_player_projections VALUES(?,?,?)",
                [(1, 2026, 321.4), (2, 2026, 287.6), (3, 2026, None)],
            )
            # Seed game logs for players 1–4 (full sample: 10+ games).
            for pid, team in [(1, 'KC'), (2, 'MIN')]:
                for g in range(1, 13):
                    connection.execute(
                        "INSERT OR IGNORE INTO player_game_logs "
                        "(player_id, league, season, game_no, team) VALUES (?, 'nfl', 2025, ?, ?)",
                        (pid, str(g), team),
                    )
            # Player 3 has a thin sample (2 games).
            for g in range(1, 3):
                connection.execute(
                    "INSERT OR IGNORE INTO player_game_logs "
                    "(player_id, league, season, game_no, team) VALUES (?, 'nfl', 2025, ?, 'BUF')",
                    (3, str(g)),
                )
            # Player 4 has no logs (sample: none).
            # Players 5–8 have no logs either.

            # Also seed playoff logs for player 1 (should be excluded from games_played).
            connection.execute(
                "INSERT OR IGNORE INTO player_game_logs "
                "(player_id, league, season, game_no, team) VALUES (?, 'nfl', 2025, '19', 'KC')",
                (1,),
            )

            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    #  Pool endpoint
    # ------------------------------------------------------------------

    def test_pool_returns_players(self):
        """Pool returns the full published universe with availability data."""
        resp = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["contract"], "nfl-mock-draft-v1")
        self.assertEqual(body["season"], self.SEASON)
        self.assertGreaterEqual(body["count"], 1)

        # The pool is every nfl_adp row for the season — player 8 has neither a
        # published ADP nor ownership, but is still a pool entry rendering a
        # "—" ADP (v0.7.0 T2: free agents are in the universe, honestly empty).
        by_id = {p["player_id"]: p for p in body["players"]}
        self.assertIn(8, by_id)
        self.assertIsNone(by_id[8]["adp"])
        self.assertEqual(by_id[8]["percent_owned"], 0.0)
        self.assertNotIn(9, by_id)
        self.assertLessEqual(
            {p["position"] for p in body["players"]},
            {"QB", "RB", "WR", "TE", "PK", "DEF"},
        )
        self.assertEqual(by_id[1]["espn_ppr_rank"], 1)
        self.assertEqual(by_id[1]["proj_ppr_points"], 321.4)
        self.assertEqual(by_id[1]["proj_season"], 2026)
        self.assertEqual(by_id[1]["proj_source"], "espn")
        self.assertIsNone(by_id[3]["proj_ppr_points"])
        self.assertIsNone(by_id[3]["proj_source"])

    def test_pool_ordering(self):
        """Real ADP players come first, sorted by ADP ascending."""
        resp = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
        body = resp.json()
        adp_values = [p["adp"] for p in body["players"]]

        published_adp = [a for a in adp_values if a is not None]
        self.assertEqual(published_adp, sorted(published_adp))

    def test_pool_availability_data(self):
        """Pool includes sample, games_played, games_missed."""
        resp = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
        body = resp.json()
        players_by_id = {p["player_id"]: p for p in body["players"]}

        # Player 1: 12 games → full sample.
        p1 = players_by_id[1]
        self.assertEqual(p1["sample"], "full")
        self.assertEqual(p1["games_played"], 12)
        self.assertEqual(p1["games_missed"], 5)  # 17 - 12

        # Player 3: 2 games → thin sample.
        p3 = players_by_id[3]
        self.assertEqual(p3["sample"], "thin")
        self.assertEqual(p3["games_played"], 2)
        self.assertEqual(p3["games_missed"], 15)

        # Player 4: no logs → none sample, games_missed is None.
        if 4 in players_by_id:
            p4 = players_by_id[4]
            self.assertEqual(p4["sample"], "none")
            self.assertIsNone(p4["games_played"])
            self.assertIsNone(p4["games_missed"])
            self.assertIsNone(p4["team_games"])

    def test_pool_wrong_season(self):
        resp = client.get("/api/nfl/mock-draft/pool?season=2025")
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  Draft creation
    # ------------------------------------------------------------------

    def _create_draft(self, seat=1, seed=42, device=None):
        headers = {"X-Device-Id": device or self.DEVICE_A}
        return client.post(
            "/api/nfl/mock-draft",
            json={"season": self.SEASON, "seat": seat, "seed": seed},
            headers=headers,
        )

    def test_create_draft_returns_id(self):
        resp = self._create_draft()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("id", resp.json())
        # id should be a UUID string.
        draft_id = resp.json()["id"]
        self.assertIsInstance(draft_id, str)
        self.assertEqual(len(draft_id), 36)  # UUID length

    def test_create_draft_missing_device_id(self):
        resp = client.post(
            "/api/nfl/mock-draft",
            json={"season": self.SEASON, "seat": 1, "seed": 42},
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_draft_invalid_seat(self):
        resp = self._create_draft(seat=0)
        self.assertEqual(resp.status_code, 400)

        resp = self._create_draft(seat=13)
        self.assertEqual(resp.status_code, 400)

    def test_create_draft_wrong_season(self):
        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.post(
            "/api/nfl/mock-draft",
            json={"season": 2025, "seat": 1, "seed": 42},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_draft_missing_seed(self):
        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.post(
            "/api/nfl/mock-draft",
            json={"season": self.SEASON, "seat": 1},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  Append picks
    # ------------------------------------------------------------------

    def test_append_picks(self):
        create = self._create_draft()
        draft_id = create.json()["id"]

        picks = [
            {"pick_no": 1, "team_no": 1, "player_id": 1},
            {"pick_no": 2, "team_no": 2, "player_id": 2, "auto": 1},
        ]
        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            json={"picks": picks},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["inserted"], 2)

    def test_append_picks_idempotent(self):
        create = self._create_draft()
        draft_id = create.json()["id"]

        picks = [
            {"pick_no": 1, "team_no": 1, "player_id": 1},
            {"pick_no": 2, "team_no": 2, "player_id": 2},
        ]
        headers = {"X-Device-Id": self.DEVICE_A}

        # First insert: 2 new.
        resp1 = client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            json={"picks": picks},
            headers=headers,
        )
        self.assertEqual(resp1.json()["inserted"], 2)

        # Repeat: 0 inserted (idempotent on pick_no).
        resp2 = client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            json={"picks": picks},
            headers=headers,
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["inserted"], 0)

    def test_append_picks_device_isolation(self):
        create = self._create_draft()
        draft_id = create.json()["id"]

        picks = [{"pick_no": 1, "team_no": 1, "player_id": 1}]
        headers_b = {"X-Device-Id": self.DEVICE_B}
        resp = client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            json={"picks": picks},
            headers=headers_b,
        )
        self.assertEqual(resp.status_code, 404)

    def test_append_picks_nonexistent_draft(self):
        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.post(
            "/api/nfl/mock-draft/nonexistent-id/picks",
            json={"picks": [{"pick_no": 1, "team_no": 1, "player_id": 1}]},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_append_picks_missing_body(self):
        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.post(
            "/api/nfl/mock-draft/some-id/picks",
            json={},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  Get / resume draft
    # ------------------------------------------------------------------

    def test_get_draft_with_picks(self):
        create = self._create_draft()
        draft_id = create.json()["id"]

        # Add picks.
        picks = [
            {"pick_no": 1, "team_no": 1, "player_id": 1},
            {"pick_no": 2, "team_no": 2, "player_id": 2, "auto": 1},
        ]
        headers = {"X-Device-Id": self.DEVICE_A}
        client.post(
            f"/api/nfl/mock-draft/{draft_id}/picks",
            json={"picks": picks},
            headers=headers,
        )

        # Resume.
        resp = client.get(
            f"/api/nfl/mock-draft/{draft_id}",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], draft_id)
        self.assertEqual(body["season"], self.SEASON)
        self.assertEqual(body["seat"], 1)
        self.assertEqual(body["status"], "active")
        self.assertEqual(len(body["picks"]), 2)
        self.assertEqual(body["picks"][0]["pick_no"], 1)
        self.assertEqual(body["picks"][0]["player_id"], 1)
        self.assertFalse(body["picks"][0]["auto"])
        self.assertTrue(body["picks"][1]["auto"])

    def test_get_draft_device_isolation(self):
        create = self._create_draft()
        draft_id = create.json()["id"]

        headers_b = {"X-Device-Id": self.DEVICE_B}
        resp = client.get(
            f"/api/nfl/mock-draft/{draft_id}",
            headers=headers_b,
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_draft_missing_header(self):
        resp = client.get("/api/nfl/mock-draft/some-id")
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------------
    #  List drafts
    # ------------------------------------------------------------------

    def test_list_drafts(self):
        # Create two drafts for Device A.
        self._create_draft(seat=1, seed=1)
        self._create_draft(seat=5, seed=42)

        headers = {"X-Device-Id": self.DEVICE_A}
        resp = client.get("/api/nfl/mock-drafts", headers=headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["drafts"]), 2)

        # Each draft entry has expected fields.
        for d in body["drafts"]:
            self.assertIn("id", d)
            self.assertIn("status", d)
            self.assertIn("seat", d)

    def test_list_drafts_device_isolation(self):
        # Device A creates a draft.
        self._create_draft(device=self.DEVICE_A)

        # Device B sees nothing.
        headers_b = {"X-Device-Id": self.DEVICE_B}
        resp = client.get("/api/nfl/mock-drafts", headers=headers_b)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["drafts"]), 0)

    def test_list_drafts_missing_header(self):
        resp = client.get("/api/nfl/mock-drafts")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
