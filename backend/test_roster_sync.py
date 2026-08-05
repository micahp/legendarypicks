import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

import roster_sync
from roster_membership import create_roster_schema, source_checksum


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
        create_roster_schema(self.connection)
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
        snapshot = self.connection.execute(
            """SELECT id,league,season,source,source_checksum,source_payload,
                      team_count,player_count,status
               FROM roster_snapshots"""
        ).fetchone()
        self.assertEqual(snapshot["id"], result["snapshot_id"])
        self.assertEqual(
            (
                snapshot["league"], snapshot["season"], snapshot["source"],
                snapshot["team_count"], snapshot["player_count"],
                snapshot["status"],
            ),
            ("nfl", 2026, "espn_site_roster", 2, 2, "published"),
        )
        self.assertEqual(
            snapshot["source_checksum"],
            source_checksum(snapshot["source_payload"]),
        )
        memberships = self.connection.execute(
            """SELECT p.name,m.source_player_key,m.team,m.position
               FROM roster_memberships m
               JOIN players p ON p.id=m.player_id
               WHERE m.snapshot_id=? ORDER BY p.name""",
            (snapshot["id"],),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in memberships],
            [
                ("Existing Quarterback", "101", "ARI", "QB"),
                ("New Receiver", "202", "ATL", "WR"),
            ],
        )

    def test_missing_snapshot_schema_fails_before_source_calls(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.addCleanup(
            lambda: os.path.exists(handle.name) and os.unlink(handle.name)
        )
        connection = sqlite3.connect(handle.name)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE players(
                 id INTEGER PRIMARY KEY,
                 name TEXT NOT NULL,
                 league TEXT NOT NULL
               )"""
        )
        try:
            with patch.object(
                roster_sync.espn, "team_strength"
            ) as team_strength:
                with self.assertRaisesRegex(
                    ValueError, "schema is not migrated"
                ):
                    roster_sync.sync_league(connection, "nfl")
                team_strength.assert_not_called()
        finally:
            connection.close()

    def test_new_complete_snapshot_supersedes_prior_snapshot(self):
        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=self.complete_roster,
        ):
            first = roster_sync.sync_league(self.connection, "nfl")
            second = roster_sync.sync_league(self.connection, "nfl")

        snapshots = self.connection.execute(
            """SELECT id,status FROM roster_snapshots
               WHERE league='nfl' ORDER BY id"""
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in snapshots],
            [
                (first["snapshot_id"], "superseded"),
                (second["snapshot_id"], "published"),
            ],
        )

    def test_failed_refresh_preserves_published_snapshot(self):
        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=self.complete_roster,
        ):
            complete = roster_sync.sync_league(self.connection, "nfl")

        def partial_roster(_league, team):
            if team == "ATL":
                raise RuntimeError("upstream unavailable")
            return self.complete_roster(_league, team)

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=partial_roster,
        ):
            failed = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(failed["status"], "incomplete")
        current = self.connection.execute(
            """SELECT id,status FROM roster_snapshots
               WHERE league='nfl' AND status='published'"""
        ).fetchone()
        self.assertEqual(
            (current["id"], current["status"]),
            (complete["snapshot_id"], "published"),
        )

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

    def test_ambiguous_name_crosswalk_queues_without_partial_roster_apply(self):
        self.connection.executemany(
            """INSERT INTO players(
                 name,league,team,position,espn_id,active,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                ("Collision Name", "nfl", "ATL", "WR", None, 1, "old"),
                ("Collision Name", "nfl", "ATL", "CB", None, 1, "old"),
            ],
        )
        self.connection.commit()
        before = [
            tuple(row)
            for row in self.connection.execute(
                """SELECT id,name,team,position,espn_id,active,updated_at
                   FROM players ORDER BY id"""
            )
        ]

        def roster(_league, team):
            if team == "ARI":
                return self.complete_roster(_league, team)
            return [{
                "player_id": "404",
                "name": "Collision Name",
                "position": "WR",
            }]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=roster,
        ):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "identity_incomplete")
        self.assertIsNone(result["verified_at"])
        after = [
            tuple(row)
            for row in self.connection.execute(
                """SELECT id,name,team,position,espn_id,active,updated_at
                   FROM players ORDER BY id"""
            )
        ]
        self.assertEqual(after, before)
        unresolved = self.connection.execute(
            """SELECT source,raw_name,source_player_key,reason
               FROM unresolved_players"""
        ).fetchone()
        self.assertEqual(
            tuple(unresolved),
            (
                "espn_roster", "Collision Name", "404",
                "ambiguous_normalized_name",
            ),
        )


    def test_same_name_on_different_teams_is_resolved_by_the_roster(self):
        """Two different people can share a name -- there are two Max Muncys.

        This used to fail the entire league: one unresolvable collision left
        every other player on the roster unsynced.
        """
        self.connection.executemany(
            """INSERT INTO players(
                 name,league,team,position,espn_id,active,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                ("Max Muncy", "nfl", "ARI", "QB", None, 1, "old"),
                ("Max Muncy", "nfl", "ATL", "WR", None, 1, "old"),
            ],
        )
        self.connection.commit()

        def roster(_league, team):
            return {
                "ARI": [{"player_id": "501", "name": "Max Muncy",
                         "position": "QB"}],
                "ATL": [{"player_id": "502", "name": "Max Muncy",
                         "position": "WR"}],
            }[team]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "complete", result.get("failures"))
        # Each was matched to the row already on that team, not to the other.
        rows = {
            r["team"]: r["espn_id"]
            for r in self.connection.execute(
                "SELECT team, espn_id FROM players WHERE name='Max Muncy'"
            )
        }
        self.assertEqual(rows, {"ARI": "501", "ATL": "502"})

    def test_middle_initial_homonyms_resolve_to_different_rows(self):
        """Two Muncys where one DB row carries a bare middle initial.

        'Max P. Muncy' and 'Max Muncy' land in DIFFERENT buckets under a
        plain name normalize, so an ESPN entry spelled plain 'Max Muncy'
        on the middle-initial player's team finds only the OTHER Muncy and
        is silently assigned the wrong player_id. The bucket key must strip
        the bare middle initial (the identity key does) so both rows are
        candidates and the team-narrowing ladder separates them.
        """
        self.connection.executemany(
            """INSERT INTO players(
                 name,league,team,position,espn_id,active,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                ("Max P. Muncy", "nfl", "ARI", "QB", None, 1, "old"),
                ("Max Muncy", "nfl", "ATL", "WR", None, 1, "old"),
            ],
        )
        self.connection.commit()

        def roster(_league, team):
            return {
                "ARI": [{"player_id": "701", "name": "Max Muncy",
                         "position": "QB"}],
                "ATL": [{"player_id": "702", "name": "Max Muncy",
                         "position": "WR"}],
            }[team]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "complete", result.get("failures"))
        rows = {
            r["team"]: (r["id"], r["name"], r["espn_id"])
            for r in self.connection.execute(
                "SELECT id, name, team, espn_id FROM players "
                "WHERE name LIKE '%Muncy%'"
            )
        }
        # The two ESPN entries resolved to DIFFERENT players -- each row kept
        # its own team and took its own source id.
        self.assertEqual(rows["ARI"], (rows["ARI"][0], "Max P. Muncy", "701"))
        self.assertEqual(rows["ATL"], (rows["ATL"][0], "Max Muncy", "702"))
        self.assertNotEqual(rows["ARI"][0], rows["ATL"][0])

    def test_a_trade_is_applied_rather_than_blocking_the_league(self):
        """A team mismatch on a unique name is a trade, and the roster is newer.

        Failing on it made the sync unable to do the one thing it exists for.
        """
        self.connection.execute(
            """INSERT INTO players(
                 name,league,team,position,espn_id,active,updated_at
               ) VALUES('Traded Player','nfl','ARI','WR',NULL,1,'old')"""
        )
        self.connection.commit()

        def roster(_league, team):
            if team == "ATL":
                return [{"player_id": "601", "name": "Traded Player",
                         "position": "WR"}]
            return [{"player_id": "101", "name": "Existing Quarterback",
                     "position": "QB"}]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "complete", result.get("failures"))
        row = self.connection.execute(
            "SELECT team, espn_id FROM players WHERE name='Traded Player'"
        ).fetchone()
        self.assertEqual((row["team"], row["espn_id"]), ("ATL", "601"))

    def test_a_conflicting_espn_id_still_blocks(self):
        """The evidence standard did not move: a contradicting id is not a trade."""
        self.connection.execute(
            """INSERT INTO players(
                 name,league,team,position,espn_id,active,updated_at
               ) VALUES('Conflicted Player','nfl','ARI','WR','999',1,'old')"""
        )
        self.connection.commit()

        def roster(_league, team):
            if team == "ATL":
                return [{"player_id": "602", "name": "Conflicted Player",
                         "position": "WR"}]
            return [{"player_id": "101", "name": "Existing Quarterback",
                     "position": "QB"}]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "identity_incomplete")
        self.assertEqual(
            result["failures"][0]["reason"], "name_match_conflicting_espn_id"
        )

    def test_missing_source_identity_queues_and_preserves_roster(self):
        before = [
            tuple(row)
            for row in self.connection.execute(
                """SELECT id,name,team,position,espn_id,active,updated_at
                   FROM players ORDER BY id"""
            )
        ]

        def roster(_league, team):
            if team == "ARI":
                return self.complete_roster(_league, team)
            return [{
                "player_id": None,
                "name": "No Source Identity",
                "position": "WR",
            }]

        with patch.object(
            roster_sync.espn, "team_strength",
            side_effect=lambda _league: self.teams(),
        ), patch.object(
            roster_sync.espn, "roster", side_effect=roster,
        ):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "identity_incomplete")
        after = [
            tuple(row)
            for row in self.connection.execute(
                """SELECT id,name,team,position,espn_id,active,updated_at
                   FROM players ORDER BY id"""
            )
        ]
        self.assertEqual(after, before)
        unresolved = self.connection.execute(
            """SELECT source_player_key,reason FROM unresolved_players"""
        ).fetchone()
        self.assertEqual(
            tuple(unresolved), (None, "missing_espn_id")
        )

    def test_one_unidentifiable_player_does_not_block_the_league(self):
        """A player we cannot identify is a fact about that player, not the league.

        On 2026-08-04 one duplicated roster id blocked all 32 NHL teams and one
        conflicting name blocked all 30 MLB ones, so neither league got a single
        team or espn_id populated. The odd player is queued; everyone else syncs.
        """
        big = [
            {"player_id": str(900 + i), "name": f"Roster Player {i}", "position": "WR"}
            for i in range(60)
        ]
        # The same source id twice -- ESPN does this when a player is carried on
        # two rosters mid-move. The second occurrence is unidentifiable.
        dupe = {"player_id": "900", "name": "Duplicated Person", "position": "TE"}

        def roster(_league, team):
            return self.complete_roster(_league, team) if team == "ARI" else big + [dupe]

        with patch.object(
            roster_sync.espn, "team_strength", side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "complete", result.get("failures"))
        self.assertEqual([u["reason"] for u in result["unresolved"]],
                         ["duplicate_source_roster_id"])
        # The point of the whole job: the other players actually got their team.
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM players WHERE league='nfl' AND team='ATL'"
            ).fetchone()[0],
            60,
        )
        # Queued for review rather than silently dropped.
        self.assertEqual(
            self.connection.execute(
                "SELECT reason FROM unresolved_players"
            ).fetchone()[0],
            "duplicate_source_roster_id",
        )

    def test_a_team_with_no_usable_entry_still_blocks_the_league(self):
        """The tolerance is for odd players, not for a source that has gone bad.

        Apply resets active=0 for the whole league first, so a roster fetch
        returning junk would deactivate everyone. That must still change nothing.
        """
        before = [
            tuple(row) for row in self.connection.execute(
                "SELECT id,name,team,espn_id,active FROM players ORDER BY id"
            )
        ]

        def roster(_league, team):
            if team == "ARI":
                return self.complete_roster(_league, team)
            return [{"player_id": None, "name": "Nameless One", "position": "WR"}]

        with patch.object(
            roster_sync.espn, "team_strength", side_effect=lambda _league: self.teams(),
        ), patch.object(roster_sync.espn, "roster", side_effect=roster):
            result = roster_sync.sync_league(self.connection, "nfl")

        self.assertEqual(result["status"], "identity_incomplete")
        self.assertEqual(result["empty_teams"], ["ATL"])
        self.assertIsNone(result["verified_at"])
        after = [
            tuple(row) for row in self.connection.execute(
                "SELECT id,name,team,espn_id,active FROM players ORDER BY id"
            )
        ]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
