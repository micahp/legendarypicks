#!/usr/bin/env python3

"""Tests for the NFL mock-draft router.

LP_DB_PATH is pointed at a tempfile BEFORE importing the router so that the
module-level ``_DB`` resolves to a disposable database rather than a real one.
Same pattern as ``test_nfl_draft_notes.py``.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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

# The router and _core resolve their module-level DB from LP_DB_PATH at import
# time. In a whole-suite run an earlier module has usually already imported
# them, binding both to ITS tempfile -- or, worse, to the real data/picks.db
# (test_nfl_dst.py imports the routers without a tempfile). This file must not
# depend on being the first importer, so re-point both at this file's own
# tempfile and apply the canonical schema -- setUpClass then sees exactly the
# tables it gets when this file runs alone.
import _core  # noqa: E402
_core.DB = _TEST_DB.name
_core._init_db()
nfl_mock_draft._DB = _TEST_DB.name
nfl_mock_draft._init_db()

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

    def test_named_stat_line_normalizes_rate_and_keeps_projection_first_downs_null(self):
        line = nfl_mock_draft._named_stat_line(json.dumps({
            "21": 0.693478,
            "64": 40,
            "68": 7,
            "72": 3,
            "211": 177,
            "212": 46,
        }))

        self.assertAlmostEqual(line["completion_pct"], 69.3478)
        self.assertEqual(line["sacks"], 40)
        self.assertEqual(line["fumbles"], 7)
        self.assertEqual(line["fumbles_lost"], 3)
        self.assertIsNone(line["passing_first_downs"])
        self.assertIsNone(line["rushing_first_downs"])

        actual_line = nfl_mock_draft._named_stat_line(
            json.dumps({"211": 177, "212": 46}),
            include_actual_first_downs=True,
        )
        self.assertEqual(actual_line["passing_first_downs"], 177)
        self.assertEqual(actual_line["rushing_first_downs"], 46)

    def setUp(self):
        """Clean draft tables between tests so counts are deterministic."""
        nfl_mock_draft._clear_pool_cache()
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
                    team TEXT,
                    opponent TEXT,
                    stats TEXT,
                    game_type TEXT
                )"""
            )
            projection_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(nfl_player_projections)")
            }
            for name, sql_type in (
                ("season_outlook", "TEXT"),
                ("outlook_source", "TEXT"),
                ("actual_season", "INTEGER"),
                ("raw_actual_json", "TEXT"),
                ("actual_qbr", "REAL"),
                ("actual_passer_rating", "REAL"),
                ("actual_adj_qbr", "REAL"),
                ("qbr_source", "TEXT"),
            ):
                if name not in projection_columns:
                    connection.execute(
                        f"ALTER TABLE nfl_player_projections ADD COLUMN {name} {sql_type}"
                    )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS player_stats (
                    player_id INTEGER,
                    league TEXT,
                    stat_type TEXT,
                    source TEXT,
                    season INTEGER,
                    games INTEGER,
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
                """INSERT OR REPLACE INTO nfl_player_projections
                   (player_id, espn_id, season, scoring_period_id,
                    stat_source_id, stat_split_type_id, raw_projection_json,
                    lp_ppr_projected_points)
                   VALUES(?, ?, ?, 0, 1, 0, '{}', ?)""",
                [
                    (1, 1001, 2026, 321.4),
                    (2, 1002, 2026, 287.6),
                    (3, 1003, 2026, None),
                ],
            )
            connection.executemany(
                """INSERT INTO player_stats(
                     player_id,player_name,team,league,stat_type,source,season,games,
                     carries_g,rush_yds_g,rec_yds_g,targets,receptions,
                     fantasy_ppr_g
                   ) VALUES(?,?,?,'nfl','season','nflverse_regular_season',2025,?,?,?,?,?,?,?)""",
                [
                    (1, "Alpha RB", "KC", 12, 17.0, 75.0, 25.0, 45, 35, 18.0),
                    (6, "Zeta RB", "DAL", 17, 15.0, 60.0, 30.0, 55, 40, 15.0),
                ],
            )
            connection.execute(
                """UPDATE nfl_player_projections
                   SET season_outlook=?, outlook_source='espn', actual_season=2025,
                       raw_actual_json=?, actual_qbr=71.4,
                       actual_passer_rating=104.2, actual_adj_qbr=72.1,
                       qbr_source='espn'
                   WHERE player_id=1 AND season=2026""",
                (
                    "Alpha enters 2026 with a secure three-down role.",
                    json.dumps({
                        "23": 201,
                        "24": 900,
                        "25": 8,
                        "53": 45,
                        "68": 4,
                        "72": 2,
                        "212": 53,
                        "213": 28,
                        "210": 12,
                    }),
                ),
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
            connection.execute(
                """UPDATE player_game_logs
                   SET stats='{"fpts_ppr": 10.0}',
                       game_type=CASE WHEN CAST(game_no AS INTEGER) >= 19 THEN 'POST' ELSE 'REG' END"""
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

    def test_pool_cache_reuses_encoded_response(self):
        original = nfl_mock_draft._availability_aggregates
        with mock.patch.object(
            nfl_mock_draft,
            "_availability_aggregates",
            wraps=original,
        ) as availability:
            first = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
            second = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")

        self.assertEqual(200, first.status_code)
        self.assertEqual(first.content, second.content)
        self.assertEqual(1, availability.call_count)

    def test_pool_cache_invalidates_after_database_write(self):
        first = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
        self.assertEqual(1.5, {
            player["player_id"]: player for player in first.json()["players"]
        }[1]["adp"])

        connection = nfl_mock_draft._conn()
        try:
            connection.execute(
                "UPDATE nfl_adp SET adp=2.5 WHERE player_id=1 AND season=?",
                (self.SEASON,),
            )
            connection.commit()
        finally:
            connection.close()

        try:
            second = client.get(f"/api/nfl/mock-draft/pool?season={self.SEASON}")
            self.assertEqual(2.5, {
                player["player_id"]: player for player in second.json()["players"]
            }[1]["adp"])
        finally:
            connection = nfl_mock_draft._conn()
            try:
                connection.execute(
                    "UPDATE nfl_adp SET adp=1.5 WHERE player_id=1 AND season=?",
                    (self.SEASON,),
                )
                connection.commit()
            finally:
                connection.close()
            nfl_mock_draft._clear_pool_cache()

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

    def test_player_detail_publishes_outlook_and_prior_season_totals(self):
        resp = client.get("/api/nfl/draft/player/1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertEqual(
            body["season_outlook"],
            "Alpha enters 2026 with a secure three-down role.",
        )
        self.assertEqual(body["season_outlook_source"], "espn")
        self.assertEqual(body["season_totals_source"], "espn")
        self.assertEqual(body["season_totals"]["season"], 2025)
        self.assertEqual(body["season_totals"]["games"], 12)
        self.assertEqual(body["season_totals"]["rush_att"], 201)
        self.assertEqual(body["season_totals"]["rush_yds"], 900)
        self.assertEqual(body["season_totals"]["rushing_first_downs"], 53)
        self.assertEqual(body["season_totals"]["receiving_first_downs"], 28)
        self.assertEqual(body["season_totals"]["fumbles"], 4)
        self.assertEqual(body["season_totals"]["fumbles_lost"], 2)
        self.assertEqual(body["season_totals"]["qbr"], 71.4)
        self.assertEqual(body["season_totals"]["passer_rating"], 104.2)
        self.assertEqual(body["season_totals"]["adj_qbr"], 72.1)
        self.assertEqual(body["season_totals"]["ppr_points"], 120.0)
        self.assertEqual(body["stat_rank_season"], 2025)
        self.assertEqual(body["stat_rank_games"], 12)
        self.assertEqual(body["stat_ranks"]["rush_yds_g"]["rank"], 1)

    def test_player_detail_keeps_profile_fields_null_on_legacy_row(self):
        resp = client.get("/api/nfl/draft/player/2")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertIsNone(body["season_outlook"])
        self.assertIsNone(body["season_totals"])
        self.assertIsNone(body["season_totals_source"])

    # ------------------------------------------------------------------
    #  Game log tabs
    # ------------------------------------------------------------------

    def test_game_log_tabs_declare_at_most_five_fields_each(self):
        """Every tab stays within the 8-column budget (Wk + Opp + anchor + 5),
        which is what keeps the view off the horizontal scrollbar."""
        for position, tabs in nfl_mock_draft._LOG_FIELDS.items():
            for tab in tabs:
                self.assertLessEqual(
                    len(tab["fields"]), 5,
                    f"{position}/{tab['id']} declares {len(tab['fields'])} fields",
                )
        for tab in nfl_mock_draft._DST_LOG_FIELDS:
            self.assertLessEqual(len(tab["fields"]), 5)

    def test_game_log_tab_fields_never_contain_the_anchor(self):
        """Wk, Opp and the points anchor are rendered by the component for
        every tab; a tab that also shipped one would print the column twice."""
        anchors = {"QB": "fpts_ppr", "RB": "fpts_ppr", "WR": "fpts_ppr",
                   "TE": "fpts_ppr", "FB": "fpts_ppr", "PK": None}
        for position, tabs in nfl_mock_draft._LOG_FIELDS.items():
            for tab in tabs:
                self.assertNotIn(anchors[position], tab["fields"])
        for tab in nfl_mock_draft._DST_LOG_FIELDS:
            self.assertNotIn("fantasy_pts", tab["fields"])

    def test_game_log_fields_is_the_ordered_union_of_the_tab_fields(self):
        """The published `fields` list is exactly the tabs' fields flattened in
        order, so the row-building code and the contract stay truthful."""
        for pid in (1, 2, 3, 5):  # RB, WR, QB, PK
            resp = client.get(f"/api/nfl/draft/player/{pid}/game-log")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            union = [f for tab in body["tabs"] for f in tab["fields"]]
            self.assertEqual(body["fields"], union, f"player {pid}")

    def test_game_log_publishes_the_expected_tabs_per_position(self):
        """QB / RB / WR / TE / PK each publish the ESPN-style tab set; the
        anchor follows the position (fpts_ppr for skill positions, null for
        PK, fantasy_pts for DEF)."""
        expected = {
            3: (["Passing", "Rushing", "Misc", "Usage"], "fpts_ppr"),   # QB
            1: (["Rushing", "Receiving", "Misc", "Usage"], "fpts_ppr"),  # RB
            2: (["Receiving", "Rushing", "Misc", "Usage"], "fpts_ppr"),  # WR
            4: (["Receiving", "Rushing", "Misc", "Usage"], "fpts_ppr"),  # TE
            5: (["Kicking"], None),                                       # PK
        }
        for pid, (labels, anchor) in expected.items():
            resp = client.get(f"/api/nfl/draft/player/{pid}/game-log")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertTrue(body["tabs"], f"player {pid} has no tabs")
            self.assertEqual(
                [t["label"] for t in body["tabs"]], labels, f"player {pid}"
            )
            self.assertEqual(body["anchor"], anchor, f"player {pid}")

    def test_game_log_publishes_def_tab(self):
        """D/ST anchor on fantasy_pts and ship a single Defense tab; even when
        per-week scoring is not loaded the tab shape is still published."""
        connection = nfl_mock_draft._conn()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO players "
                "(id, name, position, team, league, active) "
                "VALUES (9001, 'Delta DEF', 'DEF', 'SF', 'nfl', 1)"
            )
            connection.commit()
        finally:
            connection.close()
        resp = client.get("/api/nfl/draft/player/9001/game-log")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["tabs"])
        self.assertEqual([t["label"] for t in body["tabs"]], ["Defense"])
        self.assertEqual(body["anchor"], "fantasy_pts")
        self.assertEqual(
            body["fields"],
            [f for tab in body["tabs"] for f in tab["fields"]],
        )

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
