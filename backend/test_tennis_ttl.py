#!/usr/bin/env python3
"""Tennis is polled like a clock sport and it is not one.

Measured 2026-08-24 over 24h of ingest_scoreboards traffic:

    tennis    3,974   52.3% of all scoreboard load, 8/min through the play hours
    baseball  1,539   20.3%
    soccer      892   11.7%
    football    819   10.8%

and ingest_scoreboards is 69.8% of every ESPN request this project makes. A tennis
scoreboard polled twenty times inside one service game returns the same body twenty
times, so the default 20s freshness buys nothing there.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from espn_client import scoreboard as sb


class TennisTtlTests(unittest.TestCase):
    def test_tennis_gets_a_longer_window_than_the_clock_sports(self):
        for league in ("atp", "wta"):
            self.assertEqual(sb._live_ttl(league, sb.LIVE_TTL), sb.TENNIS_LIVE_TTL)

    def test_every_other_league_is_unchanged(self):
        for league in ("mlb", "nfl", "nba", "nhl", "mls", "ufc", "ncaaf", "wc"):
            self.assertEqual(sb._live_ttl(league, sb.LIVE_TTL), sb.LIVE_TTL)

    def test_the_window_outlives_one_timer_tick(self):
        """The live timer fires every 60s. A window shorter than that makes the second
        tick re-ask for a body the first one already has, which is the whole waste."""
        self.assertGreater(sb.TENNIS_LIVE_TTL, 60)

    def test_an_explicit_caller_still_wins(self):
        """This moves the DEFAULT. A caller that asked for a specific freshness has a
        reason, and silently overriding it would be a second ruler."""
        for league in ("atp", "wta", "mlb"):
            self.assertEqual(sb._live_ttl(league, 300), 300)
            self.assertEqual(sb._live_ttl(league, 0), 0)

    def test_a_zero_ttl_is_never_widened(self):
        """ttl=0 means 'do not serve me a cached body'. Turning that into 90s would hand
        a verification probe a stale answer, which is how a check validates itself."""
        self.assertEqual(sb._live_ttl("atp", 0), 0)


if __name__ == "__main__":
    unittest.main()
