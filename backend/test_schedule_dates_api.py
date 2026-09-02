import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
from routers import games


class ScheduleDatesApiTests(unittest.TestCase):
    """These cover the PUBLISHER-SEARCH rung, so the local rung is held empty.

    The arrows now answer from our own store first and only fall through to
    ESPN's schedule search when we cannot. Without this the cases below stop
    testing what they were written to test -- they short-circuit on whatever
    the ambient database happens to hold, which is why they turned red against
    `picks.dev.db` and stayed green standalone. The local rung has its own
    coverage in `LocalScheduleDatesTests`.
    """

    def setUp(self):
        local = patch.object(games, "_local_event_starts", return_value=[])
        local.start()
        self.addCleanup(local.stop)

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


class LocalScheduleDatesTests(unittest.TestCase):
    """The day arrows must not need a publisher to move.

    Measured 2026-08-18: every ESPN host was refusing this box, so
    `schedule-dates` answered `source: unavailable` with empty candidate lists
    for every league, and the board simply would not step back past Sunday --
    while UFC 330's start instants sat in our own `prop_games` the whole time.
    A navigation control whose failure mode is silence is indistinguishable
    from a dead button.
    """

    def setUp(self):
        self.refuse = patch.object(
            games.espn, "schedule_event_starts",
            side_effect=RuntimeError("publisher refused"))
        self.refuse.start()
        self.addCleanup(self.refuse.stop)

    def test_local_starts_answer_without_asking_the_publisher(self):
        with patch.object(games, "_local_event_starts") as local:
            local.side_effect = lambda lg, anchor, direction: (
                ["2026-08-19T23:00:00+00:00"] if direction == "future"
                else ["2026-08-15T22:00:00+00:00"])
            body = games.get_schedule_dates("ufc", "2026-08-17").body.decode()
        self.assertIn('"source":"local"', body.replace(" ", ""))
        self.assertIn("2026-08-15T22:00:00+00:00", body)
        # The publisher was never consulted: patching it to raise would have
        # surfaced as a 502 rather than a served payload.

    def test_one_sided_local_history_still_answers_what_it_has(self):
        """Holding only the past is a partial answer, not a failure.

        The store starts the day it is built, so the future side can be empty
        while the past side is not. Refusing to serve the half we hold is how
        the arrow went dead in the first place.
        """
        with patch.object(games, "_local_event_starts") as local:
            local.side_effect = lambda lg, anchor, direction: (
                [] if direction == "future" else ["2026-08-15T22:00:00+00:00"])
            body = games.get_schedule_dates("ufc", "2026-08-17").body.decode()
        self.assertIn("2026-08-15T22:00:00+00:00", body)
        self.assertIn("publisher_unavailable", body)


class DirectionalCandidateTests(unittest.TestCase):
    """A field named for a direction must only contain that direction.

    `_cap_schedule_candidates` used to only truncate. The local rung feeds it a
    window that deliberately overruns the anchor by a day to catch timezone
    boundaries, so past instants shipped inside `future_event_starts`.

    Measured on prod 2026-08-19 with an unfilled store: MLB offered 9 "future"
    starts and every one of them was in the past, so the next-day button did
    nothing at all. The client filtered them and was left with no target.
    """

    def test_past_instants_never_appear_as_future(self):
        anchor = dt.date(2026, 8, 19)
        capped = games._cap_schedule_candidates(
            ["2026-08-18T00:05:00+00:00", "2026-08-18T23:00:00+00:00",
             "2026-08-20T00:05:00+00:00"],
            anchor, "future")
        assert all("2026-08-18" not in value for value in capped), capped
        assert "2026-08-20T00:05:00+00:00" in capped

    def test_future_instants_never_appear_as_past(self):
        anchor = dt.date(2026, 8, 19)
        capped = games._cap_schedule_candidates(
            ["2026-08-25T00:05:00+00:00", "2026-08-15T22:00:00+00:00"],
            anchor, "past")
        assert capped == ["2026-08-15T22:00:00+00:00"]

    def test_the_near_side_keeps_a_day_of_slack(self):
        """A 00:30Z start is the previous evening in the Americas, so it IS the
        neighbouring day there. Dropping it would skip a real game."""
        anchor = dt.date(2026, 8, 19)
        capped = games._cap_schedule_candidates(
            ["2026-08-20T00:30:00+00:00"], anchor, "past")
        assert capped == ["2026-08-20T00:30:00+00:00"]
