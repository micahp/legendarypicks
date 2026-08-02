"""Tests for the two mechanisms league-0 exists to install.

Neither of these is about NBA 2025-26. They are about the properties that have to
hold for every league added after it — see docs/DATA-COVERAGE-CONTRACT.md §4 and §9.
The season-specific numbers live in verify-gates.sh (COV-nba, COV-nhl), where they
can be read next to the arithmetic that produced them.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_team_parity as bp
import reconcile_totals as rt


class TransactionStateTests(unittest.TestCase):
    """The bug that lost four NBA games and one NHL game, as a test.

    `run_league()` wraps each game's writes in an explicit BEGIN/COMMIT. Under
    sqlite3's default implicit-transaction mode the driver opens a transaction of its
    own before a DML statement, so the explicit BEGIN raises
    "cannot start a transaction within a transaction" — sporadically, because it
    depends on what ran immediately before. 4 of 1231 is easy to never notice.
    """

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.path)

    def test_default_isolation_reproduces_the_failure(self):
        """Documents the defect. If this ever stops raising, sqlite3 changed, not us."""
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE t(x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")   # driver opens a transaction here
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            con.execute("BEGIN")
        self.assertIn("transaction", str(ctx.exception))
        con.close()

    def test_autocommit_allows_explicit_transactions(self):
        """The fix: writes survive an interleaved statement, which is the real scenario."""
        con = sqlite3.connect(self.path, isolation_level=None)
        con.execute("CREATE TABLE t(x INTEGER)")
        con.execute("INSERT INTO t VALUES (1)")
        con.execute("BEGIN")
        con.execute("INSERT INTO t VALUES (2)")
        con.commit()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM t").fetchone()[0], 2)
        con.close()

    def test_main_opens_the_connection_in_autocommit(self):
        """The fix has to be at the connection, not at one call site."""
        import inspect
        src = inspect.getsource(bp.main)
        self.assertIn("isolation_level=None", src)


class PostponedGameTests(unittest.TestCase):
    """A postponed game is state="post" with a score of 0, not null.

    Both halves matter: the state filter passes it, and the `val is None` guard passes
    it, so it lands as a played 0-0 result and the makeup lands separately under its
    own event id. `completed` is the field that answers the question being asked.
    """

    @staticmethod
    def _event(state, completed, scores):
        return {
            "id": "1",
            "date": "2026-01-24T00:00Z",
            "competitions": [{
                "status": {"type": {"state": state, "completed": completed}},
                "competitors": [
                    {"team": {"abbreviation": ab},
                     "score": {"value": v}, "homeAway": ha, "winner": False}
                    for (ab, v, ha) in scores
                ],
            }],
        }

    def test_postponed_shell_is_not_a_played_game(self):
        ev = self._event("post", False, [("MIN", 0.0, "home"), ("GS", 0.0, "away")])
        comp = ev["competitions"][0]
        self.assertEqual(comp["status"]["type"]["state"], "post")       # passes the old filter
        self.assertIsNotNone(comp["competitors"][0]["score"]["value"])  # passes the None guard
        self.assertFalse(comp["status"]["type"]["completed"])           # and is still not a game

    def test_enumerate_filters_on_completed(self):
        import inspect
        src = inspect.getsource(bp.enumerate_games)
        self.assertIn('kind.get("completed")', src)
        self.assertNotIn('!= "post"', src)


class VerdictTests(unittest.TestCase):
    """`unverified` is not `partial`, and neither may be reached by accident."""

    def test_no_checks_at_all_is_unverified(self):
        rep = rt.Report()
        self.assertEqual(rep.verdict("mls", 2025), "unverified")

    def test_unreachable_oracle_is_unverified_not_partial(self):
        """Evidence unavailable must never read as evidence of health."""
        rep = rt.Report()
        rep.scope("nba", 2026)
        rep.check("games", 10, 10)
        rep.unreachable("teams", "HTTP 403 after 6 attempts")
        self.assertEqual(rep.verdict("nba", 2026), "unverified")

    def test_a_mismatch_is_partial(self):
        rep = rt.Report()
        rep.scope("nba", 2026)
        rep.check("games", 9, 10)
        self.assertEqual(rep.verdict("nba", 2026), "partial")

    def test_all_agreeing_is_complete(self):
        rep = rt.Report()
        rep.scope("nba", 2026)
        rep.check("games", 10, 10)
        rep.check("teams", 30, 30)
        self.assertEqual(rep.verdict("nba", 2026), "complete")

    def test_unreachable_beats_mismatch(self):
        """Order of arrival must not decide the verdict."""
        rep = rt.Report()
        rep.scope("nba", 2026)
        rep.unreachable("teams", "no oracle")
        rep.check("games", 9, 10)
        self.assertEqual(rep.verdict("nba", 2026), "unverified")


class GapClassificationTests(unittest.TestCase):
    """The arithmetic of §9, without the network."""

    def test_expected_excludes_exhibitions_and_unplayed(self):
        gap = rt.Gap(published=1239, exhibition=4, not_played=4, expected=1231,
                     missing=[], extra=[])
        self.assertEqual(gap.expected, gap.published - gap.exhibition - gap.not_played)

    def test_describe_gap_states_what_was_excluded(self):
        """A passing check still has to show its subtractions, or the number is magic."""
        text = rt.describe_gap(
            rt.Gap(published=1239, exhibition=4, not_played=4, expected=1231,
                   missing=[], extra=[]))
        self.assertIn("1239 published", text)
        self.assertIn("-4 exhibition", text)
        self.assertIn("-4 not played", text)

    def test_league_path_recovered_from_url(self):
        url = f"{rt.CORE}/basketball/leagues/nba/seasons/2026/types/2/events"
        self.assertEqual(rt.ESPN_PATH_BY_URL(url), "basketball/leagues/nba")

    def test_soccer_league_path_recovered(self):
        url = f"{rt.CORE}/soccer/leagues/eng.1/seasons/2025/types/1/events"
        self.assertEqual(rt.ESPN_PATH_BY_URL(url), "soccer/leagues/eng.1")


class SeasonTypeTests(unittest.TestCase):
    """Type ids are read, never assumed — the constant this module shipped with."""

    def test_no_hardcoded_season_type_constants(self):
        """Assert against the AST, not the text.

        The original defect was `REGULAR, POSTSEASON = 2, 3` at module scope. It would
        have reported the entire Premier League as missing (one type, id 1) and would
        miss MLS types 8 and 12 entirely. A grep for that string also matches the
        docstring in season_types() that records the history — which is exactly the
        kind of check that passes or fails for the wrong reason. Bind to the binding.
        """
        import ast
        tree = ast.parse(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "reconcile_totals.py")).read())
        banned = {"REGULAR", "POSTSEASON", "PRESEASON", "REGULAR_SEASON"}
        found = [
            t.id
            for node in tree.body if isinstance(node, ast.Assign)
            for target in node.targets
            for t in (target.elts if isinstance(target, ast.Tuple) else [target])
            if isinstance(t, ast.Name) and t.id in banned
        ]
        self.assertEqual(found, [], f"season-type ids bound at module scope: {found}")


if __name__ == "__main__":
    unittest.main()
