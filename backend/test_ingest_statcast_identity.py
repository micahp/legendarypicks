#!/usr/bin/env python3
"""Identity-safety tests for the Statcast season aggregate ingest."""
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_statcast


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def create_old_schema(path):
    with sqlite3.connect(path) as con:
        con.executescript(
            "CREATE TABLE players("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, league TEXT, mlbam_id INTEGER);"
            "CREATE TABLE unresolved_players("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, "
            "raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT, "
            "first_seen TEXT NOT NULL, count INTEGER DEFAULT 1);"
            "CREATE TABLE player_stats("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, player_name TEXT, name_norm TEXT, "
            "league TEXT, team TEXT, stat_type TEXT, season INTEGER, games INTEGER, "
            "avg REAL, hr INTEGER, k_pct REAL, bb_pct REAL, exit_velo REAL, "
            "hard_hit_pct REAL, barrel_pct REAL, launch_angle REAL, woba REAL, "
            "xwoba REAL, whiff_pct REAL, exit_velo_against REAL, "
            "barrel_pct_against REAL, xwoba_against REAL, source TEXT, player_id INTEGER, "
            "UNIQUE(player_name,league,season,stat_type));"
        )


class StatcastIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "statcast.db")
        create_old_schema(self.db_path)
        self.con = connect(self.db_path)
        ingest_statcast._ensure_identity_queue_schema(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def insert_player(self, name, mlbam_id):
        return self.con.execute(
            "INSERT INTO players(name,league,mlbam_id) VALUES (?,'mlb',?)",
            (name, mlbam_id),
        ).lastrowid

    def test_old_queue_schema_is_migrated_additively(self):
        columns = {
            row[1] for row in self.con.execute("PRAGMA table_info(unresolved_players)")
        }
        self.assertIn("source_player_key", columns)
        self.assertIn("reason", columns)
        player_columns = {
            row[1] for row in self.con.execute("PRAGMA table_info(players)")
        }
        self.assertEqual(player_columns, {"id", "name", "league", "mlbam_id"})

    def test_known_mlbam_resolves_without_queue_or_player_mutation(self):
        player_id = self.insert_player("Known Player", 123)
        spine, ambiguous = ingest_statcast._load_mlb_spine(self.con)
        before = self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0]

        resolved = ingest_statcast._resolve_or_queue_statcast(
            self.con, spine, ambiguous, set(), 123, "Wrong Fallback"
        )

        self.assertEqual(resolved, ("Known Player", player_id))
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], before
        )
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM unresolved_players").fetchone()[0], 0
        )

    def test_missing_mlbam_is_queued_once_per_run_and_never_inserted(self):
        queued = set()
        before = self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0]

        first = ingest_statcast._resolve_or_queue_statcast(
            self.con, {}, set(), queued, 456, "mlbam_456"
        )
        second = ingest_statcast._resolve_or_queue_statcast(
            self.con, {}, set(), queued, 456, "Resolved Name Later In Batch"
        )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], before
        )
        row = self.con.execute("SELECT * FROM unresolved_players").fetchone()
        self.assertEqual(row["source"], "statcast")
        self.assertEqual(row["source_player_key"], "456")
        self.assertEqual(row["raw_name"], "mlbam_456")
        self.assertEqual(row["reason"], "mlbam_id_not_in_spine")
        self.assertEqual(row["count"], 1)

        ingest_statcast._resolve_or_queue_statcast(
            self.con, {}, set(), set(), 456, "Official Name"
        )
        updated = self.con.execute("SELECT * FROM unresolved_players").fetchone()
        self.assertEqual(updated["count"], 2)
        self.assertEqual(updated["raw_name"], "Official Name")

    def test_duplicate_spine_mlbam_fails_closed_and_queues_reason(self):
        self.insert_player("First Identity", 789)
        self.insert_player("Second Identity", 789)
        spine, ambiguous = ingest_statcast._load_mlb_spine(self.con)

        resolved = ingest_statcast._resolve_or_queue_statcast(
            self.con, spine, ambiguous, set(), 789, "Statcast Name"
        )

        self.assertIsNone(resolved)
        self.assertEqual(ambiguous, {789})
        row = self.con.execute("SELECT * FROM unresolved_players").fetchone()
        self.assertEqual(row["source_player_key"], "789")
        self.assertEqual(row["reason"], "duplicate_spine_mlbam_id")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)

    def test_full_ingest_writes_stats_only_for_spine_resolved_ids(self):
        import pandas as pd

        self.insert_player("Known Batter", 123)
        self.insert_player("Known Pitcher", 321)
        self.con.commit()
        data = pd.DataFrame([
            {
                "batter": 123, "pitcher": 321, "events": "single",
                "launch_speed": 101.0, "launch_angle": 27.0,
                "woba_value": 0.9, "estimated_woba_using_speedangle": 0.8,
                "game_date": "2026-07-13", "description": "hit_into_play",
                "player_name": "Pitcher, Known",
            },
            {
                "batter": 456, "pitcher": 654, "events": "strikeout",
                "launch_speed": None, "launch_angle": None,
                "woba_value": 0.0, "estimated_woba_using_speedangle": None,
                "game_date": "2026-07-13", "description": "swinging_strike",
                "player_name": "Missing, Pitcher",
            },
        ])
        fake_pybaseball = types.SimpleNamespace(statcast=lambda start, end: data)
        original_db = ingest_statcast.DB
        ingest_statcast.DB = self.db_path
        try:
            with mock.patch.dict(sys.modules, {"pybaseball": fake_pybaseball}):
                ingest_statcast.ingest(days=1)
        finally:
            ingest_statcast.DB = original_db

        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)
        stats = self.con.execute(
            "SELECT player_id,stat_type FROM player_stats ORDER BY stat_type"
        ).fetchall()
        self.assertEqual(len(stats), 2)
        self.assertTrue(all(row["player_id"] is not None for row in stats))
        queued = self.con.execute(
            "SELECT source_player_key,reason FROM unresolved_players "
            "ORDER BY source_player_key"
        ).fetchall()
        self.assertEqual(
            [(row["source_player_key"], row["reason"]) for row in queued],
            [("456", "mlbam_id_not_in_spine"), ("654", "mlbam_id_not_in_spine")],
        )


if __name__ == "__main__":
    unittest.main()
