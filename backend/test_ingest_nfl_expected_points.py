#!/usr/bin/env python3
"""Expected-points ingest owns only its published JSON key."""

import json
import sqlite3
import unittest

import ingest_nfl_expected_points as expected_points


class ExpectedPointsIngestTests(unittest.TestCase):
    def test_num_preserves_published_precision(self):
        value = 12.3456789
        self.assertEqual(expected_points._num(value), value)

    def test_sync_removes_stale_owned_key_and_preserves_other_data(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """CREATE TABLE player_game_logs(
                 id INTEGER PRIMARY KEY,
                 league TEXT,
                 season INTEGER,
                 stats TEXT
               )"""
        )
        connection.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?)",
            [
                (
                    1,
                    "nfl",
                    2025,
                    '{"xfpts_ppr":1.0,"separation":2.5}',
                ),
                (
                    2,
                    "nfl",
                    2025,
                    '{"xfpts_ppr":9.0,"targets":4}',
                ),
            ],
        )
        expected_points._replace_owned_values(
            connection,
            2025,
            [(1, {"xfpts_ppr": 7.123456})],
        )
        rows = {
            row[0]: json.loads(row[1])
            for row in connection.execute(
                "SELECT id,stats FROM player_game_logs"
            )
        }
        connection.close()
        self.assertEqual(
            rows[1],
            {"xfpts_ppr": 7.123456, "separation": 2.5},
        )
        self.assertEqual(rows[2], {"targets": 4})


if __name__ == "__main__":
    unittest.main()
