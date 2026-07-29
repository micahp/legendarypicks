#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest

import migrate_player_stats


LEGACY_STATS_DDL = """
CREATE TABLE player_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  player_name TEXT NOT NULL,
  name_norm TEXT,
  league TEXT NOT NULL,
  team TEXT,
  stat_type TEXT DEFAULT 'batting',
  season INTEGER,
  games INTEGER,
  pts REAL,
  source TEXT,
  player_id INTEGER,
  UNIQUE(name_norm,league,season,stat_type)
)
"""


class PlayerStatsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix="player-stats-migration-"
        )
        self.path = os.path.join(self.tempdir.name, "fixture.db")
        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              team TEXT,
              league TEXT NOT NULL
            );
            """
            + LEGACY_STATS_DDL
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?)",
            [
                (1, "NBA Player", "BOS", "nba"),
                (2, "NHL Player", "EDM", "nhl"),
            ],
        )
        con.executemany(
            """INSERT INTO player_stats(
                 player_name,name_norm,league,team,stat_type,season,
                 games,pts,source,player_id
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    "NBA Player", "nba player", "nba", "BOS", "season",
                    2026, 20, 25.0, "espn_core", 1,
                ),
                (
                    "NHL Player", "nhl player", "nhl", "EDM", "season",
                    20252026, 40, None, "nhle.com", 2,
                ),
            ],
        )
        con.commit()
        con.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def backup(self, name):
        return os.path.join(self.tempdir.name, name)

    def test_clean_legacy_table_rebuilds_once_with_canonical_key(self):
        before = migrate_player_stats.check_database(self.path)
        self.assertEqual(before.state, "pending")

        backup, applied = migrate_player_stats.apply_database(
            self.path, backup_destination=self.backup("before.bak")
        )

        self.assertTrue(os.path.exists(backup))
        self.assertEqual(applied.state, "applied")
        after = migrate_player_stats.check_database(self.path)
        self.assertEqual(after.state, "applied")
        with sqlite3.connect(self.path) as con:
            columns = {
                row[1]: row for row in con.execute(
                    "PRAGMA table_info(player_stats)"
                )
            }
            self.assertEqual(columns["player_id"][3], 1)
            self.assertEqual(columns["stat_type"][3], 1)
            self.assertEqual(columns["source"][3], 1)
            table_sql = con.execute(
                """SELECT sql FROM sqlite_master
                   WHERE type='table' AND name='player_stats'"""
            ).fetchone()[0]
            self.assertIn(
                "UNIQUE(player_id,league,season,stat_type)",
                table_sql.replace(" ", ""),
            )
            self.assertNotIn(
                "UNIQUE(name_norm,league,season,stat_type)",
                table_sql.replace(" ", ""),
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0],
                2,
            )

        _, second = migrate_player_stats.apply_database(
            self.path, backup_destination=self.backup("second.bak")
        )
        self.assertEqual(second.state, "applied")

    def test_duplicate_canonical_key_fails_before_backup(self):
        with sqlite3.connect(self.path) as con:
            con.execute(
                """INSERT INTO player_stats(
                     player_name,name_norm,league,team,stat_type,season,
                     games,pts,source,player_id
                   ) VALUES('Duplicate','duplicate','nba','BOS','season',
                            2026,20,30,'espn_core',1)"""
            )

        result = migrate_player_stats.check_database(self.path)

        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.issues["duplicate_canonical_keys"], 1)
        with self.assertRaises(migrate_player_stats.PlayerStatsMigrationError):
            migrate_player_stats.apply_database(
                self.path, backup_destination=self.backup("blocked.bak")
            )
        self.assertFalse(os.path.exists(self.backup("blocked.bak")))

    def test_unowned_source_and_wrong_type_fail_closed(self):
        with sqlite3.connect(self.path) as con:
            con.execute(
                """UPDATE player_stats
                   SET stat_type='batting',source='derived'
                   WHERE player_id=2"""
            )

        result = migrate_player_stats.check_database(self.path)

        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.issues["invalid_stat_types"], 1)
        self.assertEqual(result.issues["unowned_sources"], 1)

    def test_check_is_byte_for_byte_read_only(self):
        with open(self.path, "rb") as handle:
            before = hashlib.sha256(handle.read()).hexdigest()
        before_stat = os.stat(self.path)

        migrate_player_stats.check_database(self.path)

        with open(self.path, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        after_stat = os.stat(self.path)
        self.assertEqual(after, before)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)

    def test_relative_path_is_rejected(self):
        with self.assertRaises(migrate_player_stats.PlayerStatsMigrationError):
            migrate_player_stats.check_database("fixture.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
