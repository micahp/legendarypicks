#!/usr/bin/env python3
"""ESPN's bulk report is positional data with the schema delivered separately.

That shape is the setup for a silent, total corruption: one inserted column and
every stat after it is someone else's number, with every row count healthy.
"""

import unittest
from unittest import mock

import ingest_nba_season_stats as ingest


SCHEMA = {
    "general": ["gamesPlayed", "avgMinutes", "avgRebounds"],
    "offensive": ["avgPoints", "avgAssists", "avgTurnovers",
                  "fieldGoalsMade", "fieldGoalsAttempted",
                  "threePointFieldGoalsMade", "threePointFieldGoalsAttempted",
                  "freeThrowsMade", "freeThrowsAttempted"],
    "defensive": ["avgSteals", "avgBlocks"],
}


def athlete(games=64.0):
    return {
        "athlete": {"id": "3945274", "displayName": "Luka Doncic"},
        "categories": [
            {"name": "general", "values": [games, 35.765625, 7.734375]},
            {"name": "offensive", "values": [33.484375, 8.28125, 3.984375,
                                             693.0, 1457.0, 254.0, 694.0,
                                             503.0, 645.0]},
            {"name": "defensive", "values": [1.640625, 0.53125]},
        ],
    }


class FlattenTest(unittest.TestCase):
    def test_values_are_named_by_the_published_schema(self):
        flat = ingest.flatten(athlete(), SCHEMA)
        self.assertEqual(flat["avgPoints"], 33.484375)
        self.assertEqual(flat["gamesPlayed"], 64.0)
        self.assertEqual(flat["avgBlocks"], 0.53125)

    def test_a_schema_that_disagrees_with_the_row_is_refused(self):
        # ESPN inserting one column shifts every stat after it. Reading on
        # regardless is how a leaderboard fills with real numbers against the
        # wrong labels -- and nothing about the row count would look wrong.
        entry = athlete()
        entry["categories"][0]["values"] = [64.0, 35.7]  # 2 values, 3 names
        with self.assertRaisesRegex(
            ingest.NBASeasonStatsError, "schema and the row disagree"
        ):
            ingest.flatten(entry, SCHEMA)


class ParseTest(unittest.TestCase):
    def test_it_maps_the_manifest_columns(self):
        record = ingest.parse_athlete(ingest.flatten(athlete(), SCHEMA))
        self.assertEqual(record["games"], 64)
        self.assertEqual(record["values"]["pts"], 33.5)
        self.assertEqual(record["values"]["reb"], 7.7)
        self.assertEqual(record["values"]["ast"], 8.3)
        self.assertEqual(record["values"]["fgm"], 693)
        self.assertEqual(record["values"]["minutes"], 35.8)

    def test_true_shooting_is_not_invented(self):
        # It is published on the per-athlete endpoint and absent from this
        # report. Absent stays absent rather than being computed.
        record = ingest.parse_athlete(ingest.flatten(athlete(), SCHEMA))
        self.assertNotIn("ts_pct", record["values"])

    def test_an_athlete_who_never_played_is_not_a_row(self):
        self.assertIsNone(
            ingest.parse_athlete(ingest.flatten(athlete(games=0.0), SCHEMA))
        )

    def test_a_missing_published_stat_fails_loud(self):
        flat = ingest.flatten(athlete(), SCHEMA)
        del flat["avgPoints"]
        with self.assertRaisesRegex(ingest.NBASeasonStatsError, "avgPoints"):
            ingest.parse_athlete(flat)


class FetchAllTest(unittest.TestCase):
    def categories(self):
        return [{"name": k, "names": v} for k, v in SCHEMA.items()]

    def test_it_pages_to_the_published_count(self):
        pages = [
            {"categories": self.categories(), "athletes": [athlete()] * 100,
             "pagination": {"count": 150, "pages": 2}},
            {"categories": self.categories(), "athletes": [athlete()] * 50,
             "pagination": {"count": 150, "pages": 2}},
        ]
        with mock.patch.object(ingest, "_get", lambda _u: pages.pop(0)):
            athletes, schema = ingest.fetch_all(2026)
        self.assertEqual(len(athletes), 150)
        self.assertEqual(schema["general"][0], "gamesPlayed")

    def test_a_short_result_fails_closed(self):
        page = {"categories": self.categories(), "athletes": [athlete()],
                "pagination": {"count": 578, "pages": 1}}
        with mock.patch.object(ingest, "_get", lambda _u: page):
            with self.assertRaisesRegex(
                ingest.NBASeasonStatsError, "published count is 578"
            ):
                ingest.fetch_all(2026)

    def test_no_schema_means_the_values_are_unlabelled(self):
        page = {"categories": [], "athletes": [athlete()],
                "pagination": {"count": 1, "pages": 1}}
        with mock.patch.object(ingest, "_get", lambda _u: page):
            with self.assertRaisesRegex(
                ingest.NBASeasonStatsError, "no category names"
            ):
                ingest.fetch_all(2026)

    def test_it_asks_for_the_regular_season(self):
        seen = []

        def fake_get(url):
            seen.append(url)
            return {"categories": self.categories(), "athletes": [athlete()],
                    "pagination": {"count": 1, "pages": 1}}

        with mock.patch.object(ingest, "_get", fake_get):
            ingest.fetch_all(2026)
        self.assertIn("seasontype=2", seen[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
