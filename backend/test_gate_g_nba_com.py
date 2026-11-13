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


def build(pairs, used, names, aliases=None, dnp=()):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT, hoopr_id TEXT);"
        "CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT);"
        "CREATE TABLE roster_snapshots(id INTEGER PRIMARY KEY, league TEXT, source TEXT);"
        "CREATE TABLE roster_memberships(id INTEGER PRIMARY KEY, snapshot_id INT, source_player_key TEXT, display_name TEXT);"
        "CREATE TABLE player_game_logs(player_id INT, league TEXT, season INT, stats TEXT);")
    con.execute("INSERT INTO roster_snapshots VALUES(1,'nba','nba.com:team-roster')")
    for pid, (name, key) in enumerate(pairs, 1):
        con.execute("INSERT INTO players(id,name,league) VALUES(?,?,'nba')", (pid, name))
        if key:
            con.execute("INSERT INTO player_source_ids VALUES(?,'nba','nba.com',?)", (pid, key))
    for key, nm in names.items():
        con.execute("INSERT INTO roster_memberships(snapshot_id,source_player_key,display_name) VALUES(1,?,?)", (key, nm))
    for pid in used:
        minutes = 0 if pid in dnp else 20
        con.execute("INSERT INTO player_game_logs VALUES(?,'nba',2027,?)", (pid, '{"MIN": %s}' % minutes))
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

    def test_participation_coverage_is_reported_beside_identity_coverage(self):
        con = build([("Ann Lee", "11"), ("Bench Only", None)], [1, 2], {"11": "Ann Lee"}, dnp={2})
        state, _, detail = self.run_gate(con)
        self.assertEqual(state, "PASS")        # a no-minutes player does not block
        self.assertIn("IDENTITY coverage: 1 of 2", detail)
        self.assertIn("PARTICIPATION coverage: 1 of 1 players with minutes verified", detail)
        self.assertIn("1 unverified players never had minutes", detail)

    def test_a_played_but_unverified_player_lowers_participation_coverage(self):
        con = build([("Ann Lee", "11"), ("No Id", None)], [1, 2], {"11": "Ann Lee"})
        _, _, detail = self.run_gate(con)
        self.assertIn("PARTICIPATION coverage: 1 of 2", detail)

    def test_an_orphan_player_id_is_not_counted_as_a_verified_participant(self):
        con = build([("Ann Lee", "11")], [1, 99], {"11": "Ann Lee"})   # 99 has no players row
        _, _, detail = self.run_gate(con)
        self.assertIn("orphan player_ids=1", detail)
        self.assertIn("PARTICIPATION coverage: 1 of 2", detail)

    def test_a_wrong_pairing_still_fails_even_if_that_player_never_played(self):
        con = build([("Ann Lee", "22"), ("Bo Ray", "11")], [1], {"11": "Ann Lee", "22": "Bo Ray"}, dnp={1})
        self.assertEqual(self.run_gate(con)[0], "FAIL")

    def test_an_orphan_log_still_blocks(self):
        con = build([("Ann Lee", "11")], [1, 99], {"11": "Ann Lee"}, dnp={99})
        self.assertEqual(self.run_gate(con)[0], "UNVERIFIED")


class GateBSample(unittest.TestCase):
    def run_b(self, rows, entry):
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, position TEXT, position_group TEXT);"
                          "CREATE TABLE player_game_logs(player_id INT, league TEXT, season INT, stats TEXT);")
        con.execute("INSERT INTO players VALUES(1,'A','nba','PG','Guard')")
        for stats in rows:
            con.execute("INSERT INTO player_game_logs VALUES(1,'nba',2027,?)", (stats,))
        out = Out()
        checks.check_position_content(con, "nba", {"position_content": {"PG": entry}}, out)
        return out.rows[0]

    ENTRY = {"keys": [["PTS"], ["MIN"]], "coverage": 0.8, "min_sample": 3, "qualify_nonzero": "MIN"}

    def test_enough_real_appearances_pass(self):
        self.assertEqual(self.run_b(['{"PTS":1,"MIN":9}'] * 3, self.ENTRY)[0], "PASS")

    def test_a_thin_sample_is_unverified_not_a_pass(self):
        state, _, detail = self.run_b(['{"PTS":1,"MIN":9}'] * 2, self.ENTRY)
        self.assertEqual(state, "UNVERIFIED")
        self.assertIn("insufficient sample", detail)

    def test_did_not_play_rows_do_not_count_as_observations(self):
        state, _, detail = self.run_b(['{"PTS":0,"MIN":0}'] * 5, self.ENTRY)
        self.assertEqual(state, "UNVERIFIED")
        self.assertIn("no actual appearance", detail)

    def test_a_collapsed_stat_still_fails(self):
        self.assertEqual(self.run_b(['{"PTS":null,"MIN":9}'] * 3, self.ENTRY)[0], "FAIL")


if __name__ == "__main__":
    unittest.main()


class GateBDeferToGroup(unittest.TestCase):
    """A thin granular position is covered by its group's PASS, never by default."""

    GROUP = {"keys": [["PTS"], ["MIN"]], "coverage": 0.8, "min_sample": 3, "qualify_nonzero": "MIN"}

    def run_b(self, pg_logs, guard_logs, defer=True):
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, position TEXT, position_group TEXT);"
                          "CREATE TABLE player_game_logs(player_id INT, league TEXT, season INT, stats TEXT);")
        con.execute("INSERT INTO players VALUES(1,'A','nba','PG','Guard')")
        con.execute("INSERT INTO players VALUES(2,'B','nba','G','Guard')")
        for stats in pg_logs:
            con.execute("INSERT INTO player_game_logs VALUES(1,'nba',2027,?)", (stats,))
        for stats in guard_logs:
            con.execute("INSERT INTO player_game_logs VALUES(2,'nba',2027,?)", (stats,))
        entry = dict(self.GROUP, **({"defer_to_group": "Guard"} if defer else {}))
        out = Out()
        checks.check_position_content(con, "nba", {"position_content": {"PG": entry},
                                                   "position_group_content": {"Guard": self.GROUP}}, out)
        return {r[1]: r for r in out.rows}

    GOOD = ['{"PTS":1,"MIN":9}'] * 4

    def test_thin_position_passes_when_its_group_passes(self):
        rows = self.run_b(['{"PTS":1,"MIN":9}'], self.GOOD)
        self.assertEqual(rows["B/position-content[PG]"][0], "PASS")
        self.assertIn("validated on the Guard group", rows["B/position-content[PG]"][2])

    def test_no_logs_at_all_defers_too(self):
        rows = self.run_b([], self.GOOD)
        self.assertEqual(rows["B/position-content[PG]"][0], "PASS")

    def test_thin_position_stays_unverified_when_the_group_is_also_thin(self):
        rows = self.run_b(['{"PTS":1,"MIN":9}'], ['{"PTS":1,"MIN":9}'])
        self.assertEqual(rows["B/position-content[PG]"][0], "UNVERIFIED")

    def test_thin_position_stays_unverified_without_a_defer_declaration(self):
        rows = self.run_b(['{"PTS":1,"MIN":9}'], self.GOOD, defer=False)
        self.assertEqual(rows["B/position-content[PG]"][0], "UNVERIFIED")

    def test_a_granular_position_with_missing_stats_still_fails(self):
        rows = self.run_b(['{"MIN":9}'] * 3, self.GOOD)
        self.assertEqual(rows["B/position-content[PG]"][0], "FAIL")
