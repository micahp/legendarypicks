import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

import roster_sync


class RosterSyncFreshnessTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE players(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT NOT NULL,
                 league TEXT NOT NULL,
                 team TEXT,
                 position TEXT,
                 espn_id TEXT,
                 active INTEGER DEFAULT 1,
                 updated_at TEXT
               )"""
        )
        self.connection.executemany(
            "INSERT INTO players(name,league,team,position,espn_id,active,updated_at) VALUES(?,?,?,?,?,?,?)",
            [
                ("Existing Quarterback", "nfl", "OLD", "QB", "101", 1, "2026-06-01T00:00:00+00:00"),
                ("Departed Player", "nfl", "OLD", "WR", "303", 1, "2026-06-01T00:00:00+00:00"),
            ],
        )
        self.connection.commit()
        self.original_expected_nfl = roster_sync._EXPECTED_TEAM_COUNTS["nfl"]
        roster_sync._EXPECTED_TEAM_COUNTS["nfl"] = 2

    def tearDown(self):
        roster_sync._EXPECTED_TEAM_COUNTS["nfl"] = self.original_expected_nfl
        self.connection.close()
        os.unlink(self.db_path)

    @staticmethod
    def teams():
        return [{"abbrev": "ARI"}, {"abbrev": "ATL"}]

    @staticmethod
    def complete_roster(_league, team):
        return {
            "ARI": [
                {"player_id": "101", "name": "Existing Quarterback", "position": "QB"},
            ],
            "ATL": [
                {"player_id": "202", "name": "New Receiver", "position": "WR"},
            ],
        }[team]

    def test_complete_population_updates_active_state_and_verification_time(self):
        with patch.object(roster_sync.espn, "team_strength", side_effect=lambda _league: self.teams()), \
             patch.object(roster_sync.espn, "roster", side_effect=self.complete_roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["teams"], 2)
        self.assertEqual(result["expected_teams"], 2)
        self.assertIsNotNone(result["verified_at"])
        rows = self.connection.execute(
            "SELECT name,team,position,espn_id,active,updated_at FROM players ORDER BY name"
        ).fetchall()
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Existing Quarterback"]["team"], "ARI")
        self.assertEqual(by_name["Existing Quarterback"]["active"], 1)
        self.assertEqual(by_name["New Receiver"]["team"], "ATL")
        self.assertEqual(by_name["New Receiver"]["active"], 1)
        self.assertEqual(by_name["Departed Player"]["active"], 0)
        self.assertTrue(all(row["updated_at"] == result["verified_at"] for row in rows))

    def test_partial_population_does_not_mutate_existing_roster(self):
        before = [tuple(row) for row in self.connection.execute(
            "SELECT id,name,team,position,espn_id,active,updated_at FROM players ORDER BY id"
        )]

        def partial_roster(_league, team):
            if team == "ATL":
                raise RuntimeError("upstream unavailable")
            return self.complete_roster(_league, team)

        with patch.object(roster_sync.espn, "team_strength", side_effect=lambda _league: self.teams()), \
             patch.object(roster_sync.espn, "roster", side_effect=partial_roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["verified_at"])
        self.assertEqual(result["failures"][0]["team"], "ATL")
        after = [tuple(row) for row in self.connection.execute(
            "SELECT id,name,team,position,espn_id,active,updated_at FROM players ORDER BY id"
        )]
        self.assertEqual(after, before)

    def test_partial_team_directory_does_not_mutate_existing_roster(self):
        before = [tuple(row) for row in self.connection.execute(
            "SELECT id,name,team,position,espn_id,active,updated_at FROM players ORDER BY id"
        )]
        with patch.object(roster_sync.espn, "team_strength", return_value=[{"abbrev": "ARI"}]), \
             patch.object(roster_sync.espn, "roster") as roster_call:
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["teams"], 1)
        self.assertEqual(result["expected_teams"], 2)
        roster_call.assert_not_called()
        after = [tuple(row) for row in self.connection.execute(
            "SELECT id,name,team,position,espn_id,active,updated_at FROM players ORDER BY id"
        )]
        self.assertEqual(after, before)

    def test_nfl_position_alias_is_normalized_at_ingest_boundary(self):
        def roster(_league, team):
            if team == "ARI":
                return [
                    {
                        "player_id": "101",
                        "name": "Existing Quarterback",
                        "position": "QB",
                    }
                ]
            return [
                {
                    "player_id": "202",
                    "name": "New Kicker",
                    "position": "K",
                }
            ]

        with patch.object(
            roster_sync.espn,
            "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=roster
        ):
            result = roster_sync.sync_league(
                self.connection, "nfl"
            )

        self.assertEqual(result["status"], "complete")
        kicker = self.connection.execute(
            "SELECT team, position FROM players "
            "WHERE name='New Kicker'"
        ).fetchone()
        self.assertEqual(
            (kicker["team"], kicker["position"]), ("ATL", "PK")
        )

    def test_unknown_nfl_position_fails_before_any_mutation(self):
        before = [
            tuple(row)
            for row in self.connection.execute(
                "SELECT id,name,team,position,espn_id,active,updated_at "
                "FROM players ORDER BY id"
            )
        ]

        def roster(_league, team):
            position = "QB" if team == "ARI" else "MYSTERY"
            return [
                {
                    "player_id": "101",
                    "name": "Existing Quarterback",
                    "position": position,
                }
            ]

        with patch.object(
            roster_sync.espn,
            "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=roster
        ):
            result = roster_sync.sync_league(
                self.connection, "nfl"
            )

        self.assertEqual(result["status"], "incomplete")
        self.assertIn(
            "not recognised", result["failures"][0]["reason"]
        )
        after = [
            tuple(row)
            for row in self.connection.execute(
                "SELECT id,name,team,position,espn_id,active,updated_at "
                "FROM players ORDER BY id"
            )
        ]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
