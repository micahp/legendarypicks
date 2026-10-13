import os
import sqlite3
import tempfile
import unittest

import ingest_nfl_injuries as mod


class InjuryIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db = handle.name
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY,league TEXT,nfl_gsis_id TEXT,
                     espn_id TEXT,name TEXT)"""
            )
            connection.executemany(
                "INSERT INTO players VALUES(?,?,?,?,?)",
                [
                    (1, "nfl", "gsis-direct", "11", "Direct Player"),
                    (2, "nfl", "legacy-key", "22", "Fallback Player"),
                ],
            )
            connection.commit()

    def tearDown(self):
        os.unlink(self.db)

    @staticmethod
    def _row(gsis_id, name, week=1, team="LAR", status="Out"):
        return {
            "season": 2026, "week": week, "team": team,
            "gsis_id": gsis_id, "full_name": name,
            "report_status": status,
            "practice_status": "Did Not Participate In Practice",
            "report_primary_injury": "Knee",
        }

    def test_publishes_all_rows_and_queues_only_stable_id_miss(self):
        rows = [
            self._row("gsis-direct", "Direct Player"),
            self._row("gsis-fallback", "Fallback Player"),
            self._row("gsis-missing", "Missing Player"),
        ]
        result = mod.publish(
            2026, rows, {"gsis-fallback": "22"}, db_path=self.db,
        )

        self.assertEqual(result["source_rows"], 3)
        self.assertEqual(result["stored_rows"], 3)
        self.assertEqual(result["unresolved_ids"], 1)
        with sqlite3.connect(self.db) as connection:
            stored = connection.execute(
                "SELECT gsis_id,team,player_id,report_status "
                "FROM injury_reports ORDER BY gsis_id"
            ).fetchall()
            queued = connection.execute(
                "SELECT source_player_key,raw_name,count FROM unresolved_players"
            ).fetchall()
        self.assertEqual(stored, [
            ("gsis-direct", "LAR", 1, "Out"),
            ("gsis-fallback", "LAR", 2, "Out"),
            ("gsis-missing", "LAR", None, "Out"),
        ])
        self.assertEqual(queued, [("gsis-missing", "Missing Player", 1)])

    def test_rerun_replaces_owned_season_and_does_not_inflate_queue(self):
        missing = self._row("gsis-missing", "Missing Player")
        mod.publish(2026, [missing], {}, db_path=self.db)
        missing_week_two = self._row(
            "gsis-missing", "Missing Player", week=2, status="Questionable"
        )
        mod.publish(2026, [missing, missing_week_two], {}, db_path=self.db)
        with sqlite3.connect(self.db) as connection:
            reports = connection.execute(
                "SELECT COUNT(*) FROM injury_reports"
            ).fetchone()[0]
            queued = connection.execute(
                "SELECT count FROM unresolved_players"
            ).fetchone()[0]
        self.assertEqual(reports, 2)
        self.assertEqual(queued, 2)

    def test_dry_run_is_read_only(self):
        result = mod.publish(
            2026, [self._row("gsis-direct", "Direct Player")], {},
            db_path=self.db, dry_run=True,
        )
        self.assertEqual(result["direct_rows"], 1)
        with sqlite3.connect(self.db) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='injury_reports'"
            ).fetchone()
        self.assertIsNone(exists)

    def test_latest_publisher_revision_wins(self):
        older = self._row("gsis-direct", "Direct Player", status="Questionable")
        older["date_modified"] = "2026-09-12T20:00:00+00:00"
        newer = self._row("gsis-direct", "Direct Player", status="Out")
        newer["date_modified"] = "2026-09-13T13:00:00+00:00"

        final = mod.collapse_final_reports([older, newer])

        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["report_status"], "Out")


if __name__ == "__main__":
    unittest.main()
