#!/usr/bin/env python3
"""Deterministic contract tests for GET /api/nfl/usage/{player_id}.

Follows the existing style in test_league_stats_contract.py:
  - Isolated temp DB per test class
  - unittest.TestCase
  - Monkeypatch _db to point at the temp DB
  - Tests that need real data use the real dev DB
"""

import json
import os
import sqlite3
import tempfile
import unittest
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from routers import nfl_usage

# ── helpers ───────────────────────────────────────────────────────────


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _create_schema(path: str) -> None:
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, team TEXT, league TEXT NOT NULL,
                position TEXT
            );
            CREATE TABLE player_game_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER, league TEXT, season INTEGER,
                game_no TEXT, game_id TEXT, game_date TEXT,
                team TEXT, opponent TEXT, home_away TEXT,
                stats TEXT, source TEXT
            );
        """)


def _insert_player(path: str, player_id: int, name: str,
                   league: str = "nfl", team: str = "TST",
                   position: str = "WR") -> None:
    with _connect(path) as con:
        con.execute(
            "INSERT OR IGNORE INTO players(id, name, team, league, position) VALUES (?,?,?,?,?)",
            (player_id, name, team, league, position),
        )


def _insert_log(path: str, player_id: int, season: int,
                game_no: str, team: str, opponent: str, stats: dict,
                game_id: Optional[str] = None, source: str = "nflverse_pbp") -> None:
    with _connect(path) as con:
        con.execute(
            "INSERT INTO player_game_logs(player_id, league, season, game_no, game_id, team, opponent, stats, source) "
            "VALUES (?, 'nfl', ?, ?, ?, ?, ?, ?, ?)",
            (player_id, season, game_no, game_id, team, opponent, json.dumps(stats), source),
        )


def _sum_target_shares(case, player_weeks, season: int) -> float:
    """Sum target_share for each (player_id, week) pair in one team-game.

    Games come back most-recent-first, so the requested week has to be located
    by its "week" field.  Asking for weeks=1 and reading games[0] returns the
    player's LAST game of the season, not the one under test.
    """
    total = 0.0
    for player_id, week in player_weeks:
        result = nfl_usage.nfl_usage(player_id, season=season, weeks=18)
        game = next((g for g in result["games"] if g["week"] == week), None)
        case.assertIsNotNone(
            game, f"player {player_id} has no week {week} game in {season}")
        share = game["target_share"]
        case.assertIsNotNone(
            share, f"player {player_id} week {week} had targets but no target_share")
        total += share
    return total


# ── tests ─────────────────────────────────────────────────────────────


class NflUsageIsolatedTests(unittest.TestCase):
    """Tests using an isolated temp DB (no dependency on dev data)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "usage.db")
        _create_schema(self.db_path)
        self._orig_db = nfl_usage._db
        nfl_usage._db = lambda: _connect(self.db_path)
        app = FastAPI()
        app.include_router(nfl_usage.router)
        self.client = TestClient(app)

    def tearDown(self):
        nfl_usage._db = self._orig_db
        self.tmp.cleanup()

    # ── 2. 2024 vocabulary resolves ──────────────────────────────────

    def test_2024_vocabulary_resolves(self):
        """A 2024 (nflverse) receiver must return non-null rec_yds."""
        _insert_player(self.db_path, 100, "Test WR", "nfl", "TST", "WR")
        stats_2024 = {
            "targets": 8,
            "receiving_yards": 95,
            "receptions": 6,
            "receiving_tds": 1,
            "fantasy_points_ppr": 21.5,
            "off_snaps": 55,
            "off_pct": 0.82,
            "air_yds_share": 35.0,
            "adot": 9.2,
        }
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 100, 2024, g, "TST", "OPP", stats_2024,
                        source="nflverse")
        # Teammate for target share
        _insert_player(self.db_path, 101, "Teammate", "nfl", "TST", "TE")
        _insert_log(self.db_path, 101, 2024, "1", "TST", "OPP",
                    {"targets": 2, "off_snaps": 20, "off_pct": 0.3},
                    source="nflverse")

        result = nfl_usage.nfl_usage(100, season=2024, weeks=4)
        self.assertEqual(result["games"][0]["rec_yds"], 95.0,
                         "2024 receiving_yards must resolve to rec_yds")
        self.assertEqual(result["games"][0]["rec"], 6.0,
                         "2024 receptions must resolve to rec")
        self.assertEqual(result["games"][0]["rec_td"], 1.0,
                         "2024 receiving_tds must resolve to rec_td")
        self.assertEqual(result["games"][0]["fpts_ppr"], 21.5,
                         "2024 fantasy_points_ppr must resolve to fpts_ppr")

    # ── 3. WOPR matches formula ──────────────────────────────────────

    def test_wopr_matches_formula(self):
        """WOPR = 1.5 * target_share + 0.7 * (air_yds_share / 100)."""
        _insert_player(self.db_path, 200, "Wopr WR", "nfl", "TST", "WR")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 200, 2025, g, "TST", "OPP", {
                "targets": 5, "off_snaps": 50, "off_pct": 0.75,
                "air_yds_share": 40.0, "adot": 12.0,
            })
        # Teammate for target share denominator
        _insert_player(self.db_path, 201, "Teammate2", "nfl", "TST", "RB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 201, 2025, g, "TST", "OPP",
                        {"targets": 5, "off_snaps": 20, "off_pct": 0.3})

        result = nfl_usage.nfl_usage(200, season=2025, weeks=4)
        game = result["games"][0]
        self.assertAlmostEqual(game["target_share"], 0.5, places=2)
        self.assertAlmostEqual(game["air_yds_share"], 40.0, places=1)
        self.assertAlmostEqual(game["wopr"], 1.03, places=2)

    # ── 4. Null preservation ─────────────────────────────────────────

    def test_null_preservation_air_yds_share(self):
        """A row lacking air_yds_share returns null, and wopr is null."""
        _insert_player(self.db_path, 300, "RB NoAir", "nfl", "TST", "RB")
        for g, dat in [("1", {"targets": 2, "off_snaps": 20, "off_pct": 0.35, "rush_yds": 45}),
                        ("2", {"targets": 1, "off_snaps": 18, "off_pct": 0.30, "rush_yds": 30}),
                        ("3", {"targets": 3, "off_snaps": 22, "off_pct": 0.38, "rush_yds": 55}),
                        ("4", {"targets": 0, "off_snaps": 15, "off_pct": 0.25, "rush_yds": 20})]:
            _insert_log(self.db_path, 300, 2025, g, "TST", "OPP", dat)
        # Teammate
        _insert_player(self.db_path, 301, "Teammate3", "nfl", "TST", "TE")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 301, 2025, g, "TST", "OPP",
                        {"targets": 4, "off_snaps": 30, "off_pct": 0.5})

        result = nfl_usage.nfl_usage(300, season=2025, weeks=4)
        # Most recent game first (week 4): snaps=15, snap_share=0.25
        game = result["games"][0]
        self.assertIsNone(game["air_yds_share"],
                          "air_yds_share must be null for non-receiver")
        self.assertIsNone(game["wopr"],
                          "wopr must be null when air_yds_share is absent")
        self.assertEqual(game["snaps"], 15.0)
        self.assertAlmostEqual(game["snap_share"], 0.25, places=2)

    # ── 5. Empty case ────────────────────────────────────────────────

    def test_empty_nfl_player_no_logs(self):
        """NFL player with no game logs returns 200 with games: []."""
        _insert_player(self.db_path, 400, "Ghost Player", "nfl", "TST", "WR")
        result = nfl_usage.nfl_usage(400, season=None, weeks=8)
        self.assertEqual(result["season"], None)
        self.assertEqual(result["games"], [])
        self.assertIsNone(result["averages"]["snap_share"])
        self.assertIsNone(result["averages"]["target_share"])
        self.assertIsNone(result["averages"]["wopr"])
        self.assertIsNone(result["trend"]["snap_share"])

    # ── 6. Non-NFL player returns 400 ────────────────────────────────

    def test_non_nfl_player_400(self):
        """A non-NFL player raises HTTP 400."""
        _insert_player(self.db_path, 500, "MLB Guy", "mlb", "NYM", "P")
        with self.assertRaises(HTTPException) as ctx:
            nfl_usage.nfl_usage(500, season=None, weeks=8)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "NFL only")

    # ── 7. weeks cap ─────────────────────────────────────────────────

    def test_weeks_cap(self):
        """Requesting weeks=99 returns at most 18 games."""
        _insert_player(self.db_path, 600, "Many Games", "nfl", "TST", "WR")
        for g in range(1, 21):
            _insert_log(self.db_path, 600, 2025, str(g), "TST", "OPP", {
                "targets": 4, "off_snaps": 40, "off_pct": 0.65,
                "air_yds_share": 25.0, "adot": 8.0,
            })
        _insert_player(self.db_path, 601, "Teammate4", "nfl", "TST", "TE")
        for g in range(1, 21):
            _insert_log(self.db_path, 601, 2025, str(g), "TST", "OPP",
                        {"targets": 4, "off_snaps": 30, "off_pct": 0.5})

        result = nfl_usage.nfl_usage(600, season=2025, weeks=99)
        self.assertLessEqual(len(result["games"]), 18,
                            "weeks=99 must be capped at 18")
        self.assertEqual(len(result["games"]), 18)

    # ── 7b. weeks bounds over HTTP ───────────────────────────────────

    def test_weeks_bounds_enforced_over_http(self):
        """Over HTTP the Query bounds reject weeks outside 1..18 with 422.

        The direct-call cap in test_weeks_cap is defensive; FastAPI never lets
        an out-of-range value reach it, so the contract must be asserted here.
        """
        _insert_player(self.db_path, 700, "Api WR", "nfl", "TST", "WR")
        for g in range(1, 21):
            _insert_log(self.db_path, 700, 2025, str(g), "TST", "OPP", {
                "targets": 4, "off_snaps": 40, "off_pct": 0.65,
                "air_yds_share": 25.0, "adot": 8.0,
            })

        for bad in (99, 19, 0, -1):
            with self.subTest(weeks=bad):
                r = self.client.get("/api/nfl/usage/700",
                                    params={"season": 2025, "weeks": bad})
                self.assertEqual(r.status_code, 422,
                                 f"weeks={bad} must be rejected by the API")

        # 18 is the inclusive upper bound and must be accepted.
        r = self.client.get("/api/nfl/usage/700",
                            params={"season": 2025, "weeks": 18})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["games"]), 18)

    # ── 8. Carry share partitions the backfield ──────────────────────

    def test_carry_share_partitions_backfield(self):
        """carry_share is the runner's cut of the team's carries in that game."""
        _insert_player(self.db_path, 800, "Lead Back", "nfl", "TST", "RB")
        _insert_player(self.db_path, 801, "Change Up", "nfl", "TST", "RB")
        _insert_player(self.db_path, 802, "Scrambler", "nfl", "TST", "QB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 800, 2025, g, "TST", "OPP",
                        {"carries": 15, "rush_yds": 70, "off_snaps": 40, "off_pct": 0.62})
            _insert_log(self.db_path, 801, 2025, g, "TST", "OPP",
                        {"carries": 4, "rush_yds": 18, "off_snaps": 14, "off_pct": 0.22})
            _insert_log(self.db_path, 802, 2025, g, "TST", "OPP",
                        {"carries": 1, "rush_yds": 3, "off_snaps": 65, "off_pct": 1.0})

        lead = nfl_usage.nfl_usage(800, season=2025, weeks=4)["games"][0]
        backup = nfl_usage.nfl_usage(801, season=2025, weeks=4)["games"][0]
        qb = nfl_usage.nfl_usage(802, season=2025, weeks=4)["games"][0]

        self.assertAlmostEqual(lead["carry_share"], 0.75, places=3)
        self.assertAlmostEqual(backup["carry_share"], 0.20, places=3)
        self.assertAlmostEqual(qb["carry_share"], 0.05, places=3)
        # The quarterback's carries count against the denominator, so the
        # backfield alone must not sum to 1.0.
        self.assertAlmostEqual(
            lead["carry_share"] + backup["carry_share"] + qb["carry_share"],
            1.0, places=3)

    def test_carry_share_null_without_carries(self):
        """A receiver who never runs gets null, not zero — he has no backfield role."""
        _insert_player(self.db_path, 810, "Pure WR", "nfl", "TST", "WR")
        _insert_player(self.db_path, 811, "The Back", "nfl", "TST", "RB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 810, 2025, g, "TST", "OPP",
                        {"targets": 9, "rec": 6, "off_snaps": 58, "off_pct": 0.9})
            _insert_log(self.db_path, 811, 2025, g, "TST", "OPP",
                        {"carries": 20, "off_snaps": 40, "off_pct": 0.62})

        wr = nfl_usage.nfl_usage(810, season=2025, weeks=4)["games"][0]
        self.assertIsNone(wr["carries"])
        self.assertIsNone(wr["carry_share"],
                          "no carries must read as null, not a 0.0 share")

    # ── 9. Next Gen / play-by-play passthrough ───────────────────────

    def test_advanced_stats_passthrough(self):
        """separation/cushion/yac_above_exp/cpoe/pass_epa/st reach the response."""
        _insert_player(self.db_path, 820, "Ngs WR", "nfl", "TST", "WR")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 820, 2025, g, "TST", "OPP", {
                "targets": 7, "off_snaps": 50, "off_pct": 0.8,
                "separation": 3.1, "cushion": 6.4, "yac_above_exp": -0.8,
                "st_snaps": 4, "st_pct": 0.15,
            })

        game = nfl_usage.nfl_usage(820, season=2025, weeks=4)["games"][0]
        self.assertAlmostEqual(game["separation"], 3.1, places=2)
        self.assertAlmostEqual(game["cushion"], 6.4, places=2)
        self.assertAlmostEqual(game["yac_above_exp"], -0.8, places=2,
                               msg="a negative NGS value must survive, not clamp to 0")
        self.assertAlmostEqual(game["st_pct"], 0.15, places=2)
        self.assertEqual(game["st_snaps"], 4.0)
        # Passing metrics belong to a different phase and stay null for a WR.
        self.assertIsNone(game["cpoe"])
        self.assertIsNone(game["pass_epa"])

    def test_advanced_stats_absent_are_null(self):
        """A 2024 row carries none of these; every advanced key must be null."""
        _insert_player(self.db_path, 830, "Legacy WR", "nfl", "TST", "WR")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 830, 2024, g, "TST", "OPP", {
                "targets": 6, "receiving_yards": 71, "receptions": 5,
                "off_snaps": 48, "off_pct": 0.77,
            }, source="nflverse")

        game = nfl_usage.nfl_usage(830, season=2024, weeks=4)["games"][0]
        for key in ("separation", "cushion", "yac_above_exp", "cpoe",
                    "pass_epa", "st_snaps", "st_pct", "epa_per_db"):
            self.assertIsNone(game[key], f"{key} must be null on a 2024 row")

    # ── 10. EPA per dropback ─────────────────────────────────────────

    def test_epa_per_dropback_prefers_dropbacks_over_attempts(self):
        """`att` was only ever the right denominator by accident, back when the
        ingest counted sacks as attempts. A sacked quarterback has more
        dropbacks than attempts, and the rate must use the larger number."""
        _insert_player(self.db_path, 841, "Sacked QB", "nfl", "TST", "QB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 841, 2025, g, "TST", "OPP", {
                "att": 30, "dropbacks": 35, "cmp": 20, "pass_yds": 210,
                "pass_epa": 7.0, "off_snaps": 60, "off_pct": 1.0,
            })
        game = nfl_usage.nfl_usage(841, season=2025, weeks=4)["games"][0]
        self.assertAlmostEqual(game["epa_per_db"], 0.2, places=3)   # 7.0 / 35
        self.assertNotAlmostEqual(game["epa_per_db"], 7.0 / 30, places=3)
        # The displayed attempt count stays the official one.
        self.assertEqual(game["pass_att"], 30.0)

    def test_epa_per_dropback_divides_by_attempts(self):
        """pass_epa is a game total; the response also carries it per attempt."""
        _insert_player(self.db_path, 840, "Starter QB", "nfl", "TST", "QB")
        for g, att, epa in [("1", 40, 12.0), ("2", 20, 6.0),
                            ("3", 30, -9.0), ("4", 25, 5.0)]:
            _insert_log(self.db_path, 840, 2025, g, "TST", "OPP", {
                "att": att, "cmp": att - 8, "pass_yds": att * 7,
                "pass_epa": epa, "cpoe": 2.5,
                "off_snaps": 60, "off_pct": 1.0,
            })

        games = {g["week"]: g for g in
                 nfl_usage.nfl_usage(840, season=2025, weeks=4)["games"]}
        # Same total EPA over half the attempts is twice the rate.
        self.assertAlmostEqual(games[1]["epa_per_db"], 0.3, places=3)
        self.assertAlmostEqual(games[2]["epa_per_db"], 0.3, places=3)
        self.assertEqual(games[1]["pass_att"], 40.0)
        self.assertEqual(games[2]["pass_att"], 20.0)
        # A negative game must stay negative.
        self.assertAlmostEqual(games[3]["epa_per_db"], -0.3, places=3)

    def test_epa_per_dropback_null_without_attempts(self):
        """No attempts means no dropbacks — a rate, not a divide-by-zero."""
        _insert_player(self.db_path, 850, "Wildcat RB", "nfl", "TST", "RB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 850, 2025, g, "TST", "OPP", {
                "carries": 12, "rush_yds": 50, "pass_epa": 1.4,
                "off_snaps": 35, "off_pct": 0.55,
            })

        game = nfl_usage.nfl_usage(850, season=2025, weeks=4)["games"][0]
        self.assertIsNone(game["pass_att"])
        self.assertAlmostEqual(game["pass_epa"], 1.4, places=2)
        self.assertIsNone(game["epa_per_db"],
                          "pass_epa with zero attempts must not divide")

    def test_epa_per_dropback_reads_2024_attempts_key(self):
        """2024 spells attempts `attempts`; pass_att must still resolve.

        pass_epa itself is 2025-only, so epa_per_db stays null here — the point
        is that the attempt count is not lost to the vocabulary split.
        """
        _insert_player(self.db_path, 860, "Legacy QB", "nfl", "TST", "QB")
        for g in ["1", "2", "3", "4"]:
            _insert_log(self.db_path, 860, 2024, g, "TST", "OPP", {
                "attempts": 33, "completions": 22, "passing_yards": 260,
                "off_snaps": 62, "off_pct": 1.0,
            }, source="nflverse")

        game = nfl_usage.nfl_usage(860, season=2024, weeks=4)["games"][0]
        self.assertEqual(game["pass_att"], 33.0,
                         "2024 `attempts` must resolve to pass_att")
        self.assertIsNone(game["epa_per_db"])

    # ── 11. The team-sum whitelist ───────────────────────────────────

    def test_team_stat_sums_rejects_unlisted_key(self):
        """_fetch_team_stat_sums interpolates its key into SQL, so it is a whitelist."""
        _insert_player(self.db_path, 870, "Sum WR", "nfl", "TST", "WR")
        _insert_log(self.db_path, 870, 2025, "1", "TST", "OPP", {"targets": 6})
        keys = [(2025, "1", None, "TST")]  # (season, game_no, game_id, team)
        with _connect(self.db_path) as con:
            listed = nfl_usage._fetch_team_stat_sums(con, keys, "targets")
            self.assertEqual(list(listed.values()), [6.0],
                             "a listed key sums normally")
            for unlisted in ("rec_yds", "targets') + 1 --", ""):
                with self.subTest(stat=unlisted):
                    with self.assertRaises(ValueError):
                        nfl_usage._fetch_team_stat_sums(con, keys, unlisted)


