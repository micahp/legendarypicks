import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
from routers import games


class ScheduleDatesApiTests(unittest.TestCase):
    def payload(self, league="nba", anchor="2026-07-21"):
        response = games.get_schedule_dates(league, anchor)
        return response.body.decode("utf-8")

    @patch.object(games.espn, "schedule_event_starts")
    def test_uses_bounded_windows_and_returns_absolute_candidates(self, starts):
        starts.side_effect = [
            [],
            ["2026-10-06T00:00Z", "2026-10-05T23:00Z"],
            ["2026-06-13T23:00Z", "2026-06-14T01:00Z"],
        ]

        import json
        payload = json.loads(self.payload())

        self.assertEqual(payload["contract"], "league-schedule-dates-v1")
        self.assertEqual(payload["anchor_date"], "2026-07-21")
        self.assertEqual(
            payload["future_event_starts"],
            ["2026-10-05T23:00Z", "2026-10-06T00:00Z"],
        )
        self.assertEqual(
            payload["past_event_starts"],
            ["2026-06-13T23:00Z", "2026-06-14T01:00Z"],
        )
        self.assertEqual(starts.call_count, 3)
        calls = starts.call_args_list
        self.assertEqual(calls[0].args[1:], (dt.date(2026, 7, 21), dt.date(2026, 8, 4)))
        self.assertEqual(calls[1].args[1:], (dt.date(2026, 8, 5), dt.date(2026, 10, 19)))
        self.assertEqual(calls[2].args[1:], (dt.date(2026, 7, 7), dt.date(2026, 7, 20)))

    @patch.object(games.espn, "schedule_event_starts", return_value=[])
    def test_empty_verified_horizon_fails_closed_to_empty_candidates(self, starts):
        import json
        payload = json.loads(self.payload("wc"))

        self.assertEqual(payload["future_event_starts"], [])
        self.assertEqual(payload["past_event_starts"], [])
        self.assertEqual(len(payload["search"]["future"]), 3)
        self.assertEqual(len(payload["search"]["past"]), 3)
        self.assertEqual(starts.call_count, 6)

    @patch.object(games.espn, "schedule_event_starts")
    def test_candidate_population_is_capped(self, starts):
        base = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
        population = [
            (base + dt.timedelta(hours=index)).isoformat().replace("+00:00", "Z")
            for index in range(100)
        ]
        starts.side_effect = [population, population]

        import json
        payload = json.loads(self.payload("nfl"))

        self.assertEqual(len(payload["future_event_starts"]), 64)
        self.assertEqual(len(payload["past_event_starts"]), 64)
        self.assertEqual(payload["future_event_starts"], sorted(population)[:64])
        self.assertEqual(payload["past_event_starts"], sorted(population)[-64:])

    def test_rejects_bad_anchor_and_unknown_league(self):
        with self.assertRaises(HTTPException) as bad_date:
            games.get_schedule_dates("nba", "07/21/2026")
        self.assertEqual(bad_date.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_league:
            games.get_schedule_dates("quidditch", "2026-07-21")
        self.assertEqual(bad_league.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
