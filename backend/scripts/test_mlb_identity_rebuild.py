#!/usr/bin/env python3

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_mlb_identity_rebuild_copy as applier  # noqa: E402
import plan_mlb_identity_rebuild as planner  # noqa: E402


SCHEMA = """
CREATE TABLE players(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  team TEXT,
  league TEXT NOT NULL,
  espn_id TEXT,
  mlbam_id INTEGER,
  nfl_gsis_id TEXT,
  nhl_id INTEGER,
  nba_id INTEGER,
  active INTEGER,
  position TEXT
);
CREATE TABLE props(
  id INTEGER PRIMARY KEY,
  player_id INTEGER REFERENCES players(id)
);
CREATE TABLE player_stats(
  id INTEGER PRIMARY KEY,
  player_id INTEGER REFERENCES players(id),
  player_name TEXT,
  league TEXT,
  season INTEGER
);
CREATE TABLE player_game_logs(
  id INTEGER PRIMARY KEY,
  player_id INTEGER,
  league TEXT,
  source_player_key TEXT
);
CREATE TABLE name_alias(
  id INTEGER PRIMARY KEY,
  player_id INTEGER REFERENCES players(id),
  alias_norm TEXT,
  UNIQUE(player_id,alias_norm)
);
CREATE TABLE unresolved_players(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  raw_name TEXT NOT NULL,
  league TEXT NOT NULL,
  team TEXT,
  first_seen TEXT NOT NULL,
  count INTEGER DEFAULT 1
);
"""


class MlbIdentityRebuildTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        directory = Path(self.tempdir.name)
        self.candidate_path = directory / "candidate.db"
        self.reference_path = directory / "reference.db"

        candidate = sqlite3.connect(self.candidate_path)
        candidate.executescript(SCHEMA)
        candidate.executemany(
            """INSERT INTO players(
                 id,name,team,league,espn_id,mlbam_id,nfl_gsis_id,
                 nhl_id,nba_id,active,position
               ) VALUES(?,?,NULL,'mlb',NULL,?,NULL,NULL,NULL,1,NULL)""",
            [
                (1, "Alpha One", 100),
                (2, "alpha one", 100),
                (3, "Gamma Three", 300),
                (4, "Gamma Three", 400),
                (5, "Delta Four", 300),
                (6, "Mystery Person", 200),
                (7, "Beta Two", 200),
            ],
        )
        candidate.executemany(
            "INSERT INTO props(id,player_id) VALUES(?,?)",
            [(1, 1), (2, 3), (3, 6)],
        )
        candidate.executemany(
            """INSERT INTO player_game_logs(
                 id,player_id,league,source_player_key
               ) VALUES(?,?,'mlb',?)""",
            [
                (1, 2, "100"),
                (2, 4, "400"),
                (3, 5, "300"),
                (4, 6, "200"),
                (5, 2, "999"),
            ],
        )
        candidate.executemany(
            """INSERT INTO player_stats(
                 id,player_id,player_name,league,season
               ) VALUES(?,?,?,'mlb',2026)""",
            [
                (player_id, player_id, name)
                for player_id, name in (
                    (1, "Alpha One"),
                    (2, "alpha one"),
                    (3, "Gamma Three"),
                    (4, "Gamma Three"),
                    (5, "Delta Four"),
                    (6, "Mystery Person"),
                    (7, "Beta Two"),
                )
            ],
        )
        candidate.execute(
            "INSERT INTO name_alias VALUES(1,2,'alpha one')"
        )
        candidate.commit()
        candidate.close()

        reference = sqlite3.connect(self.reference_path)
        reference.executescript(SCHEMA)
        reference.executemany(
            """INSERT INTO players(
                 id,name,team,league,espn_id,mlbam_id,nfl_gsis_id,
                 nhl_id,nba_id,active,position
               ) VALUES(?,?,NULL,'mlb',NULL,?,NULL,NULL,NULL,1,NULL)""",
            [
                (101, "Alpha One", 100),
                (102, "Beta Two", 200),
                (103, "Delta Four", 300),
                (104, "Gamma Three", 400),
            ],
        )
        reference.commit()
        reference.close()

        self.official = {
            "people": [
                {"id": 100, "fullName": "Alpha One"},
                {"id": 200, "fullName": "Beta Two"},
                {"id": 300, "fullName": "Delta Four"},
                {"id": 400, "fullName": "Gamma Three"},
            ]
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def build_plan(self):
        candidate = planner.connect_read_only(str(self.candidate_path))
        reference = planner.connect_read_only(str(self.reference_path))
        try:
            return planner.build_plan(
                candidate,
                str(self.candidate_path),
                reference,
                str(self.reference_path),
                self.official,
                season=2026,
            )
        finally:
            reference.close()
            candidate.close()

    def test_plan_requires_official_and_clean_reference_agreement(self):
        plan = self.build_plan()

        self.assertEqual(
            plan["summary"]["original_duplicate_mlbam_groups"], 3
        )
        self.assertEqual(plan["summary"]["corroborated_crosswalks"], 1)
        self.assertEqual(plan["summary"]["post_assignment_merge_groups"], 2)
        self.assertEqual(plan["delete_player_ids"], [2, 4])
        self.assertEqual(
            plan["canonical_by_mlbam"],
            {"100": 1, "200": 7, "300": 5, "400": 3},
        )
        self.assertEqual(
            [item["player_id"] for item in plan["detachments"]],
            [6],
        )
        self.assertEqual(plan["summary"]["game_logs_to_repoint"], 3)
        self.assertEqual(plan["summary"]["game_logs_to_archive"], 1)
        self.assertEqual(
            plan["summary"]["game_log_source_keys_to_queue"], 1
        )
        self.assertEqual(plan["summary"]["player_stats_to_archive"], 7)
        self.assertEqual(plan["summary"]["props_to_repoint"], 1)

    def test_copy_transaction_preserves_props_and_routes_logs_by_key(self):
        plan = self.build_plan()
        connection = sqlite3.connect(self.candidate_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        changes = applier.apply_transaction(
            connection, plan, run_id="fixture-rebuild"
        )
        connection.commit()

        self.assertEqual(changes["props_before"], 3)
        self.assertEqual(changes["props_after"], 3)
        self.assertEqual(changes["props_repointed"], 1)
        self.assertEqual(changes["duplicate_mlbam_groups"], 0)
        self.assertEqual(
            [
                tuple(row)
                for row in connection.execute(
                    "SELECT id,mlbam_id FROM players ORDER BY id"
                )
            ],
            [(1, 100), (3, 400), (5, 300), (6, None), (7, 200)],
        )
        self.assertEqual(
            [
                tuple(row)
                for row in connection.execute(
                    "SELECT id,player_id FROM player_game_logs ORDER BY id"
                )
            ],
            [(1, 1), (2, 3), (3, 5), (4, 7)],
        )
        self.assertEqual(
            [
                tuple(row)
                for row in connection.execute(
                    "SELECT id,player_id FROM props ORDER BY id"
                )
            ],
            [(1, 1), (2, 3), (3, 6)],
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM player_stats"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute(
                """SELECT COUNT(*) FROM unresolved_players
                   WHERE source LIKE 'mlb_identity_rebuild%'"""
            ).fetchone()[0],
            2,
        )
        connection.close()

    def test_copy_guard_refuses_hard_links(self):
        target = Path(self.tempdir.name) / "target.db"
        link = Path(self.tempdir.name) / "link.db"
        target.write_bytes(b"sqlite-copy")
        os.link(target, link)
        with self.assertRaisesRegex(
            applier.RebuildInvariantError, "hard-linked"
        ):
            applier.require_copy_path(str(link))

    def test_plan_json_is_serializable(self):
        json.dumps(self.build_plan(), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
