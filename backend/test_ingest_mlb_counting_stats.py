#!/usr/bin/env python3
"""MLB publishes its own counting stats; these pin how we read them."""

import unittest
from unittest import mock

import ingest_mlb_counting_stats as ingest


HITTING_STAT = {
    "plateAppearances": 494,
    "atBats": 406,
    "hits": 134,
    "runs": 77,
    "rbi": 84,
    "doubles": 28,
    "triples": 1,
    "baseOnBalls": 80,
    "stolenBases": 2,
    "obp": ".443",
    "slg": ".648",
    "ops": "1.091",
    "totalBases": 263,
}

PITCHING_STAT = {
    "era": "1.63",
    "whip": "0.73",
    "earnedRuns": 23,
    "strikeOuts": 195,
    "saves": 0,
    "wins": 11,
    "losses": 5,
    "shutouts": 1,
    "inningsPitched": "127.0",
    "outs": 381,
}


class MappingTest(unittest.TestCase):
    def test_a_base_hit_does_not_land_in_the_nhl_hits_column(self):
        values = ingest.batting_values(HITTING_STAT)
        self.assertEqual(values["mlb_hits"], 134)
        self.assertNotIn("hits", values)

    def test_rates_are_published_as_strings(self):
        values = ingest.batting_values(HITTING_STAT)
        self.assertEqual(values["obp"], 0.443)
        self.assertEqual(values["ops"], 1.091)
        self.assertEqual(ingest.pitching_values(PITCHING_STAT)["era"], 1.63)

    def test_innings_are_thirds_not_decimals(self):
        # "128.2" is 128 and two thirds. Storing 128.2 and comparing it to a
        # published "1.0 IP x team games" threshold is arithmetic on a number
        # that does not mean what it looks like.
        values = ingest.pitching_values(dict(PITCHING_STAT, outs=386))
        self.assertEqual(values["innings"], round(386 / 3, 3))
        self.assertNotEqual(values["innings"], 128.2)

    def test_no_published_outs_means_no_innings(self):
        values = ingest.pitching_values(dict(PITCHING_STAT, outs=None))
        self.assertIsNone(values["innings"])

    def test_a_pitcher_save_does_not_land_in_the_goalie_column(self):
        values = ingest.pitching_values(PITCHING_STAT)
        self.assertEqual(values["mlb_saves"], 0)
        self.assertNotIn("saves", values)

    def test_absent_and_unpublishable_values_stay_none(self):
        self.assertIsNone(ingest._number(None))
        self.assertIsNone(ingest._number(""))
        self.assertIsNone(ingest._number("-.--"))


class FetchGroupTest(unittest.TestCase):
    def test_it_asks_for_the_full_player_pool(self):
        # The default pool is Qualified -- 149 hitters of 679 for 2026. A
        # league snapshot built on the default is silently the leaderboard.
        seen = []

        def fake_get(url):
            seen.append(url)
            return {"stats": [{"splits": [{"player": {"id": 1}}],
                               "totalSplits": 1}]}

        with mock.patch.object(ingest, "_get", fake_get):
            ingest.fetch_group("hitting", 2026)
        self.assertIn("playerPool=All", seen[0])

    def test_a_short_response_fails_closed(self):
        def fake_get(_url):
            return {"stats": [{"splits": [{"player": {"id": 1}}],
                               "totalSplits": 679}]}

        with mock.patch.object(ingest, "_get", fake_get):
            with self.assertRaisesRegex(
                ingest.MLBStatsIngestError, "totalSplits is 679"
            ):
                ingest.fetch_group("hitting", 2026)

    def test_no_stats_block_is_not_an_empty_season(self):
        with mock.patch.object(ingest, "_get", lambda _u: {"stats": []}):
            with self.assertRaisesRegex(
                ingest.MLBStatsIngestError, "no stats block published"
            ):
                ingest.fetch_group("hitting", 2026)


if __name__ == "__main__":
    unittest.main(verbosity=2)
