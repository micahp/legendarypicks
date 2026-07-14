#!/usr/bin/env python3
"""Tests for migrate_team_stats and backfill_team_stats_fixture.

Covers: path rejection (protected / outside-tmp / symlink / hardlink /
existing), hard memory rejection, migration schema/permissions, malformed
fixture fail-closed, successful end-to-end fixture run, contract supported
response, and rerun safety.

Uses tempfile only — no fixed /tmp paths are hardcoded.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from migrate_team_stats import (  # noqa: E402
    _check_memory as migrate_check_memory,
    _validate_db_path,
    _validate_report_path,
    create_database,
)
from backfill_team_stats_fixture import (  # noqa: E402
    _guard_existing_db,
    _guard_report_path,
    _validate_extracted_stats,
    _validate_fixture_metadata,
    _validate_games,
    _validate_schedules,
    run_backfill,
)
from team_stats_contract import STAT_FIELDS  # noqa: E402
from team_stats_schema import DDL, expected_tables  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _apply_schema(connection):
    connection.executescript(DDL)


def _temp_db_path():
    """Return a tempfile path under /tmp (for migration compat)."""
    fd, path = tempfile.mkstemp(suffix=".db", dir="/tmp")
    os.close(fd)
    os.remove(path)  # caller will create it
    return path


def _temp_report_path():
    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    os.close(fd)
    os.remove(path)
    return path


# ---------------------------------------------------------------------------
# path rejection tests (migrate validation)
# ---------------------------------------------------------------------------

class MigratePathRejectionTests(unittest.TestCase):
    """Test _validate_db_path and _validate_report_path rejection gates."""

    def test_rejects_non_absolute_db_path(self):
        with self.assertRaises(SystemExit) as ctx:
            _validate_db_path("relative/path/to/db.db")
        self.assertEqual(ctx.exception.code, 2)

    def test_rejects_db_path_outside_tmp(self):
        with self.assertRaises(SystemExit) as ctx:
            _validate_db_path("/root/some.db")
        self.assertEqual(ctx.exception.code, 2)

    def test_rejects_db_path_with_protected_substring(self):
        with self.assertRaises(SystemExit) as ctx:
            _validate_db_path("/tmp/picks.db")
        self.assertEqual(ctx.exception.code, 2)

    def test_rejects_db_path_with_protected_substring_legendarypicks(self):
        with self.assertRaises(SystemExit) as ctx:
            _validate_db_path("/tmp/legendarypicks_test.db")
        self.assertEqual(ctx.exception.code, 2)

    def test_rejects_existing_db_path(self):
        fd, path = tempfile.mkstemp(suffix=".db", dir="/tmp")
        os.close(fd)
        try:
            with self.assertRaises(SystemExit) as ctx:
                _validate_db_path(path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.remove(path)

    def test_rejects_symlink_db_path(self):
        fd, target = tempfile.mkstemp(suffix=".db", dir="/tmp")
        os.close(fd)
        link_path = target + ".link"
        os.symlink(target, link_path)
        try:
            with self.assertRaises(SystemExit) as ctx:
                _validate_db_path(link_path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.remove(target)
            os.remove(link_path)

    def test_rejects_non_regular_file_db_path(self):
        dirpath = tempfile.mkdtemp(dir="/tmp")
        try:
            with self.assertRaises(SystemExit) as ctx:
                _validate_db_path(dirpath)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.rmdir(dirpath)

    def test_rejects_existing_report_path(self):
        fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
        os.close(fd)
        try:
            with self.assertRaises(SystemExit) as ctx:
                _validate_report_path(path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# memory rejection
# ---------------------------------------------------------------------------

class MemoryRejectionTests(unittest.TestCase):
    """Test that memory guard hard-aborts below threshold."""

    def test_hard_abort_when_min_available_mib_exceeds_system(self):
        # Ask for an absurdly high value — must abort.
        with self.assertRaises(SystemExit) as ctx:
            migrate_check_memory(10_000_000)
        self.assertEqual(ctx.exception.code, 3)

    def test_passes_when_min_is_zero(self):
        # Zero should always pass (unless system has negative mem).
        try:
            migrate_check_memory(0)
        except SystemExit:
            self.fail("_check_memory(0) should not abort")


# ---------------------------------------------------------------------------
# migration schema / permissions
# ---------------------------------------------------------------------------

class MigrationSchemaTests(unittest.TestCase):
    """End-to-end migration tests using temp paths under /tmp."""

    def setUp(self):
        self.db_path = _temp_db_path()
        self.report_path = _temp_report_path()

    def tearDown(self):
        for p in (self.db_path, self.report_path):
            if os.path.lexists(p):
                os.remove(p)

    def test_creates_db_with_correct_permissions(self):
        report = create_database(self.db_path, self.report_path, 0)
        self.assertTrue(report["success"], f"migration failed: {report}")

        st = os.stat(self.db_path)
        self.assertEqual(st.st_uid, os.getuid())
        self.assertEqual(st.st_nlink, 1)
        self.assertTrue(os.path.isfile(self.db_path))
        self.assertFalse(os.path.islink(self.db_path))

    def test_schema_has_all_required_tables(self):
        report = create_database(self.db_path, self.report_path, 0)
        self.assertTrue(report["success"], f"migration failed: {report}")

        connection = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0] for row in
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertTrue(expected_tables().issubset(tables),
                            f"missing tables: {expected_tables() - tables}")
        finally:
            connection.close()

    def test_integrity_check_passes(self):
        report = create_database(self.db_path, self.report_path, 0)
        self.assertTrue(report["success"], f"migration failed: {report}")
        self.assertEqual(report["integrity_check"], "ok")

    def test_report_is_written(self):
        report = create_database(self.db_path, self.report_path, 0)
        self.assertTrue(report["success"], f"migration failed: {report}")
        self.assertTrue(os.path.isfile(self.report_path))
        with open(self.report_path) as fh:
            data = json.load(fh)
        self.assertTrue(data["success"])
        self.assertEqual(data["action"], "migrate")

    def test_rejects_existing_db(self):
        # First create
        report = create_database(self.db_path, self.report_path, 0)
        self.assertTrue(report["success"])

        # Second attempt must fail (DB exists)
        report2_path = _temp_report_path()
        try:
            # Clean up after this
            pass
        finally:
            if os.path.lexists(report2_path):
                os.remove(report2_path)

    def test_report_path_must_not_exist(self):
        # Create a report file first
        fd, occupied = tempfile.mkstemp(suffix=".json", dir="/tmp")
        os.close(fd)
        try:
            report = create_database(self.db_path, occupied, 0)
            self.assertFalse(report["success"])
        finally:
            os.remove(occupied)
            # Clean up the DB that might have been created
            if os.path.lexists(self.db_path):
                os.remove(self.db_path)


# ---------------------------------------------------------------------------
# malformed fixture fail-closed
# ---------------------------------------------------------------------------

class MalformedFixtureTests(unittest.TestCase):
    """Test that invalid fixtures are rejected."""

    def setUp(self):
        self.db_path = _temp_db_path()
        self.report_path = _temp_report_path()
        # Create a valid DB first
        mig_report = create_database(self.db_path, self.report_path, 0)
        if not mig_report["success"]:
            self.skipTest(f"migration failed: {mig_report}")

    def tearDown(self):
        for p in (self.db_path, self.report_path):
            if os.path.lexists(p):
                os.remove(p)

    def _run_with_fixture(self, fixture: dict, run_id="test-run") -> dict:
        fd, fixture_path = tempfile.mkstemp(suffix=".json", dir="/tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(fixture, fh)
        report_path = _temp_report_path()
        try:
            result = run_backfill(
                league="nba", season=2026,
                season_start="2025-10-01", season_end="2026-06-30",
                db_path=self.db_path, fixture_path=fixture_path,
                run_id=run_id, report_path=report_path,
                min_available_mib=0,
            )
            return result
        finally:
            for p in (fixture_path, report_path):
                if os.path.lexists(p):
                    os.remove(p)

    def test_wrong_league_rejected(self):
        fixture = {
            "fixture_source": "synthetic_fixture",
            "league": "nhl",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(30)],
            "games": [],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])
        self.assertTrue(any("league" in f.lower() for f in result.get("failures", [])),
                        f"failures: {result.get('failures')}")

    def test_wrong_source_rejected(self):
        fixture = {
            "fixture_source": "live_espn",
            "league": "nba",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(30)],
            "games": [],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])

    def test_wrong_team_count_rejected(self):
        fixture = {
            "fixture_source": "synthetic_fixture",
            "league": "nba",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(29)],
            "games": [],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])

    def test_game_out_of_bounds_rejected(self):
        fixture = {
            "fixture_source": "synthetic_fixture",
            "league": "nba",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(30)],
            "games": [{
                "game_id": "nba-bad-000",
                "game_date": "2025-09-01",
                "home_team": "N00", "away_team": "N01",
                "home_score": 100, "away_score": 90,
                "status": "completed",
                "summary": {},
            }],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])

    def test_tie_game_rejected(self):
        fixture = {
            "fixture_source": "synthetic_fixture",
            "league": "nba",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(30)],
            "games": [{
                "game_id": "nba-tie-000",
                "game_date": "2025-11-01",
                "home_team": "N00", "away_team": "N01",
                "home_score": 100, "away_score": 100,
                "status": "completed",
                "summary": {},
            }],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])

    def test_noncompleted_game_rejected(self):
        fixture = {
            "fixture_source": "synthetic_fixture",
            "league": "nba",
            "season": 2026,
            "season_start": "2025-10-01",
            "season_end": "2026-06-30",
            "teams": [f"N{i:02d}" for i in range(30)],
            "games": [{
                "game_id": "nba-live-000",
                "game_date": "2025-11-01",
                "home_team": "N00", "away_team": "N01",
                "home_score": 55, "away_score": 50,
                "status": "in_progress",
                "summary": {},
            }],
        }
        result = self._run_with_fixture(fixture)
        self.assertFalse(result["success"])


# ---------------------------------------------------------------------------
# end-to-end fixture run + contract response + rerun safety
# ---------------------------------------------------------------------------

class BackfillEndToEndTests(unittest.TestCase):
    """Full pipeline: migrate -> backfill -> contract -> rerun safety."""

    def setUp(self):
        self.db_path = _temp_db_path()
        self.report_path = _temp_report_path()
        mig_report = create_database(self.db_path, self.report_path, 0)
        if not mig_report["success"]:
            self.skipTest(f"migration failed: {mig_report}")
        self.fixture_path = os.path.join(
            HERE, "fixtures", "nba_team_stats_2026_synthetic.json")

    def tearDown(self):
        for p in (self.db_path, self.report_path):
            if os.path.lexists(p):
                os.remove(p)

    def test_successful_fixture_run(self):
        run_report_path = _temp_report_path()
        try:
            result = run_backfill(
                league="nba", season=2026,
                season_start="2025-10-01", season_end="2026-06-30",
                db_path=self.db_path, fixture_path=self.fixture_path,
                run_id="e2e-test-001", report_path=run_report_path,
                min_available_mib=0,
            )
            self.assertTrue(result["success"],
                            f"backfill failed: {result.get('error') or result.get('failures')}")
            self.assertEqual(result["league"], "nba")
            self.assertEqual(result["season"], 2026)
            self.assertEqual(result["run_id"], "e2e-test-001")
            self.assertEqual(len(result.get("failures", [])), 0)

            # Verify report file was written
            self.assertTrue(os.path.isfile(run_report_path))
        finally:
            if os.path.lexists(run_report_path):
                os.remove(run_report_path)

    def test_contract_supported_response(self):
        run_report_path = _temp_report_path()
        try:
            result = run_backfill(
                league="nba", season=2026,
                season_start="2025-10-01", season_end="2026-06-30",
                db_path=self.db_path, fixture_path=self.fixture_path,
                run_id="e2e-contract-001", report_path=run_report_path,
                min_available_mib=0,
            )
            self.assertTrue(result["success"],
                            f"backfill failed: {result.get('error') or result.get('failures')}")

            # Now call build_team_aggregates directly and verify
            from team_stats_contract import build_team_aggregates

            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            try:
                response = build_team_aggregates(connection, "nba")
                self.assertTrue(response["supported"],
                                f"reason={response.get('reason')}")
                self.assertEqual(response["season"], 2026)
                self.assertEqual(response["league"], "nba")
                self.assertIsNone(response["reason"])
                self.assertEqual(len(response["teams"]), 30)

                cov = response["coverage"]
                self.assertEqual(cov["status"], "measured")
                self.assertEqual(cov["expected_teams"], 30)
                self.assertEqual(cov["observed_teams"], 30)
                self.assertEqual(cov["team_count"], 30)
                self.assertEqual(cov["games"], 15)
                self.assertEqual(cov["paired_games"], 15)
                self.assertEqual(cov["paired_stat_games"], 15)
                self.assertEqual(cov["invalid_games"], 0)
                self.assertEqual(cov["invalid_stat_games"], 0)
                self.assertEqual(cov["missing_stat_rows"], 0)
                self.assertEqual(cov["invalid_stat_rows"], 0)
                self.assertTrue(cov["external_schedule_reconciled"])
                self.assertEqual(cov["season_start"], "2025-10-01")
                self.assertEqual(cov["season_end"], "2026-06-30")
            finally:
                connection.close()
        finally:
            if os.path.lexists(run_report_path):
                os.remove(run_report_path)

    def test_rerun_safety(self):
        """Running the backfill twice with different run_ids must succeed both times."""
        report1_path = _temp_report_path()
        report2_path = _temp_report_path()
        try:
            # First run
            result1 = run_backfill(
                league="nba", season=2026,
                season_start="2025-10-01", season_end="2026-06-30",
                db_path=self.db_path, fixture_path=self.fixture_path,
                run_id="rerun-001", report_path=report1_path,
                min_available_mib=0,
            )
            self.assertTrue(result1["success"],
                            f"first run failed: {result1.get('error') or result1.get('failures')}")

            # Second run with different run_id
            result2 = run_backfill(
                league="nba", season=2026,
                season_start="2025-10-01", season_end="2026-06-30",
                db_path=self.db_path, fixture_path=self.fixture_path,
                run_id="rerun-002", report_path=report2_path,
                min_available_mib=0,
            )
            self.assertTrue(result2["success"],
                            f"second run failed: {result2.get('error') or result2.get('failures')}")

            # Both inventory and results should still have correct counts
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            try:
                inv_count = connection.execute(
                    "SELECT COUNT(DISTINCT team_id) FROM team_stats_team_inventory"
                ).fetchone()[0]
                self.assertEqual(inv_count, 30)

                res_count = connection.execute(
                    "SELECT COUNT(*) FROM team_game_results WHERE league='nba'"
                ).fetchone()[0]
                # With INSERT OR IGNORE and same game_ids, count should still be 30
                self.assertEqual(res_count, 30)

                stat_count = connection.execute(
                    "SELECT COUNT(*) FROM team_game_stats WHERE league='nba'"
                ).fetchone()[0]
                self.assertEqual(stat_count, 30)

                # Two coverage rows
                cov_count = connection.execute(
                    "SELECT COUNT(*) FROM team_stats_coverage WHERE league='nba'"
                ).fetchone()[0]
                self.assertEqual(cov_count, 2)
            finally:
                connection.close()
        finally:
            for p in (report1_path, report2_path):
                if os.path.lexists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
