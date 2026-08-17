#!/usr/bin/env python3
"""Classification must survive the other migration, and must survive a re-run.

The regression this file exists for, 2026-08-17: `migrate_player_fantasy_positions`
NULLs `players.position` for rows it selects BY `entity_type`, and this migration
used to classify FROM `position`. Run them in that order and every one of the 96
NFL constructs came back 'unknown' -- which is what `ingest_nfl_adp.py` builds its
D/ST team map from, so its fail-closed preflight aborted every run with
`def_to_pid has 0 entries, expected 32`.

Two independent properties are asserted here, because either alone would have
been enough to prevent it: classification comes from the publisher's id encoding
(a fact no migration in this repo can empty), and a known category is never
downgraded to 'unknown' by a re-run.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import migrate_player_entity_type as mig  # noqa: E402
import migrate_player_fantasy_positions as fantasy  # noqa: E402


def make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT,"
                " league TEXT, position TEXT, espn_id TEXT, active INTEGER,"
                " entity_type TEXT)")

    def row(pid, name, league, pos, eid, entity):
        con.execute(
            "INSERT INTO players(id,name,team,league,position,espn_id,active,"
            "entity_type) VALUES(?,?,'DAL',?,?,?,1,?)",
            (pid, name, league, pos, eid, entity))

    for i in range(1, 33):
        row(i, f"Team {i} D/ST", "nfl", "DEF", str(-16000 - i), "team_defense")
        row(100 + i, f"Team {i} TQB", "nfl", "TQB", str(-15000 - i), "team_qb")
        row(200 + i, f"Coach {i}", "nfl", "HC", str(-14000 - i), "coach")
    row(300, "Dak Prescott", "nfl", "QB", "1", "player")
    # The publisher's own unresolved row: negative, but no construct base.
    row(301, "?", "nfl", None, "-65018", "unknown")
    # Two NCAAF team rows sit inside the same numeric window and are NOT
    # fantasy constructs. Measured on prod: -15591 (CCU), -14550 (FIU).
    row(302, "Team", "ncaaf", None, "-15591", "unknown")
    row(303, "Team", "ncaaf", None, "-14550", "unknown")
    con.commit()
    con.close()


def types(db):
    con = sqlite3.connect(db)
    try:
        return dict(con.execute(
            "SELECT entity_type, COUNT(*) FROM players GROUP BY 1"))
    finally:
        con.close()


class ClassifyTests(unittest.TestCase):
    def test_id_base_decides_not_position(self):
        # No position at all -- the id alone must be enough.
        self.assertEqual("team_defense", mig.classify(None, "-16001", "nfl"))
        self.assertEqual("team_qb", mig.classify(None, "-15034", "nfl"))
        self.assertEqual("coach", mig.classify(None, "-14012", "nfl"))

    def test_position_still_works_as_fallback(self):
        # A database migrated in the other order: labels survive, and a base we
        # do not recognise must still classify from them.
        self.assertEqual("team_defense", mig.classify("DEF", "-99001", "nfl"))

    def test_non_nfl_in_the_same_window_is_not_a_construct(self):
        self.assertEqual("unknown", mig.classify(None, "-15591", "ncaaf"))
        self.assertEqual("unknown", mig.classify(None, "-14550", "ncaaf"))

    def test_bare_base_is_no_team(self):
        self.assertEqual("unknown", mig.classify(None, "-16000", "nfl"))

    def test_positive_id_is_a_person(self):
        self.assertEqual("player", mig.classify(None, "4361741", "nfl"))
        self.assertEqual("player", mig.classify(None, None, "nfl"))


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "picks.db")
        make_db(self.db)

    def test_survives_the_fantasy_position_migration(self):
        """The exact 2026-08-17 sequence. 32 team defences must remain 32."""
        self.assertEqual(0, fantasy.main(["--db", self.db, "--apply"]))
        con = sqlite3.connect(self.db)
        left = con.execute(
            "SELECT COUNT(*) FROM players WHERE league='nfl' "
            "AND position IS NOT NULL AND entity_type='team_defense'").fetchone()[0]
        con.close()
        self.assertEqual(0, left, "precondition: position was emptied")

        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        self.assertEqual(32, types(self.db).get("team_defense"))
        self.assertEqual(32, types(self.db).get("team_qb"))
        self.assertEqual(32, types(self.db).get("coach"))

    def test_never_downgrades_a_classified_row(self):
        """Belt and braces: even with the id gone, a category is not taken back."""
        con = sqlite3.connect(self.db)
        con.execute("UPDATE players SET position=NULL, espn_id='-99999' "
                    "WHERE entity_type='team_defense'")
        con.commit()
        con.close()
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        self.assertEqual(32, types(self.db).get("team_defense"))

    def test_rerun_is_a_no_op(self):
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        first = types(self.db)
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        self.assertEqual(first, types(self.db))

    def test_dry_run_writes_nothing(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE players SET entity_type='unknown' WHERE league='nfl'")
        con.commit()
        con.close()
        before = types(self.db)
        self.assertEqual(0, mig.main(["--db", self.db]))
        self.assertEqual(before, types(self.db))


class ProbeTests(unittest.TestCase):
    """The manifest probe must fail on the broken state, not read 'applied'."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "picks.db")
        make_db(self.db)

    def test_probe_rejects_populated_but_unclassified(self):
        import migration_manifest
        con = sqlite3.connect(self.db)
        con.execute("UPDATE players SET entity_type='unknown' WHERE league='nfl'")
        con.commit()
        result = migration_manifest._probe_player_entity_type(con)
        con.close()
        self.assertIn("expected 32", result)

    def test_probe_accepts_the_repaired_state(self):
        import migration_manifest
        con = sqlite3.connect(self.db)
        result = migration_manifest._probe_player_entity_type(con)
        con.close()
        self.assertEqual("applied", result)

    def test_probe_is_silent_on_a_database_with_no_nfl_spine(self):
        """A fixture holding no constructs has nothing to classify."""
        import migration_manifest
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM players WHERE league='nfl'")
        con.commit()
        result = migration_manifest._probe_player_entity_type(con)
        con.close()
        self.assertEqual("applied", result)


if __name__ == "__main__":
    unittest.main()
