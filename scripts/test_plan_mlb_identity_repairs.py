#!/usr/bin/env python3

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("plan_mlb_identity_repairs.py")
SPEC = importlib.util.spec_from_file_location("plan_mlb_identity_repairs", SCRIPT)
planner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(planner)


class MlbIdentityRepairPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "fixture.db"
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              team TEXT,
              league TEXT NOT NULL,
              espn_id TEXT,
              mlbam_id INTEGER,
              active INTEGER,
              position TEXT
            );
            CREATE TABLE player_stats(
              id INTEGER PRIMARY KEY,
              player_id INTEGER,
              league TEXT,
              season INTEGER
            );
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INTEGER);
            CREATE TABLE props(id INTEGER PRIMARY KEY, player_id INTEGER);
            CREATE TABLE predictions(id INTEGER PRIMARY KEY, player_id INTEGER);
            """
        )
        connection.executemany(
            "INSERT INTO players VALUES (?,?,?,?,?,?,?,?)",
            [
                (1, "Jack Perkins", "ATH", "mlb", "4418686", 592450, 1, "P"),
                (2, "Jack Perkins", None, "mlb", None, 678022, 0, None),
                (3, "Mookie Betts", "LAD", "mlb", "33039", 605141, 1, "SS"),
            ],
        )
        connection.executemany(
            "INSERT INTO player_stats VALUES (?,?,?,?)",
            [(1, 1, "mlb", 2026), (2, 2, "mlb", 2026), (3, 3, "mlb", 2026)],
        )
        connection.execute("INSERT INTO props VALUES (1,1)")
        connection.execute("INSERT INTO player_game_logs VALUES (1,2)")
        connection.commit()
        connection.close()

        self.official = {
            "people": [
                {"id": 592450, "fullName": "Aaron Judge"},
                {"id": 678022, "fullName": "Jack Perkins"},
                {"id": 605141, "fullName": "Mookie Betts"},
            ]
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def build(self, official=None):
        connection = planner.connect_read_only(str(self.db_path))
        try:
            return planner.build_plan(
                connection,
                str(self.db_path),
                2026,
                official or self.official,
                "fixture",
            )
        finally:
            connection.close()

    def test_proposes_only_unique_exact_crosswalk(self):
        before = sqlite3.connect(self.db_path).execute(
            "SELECT id,name,espn_id,mlbam_id FROM players ORDER BY id"
        ).fetchall()

        plan = self.build()

        self.assertEqual(plan["summary"]["season_population_players"], 3)
        self.assertEqual(plan["summary"]["stored_name_vs_official_name_mismatches"], 1)
        self.assertEqual(plan["summary"]["safe_crosswalk_proposals"], 1)
        proposal = plan["proposals"][0]
        self.assertEqual(proposal["canonical_player_id"], 1)
        self.assertEqual(proposal["source_player_id"], 2)
        self.assertEqual(proposal["correct_mlbam_id"], 678022)
        self.assertEqual(proposal["displaced_mlbam_id"], 592450)
        self.assertEqual(proposal["canonical_reference_counts"]["props"], 1)
        self.assertEqual(proposal["source_reference_counts"]["player_game_logs"], 1)
        self.assertIn(
            "displaced_official_identity_not_represented",
            plan["summary"]["review_queue_reasons"],
        )

        after = sqlite3.connect(self.db_path).execute(
            "SELECT id,name,espn_id,mlbam_id FROM players ORDER BY id"
        ).fetchall()
        self.assertEqual(before, after)

    def test_queues_ambiguous_authoritative_name(self):
        ambiguous = {
            "people": self.official["people"]
            + [{"id": 999999, "fullName": "Jack Perkins"}]
        }
        plan = self.build(ambiguous)
        self.assertEqual(plan["summary"]["safe_crosswalk_proposals"], 0)
        self.assertIn(
            "stored_name_not_unique_in_authoritative_population",
            plan["summary"]["review_queue_reasons"],
        )

    def test_queues_missing_official_record(self):
        incomplete = {
            "people": [person for person in self.official["people"] if person["id"] != 592450]
        }
        plan = self.build(incomplete)
        self.assertIn("official_person_missing", plan["summary"]["review_queue_reasons"])
        self.assertIn(592450, plan["missing_official_mlbam_ids"])

    def test_name_key_preserves_suffixes(self):
        self.assertNotEqual(
            planner.identity_name_key("Luis Garcia Jr."),
            planner.identity_name_key("Luis Garcia"),
        )
        self.assertEqual(
            planner.identity_name_key("Ronald Acuña Jr."),
            planner.identity_name_key("Ronald Acuna Jr"),
        )
        self.assertEqual(
            planner.same_identity_display_key("Victor Scott"),
            planner.same_identity_display_key("Victor Scott II"),
        )
        self.assertNotEqual(
            planner.same_identity_display_key("Max P. Muncy"),
            planner.same_identity_display_key("Max Muncy"),
        )


if __name__ == "__main__":
    unittest.main()
