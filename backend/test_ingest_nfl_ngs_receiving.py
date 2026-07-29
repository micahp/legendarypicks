#!/usr/bin/env python3
"""NGS receiving synchronization tests."""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import pandas as pd

import ingest_nfl_ngs_receiving as ngs


def _row(week=1, separation=2.345678):
    return {
        "player_gsis_id": "gsis-1",
        "season": 2025,
        "season_type": "REG",
        "week": week,
        "percent_share_of_intended_air_yards": 0.312345,
        "avg_intended_air_yards": 11.23456,
        "avg_separation": separation,
        "avg_cushion": 6.78901,
        "avg_yac_above_expectation": -0.12345,
    }


class NgsReceivingIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY,
                     league TEXT,
                     nfl_gsis_id TEXT,
                     name TEXT
                   );
                   CREATE TABLE player_game_logs(
                     id INTEGER PRIMARY KEY,
                     player_id INTEGER,
                     league TEXT,
                     season INTEGER,
                     game_no TEXT,
                     team TEXT,
                     stats TEXT
                   );"""
            )
            connection.execute(
                "INSERT INTO players VALUES"
                "(1,'nfl','gsis-1','Fixture Receiver')"
            )
            connection.executemany(
                "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        1,
                        1,
                        "nfl",
                        2025,
                        "1",
                        "ARI",
                        '{"separation":1.0,"targets":4}',
                    ),
                    (
                        2,
                        1,
                        "nfl",
                        2025,
                        "2",
                        "ARI",
                        '{"separation":9.0,"targets":3}',
                    ),
                ],
            )
        self.original_db = ngs.DB
        ngs.DB = self.db_path

    def tearDown(self):
        ngs.DB = self.original_db
        os.unlink(self.db_path)

    def test_sync_preserves_precision_and_removes_stale_owned_fields(self):
        frame = pd.DataFrame([_row()])
        with mock.patch.object(
            ngs.nfl, "import_ngs_data", return_value=frame
        ):
            self.assertEqual(ngs.ingest(2025), 1)
        with sqlite3.connect(self.db_path) as connection:
            stats = {
                row[0]: json.loads(row[1])
                for row in connection.execute(
                    "SELECT id,stats FROM player_game_logs"
                )
            }
        self.assertEqual(stats[1]["separation"], 2.345678)
        self.assertEqual(stats[1]["targets"], 4)
        self.assertNotIn("separation", stats[2])
        self.assertEqual(stats[2]["targets"], 3)

    def test_duplicate_player_week_fails_before_writing(self):
        frame = pd.DataFrame([_row(), _row(separation=7.0)])
        with mock.patch.object(
            ngs.nfl, "import_ngs_data", return_value=frame
        ):
            with self.assertRaisesRegex(
                RuntimeError, "duplicate player/week"
            ):
                ngs.ingest(2025)
        with sqlite3.connect(self.db_path) as connection:
            value = json.loads(
                connection.execute(
                    "SELECT stats FROM player_game_logs WHERE id=1"
                ).fetchone()[0]
            )["separation"]
        self.assertEqual(value, 1.0)

    def test_missing_artifact_fails_before_network_fetch(self):
        missing = os.path.join(
            os.path.dirname(self.db_path), "missing-ngs.parquet"
        )
        with mock.patch.object(
            ngs.nfl, "import_ngs_data"
        ) as network_fetch:
            with self.assertRaisesRegex(
                RuntimeError, "does not exist"
            ):
                ngs._load_ngs(2025, missing)
        network_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
