import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

import ingest_mlb_spine_identity as spine  # noqa: E402


class SpinePositionVocabularyTests(unittest.TestCase):
    """`players.position`/`position_group` get MLB's own two levels.

    MLB publishes both the specific spot (abbreviation) and the group (type)
    for every player. The group-level abbreviation `OF` is published fact for
    players with no designated spot: `position` keeps it verbatim, and
    `position_group` carries the parent so the levels stay distinguishable.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.people = []
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """CREATE TABLE players(
                 id INTEGER PRIMARY KEY,
                 name TEXT NOT NULL,
                 league TEXT NOT NULL,
                 team TEXT,
                 position TEXT,
                 position_group TEXT,
                 pitcher_role TEXT,
                 espn_id TEXT,
                 mlbam_id INTEGER,
                 active INTEGER DEFAULT 1,
                 updated_at TEXT
               )"""
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def _insert_player(self, row_id, name, mlbam_id, position):
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """INSERT INTO players(id,name,league,mlbam_id,position)
               VALUES(?,?,?,?,?)""",
            (row_id, name, "mlb", mlbam_id, position),
        )
        connection.commit()
        connection.close()

    def _run_refresh(self):
        def fake_get(url):
            if "teams" in url:
                return {"teams": [{"id": 121, "abbreviation": "NYM"}]}
            return {"people": self.people}

        with patch.object(spine, "_get", side_effect=fake_get):
            return spine.refresh(self.db_path, season=2026)

    def _row(self, mlbam_id):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT position, position_group FROM players WHERE mlbam_id=?",
            (mlbam_id,),
        ).fetchone()
        connection.close()
        return row

    def test_group_level_of_abbreviation_keeps_position_and_group(self):
        """`abbreviation='OF'` -> position='OF', position_group Outfielder.

        MLB publishes OF for players it gives no designated spot (Pache); that
        is a fact about the player, not a gap -- position keeps the published
        value and the parent lives in position_group.
        """
        self._insert_player(1, "Cristian Pache", 665506, "OF")
        self.people = [{
            "id": 665506,
            "currentTeam": {"id": 121},
            "primaryPosition": {"abbreviation": "OF", "type": "Outfielder"},
        }]
        self._run_refresh()
        row = self._row(665506)
        self.assertEqual(row["position"], "OF")
        self.assertEqual(row["position_group"], "Outfielder")

    def test_specific_spot_abbreviation_keeps_position_and_group(self):
        """`abbreviation='CF'` -> position='CF', position_group Outfielder."""
        self._insert_player(2, "A Center Fielder", 999001, "CF")
        self.people = [{
            "id": 999001,
            "currentTeam": {"id": 121},
            "primaryPosition": {"abbreviation": "CF", "type": "Outfielder"},
        }]
        self._run_refresh()
        row = self._row(999001)
        self.assertEqual(row["position"], "CF")
        self.assertEqual(row["position_group"], "Outfielder")

    def test_pitcher_position_and_group(self):
        """A starter is position='P', group 'Pitcher' -- never SP/RP here."""
        self._insert_player(3, "A Pitcher", 999002, "P")
        self.people = [{
            "id": 999002,
            "currentTeam": {"id": 121},
            "primaryPosition": {"abbreviation": "P", "type": "Pitcher"},
        }]
        self._run_refresh()
        row = self._row(999002)
        self.assertEqual(row["position"], "P")
        self.assertEqual(row["position_group"], "Pitcher")

    def test_stale_of_position_is_filled_not_nulled(self):
        """A row that previously carried 'OF' keeps it -- the value is published."""
        self._insert_player(4, "Cristian Pache", 665506, "OF")
        self._insert_player(5, "A Center Fielder", 999001, "CF")
        self.people = [
            {
                "id": 665506,
                "currentTeam": {"id": 121},
                "primaryPosition": {"abbreviation": "OF", "type": "Outfielder"},
            },
            {
                "id": 999001,
                "currentTeam": {"id": 121},
                "primaryPosition": {"abbreviation": "CF", "type": "Outfielder"},
            },
        ]
        self._run_refresh()
        pache = self._row(665506)
        cf = self._row(999001)
        self.assertEqual(pache["position"], "OF")
        self.assertEqual(pache["position_group"], "Outfielder")
        self.assertEqual(cf["position"], "CF")
        self.assertEqual(cf["position_group"], "Outfielder")


if __name__ == "__main__":
    unittest.main()
