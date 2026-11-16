import os
import sqlite3
import tempfile
import unittest

import hoopr_column
import migrate_players_hoopr_id as mig


def make_db(path, column="nba_id"):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, league TEXT, "
                "espn_id TEXT, {} INTEGER, active INTEGER)".format(column))
    con.execute("CREATE INDEX idx_h ON players(league, {})".format(column))
    con.executemany("INSERT INTO players VALUES (?,?,?,?,?,?)", [
        (1, "A", "nba", None, 111, 0), (2, "B", "nba", "222", None, 1),
        (3, "C", "nfl", "333", None, 1), (4, "D", "nba", "444", 444, 1)])
    con.commit()
    con.close()


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "t.db")
        make_db(self.db)

    def tearDown(self):
        self.dir.cleanup()

    def rows(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT * FROM players ORDER BY id").fetchall()
        finally:
            con.close()

    def test_dry_run_changes_nothing(self):
        before = self.rows()
        self.assertEqual(mig.main(["--db", self.db]), 0)
        con = sqlite3.connect(self.db)
        self.assertEqual(hoopr_column.hoopr_column(con), "nba_id")
        self.assertEqual(self.rows(), before)

    def test_apply_keeps_every_value_id_and_index(self):
        before = self.rows()
        mig.main(["--db", self.db, "--apply"])
        con = sqlite3.connect(self.db)
        self.assertEqual(hoopr_column.hoopr_column(con), "hoopr_id")
        self.assertEqual(self.rows(), before)
        self.assertIn("hoopr_id", con.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_h'").fetchone()[0])

    def test_idempotent_and_rollback(self):
        before = self.rows()
        mig.main(["--db", self.db, "--apply"])
        self.assertEqual(mig.main(["--db", self.db, "--apply"]), 0)
        mig.main(["--db", self.db, "--rollback"])
        con = sqlite3.connect(self.db)
        self.assertEqual(hoopr_column.hoopr_column(con), "nba_id")
        self.assertEqual(self.rows(), before)

    def test_refuses_when_both_columns_exist(self):
        con = sqlite3.connect(self.db)
        con.execute("ALTER TABLE players ADD COLUMN hoopr_id INTEGER")
        con.commit()
        con.close()
        with self.assertRaises(SystemExit):
            mig.main(["--db", self.db, "--apply"])


if __name__ == "__main__":
    unittest.main()
