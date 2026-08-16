#!/usr/bin/env python3
"""The fantasy-slot migration must move positions and nothing else.

A team defence plays no position. `players.position` holds fantasy slots
(DEF/TQB/HC) beside real positions, and check C read that as a vocabulary
clash. The migration NULLs position for construct rows and leaves humans
alone, fails closed without `entity_type`, and refuses to run against a spine
whose construct count is not the expected 96.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import migrate_player_fantasy_positions as mig  # noqa: E402


def make_db(path, with_entity=True):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT,"
                " league TEXT, position TEXT, espn_id TEXT, active INTEGER"
                + (", entity_type TEXT" if with_entity else "") + ")")
    def row(pid, name, pos, eid, active, entity):
        cols = "id,name,team,league,position,espn_id,active"
        vals = (pid, name, "DAL", "nfl", pos, eid, active)
        ncols = 7
        if with_entity:
            cols += ",entity_type"
            vals += (entity,)
            ncols = 8
        placeholders = ",".join("?" for _ in range(ncols))
        con.execute(f"INSERT INTO players({cols}) VALUES({placeholders})", vals)
    for pid in range(1, 33):     # 32 defences
        row(pid, f"Team {pid} D/ST", "DEF", str(-16000 - pid), 1, "team_defense")
    for pid in range(33, 65):    # 32 TQB
        row(pid, f"Team {pid - 32} TQB", "TQB", str(-15000 - pid), 0, "team_qb")
    for pid in range(65, 97):    # 32 coaches
        row(pid, f"Coach {pid - 64}", "HC", str(-14000 - pid), 0, "coach")
    row(97, "Dak Prescott", "QB", "1", 1, "player")     # a human stays
    row(98, "Some Wideout", None, "2", 1, "player")     # blank stays blank
    con.commit()
    con.close()


class FantasyPositionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "picks.db")

    def test_dry_run_writes_nothing(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db]))
        con = sqlite3.connect(self.db)
        count = con.execute(
            "SELECT COUNT(*) FROM players WHERE league='nfl' AND position='DEF'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(32, count)

    def test_apply_nulls_fantasy_positions_and_leaves_humans(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        con = sqlite3.connect(self.db)
        try:
            counts = dict(con.execute(
                "SELECT position, COUNT(*) FROM players WHERE league='nfl' "
                "GROUP BY position"))
            self.assertNotIn("DEF", counts)
            self.assertNotIn("TQB", counts)
            self.assertNotIn("HC", counts)
            self.assertEqual("QB", con.execute(
                "SELECT position FROM players WHERE id=97").fetchone()[0])
            self.assertEqual(1, con.execute(
                "SELECT COUNT(*) FROM players WHERE entity_type='team_defense'"
            ).fetchone()[0] > 0 and 1 or 0)
        finally:
            con.close()

    def test_idempotent(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))

    def test_refuses_without_entity_type(self):
        make_db(self.db, with_entity=False)
        self.assertEqual(2, mig.main(["--db", self.db, "--apply"]))

    def test_refuses_unexpected_construct_count(self):
        make_db(self.db)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE players SET entity_type='coach' WHERE id=1")
        con.commit()
        con.close()
        self.assertEqual(2, mig.main(["--db", self.db, "--apply"]))
        # --force applies anyway
        self.assertEqual(0, mig.main(["--db", self.db, "--apply", "--force"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
