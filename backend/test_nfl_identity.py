import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from nfl_identity import (  # noqa: E402
    espn_assignment_conflict,
    load_espn_to_gsis,
)
import ingest_nfl_adp  # noqa: E402


class NFLIdentityCrosswalkTests(unittest.TestCase):
    def test_assignment_requires_publisher_ids_to_agree(self):
        crosswalk = {"4686658": "00-0040878"}

        self.assertIsNone(
            espn_assignment_conflict("4686658", "00-0040878", crosswalk)
        )
        self.assertEqual(
            "espn_gsis_identity_conflict",
            espn_assignment_conflict("4686658", "WAS569019", crosswalk),
        )
        self.assertEqual(
            "unverified_published_espn_id",
            espn_assignment_conflict("new-player", "00-0099999", crosswalk),
        )
        self.assertIsNone(
            espn_assignment_conflict("new-player", None, crosswalk)
        )

    def test_committed_register_links_the_known_conflicting_pair(self):
        crosswalk, ambiguous = load_espn_to_gsis()

        self.assertEqual("00-0040878", crosswalk["4686658"])
        self.assertEqual("00-0041026", crosswalk["4685248"])
        self.assertNotIn("4686658", ambiguous)

    def test_adp_name_fallback_rejects_a_conflicting_gsis_before_update(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT,league TEXT,"
            "team TEXT,espn_id TEXT,nfl_gsis_id TEXT)"
        )
        connection.execute(
            "INSERT INTO players VALUES(1,'Mike Washington','nfl','LV',NULL,'WAS569019')"
        )

        with self.assertRaisesRegex(RuntimeError, "espn_gsis_identity_conflict"):
            ingest_nfl_adp._find_name_only_player(
                connection,
                "Mike Washington",
                "LV",
                "4686658",
                {"4686658": "00-0040878"},
                set(),
            )

        self.assertEqual(
            (None, "WAS569019"),
            tuple(connection.execute(
                "SELECT espn_id,nfl_gsis_id FROM players WHERE id=1"
            ).fetchone()),
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
