"""Gate G for NBA checks official nba.com ids against nba.com's own published names."""
import os, sqlite3, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audit_league_stats import checks  # noqa: E402


class Out:
    def __init__(self):
        self.rows = []

    def add(self, state, league, check, detail):
        self.rows.append((state, check, detail))


def build(pairs, used, names, aliases=None):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT, hoopr_id TEXT);"
        "CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT);"
        "CREATE TABLE roster_snapshots(id INTEGER PRIMARY KEY, league TEXT, source TEXT);"
        "CREATE TABLE roster_memberships(id INTEGER PRIMARY KEY, snapshot_id INT, source_player_key TEXT, display_name TEXT);"
        "CREATE TABLE player_game_logs(player_id INT, league TEXT, season INT);")
    con.execute("INSERT INTO roster_snapshots VALUES(1,'nba','nba.com:team-roster')")
    for pid, (name, key) in enumerate(pairs, 1):
        con.execute("INSERT INTO players(id,name,league) VALUES(?,?,'nba')", (pid, name))
        if key:
            con.execute("INSERT INTO player_source_ids VALUES(?,'nba','nba.com',?)", (pid, key))
    for key, nm in names.items():
        con.execute("INSERT INTO roster_memberships(snapshot_id,source_player_key,display_name) VALUES(1,?,?)", (key, nm))
    for pid in used:
        con.execute("INSERT INTO player_game_logs VALUES(?,'nba',2027)", (pid,))
    return con


class GateG(unittest.TestCase):
    def run_gate(self, con):
        out = Out()
        checks.check_published_identity(con, "nba", {}, out)
        return out.rows[0]

    def test_pass(self):
        con = build([("Ann Lee", "11"), ("Bo Ray", "22")], [1, 2], {"11": "Ann Lee", "22": "Bo Ray"})
        self.assertEqual(self.run_gate(con)[0], "PASS")

    def test_wrong_id_fails(self):
        con = build([("Ann Lee", "22"), ("Bo Ray", "11")], [1, 2], {"11": "Ann Lee", "22": "Bo Ray"})
        state, _, detail = self.run_gate(con)
        self.assertEqual(state, "FAIL")
        self.assertIn("different player", detail)

    def test_used_player_without_id_is_unverified(self):
        con = build([("Ann Lee", "11"), ("No Id", None)], [1, 2], {"11": "Ann Lee"})
        self.assertEqual(self.run_gate(con)[0], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
