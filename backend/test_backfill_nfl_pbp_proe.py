"""Tests for backfill_nfl_pbp_proe.py: update-only, refuses a mismatched or misaligned file, dry run writes nothing.

A temp DB and a tiny parquet file stand in for nflverse; no network.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_nfl_pbp_proe as bf  # noqa: E402

STORED = [  # game_id, play_id, play_type, epa
    ("2025_01_A_B", 1.0, "pass", 0.5),
    ("2025_01_A_B", 2.0, "run", -0.2),
    ("2025_01_A_B", 3.0, "punt", 0.0),
    ("2025_01_A_B", 4.0, "pass", 0.1),
]
FILE = [  # game_id, play_id, play_type, xpass, pass_oe, season_type
    ("2025_01_A_B", 1.0, "pass", 0.70, 30.0, "REG"),
    ("2025_01_A_B", 2.0, "run", 0.40, -40.0, "REG"),
    ("2025_01_A_B", 3.0, "punt", None, None, "REG"),
    ("2025_01_A_B", 4.0, "pass", 0.65, 35.0, "REG"),
    ("2025_19_A_B", 1.0, "pass", 0.5, 50.0, "POST"),
]


def write_file(path, rows, season=2025):
    cols = list(zip(*rows))
    pq.write_table(pa.table({
        "game_id": list(cols[0]), "play_id": list(cols[1]), "play_type": list(cols[2]),
        "xpass": list(cols[3]), "pass_oe": list(cols[4]), "season_type": list(cols[5]),
        "season": [season] * len(rows)}), path)


class Backfill(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "t.db")
        self.file = os.path.join(self._tmp.name, "f.parquet")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE nfl_pbp (game_id TEXT, play_id REAL, season INT, play_type TEXT, epa REAL, "
                    "UNIQUE(game_id, play_id))")
        con.executemany("INSERT INTO nfl_pbp VALUES (?,?,2025,?,?)", STORED)
        con.commit()
        con.close()
        write_file(self.file, FILE)

    def tearDown(self):
        self._tmp.cleanup()

    def con(self):
        c = sqlite3.connect(self.db, isolation_level=None)
        return c

    def rows(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        out = {r["play_id"]: dict(r) for r in c.execute("SELECT * FROM nfl_pbp")}
        c.close()
        return out

    def test_dry_run_writes_nothing_and_adds_no_column(self):
        c = self.con()
        rep = bf.backfill(c, self.file, 2025, apply=False)
        c.close()
        self.assertEqual(rep["matched"], 4)
        self.assertNotIn("xpass", self.rows()[1.0])

    def test_apply_fills_only_the_two_columns_on_stored_plays(self):
        before = self.rows()
        c = self.con()
        bf.backfill(c, self.file, 2025, apply=True)
        c.close()
        after = self.rows()
        self.assertEqual(after[1.0]["xpass"], 0.70)
        self.assertEqual(after[2.0]["pass_oe"], -40.0)
        self.assertIsNone(after[3.0]["xpass"])
        for pid, row in before.items():
            for col, val in row.items():
                self.assertEqual(after[pid][col], val, (pid, col))      # nothing else changed
        self.assertEqual(len(after), 4)                                 # no row inserted (the POST play is ignored)

    def test_a_stored_play_missing_from_the_file_is_refused_and_nothing_is_written(self):
        write_file(self.file, FILE[:2] + FILE[3:])
        c = self.con()
        with self.assertRaisesRegex(RuntimeError, "not in the file"):
            bf.backfill(c, self.file, 2025, apply=True)
        c.close()
        self.assertNotIn("xpass", self.rows()[1.0])

    def test_a_value_on_a_kind_of_play_that_never_has_one_is_refused(self):
        bad = list(FILE)
        bad[2] = ("2025_01_A_B", 3.0, "punt", 0.3, 5.0, "REG")
        write_file(self.file, bad)
        c = self.con()
        with self.assertRaisesRegex(RuntimeError, "never has xpass"):
            bf.backfill(c, self.file, 2025, apply=False)
        c.close()

    def test_a_file_of_another_season_is_refused(self):
        write_file(self.file, FILE, season=2024)
        with self.assertRaisesRegex(RuntimeError, "seasons"):
            bf.read_file(self.file, 2025)

    def test_misaligned_xpass_on_run_and_pass_plays_is_refused(self):
        sparse = [("2025_01_A_B", 1.0, "pass", None, None, "REG"), ("2025_01_A_B", 2.0, "run", None, None, "REG"),
                  ("2025_01_A_B", 3.0, "punt", None, None, "REG"), ("2025_01_A_B", 4.0, "pass", 0.6, 20.0, "REG")]
        write_file(self.file, sparse)
        c = self.con()
        with self.assertRaisesRegex(RuntimeError, "only"):
            bf.backfill(c, self.file, 2025, apply=False)
        c.close()


if __name__ == "__main__":
    unittest.main()
