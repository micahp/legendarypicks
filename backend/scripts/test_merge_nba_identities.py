#!/usr/bin/env python3

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import merge_nba_identities
import name_aliases


class NBAMergeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = os.path.join(self.temporary.name, "nba.db")
        # The merge logs consolidations to the artifact; a test must never
        # append to the real one.
        self._orig_consolidations = name_aliases.CONSOLIDATIONS_PATH
        name_aliases.CONSOLIDATIONS_PATH = Path(self.temporary.name) / "consolidations.jsonl"
        self.addCleanup(self._restore_consolidations)
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              league TEXT NOT NULL,
              team TEXT,
              espn_id TEXT,
              nba_id TEXT
            );
            CREATE TABLE player_game_logs(
              id INTEGER PRIMARY KEY,
              player_id INTEGER,
              league TEXT,
              season INTEGER
            );
            CREATE TABLE player_stats(
              id INTEGER PRIMARY KEY,
              player_id INTEGER,
              player_name TEXT,
              name_norm TEXT,
              league TEXT,
              season INTEGER,
              stat_type TEXT
            );
            CREATE TABLE props(
              id INTEGER PRIMARY KEY,
              player_id INTEGER,
              market TEXT
            );
            CREATE TABLE prop_results(id INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY, value TEXT);
            """
        )
        connection.executemany(
            """INSERT INTO players(
                 id,name,league,team,espn_id,nba_id
               ) VALUES(?,?,?,?,?,?)""",
            [
                (1, "Current Name", "nba", "BOS", "101", None),
                (2, "Historical Name", "nba", "OLD", None, "101"),
                (3, "Unrelated", "nba", "NY", "303", "303"),
            ],
        )
        connection.execute(
            "INSERT INTO player_game_logs VALUES(1,1,'nba',2026)"
        )
        connection.execute(
            """INSERT INTO player_stats VALUES(
                 1,2,'Historical Name','historical name',
                 'nba',2023,'season'
               )"""
        )
        connection.execute(
            "INSERT INTO props VALUES(1,3,'points')"
        )
        connection.execute(
            "INSERT INTO prop_results VALUES(1,'protected')"
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'protected')"
        )
        connection.commit()
        connection.close()

    def _restore_consolidations(self):
        name_aliases.CONSOLIDATIONS_PATH = self._orig_consolidations

    def test_stable_id_merge_moves_history_and_preserves_protected_rows(self):
        plan = merge_nba_identities.build_plan(self.path)
        self.assertEqual(plan["pair_count"], 1)
        self.assertEqual(plan["moved"], {"player_stats": 1})

        backup = merge_nba_identities.apply_plan(
            self.path,
            plan,
            expected_pairs=1,
            expected_moved={"player_stats": 1},
        )

        self.assertTrue(os.path.isfile(backup))
        connection = sqlite3.connect(self.path)
        self.assertEqual(
            connection.execute(
                "SELECT id,name,espn_id,nba_id FROM players ORDER BY id"
            ).fetchall(),
            [
                (1, "Current Name", "101", "101"),
                (3, "Unrelated", "303", "303"),
            ],
        )
        self.assertEqual(
            connection.execute(
                """SELECT player_id,player_name,name_norm
                   FROM player_stats"""
            ).fetchone(),
            (1, "Current Name", "current name"),
        )
        self.assertEqual(
            connection.execute(
                "SELECT player_id,market FROM props"
            ).fetchone(),
            (3, "points"),
        )
        connection.close()

    def test_stat_key_collision_fails_before_backup_or_mutation(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            """INSERT INTO player_stats VALUES(
                 2,1,'Current Name','current name',
                 'nba',2023,'season'
               )"""
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(
            merge_nba_identities.NBAMergeError,
            "collide in player_stats",
        ):
            merge_nba_identities.build_plan(self.path)

        connection = sqlite3.connect(self.path)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM players"
            ).fetchone()[0],
            3,
        )
        connection.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
