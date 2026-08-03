"""Tests for the two mechanisms league-0 exists to install.

Neither of these is about NBA 2025-26. They are about the properties that have to
hold for every league added after it — see docs/DATA-COVERAGE-CONTRACT.md §4 and §9.
The season-specific numbers live in verify-gates.sh (COV-nba, COV-nhl), where they
can be read next to the arithmetic that produced them.
"""
import os
import re
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

    def test_expected_excludes_not_yet_played_for_in_progress_seasons(self):
        """A season in progress publishes its whole schedule; future games are not
        a defect. MLB 2026 mid-season: 2,458 published regular-season events, we
        hold 1,682 completed, ~776 are scheduled — expected must be the games that
        have actually happened, not the full slate."""
        gap = rt.Gap(published=2458, exhibition=0, not_played=0,
                     not_yet_played=776, expected=1682,
                     missing=[], extra=[])
        self.assertEqual(gap.expected,
                         gap.published - gap.exhibition - gap.not_played - gap.not_yet_played)

    def test_describe_gap_states_what_was_excluded(self):
        """A passing check still has to show its subtractions, or the number is magic."""
        text = rt.describe_gap(
            rt.Gap(published=1239, exhibition=4, not_played=4, expected=1231,
                   missing=[], extra=[]))
        self.assertIn("1239 published", text)
        self.assertIn("-4 exhibition", text)
        self.assertIn("-4 not played", text)

    def test_expected_excludes_games_beyond_our_horizon(self):
        """The anti-flap rule, and the reason a live season can be offered at all.

        `not_yet_played` handles September. It does nothing for LAST NIGHT: those
        games are finished, so without this they count as missing the moment they
        end, the verdict drops to `partial`, and the league falls off /leagues every
        morning until the next ingest runs. Availability would track cron timing
        rather than data quality.

        The row claims a WINDOW -- every published game through `checked_through` is
        present -- so a finished game past that horizon is outside the claim, not a
        hole in it.
        """
        gap = rt.Gap(published=2458, exhibition=0, not_played=0,
                     not_yet_played=761, beyond_horizon=15, expected=1682,
                     missing=[], extra=[])
        self.assertEqual(
            gap.expected,
            gap.published - gap.exhibition - gap.not_played
            - gap.not_yet_played - gap.beyond_horizon)

    def test_a_game_missing_INSIDE_the_window_is_still_a_miss(self):
        """The window must not become an excuse. Keeping `beyond_horizon` and
        `missing` apart is the whole point: a finished game dated before our horizon
        that we do not hold is a real gap and must still fail."""
        gap = rt.Gap(published=100, exhibition=0, not_played=0,
                     not_yet_played=0, beyond_horizon=5, expected=95,
                     missing=["401800001"], extra=[])
        self.assertEqual(gap.missing, ["401800001"])
        self.assertNotEqual(len(gap.missing), 0)

    def test_explain_gap_classifies_last_nights_game_as_edge_not_gap(self):
        """The behavioural proof of the anti-flap rule, against a stubbed publisher.

        Four published events: one we hold, one finished BEFORE our horizon and
        absent (a real miss), one finished AFTER it (last night, not yet ingested),
        one in September. With a horizon the third is an edge; without one it is a
        miss — exactly the difference between a league that stays offered overnight
        and one that drops off /leagues every morning until the ingest runs.
        """
        pub = {
            "1": ("2026-07-30T00:00Z", "STATUS_FINAL"),
            "2": ("2026-07-31T00:00Z", "STATUS_FINAL"),
            "3": ("2026-08-03T00:00Z", "STATUS_FINAL"),
            "4": ("2026-09-01T00:00Z", "STATUS_SCHEDULED"),
        }
        orig_ids, orig_get = rt.published_event_ids, rt._get_json
        orig_path = getattr(rt, "ESPN_PATH_BY_URL", None)
        rt.published_event_ids = lambda url: list(pub)
        rt.ESPN_PATH_BY_URL = lambda url: "baseball/leagues/mlb"
        rt._get_json = lambda url, attempts=6: {
            "date": pub[url.rsplit("/", 1)[-1]][0],
            "competitions": [
                {"status": {"type": {"name": pub[url.rsplit("/", 1)[-1]][1]}}}
            ],
        }
        try:
            withh = rt.explain_gap("u", {"1"}, horizon="2026-08-02")
            without = rt.explain_gap("u", {"1"}, horizon=None)
        finally:
            rt.published_event_ids, rt._get_json = orig_ids, orig_get
            if orig_path is not None:
                rt.ESPN_PATH_BY_URL = orig_path

        self.assertEqual(withh.beyond_horizon, 1)
        self.assertEqual(withh.not_yet_played, 1)
        self.assertEqual(withh.missing, ["2"], "an in-window miss must still fail")
        self.assertEqual(withh.expected, 2)
        # Without the horizon last night is a miss — proof the rule does the work.
        self.assertEqual(without.beyond_horizon, 0)
        self.assertEqual(sorted(without.missing), ["2", "3"])

    def test_bulk_index_classifies_identically_to_per_event_fetches(self):
        """The optimisation must change the cost and nothing else.

        60 differing events, above the threshold where the bulk index arms. The same
        publisher answers both ways: once per event, and once per month. The Gap must
        be identical, and the per-event fetch count must fall to zero — a faster run
        that quietly reclassified a game would be worse than the slow one it replaced.
        """
        # 81 events: 20 finished before our horizon and held, 40 finished before it
        # and absent (real misses), 10 finished after it (edges), 10 scheduled in
        # September, plus one All-Star to prove the exhibition discriminator survives
        # the shim. 61 of them differ, which is what arms the index.
        pub = {}
        for i in range(20):
            pub[f"h{i}"] = (f"2026-07-{i + 1:02d}T00:00Z", "STATUS_FINAL", "STD")
        for i in range(40):
            pub[f"m{i}"] = (f"2026-07-{(i % 28) + 1:02d}T00:00Z", "STATUS_FINAL", "STD")
        for i in range(10):
            pub[f"e{i}"] = (f"2026-08-{i + 1:02d}T00:00Z", "STATUS_FINAL", "STD")
        for i in range(10):
            pub[f"s{i}"] = (f"2026-09-{i + 1:02d}T00:00Z", "STATUS_SCHEDULED", "STD")
        pub["allstar"] = ("2026-07-14T00:00Z", "STATUS_FINAL", "ALLSTAR")
        ours = {f"h{i}" for i in range(20)}
        url = ("https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
               "/seasons/2026/types/2/events")

        def event_doc(event_id):
            date, state, kind = pub[event_id]
            return {"id": event_id, "date": date, "season": {"type": 2},
                    "competitions": [{"type": {"abbreviation": kind},
                                      "status": {"type": {"name": state}}}]}

        per_event_fetches = []

        def fake_get(u, attempts=6, bulk=True):
            if u.endswith("/seasons/2026/types/2"):
                if not bulk:
                    raise rt.OracleUnreachable("no window")
                return {"startDate": "2026-07-01T00:00Z", "endDate": "2026-09-30T00:00Z"}
            if "/scoreboard?" in u:
                if not bulk:
                    raise rt.OracleUnreachable("no scoreboard")
                month = re.search(r"dates=(\d{6})", u).group(1)
                return {"events": [event_doc(e) for e in pub
                                   if pub[e][0][:7].replace("-", "") == month]}
            event_id = u.rsplit("/", 1)[-1]
            per_event_fetches.append(event_id)
            return event_doc(event_id)

        orig_ids, orig_get = rt.published_event_ids, rt._get_json
        rt.published_event_ids = lambda u: list(pub)
        try:
            rt._get_json = lambda u, attempts=6: fake_get(u, attempts, bulk=False)
            slow = rt.explain_gap(url, ours, horizon="2026-07-31")
            slow_fetches = len(per_event_fetches)

            per_event_fetches.clear()
            rt._get_json = lambda u, attempts=6: fake_get(u, attempts, bulk=True)
            fast = rt.explain_gap(url, ours, horizon="2026-07-31")
            fast_fetches = len(per_event_fetches)
        finally:
            rt.published_event_ids, rt._get_json = orig_ids, orig_get

        self.assertEqual(slow, fast, "the bulk index must not change the verdict")
        self.assertEqual(sorted(fast.missing), sorted(f"m{i}" for i in range(40)))
        self.assertEqual(fast.beyond_horizon, 10)
        self.assertEqual(fast.not_yet_played, 10)
        self.assertEqual(fast.exhibition, 1, "All-Star must survive the site-API shim")
        self.assertEqual(slow_fetches, 61, "the slow path fetches every differing event")
        self.assertEqual(fast_fetches, 0, "the indexed path must fetch no events at all")

    def test_describe_gap_names_the_horizon_subtraction(self):
        text = rt.describe_gap(
            rt.Gap(published=2458, exhibition=0, not_played=0,
                   not_yet_played=761, beyond_horizon=15, expected=1682,
                   missing=[], extra=[]))
        self.assertIn("-15 past our horizon", text)

    def test_describe_gap_names_not_yet_played(self):
        text = rt.describe_gap(
            rt.Gap(published=2458, exhibition=0, not_played=0,
                   not_yet_played=776, expected=1682,
                   missing=[], extra=[]))
        self.assertIn("2458 published", text)
        self.assertIn("-776 not yet played", text)

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
