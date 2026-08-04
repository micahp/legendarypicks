#!/usr/bin/env python3
"""Hockey's three player types must each come out described by their own job.

The bug these pin: every goalie row in the database read 0 goals, 0 assists,
0 shots, because the only mapping that existed was forward-shaped.
"""

import unittest
from unittest import mock

import ingest_nhl_season_stats as ingest


GOALIE_ROW = {
    "playerId": 8481611,
    "goalieFullName": "Pyotr Kochetkov",
    "teamAbbrevs": "CAR",
    "gamesPlayed": 9,
    "gamesStarted": 8,
    "goalsAgainst": 19,
    "goalsAgainstAverage": 2.32581,
    "losses": 2,
    "otLosses": 0,
    "savePct": 0.89947,
    "saves": 170,
    "shotsAgainst": 189,
    "shutouts": 1,
    "wins": 6,
}

DEFENCEMAN_ROW = {
    "playerId": 8476882,
    "skaterFullName": "Moritz Seider",
    "positionCode": "D",
    "teamAbbrevs": "DET",
    "gamesPlayed": 82,
    "goals": 10,
    "assists": 50,
    "points": 60,
    "shots": 150,
    "shootingPct": 0.0667,
    "plusMinus": 15,
    "penaltyMinutes": 40,
    "ppGoals": 3,
    "ppPoints": 20,
    "shGoals": 0,
    "timeOnIcePerGame": 1540.0,
    "faceoffWinPct": None,
}

REALTIME_ROW = {
    "playerId": 8476882,
    "blockedShots": 180,
    "hits": 128,
    "takeaways": 45,
    "giveaways": 60,
}


class GoalieMappingTest(unittest.TestCase):
    def test_a_goalie_is_described_by_goaltending(self):
        values = ingest.goalie_values(GOALIE_ROW)
        self.assertEqual(values["saves"], 170)
        self.assertEqual(values["shots_against"], 189)
        self.assertEqual(values["goals_against"], 19)
        self.assertEqual(values["shutouts"], 1)
        self.assertEqual(values["wins"], 6)
        self.assertEqual(values["losses"], 2)
        self.assertEqual(values["games_started"], 8)
        self.assertEqual(values["nhl_position"], "G")

    def test_saves_is_taken_from_the_publisher_not_derived(self):
        # shotsAgainst - goalsAgainst would also give 170 here, so a derivation
        # would look correct. Change the published value alone and the mapping
        # must follow it, which only a read of `saves` can do.
        row = dict(GOALIE_ROW, saves=171)
        self.assertEqual(ingest.goalie_values(row)["saves"], 171)

    def test_percentages_are_published_as_fractions(self):
        self.assertEqual(ingest.goalie_values(GOALIE_ROW)["save_pct"], 89.9)
        self.assertEqual(ingest.goalie_values(GOALIE_ROW)["gaa"], 2.33)

    def test_a_missing_published_value_stays_missing(self):
        values = ingest.goalie_values(dict(GOALIE_ROW, saves=None, shutouts=None))
        self.assertIsNone(values["saves"])
        self.assertIsNone(values["shutouts"])


class SkaterMappingTest(unittest.TestCase):
    def test_a_defenceman_gets_the_stats_defencemen_are_judged_on(self):
        values = ingest.skater_values(DEFENCEMAN_ROW, REALTIME_ROW)
        self.assertEqual(values["nhl_position"], "D")
        self.assertEqual(values["blocked_shots"], 180)
        self.assertEqual(values["hits"], 128)
        self.assertEqual(values["takeaways"], 45)
        self.assertEqual(values["giveaways"], 60)
        self.assertEqual(values["goals"], 10)
        self.assertEqual(values["assists"], 50)

    def test_no_realtime_row_means_no_invented_zeroes(self):
        values = ingest.skater_values(DEFENCEMAN_ROW, None)
        self.assertNotIn("blocked_shots", values)
        self.assertNotIn("hits", values)

    def test_time_on_ice_is_published_in_seconds(self):
        self.assertEqual(ingest.skater_values(DEFENCEMAN_ROW, None)["toi"], "25:40")
        self.assertIsNone(ingest._toi(None))


class FetchReportTest(unittest.TestCase):
    """The report must be complete, and it must be the regular season."""

    def test_it_asks_for_the_regular_season_explicitly(self):
        seen = []

        def fake_get(url):
            seen.append(url)
            return {"data": [GOALIE_ROW], "total": 1}

        with mock.patch.object(ingest, "_get", fake_get):
            ingest.fetch_report("goalie/summary", 20252026)
        self.assertIn("gameTypeId%3D2", seen[0].replace("+", "%20"))

    def test_a_short_page_run_fails_closed(self):
        # The publisher says 500 rows exist and hands back 1. Publishing that
        # as a league snapshot is how a partial pull becomes "the season".
        def fake_get(_url):
            return {"data": [GOALIE_ROW], "total": 500}

        with mock.patch.object(ingest, "_get", fake_get):
            with self.assertRaisesRegex(
                ingest.NHLStatsIngestError, "the report ended early"
            ):
                ingest.fetch_report("goalie/summary", 20252026)

    def test_it_pages_to_completion(self):
        pages = [
            {"data": [dict(GOALIE_ROW, playerId=i) for i in range(100)], "total": 150},
            {"data": [dict(GOALIE_ROW, playerId=i) for i in range(50)], "total": 150},
        ]

        def fake_get(_url):
            return pages.pop(0)

        with mock.patch.object(ingest, "_get", fake_get):
            rows = ingest.fetch_report("goalie/summary", 20252026)
        self.assertEqual(len(rows), 150)


if __name__ == "__main__":
    unittest.main(verbosity=2)
