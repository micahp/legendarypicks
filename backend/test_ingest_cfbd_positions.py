#!/usr/bin/env python3
"""A player is never minted into the spine without the position his publisher gives.

ingest_cfbd_logs inserted every unknown athlete as `position NULL, position_group NULL`
with the comment "left NULL for the roster sync to backfill". The roster sync reads ESPN's
published team rosters, and these athletes are in the DB precisely because they appeared in
a game CFBD covered rather than on an ESPN roster — so the promised backfill never ran for
any of them. Measured 2026-08-16: 5,853 active NCAAF players with no position, 27% of the
league, and nothing ever raised, because position decides which columns a game log renders
and a blank one renders a generic table that reads as coverage (fail-loudly §2c).

CFBD publishes the position, keyed by the same athlete id, one request per season.
"""
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_cfbd_logs as cfbd


class MintWithPublishedPositionTests(unittest.TestCase):
    def setUp(self):
        del cfbd._MINTED_WITHOUT_POSITION[:]
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE players(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,"
            " team TEXT, league TEXT, espn_id TEXT, position TEXT, position_group TEXT,"
            " active INTEGER, updated_at TEXT)")

    def _mint(self, athlete_id, positions):
        player_id = cfbd._resolve_or_create(
            self.con, {}, athlete_id, "Some Athlete", "ARK", positions)
        return self.con.execute(
            "SELECT position, position_group FROM players WHERE id=?",
            (player_id,)).fetchone()

    def test_a_published_position_is_written_at_mint_time(self):
        row = self._mint("3116099", {"3116099": ("WR", "Offense")})
        self.assertEqual((row["position"], row["position_group"]), ("WR", "Offense"))
        self.assertEqual(cfbd._MINTED_WITHOUT_POSITION, [])

    def test_an_athlete_the_roster_does_not_cover_is_counted_not_hidden(self):
        """FCS squads CFBD does not roster are a real residue — it must be a number."""
        row = self._mint("999999", {"3116099": ("WR", "Offense")})
        self.assertIsNone(row["position"])
        self.assertEqual(cfbd._MINTED_WITHOUT_POSITION, ["Some Athlete"])

    def test_no_roster_at_all_still_ingests_and_still_counts(self):
        """An unreadable roster degrades the run; it must not silently zero the count."""
        row = self._mint("3116099", {})
        self.assertIsNone(row["position"])
        self.assertEqual(len(cfbd._MINTED_WITHOUT_POSITION), 1)

    def test_cfbd_unknown_marker_is_not_stored_as_a_position(self):
        """CFBD writes '?' for unknown. Storing it is worse than NULL: it looks like
        a value, and no position vocabulary contains it."""
        rows = [{"id": 1, "position": "?"}, {"id": 2, "position": "QB"}]
        cfbd._get_json = lambda url: rows
        published = cfbd._published_positions(2026)
        self.assertNotIn("1", published)
        self.assertEqual(published["2"][0], "QB")


if __name__ == "__main__":
    unittest.main()
