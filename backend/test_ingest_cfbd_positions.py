#!/usr/bin/env python3
"""Position contracts owned by the CFBD roster/identity publisher."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_ncaaf_rosters_cfbd as rosters
import backfill_ncaaf_positions_espn as espn_positions
from roster_membership import create_roster_schema, source_checksum


class CfbdRosterPositionTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-roster-position-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        with sqlite3.connect(self.path) as con:
            con.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
                     team TEXT,
                     league TEXT NOT NULL,
                     espn_id TEXT,
                     position TEXT,
                     position_group TEXT,
                     active INTEGER DEFAULT 1,
                     updated_at TEXT
                   )"""
            )

    def _ingest(self, rows):
        with mock.patch.object(rosters, "DB", self.path), \
             mock.patch.object(
                 rosters, "_team_vocabulary", return_value={"Alpha": "ALP"}
             ), \
             mock.patch.object(rosters, "_get_json", return_value=rows):
            return rosters.ingest(2026)

    def test_cfbd_unknown_marker_is_stored_as_null(self):
        self._ingest([{
            "id": 101,
            "firstName": "Known",
            "lastName": "Athlete",
            "team": "Alpha",
            "position": "?",
        }])

        with sqlite3.connect(self.path) as con:
            position = con.execute(
                "SELECT position FROM players WHERE espn_id='101'"
            ).fetchone()[0]
        self.assertIsNone(position)

    def test_existing_position_is_never_overwritten(self):
        with sqlite3.connect(self.path) as con:
            con.execute(
                """INSERT INTO players(
                     name,team,league,espn_id,position,position_group
                   ) VALUES('Known Athlete','ALP','ncaaf','101','PK','Special Teams')"""
            )
        self._ingest([{
            "id": 101,
            "firstName": "Known",
            "lastName": "Athlete",
            "team": "Alpha",
            "position": "P",
        }])

        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT position,position_group FROM players WHERE espn_id='101'"
            ).fetchone()
        self.assertEqual(row, ("PK", "Special Teams"))


class EspnRosterPositionTests(unittest.TestCase):
    def test_team_directory_normalizes_espn_code_to_committed_vocabulary(self):
        document = {
            "sports": [{"leagues": [{"teams": [{"team": {
                "id": "2005",
                "abbreviation": "AF",
                "displayName": "Air Force Falcons",
            }}]}]}]
        }
        with mock.patch.object(espn_positions.espn, "_get", return_value=document):
            self.assertEqual(espn_positions.team_ids()["AFA"], "2005")


class CfbdRosterMembershipTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-roster-membership-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        with sqlite3.connect(self.path) as con:
            con.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
                     team TEXT,
                     league TEXT NOT NULL,
                     espn_id TEXT,
                     position TEXT,
                     position_group TEXT,
                     active INTEGER DEFAULT 1,
                     updated_at TEXT,
                     UNIQUE(espn_id, league)
                   )"""
            )
            create_roster_schema(con)
            con.commit()

    @staticmethod
    def rows():
        return [
            {
                "id": 101, "firstName": "Alpha", "lastName": "Quarterback",
                "team": "Alpha University", "position": "QB", "jersey": 7,
            },
            {
                "id": 202, "firstName": "Beta", "lastName": "Kicker",
                "team": "Beta College", "position": "K", "jersey": "9",
            },
        ]

    def _ingest(self, rows=None, *, dry_run=False):
        with mock.patch.object(rosters, "DB", self.path), \
             mock.patch.object(rosters, "EXPECTED_TEAM_CODES", frozenset({"ALP", "BET"})), \
             mock.patch.object(
                 rosters, "_team_vocabulary",
                 return_value={"Alpha University": "ALP", "Beta College": "BET"},
             ), \
             mock.patch.object(
                 rosters, "_get_json",
                 return_value=self.rows() if rows is None else rows,
             ):
            return rosters.ingest(
                2026, dry_run=dry_run, publish_membership=True
            )

    def test_complete_population_publishes_atomic_snapshot(self):
        result = self._ingest()
        self.assertEqual(result["status"], "published")
        self.assertEqual((result["teams"], result["players"]), (2, 2))

        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            snapshot = con.execute(
                "SELECT * FROM roster_snapshots WHERE status='published'"
            ).fetchone()
            self.assertEqual(
                (snapshot["league"], snapshot["season"], snapshot["source"],
                 snapshot["team_count"], snapshot["player_count"]),
                ("ncaaf", 2026, "cfbd:roster+espn:verified-identity", 2, 2),
            )
            self.assertEqual(
                snapshot["source_checksum"],
                source_checksum(snapshot["source_payload"]),
            )
            members = con.execute(
                """SELECT m.source_player_key,m.team,m.position,p.position_group
                   FROM roster_memberships m
                   JOIN players p ON p.id=m.player_id
                   ORDER BY m.source_player_key"""
            ).fetchall()
            self.assertEqual(
                [tuple(row) for row in members],
                [
                    ("101", "ALP", "QB", "Offense"),
                    ("202", "BET", "PK", "Special Teams"),
                ],
            )

    def test_duplicate_source_id_preserves_previous_snapshot(self):
        first = self._ingest()
        duplicate = self.rows()
        duplicate[1] = {**duplicate[1], "id": 101}
        with self.assertRaisesRegex(
            rosters.NCAAFRosterError, "conflicting memberships"
        ):
            self._ingest(duplicate)

        with sqlite3.connect(self.path) as con:
            current = con.execute(
                "SELECT id,status FROM roster_snapshots WHERE status='published'"
            ).fetchone()
            self.assertEqual(current, (first["snapshot_id"], "published"))
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2
            )

    def test_identical_duplicate_source_row_collapses(self):
        result = self._ingest(self.rows() + [dict(self.rows()[0])])
        self.assertEqual((result["status"], result["players"]), ("published", 2))

    @staticmethod
    def collided_darius_rows():
        shared = {
            "id": "5212990", "firstName": "Darius", "lastName": "Johnson",
            "weight": 180, "height": 70, "jersey": 12, "year": 1,
            "position": "CB", "homeCity": "Watkinsville", "homeState": "GA",
            "recruitIds": ["108016"],
        }
        return [
            {**shared, "team": "Georgia State"},
            {**shared, "team": "Syracuse"},
            {
                "id": "5095071", "firstName": "Darius",
                "lastName": "Johnson Jr.", "team": "Georgia State",
                "weight": 180, "height": 70, "jersey": 12, "year": 4,
                "position": "CB", "homeCity": "Watkinsville",
                "homeState": "GA", "recruitIds": ["256120"],
            },
        ]

    def test_verified_cfbd_collision_preserves_both_real_people(self):
        rosters_by_team, skipped, corrected = rosters._validated_rosters(
            self.collided_darius_rows(),
            {"Georgia State": "GAST", "Syracuse": "SYR"},
            expected_codes={"GAST", "SYR"},
        )
        self.assertEqual((skipped, corrected), (0, 2))
        self.assertEqual(
            rosters_by_team,
            {
                "GAST": [{
                    "player_id": "5095071", "name": "Darius Johnson Jr.",
                    "team": "GAST", "position": "CB",
                    "position_group": "Defense", "jersey": "12",
                }],
                "SYR": [{
                    "player_id": "5212990", "name": "Darius Johnson",
                    "team": "SYR", "position": "WR",
                    "position_group": "Offense", "jersey": "6",
                }],
            },
        )

    def test_verified_cfbd_collision_fails_closed_when_payload_drifts(self):
        rows = self.collided_darius_rows()
        rows[0] = {**rows[0], "year": 2}
        with self.assertRaisesRegex(
            rosters.NCAAFRosterError, "no longer matches.*revalidate"
        ):
            rosters._validated_rosters(
                rows,
                {"Georgia State": "GAST", "Syracuse": "SYR"},
                expected_codes={"GAST", "SYR"},
            )

    def test_empty_team_preserves_database(self):
        with self.assertRaisesRegex(
            rosters.NCAAFRosterError, "no usable members"
        ):
            self._ingest(self.rows()[:1])
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM roster_snapshots").fetchone()[0], 0
            )

    def test_unknown_position_preserves_previous_snapshot(self):
        first = self._ingest()
        invalid = self.rows()
        invalid[1] = {**invalid[1], "position": "NOT-A-POSITION"}
        with self.assertRaisesRegex(
            rosters.NCAAFRosterError, "unrecognised NCAAF position"
        ):
            self._ingest(invalid)

        with sqlite3.connect(self.path) as con:
            current = con.execute(
                "SELECT id,status FROM roster_snapshots WHERE status='published'"
            ).fetchone()
            self.assertEqual(current, (first["snapshot_id"], "published"))
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2
            )

    def test_dry_run_plans_without_mutation(self):
        result = self._ingest(dry_run=True)
        self.assertEqual(result["status"], "ready")
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM roster_snapshots").fetchone()[0], 0
            )

    def test_direct_canonical_abbreviation_beats_prefix_fallback(self):
        teams = [
            {"school": "Eastern", "abbreviation": "EWU"},
            {"school": "Eastern Michigan", "abbreviation": "EMU"},
        ]
        published, mapping = rosters._canonical_team_vocabulary(
            teams, expected_codes={"EMU"}
        )
        self.assertEqual(published, 2)
        self.assertEqual(mapping, {"Eastern Michigan": "EMU"})

    def test_missing_snapshot_schema_fails_before_source_requests(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-roster-no-schema-", suffix=".db", delete=False
        )
        path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        with sqlite3.connect(path) as con:
            con.execute(
                "CREATE TABLE players(id INTEGER PRIMARY KEY, league TEXT)"
            )
            con.commit()

        with mock.patch.object(rosters, "DB", path), \
             mock.patch.object(rosters, "_team_vocabulary") as teams, \
             mock.patch.object(rosters, "_get_json") as get_json:
            with self.assertRaisesRegex(
                ValueError, "canonical roster schema is not migrated"
            ):
                rosters.ingest(
                    2026, dry_run=True, publish_membership=True
                )
        teams.assert_not_called()
        get_json.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
