import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import pandas as pd

import ingest_nfl_snap_counts


class NflSnapCountIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE players(
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
                );
                """
            )
            connection.execute(
                "INSERT INTO players VALUES(1,'nfl','gsis-1','Test Ram')"
            )
            ingest_nfl_snap_counts.ensure_snap_table(connection)
            connection.execute(
                """INSERT INTO nfl_snap_counts(
                     player_id,season,week,team,off_snaps,off_pct
                   ) VALUES(1,2025,1,'LA',1,0.01)"""
            )
            connection.commit()

        self.original_db = ingest_nfl_snap_counts.DB
        ingest_nfl_snap_counts.DB = self.db_path

    def tearDown(self):
        ingest_nfl_snap_counts.DB = self.original_db
        os.unlink(self.db_path)

    def test_rerun_normalizes_and_refreshes_existing_snap_row(self):
        frame = pd.DataFrame(
            [
                {
                    "pfr_player_id": "pfr-1",
                    "season": 2025,
                    "week": 1,
                    "game_type": "REG",
                    "team": "LA",
                    "offense_snaps": 42,
                    "offense_pct": 0.75,
                    "defense_snaps": 0,
                    "defense_pct": 0.0,
                    "st_snaps": 3,
                    "st_pct": 0.1,
                }
            ]
        )
        with mock.patch.object(
            ingest_nfl_snap_counts.nfl,
            "import_snap_counts",
            return_value=frame,
        ), mock.patch.object(
            ingest_nfl_snap_counts,
            "_pfr_to_gsis",
            return_value={"pfr-1": "gsis-1"},
        ):
            result = ingest_nfl_snap_counts.ingest(2025)

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """SELECT team,off_snaps,off_pct,st_snaps,st_pct
                   FROM nfl_snap_counts
                   WHERE player_id=1 AND season=2025 AND week=1"""
            ).fetchone()

        self.assertEqual(row, ("LAR", 42, 0.75, 3, 0.1))
        self.assertEqual(result["inserted_snaps"], 0)
        self.assertEqual(result["updated_snaps"], 1)
        self.assertEqual(result["skipped_snaps"], 0)


if __name__ == "__main__":
    unittest.main()
