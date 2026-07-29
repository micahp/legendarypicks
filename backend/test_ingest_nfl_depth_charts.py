#!/usr/bin/env python3
"""Depth-chart dry runs are strictly read-only."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_nfl_depth_charts as depth


class DepthChartIngestTests(unittest.TestCase):
    def test_dry_run_does_not_create_table(self):
        handle = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        handle.close()
        original_db = depth.DB
        depth.DB = handle.name
        try:
            with sqlite3.connect(handle.name) as connection:
                connection.execute(
                    """CREATE TABLE players(
                         id INTEGER PRIMARY KEY,
                         league TEXT,
                         nfl_gsis_id TEXT,
                         espn_id TEXT
                       )"""
                )
                connection.execute(
                    "INSERT INTO players VALUES"
                    "(1,'nfl','gsis-1','espn-1')"
                )
            rows = [
                {
                    "gsis_id": "gsis-1",
                    "espn_id": "espn-1",
                    "team": "ARI",
                    "player_name": "Fixture Receiver",
                    "pos_abb": "WR",
                    "pos_name": "Wide Receiver",
                    "pos_rank": 1,
                    "snapshot_at": "2026-07-28T00:00:00Z",
                }
            ]
            with mock.patch.object(
                depth, "fetch", return_value="/tmp/fixture.parquet"
            ), mock.patch.object(
                depth, "build_rows", return_value=rows
            ):
                self.assertEqual(
                    depth.run(2026, "/tmp", dry_run=True), 0
                )
            with sqlite3.connect(handle.name) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='nfl_depth_chart'"
                ).fetchone()
            self.assertIsNone(table)
        finally:
            depth.DB = original_db
            os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main()
