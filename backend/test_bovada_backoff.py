#!/usr/bin/env python3
"""An out-of-season league is not asked 48 times a day what it already said.

`bovada_scraper.py all` ran on a 30-minute timer against every league in the map, in season
or not. UFC sits at zero between cards, tennis between tournaments, MLB/NBA/WC out of
season — each one costing 48 requests a day to be told "no board" 48 times. Bovada publishes
this API with no auth and no key. Asking it that many times for an answer that changes once
is a cost pushed onto them for nothing.

The rule has to fail OPEN. The coupon is how we DISCOVER that a season started, so a league
with no history is always fetched; refusing to look would make the backoff self-fulfilling
and a league would never come back.
"""
import os
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import bovada_scraper as bs


class LeagueBackoffTests(unittest.TestCase):
    def test_an_unknown_league_is_always_fetched(self):
        """No history means no evidence. Fail open, or a season never restarts."""
        fetch, _ = bs._should_fetch("nba", {})
        self.assertTrue(fetch)

    def test_one_empty_run_does_not_rest_a_league(self):
        """A single empty board is a slate gap, not an off-season."""
        state = {}
        bs._record_result("ufc", state, 0)
        self.assertTrue(bs._should_fetch("ufc", state)[0])

    def test_three_empty_runs_earn_a_rest(self):
        state = {}
        for _ in range(bs._EMPTY_RUNS_BEFORE_BACKOFF):
            self.assertTrue(bs._should_fetch("ufc", state)[0])
            bs._record_result("ufc", state, 0)
        fetch, why = bs._should_fetch("ufc", state)
        self.assertFalse(fetch)
        self.assertIn("resting", why)

    def test_a_board_clears_the_rest_immediately(self):
        """A card is announced; the next run must see it, not wait out a timer."""
        state = {}
        for _ in range(bs._EMPTY_RUNS_BEFORE_BACKOFF):
            bs._record_result("ufc", state, 0)
        self.assertFalse(bs._should_fetch("ufc", state)[0])
        bs._record_result("ufc", state, 16)
        self.assertTrue(bs._should_fetch("ufc", state)[0])
        self.assertEqual(state["ufc"]["empty_runs"], 0)

    def test_the_rest_expires(self):
        state = {"ufc": {"empty_runs": 9, "last_empty_at": "2020-01-01T00:00:00+00:00"}}
        self.assertTrue(bs._should_fetch("ufc", state)[0])

    def test_unparseable_state_fails_open(self):
        """Corrupt scheduling state must never be able to silence a league."""
        state = {"ufc": {"empty_runs": 9, "last_empty_at": "not-a-timestamp"}}
        self.assertTrue(bs._should_fetch("ufc", state)[0])

    def test_every_league_we_carry_props_for_is_configured(self):
        """MLS and NCAAF were both absent and both were mistakes, for different reasons.

        MLS was REMOVED 2026-08-17 on the premise that a second book writing goals and
        assists would mean two sources disagreeing with the relay. The relay writes ZERO
        of both, so there was no disagreement to create and the board shipped a soccer
        league with no goalscorer market for 19 days.

        NCAAF was never configured at all. Every one of its props came from the relay,
        and 3,802 of those carry a fabricated -137 price.

        Bovada is the only real-price source for several of these leagues, so a league
        we serve props for and do not fetch here is a league priced by placeholder.
        """
        for league in ("mls", "ncaaf", "nfl", "mlb", "atp", "wta", "ufc", "lcup"):
            self.assertIn(league, bs.LEAGUES, league)


if __name__ == "__main__":
    unittest.main()
