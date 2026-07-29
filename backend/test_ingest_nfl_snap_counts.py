import json
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
        self.assertEqual(result["deleted_stale_snaps"], 0)

    def test_reviewed_pfr_collision_maps_each_jonah_to_the_right_gsis(self):
        ids = pd.DataFrame(
            [{"pfr_id": "WillJo10", "gsis_id": "00-0035944"}]
        )
        with mock.patch.object(
            ingest_nfl_snap_counts.nfl,
            "import_ids",
            return_value=ids,
        ):
            crosswalk = ingest_nfl_snap_counts._pfr_to_gsis()

        self.assertEqual(crosswalk["WillJo10"], "00-0035629")
        self.assertEqual(crosswalk["WillJo16"], "00-0035944")

    def test_rerun_removes_stale_snap_rows_and_owned_log_fields_only(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT INTO nfl_snap_counts(
                     player_id,season,week,team,off_snaps,off_pct
                   ) VALUES(1,2025,2,'LAR',55,0.9)"""
            )
            connection.execute(
                """INSERT INTO player_game_logs
                   (id,player_id,league,season,game_no,team,stats)
                   VALUES(1,1,'nfl',2025,'2','LAR',
                          '{"off_snaps":55,"off_pct":0.9,"separation":2.7}')"""
            )
            connection.commit()

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
            stale = connection.execute(
                """SELECT COUNT(*) FROM nfl_snap_counts
                   WHERE player_id=1 AND season=2025 AND week=2"""
            ).fetchone()[0]
            stats = connection.execute(
                "SELECT stats FROM player_game_logs WHERE id=1"
            ).fetchone()[0]

        self.assertEqual(stale, 0)
        self.assertEqual(result["deleted_stale_snaps"], 1)
        self.assertEqual(
            json.loads(stats),
            {"separation": 2.7},
        )

    def test_missing_pinned_artifact_fails_before_network_fetch(self):
        missing = os.path.join(
            os.path.dirname(self.db_path),
            "missing-snap-counts.parquet",
        )
        with mock.patch.object(
            ingest_nfl_snap_counts.nfl,
            "import_snap_counts",
        ) as network_fetch:
            with self.assertRaisesRegex(
                RuntimeError, "does not exist"
            ):
                ingest_nfl_snap_counts._load_snap_counts(
                    2025, missing
                )
        network_fetch.assert_not_called()

    def test_dry_run_does_not_create_missing_snap_table(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DROP TABLE nfl_snap_counts")
            connection.commit()
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
            ingest_nfl_snap_counts.ingest(2025, dry_run=True)
        with sqlite3.connect(self.db_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='nfl_snap_counts'"
            ).fetchone()
        self.assertIsNone(exists)


if __name__ == "__main__":
    unittest.main()