def _dev_db_path() -> str:
    """The database these tests mean, resolved without trusting _core.

    _core binds its module-level DB at import, and several sibling suites point
    LP_DB_PATH at a throwaway file before importing the app. In a whole-suite run
    whichever of them imports first decides where _core._db connects, so reusing
    it made these tests read an empty temp database and fail with "no such table:
    player_game_logs" — but only when the full suite ran, never file by file.
    conftest.py keeps the environment variable honest; this resolves the path
    from it rather than from _core's frozen copy.
    """
    return os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")


class NflUsageRealDBTests(unittest.TestCase):
    """Tests against the real dev DB that need actual multi-player data."""

    def setUp(self):
        self._orig_db = nfl_usage._db
        path = _dev_db_path()
        if not os.path.exists(path):
            self.skipTest(f"dev database not present at {path}")
        nfl_usage._db = lambda: _connect(path)

    def tearDown(self):
        nfl_usage._db = self._orig_db

    # ── 1. Target share sums to ~1.0 ─────────────────────────────────

    def test_target_share_sums_to_one(self):
        """2024 fallback partition: every targeted player in one team-game sums to ~1.0.

        2024 rows have no game_id, so this exercises the (season, game_no, team)
        fallback.  Every player with targets > 0 must be included — a subset
        would not sum to 1.0 and would make the assertion meaningless.
        """
        db_path = _dev_db_path()
        with _connect(db_path) as con:
            rows = con.execute(
                """SELECT player_id FROM player_game_logs
                   WHERE league='nfl' AND season=2024 AND game_no='1' AND team='NO'
                   AND json_extract(stats, '$.targets') > 0"""
            ).fetchall()

        self.assertGreaterEqual(
            len(rows), 3,
            "Need the full targeted receiving corps for 2024 NO wk 1")

        total_share = _sum_target_shares(
            self, [(r["player_id"], 1) for r in rows], season=2024)
        self.assertAlmostEqual(
            total_share, 1.0, delta=0.02,
            msg=f"Sum of target shares across {len(rows)} NO players "
                f"was {total_share:.4f}, expected ~1.0")

    # ── 1b. Full target share sum for all players in a team-game ─────

    def test_target_share_full_sum(self):
        """2025 game_id partition: target shares in a real team-game sum to ~1.0.

        The team-game is chosen from the data rather than hardcoded — a fixed
        game_id silently skipped this test when that id was absent.
        """
        db_path = _dev_db_path()
        with _connect(db_path) as con:
            pick = con.execute(
                """SELECT game_id, team FROM player_game_logs
                   WHERE league='nfl' AND season=2025 AND game_id IS NOT NULL
                   AND json_extract(stats, '$.targets') > 0
                   GROUP BY game_id, team
                   HAVING COUNT(*) >= 3
                   ORDER BY game_id LIMIT 1"""
            ).fetchone()

            self.assertIsNotNone(
                pick, "No 2025 team-game with >=3 targeted players in the dev DB")

            rows = con.execute(
                """SELECT player_id, game_no FROM player_game_logs
                   WHERE league='nfl' AND season=2025 AND game_id=? AND team=?
                   AND json_extract(stats, '$.targets') > 0""",
                (pick["game_id"], pick["team"]),
            ).fetchall()

        total_share = _sum_target_shares(
            self, [(r["player_id"], int(r["game_no"])) for r in rows], season=2025)
        self.assertAlmostEqual(
            total_share, 1.0, delta=0.02,
            msg=f"Sum of target shares across {len(rows)} {pick['team']} players "
                f"in game {pick['game_id']} was {total_share:.4f}, expected ~1.0")

    # ── 2b. 2024 vocabulary against real data ────────────────────────

    def test_2024_returns_populated_yards(self):
        """Real 2024 receiver must have non-null rec_yds, proving COALESCE works."""
        result = nfl_usage.nfl_usage(187, season=2024, weeks=8)
        self.assertGreater(len(result["games"]), 0)
        for g in result["games"]:
            if g["targets"] is not None and g["targets"] > 0:
                self.assertIsNotNone(g["rec_yds"],
                                     f"Week {g['week']}: rec_yds must not be null for a 2024 WR")
                break
        else:
            self.skipTest("Davante Adams had no targets in first 8 weeks")


if __name__ == "__main__":
    unittest.main()
