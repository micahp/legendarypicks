import os, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_identity_resolve as r  # noqa: E402


def db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT, hoopr_id TEXT);"
        "CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT);")
    # the real William Kyle collision: existing row, nba.com id only
    con.execute("INSERT INTO players(id,name,league) VALUES(63170,'William Kyle','nba')")
    con.execute("INSERT INTO player_source_ids VALUES(63170,'nba','nba.com','1643759')")
    return con


class Resolve(unittest.TestCase):
    def test_william_kyle_iii_reuses_63170_through_the_nba_com_id(self):
        action, pid, _ = r.resolve(db(), "5107258", "William Kyle III", nba_com_id="1643759")
        self.assertEqual((action, pid), ("attach_espn", 63170))

    def test_without_id_evidence_it_holds_instead_of_creating(self):
        action, pid, _ = r.resolve(db(), "5107258", "William Kyle III")
        self.assertEqual((action, pid), ("hold", 63170))

    def test_conflicting_espn_id_holds(self):
        con = db()
        con.execute("UPDATE players SET espn_id='999' WHERE id=63170")
        action, pid, _ = r.resolve(con, "5107258", "William Kyle III", nba_com_id="1643759")
        self.assertEqual(action, "hold")

    def test_existing_espn_owner_is_reused(self):
        con = db()
        con.execute("UPDATE players SET espn_id='5107258' WHERE id=63170")
        self.assertEqual(r.resolve(con, "5107258", "William Kyle III")[:2], ("reuse", 63170))

    def test_hoopr_id_owner_with_a_different_espn_id_holds(self):
        con = db()
        con.execute("UPDATE players SET hoopr_id='5107258', espn_id='4001' WHERE id=63170")
        self.assertEqual(r.resolve(con, "5107258", "Bill Kyle")[0], "hold")

    def test_espn_owner_with_a_conflicting_nba_com_id_holds(self):
        con = db()
        con.execute("UPDATE players SET espn_id='5107258' WHERE id=63170")
        action, _, why = r.resolve(con, "5107258", "William Kyle III", nba_com_id="9999999")
        self.assertEqual(action, "hold")
        self.assertIn("conflicts", why)

    def test_unrelated_player_is_created(self):
        self.assertEqual(r.resolve(db(), "123", "Someone Else")[0], "create")


if __name__ == "__main__":
    unittest.main()
