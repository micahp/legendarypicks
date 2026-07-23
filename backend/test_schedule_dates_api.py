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
            ["2026-08-10T00:00Z", "2026-08-09T23:00Z"],
            ["2026-06-13T23:00Z", "2026-06-14T01:00Z"],
        ]

        import json
        payload = json.loads(self.payload())

        self.assertEqual(payload["contract"], "league-schedule-dates-v1")
        self.assertEqual(payload["anchor_date"], "2026-07-21")
        self.assertEqual(
            payload["future_event_starts"],
            ["2026-08-09T23:00Z", "2026-08-10T00:00Z"],
        )
        self.assertEqual(
            payload["past_event_starts"],
            ["2026-06-13T23:00Z", "2026-06-14T01:00Z"],
        )
        self.assertEqual(starts.call_count, 3)
        calls = starts.call_args_list
        self.assertEqual(calls[0].args[1:], (dt.date(2026, 7, 21), dt.date(2026, 8, 4)))
        self.assertEqual(calls[1].args[1:], (dt.date(2026, 8, 5), dt.date(2026, 9, 4)))
        self.assertEqual(calls[2].args[1:], (dt.date(2026, 7, 7), dt.date(2026, 7, 20)))

    @patch.object(games.espn, "schedule_event_starts")
    def test_future_search_continues_past_same_local_day_boundary(self, starts):
        starts.side_effect = [
            ["2026-06-14T00:30Z"],  # June 13 evening in US timezones
            [],
            [],
            ["2026-10-05T23:00Z"],
            ["2026-06-11T00:30Z"],
        ]

        import json
        payload = json.loads(self.payload("nba", "2026-06-13"))

        self.assertEqual(
            payload["future_event_starts"],
            ["2026-06-14T00:30Z", "2026-10-05T23:00Z"],
        )
        self.assertEqual(len(payload["search"]["future"]), 4)
        self.assertEqual(
            payload["search"]["future"][-1],
            {
                "start_date": "2026-09-12",
                "end_date": "2026-11-10",
                "event_starts_found": 1,
            },
        )

    @patch.object(games.espn, "schedule_event_starts")
    def test_past_search_uses_small_windows_near_offseason_boundary(self, starts):
        starts.side_effect = [
            ["2026-10-07T00:00Z"],
            [],
            [],
            [],
            ["2026-06-14T00:30Z"],
        ]

        import json
        payload = json.loads(self.payload("nba", "2026-10-05"))

        self.assertEqual(payload["past_event_starts"], ["2026-06-14T00:30Z"])
        self.assertEqual(len(payload["search"]["past"]), 4)
        for attempt in payload["search"]["past"]:
            start_date = dt.date.fromisoformat(attempt["start_date"])
            end_date = dt.date.fromisoformat(attempt["end_date"])
            self.assertLessEqual((end_date - start_date).days, 59)

    @patch.object(games.espn, "schedule_event_starts", return_value=[])
    def test_empty_verified_horizon_fails_closed_to_empty_candidates(self, starts):
        import json
        payload = json.loads(self.payload("wc"))

        self.assertEqual(payload["future_event_starts"], [])
        self.assertEqual(payload["past_event_starts"], [])
        self.assertEqual(len(payload["search"]["future"]), 8)
        self.assertEqual(len(payload["search"]["past"]), 8)
        self.assertEqual(starts.call_count, 16)

    @patch.object(games.espn, "schedule_event_starts")
    def test_candidate_population_is_capped(self, starts):
        future_base = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
        past_base = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
        future_population = [
            (future_base + dt.timedelta(hours=index)).isoformat().replace("+00:00", "Z")
            for index in range(100)
        ]
        past_population = [
            (past_base + dt.timedelta(hours=index)).isoformat().replace("+00:00", "Z")
            for index in range(100)
        ]
        starts.side_effect = [future_population, past_population]

        import json
        payload = json.loads(self.payload("nfl"))

        self.assertEqual(len(payload["future_event_starts"]), 64)
        self.assertEqual(len(payload["past_event_starts"]), 64)
        self.assertEqual(payload["future_event_starts"], sorted(future_population)[:64])
        self.assertEqual(payload["past_event_starts"], sorted(past_population)[-64:])

    def test_candidate_cap_keeps_a_cross_timezone_future_start(self):
        anchor = dt.date(2026, 6, 13)
        boundary_base = dt.datetime(2026, 6, 14, tzinfo=dt.timezone.utc)
        boundary_starts = [
            (boundary_base + dt.timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
            for index in range(100)
        ]
        next_season = "2026-10-05T23:00:00Z"

        capped = games._cap_schedule_candidates(
            [*boundary_starts, next_season],
            anchor,
            "future",
        )

        self.assertEqual(len(capped), 64)
        self.assertIn(next_season, capped)

    def test_rejects_bad_anchor_and_unknown_league(self):
        with self.assertRaises(HTTPException) as bad_date:
            games.get_schedule_dates("nba", "07/21/2026")
        self.assertEqual(bad_date.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_league:
            games.get_schedule_dates("quidditch", "2026-07-21")
        self.assertEqual(bad_league.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
