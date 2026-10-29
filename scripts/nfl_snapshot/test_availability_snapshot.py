"""Focused tests for the immutable NFL availability snapshot builder."""
import os
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import pandas as pd

from scripts.nfl_snapshot.availability_snapshot import build


FREEZE = "2026-10-20T17:00:00+00:00"
BEFORE_FREEZE = "2026-10-20T16:00:00+00:00"
AFTER_FREEZE = "2026-10-20T18:00:00+00:00"


class AvailabilitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.roster_path = os.path.join(self.root, "fixture_roster.parquet")
        self.db_path = os.path.join(self.root, "fixture_picks.sqlite")
        self.injury_path = os.path.join(self.root, "fixture_injuries.sqlite")
        self._write_roster()
        self._write_database()
        self._write_injuries()

    def _write_roster(self):
        rows = [
            ("Q", "BUF", "ACT"),
            ("D", "BUF", "ACT"),
            ("OUT", "BUF", "ACT"),
            ("MISSING", "BUF", "ACT"),
            ("NULL", "BUF", "ACT"),
            ("RES", "BUF", "RES"),
            ("CUT", "BUF", "CUT"),
            ("INA_Q", "BUF", "INA"),
            ("FUTURE", "BUF", "ACT"),
            ("TRADE", "SEA", "ACT"),
        ]
        pd.DataFrame(
            [
                {
                    "season": 2026,
                    "game_type": "REG",
                    "week": 8,
                    "team": team,
                    "gsis_id": gsis,
                    "full_name": f"Fixture {gsis}",
                    "position": "RB",
                    "status": status,
                }
                for gsis, team, status in rows
            ]
        ).to_parquet(self.roster_path, index=False)

    def _write_database(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript(
                """
                CREATE TABLE nfl_schedule (
                    game_id TEXT, season INTEGER, game_type TEXT, week INTEGER,
                    gameday TEXT, gametime TEXT, home_team TEXT, away_team TEXT,
                    ingested_at TEXT
                );
                INSERT INTO nfl_schedule VALUES
                    ('2026_08_MIA_BUF', 2026, 'REG', 8, '2026-10-20', '13:00',
                     'BUF', 'MIA', '2026-10-19T12:00:00Z'),
                    ('2026_08_SF_SEA', 2026, 'REG', 8, '2026-10-20', '16:00',
                     'SEA', 'SF', '2026-10-19T12:00:00Z');
                CREATE TABLE nfl_depth_chart (
                    season INTEGER, snapshot_at TEXT, team TEXT, gsis_id TEXT,
                    pos_abb TEXT, pos_rank INTEGER
                );
                """
            )

    def _write_injuries(self):
        rows = [
            ("Q", "BUF", "Questionable", BEFORE_FREEZE),
            ("D", "BUF", "Doubtful", BEFORE_FREEZE),
            ("OUT", "BUF", "Out", BEFORE_FREEZE),
            ("NULL", "BUF", None, BEFORE_FREEZE),
            ("INA_Q", "BUF", "Questionable", BEFORE_FREEZE),
            ("FUTURE", "BUF", "Out", AFTER_FREEZE),
            # Same GSIS ID, wrong team: exact-key lookup must not match this row.
            ("TRADE", "SF", "Questionable", BEFORE_FREEZE),
        ]
        with sqlite3.connect(self.injury_path) as con:
            con.executescript(
                """
                CREATE TABLE snapshot_runs (
                    status TEXT, season INTEGER, observed_at_utc TEXT
                );
                INSERT INTO snapshot_runs VALUES
                    ('ok', 2026, '2026-10-20T16:30:00+00:00');
                CREATE TABLE injury_snapshot_rows (
                    row_id INTEGER PRIMARY KEY, season INTEGER, game_type TEXT,
                    week INTEGER, team TEXT, gsis_id TEXT, report_status TEXT,
                    observed_at_utc TEXT, date_modified_as_published TEXT
                );
                """
            )
            con.executemany(
                "INSERT INTO injury_snapshot_rows "
                "(season, game_type, week, team, gsis_id, report_status, "
                "observed_at_utc, date_modified_as_published) "
                "VALUES (2026, 'REG', 8, ?, ?, ?, ?, NULL)",
                [(team, gsis, designation, observed) for gsis, team, designation, observed in rows],
            )

    def _args(self, store_dir):
        return Namespace(
            season=2026,
            week=8,
            roster_file=self.roster_path,
            injury_store=self.injury_path,
            db=self.db_path,
            freeze_time=FREEZE,
            store_dir=store_dir,
        )

    def _build(self, name="snapshot_store"):
        store_dir = os.path.join(self.root, name)
        body, path = build(self._args(store_dir))
        return body, path, store_dir

    def _player(self, body, gsis_id):
        return next(p for p in body["players"] if p["gsis_id"] == gsis_id)

    def test_questionable_is_included_and_flagged(self):
        body, _, _ = self._build()
        player = self._player(body, "Q")
        self.assertTrue(player["include"])
        self.assertEqual(player["decision"], "include_questionable")
        self.assertEqual(player["flags"], ["questionable"])

    def test_doubtful_is_excluded(self):
        body, _, _ = self._build()
        player = self._player(body, "D")
        self.assertFalse(player["include"])
        self.assertEqual(player["decision"], "exclude_doubtful")

    def test_out_is_excluded(self):
        body, _, _ = self._build()
        player = self._player(body, "OUT")
        self.assertFalse(player["include"])
        self.assertEqual(player["decision"], "exclude_out")

    def test_missing_report_is_included_and_flagged(self):
        body, _, _ = self._build()
        player = self._player(body, "MISSING")
        self.assertTrue(player["include"])
        self.assertEqual(player["decision"], "include_missing_report")
        self.assertEqual(player["flags"], ["missing_report"])

    def test_null_status_is_included_and_flagged(self):
        body, _, _ = self._build()
        player = self._player(body, "NULL")
        self.assertTrue(player["include"])
        self.assertEqual(player["designation"], "NULL")
        self.assertEqual(player["decision"], "include_unknown_status")
        self.assertEqual(player["flags"], ["unknown_status"])

    def test_res_and_cut_are_excluded_by_roster_status(self):
        body, _, _ = self._build()
        for gsis_id in ("RES", "CUT"):
            with self.subTest(gsis_id=gsis_id):
                player = self._player(body, gsis_id)
                self.assertFalse(player["include"])
                self.assertEqual(player["decision"], "exclude_roster_status")

    def test_ina_is_roster_membership_not_an_availability_decision(self):
        body, _, _ = self._build()
        player = self._player(body, "INA_Q")
        self.assertEqual(player["roster_status"], "INA")
        self.assertTrue(player["include"])
        self.assertEqual(player["decision"], "include_questionable")

    def test_observation_after_freeze_is_ignored(self):
        body, _, _ = self._build()
        player = self._player(body, "FUTURE")
        self.assertTrue(player["include"])
        self.assertIsNone(player["designation"])
        self.assertIsNone(player["designation_observed_at_utc"])
        self.assertEqual(player["decision"], "include_missing_report")

    def test_capture_after_freeze_does_not_replace_cutoff_eligible_run(self):
        with sqlite3.connect(self.injury_path) as con:
            con.execute("INSERT INTO snapshot_runs VALUES ('ok', 2026, ?)", (AFTER_FREEZE,))
        body, _, _ = self._build()
        self.assertEqual(body["provenance"]["injury_store_last_run_utc"], BEFORE_FREEZE)
        self.assertTrue(body["provenance"]["injury_capture_within_gap"])

    def test_trade_week_team_mismatch_does_not_match(self):
        body, _, _ = self._build()
        player = self._player(body, "TRADE")
        self.assertEqual(player["team"], "SEA")
        self.assertTrue(player["include"])
        self.assertIsNone(player["designation"])
        self.assertEqual(player["decision"], "include_missing_report")

    def test_second_build_at_same_freeze_refuses_to_rewrite(self):
        body, path, store_dir = self._build()
        original_bytes = Path(path).read_bytes()
        index_path = os.path.join(store_dir, "index.jsonl")
        original_index = Path(index_path).read_bytes()
        with self.assertRaisesRegex(SystemExit, "snapshot exists and is never rewritten"):
            build(self._args(store_dir))
        self.assertEqual(Path(path).read_bytes(), original_bytes)
        self.assertEqual(Path(index_path).read_bytes(), original_index)
        self.assertEqual(body["freeze_time_utc"], FREEZE)

    def test_content_hash_is_stable_for_identical_builds(self):
        first, _, _ = self._build("store_one")
        second, _, _ = self._build("store_two")
        self.assertEqual(first["content_sha256"], second["content_sha256"])


if __name__ == "__main__":
    unittest.main()
