#!/usr/bin/env python3
"""The declared foreign keys must actually fire.

`props.player_id`, `props.game_id` and `prop_results.prop_id` have declared
their references since the schema was written. SQLite defaults enforcement OFF
per connection, so none of them had ever fired: 78 props on both databases
pointed at 15 deleted `players` rows, and 4 `prop_results` outlived the props
they graded. Nothing raised and nothing counted them.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class TheDeclaredForeignKeysAreEnforced(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="fk-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        # Let _core build the schema. Hand-writing it here would be a fixture
        # declaring its own version of a shipped table -- the drift that had
        # earlier fixtures in this repo describing a `player_game_logs` without
        # the `source` column the real one has.
        # Reloading _core rebinds a MODULE-LEVEL DB path, so this must be put
        # back or every test collected afterwards talks to a deleted temp file.
        # The first version of this test did not, and it broke
        # test_game_detail_live_status two files later -- a failure that
        # disappeared when that test was run alone.
        import importlib
        import _core
        previous = os.environ.get("LP_DB_PATH")

        def restore():
            if previous is None:
                os.environ.pop("LP_DB_PATH", None)
            else:
                os.environ["LP_DB_PATH"] = previous
            importlib.reload(_core)

        self.addCleanup(restore)
        os.environ["LP_DB_PATH"] = self.path
        importlib.reload(_core)
        self.core = _core
        con = self.core._db()
        con.execute("INSERT INTO players(id, name, league) VALUES(1,'Real Player','mlb')")
        con.execute("INSERT INTO prop_games(id, league, date, home, away)"
                    " VALUES(1,'mlb','2026-08-26','H','A')")
        con.commit()

    def test_the_pragma_is_on_for_every_connection(self):
        self.assertEqual(
            self.core._db().execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_a_prop_cannot_name_a_player_that_does_not_exist(self):
        con = self.core._db()
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO props(game_id, player_id, market, line, side, source,"
                " captured_at) VALUES(1, 99999, 'hits', 0.5, 'over', 'bovada', 'now')")
            con.commit()

    def test_a_result_cannot_outlive_its_prop(self):
        con = self.core._db()
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO prop_results(prop_id, actual_value, hit,"
                        " settled_at) VALUES(99999, 1.0, 1, 'now')")
            con.commit()

    def test_an_unresolved_prop_is_still_allowed(self):
        """NULL is the fail-closed path the resolvers already use; enforcement
        must not turn an honestly unresolved prop into an error."""
        con = self.core._db()
        con.execute(
            "INSERT INTO props(game_id, player_id, market, line, side, source,"
            " captured_at) VALUES(1, NULL, 'hits', 0.5, 'over', 'bovada', 'now')")
        con.commit()
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM props WHERE player_id IS NULL").fetchone()[0], 1)

    def test_a_real_prop_still_writes(self):
        con = self.core._db()
        con.execute(
            "INSERT INTO props(game_id, player_id, market, line, side, source,"
            " captured_at) VALUES(1, 1, 'hits', 0.5, 'over', 'bovada', 'now')")
        con.commit()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM props").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
