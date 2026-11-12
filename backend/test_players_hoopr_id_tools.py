"""Probe, link script and report work with the old and the new column name."""
import os, sqlite3, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))
import migration_manifest  # noqa: E402
import link_nba_espn_ids  # noqa: E402


def make(path, col):
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, "
        "espn_id TEXT, %s TEXT, team TEXT, position TEXT, active INTEGER);"
        "CREATE TABLE unresolved_players(source_player_key TEXT, league TEXT);"
        "CREATE TABLE player_source_ids(source TEXT, source_player_key TEXT, "
        "league TEXT, player_id INTEGER);" % col)
    con.execute("INSERT INTO players(id,name,league,%s) VALUES(1,'A','nba','777')" % col)
    con.execute("INSERT INTO unresolved_players VALUES('777','nba')")
    con.commit()
    return con


class Tools(unittest.TestCase):
    def check(self, col, probe_prefix):
        with tempfile.TemporaryDirectory() as d:
            con = make(os.path.join(d, "x.db"), col)
            self.assertTrue(migration_manifest._probe_players_hoopr_id(con).startswith(probe_prefix))
            plan, skipped = link_nba_espn_ids.build_plan(con)
            self.assertEqual([(k, p) for k, p, _ in plan], [("777", 1)])
            self.assertEqual(skipped, [])

    def test_new_name(self):
        self.check("hoopr_id", "applied")

    def test_old_name(self):
        self.check("nba_id", "not_applied")


if __name__ == "__main__":
    unittest.main()
