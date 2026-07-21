import json
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
import espn_client as espn
from routers import games


PHASES = [
    {
        "season_type": 1,
        "label": "Preseason",
        "start_time": "2026-08-06T07:00Z",
        "end_time": "2026-09-09T06:59Z",
        "weeks": [
            {
                "key": "1:1",
                "season_type": 1,
                "week": 1,
                "label": "Hall of Fame Weekend",
                "alternate_label": "HOF",
                "detail": "Aug 6-12",
                "start_time": "2026-08-06T07:00Z",
                "end_time": "2026-08-13T06:59Z",
            },
            {
                "key": "1:2",
                "season_type": 1,
                "week": 2,
                "label": "Preseason Week 1",
                "alternate_label": "Pre Wk 1",
                "detail": "Aug 13-19",
                "start_time": "2026-08-13T07:00Z",
                "end_time": "2026-08-20T06:59Z",
            },
        ],
    },
    {
        "season_type": 2,
        "label": "Regular Season",
        "start_time": "2026-09-09T07:00Z",
        "end_time": "2027-01-13T07:59Z",
        "weeks": [
            {
                "key": "2:1",
                "season_type": 2,
                "week": 1,
                "label": "Week 1",
                "alternate_label": "Week 1",
                "detail": "Sep 9-15",
                "start_time": "2026-09-09T07:00Z",
                "end_time": "2026-09-16T06:59Z",
            },
        ],
    },
    {
        "season_type": 3,
        "label": "Postseason",
        "start_time": "2027-01-13T08:00Z",
        "end_time": "2027-02-16T07:59Z",
        "weeks": [
            {
                "key": "3:5",
                "season_type": 3,
                "week": 5,
                "label": "Super Bowl",
                "alternate_label": "Super Bowl",
                "detail": "Feb 10-15",
                "start_time": "2027-02-10T08:00Z",
                "end_time": "2027-02-16T07:59Z",
            },
        ],
    },
]


class NflScheduleClientTests(unittest.TestCase):
    @patch.object(espn, "_get")
    def test_calendar_preserves_espn_phase_and_week_identity(self, get):
        get.return_value = {
            "leagues": [{
                "season": {"year": 2026},
                "calendar": [{
                    "label": "Preseason",
                    "value": "1",
                    "startDate": "2026-08-06T07:00Z",
                    "endDate": "2026-09-09T06:59Z",
                    "entries": [{
                        "label": "Hall of Fame Weekend",
                        "alternateLabel": "HOF",
                        "detail": "Aug 6-12",
                        "value": "1",
                        "startDate": "2026-08-06T07:00Z",
                        "endDate": "2026-08-13T06:59Z",
                    }],
                }],
            }],
        }

        phases = espn.nfl_schedule_weeks(2026)

        self.assertEqual(phases[0]["season_type"], 1)
        self.assertEqual(phases[0]["weeks"][0]["key"], "1:1")
        self.assertEqual(phases[0]["weeks"][0]["label"], "Hall of Fame Weekend")
        self.assertIn("dates=2026", get.call_args.args[0])

    @patch.object(espn, "_get")
    def test_week_games_fail_closed_to_requested_season_type_and_week(self, get):
        def event(event_id, season, season_type, week):
            return {
                "id": event_id,
                "date": "2026-09-10T00:20Z",
                "season": {"year": season, "type": season_type},
                "week": {"number": week},
                "competitions": [{
                    "status": {"type": {"state": "pre", "description": "Scheduled"}},
                    "competitors": [],
                }],
            }

        get.return_value = {
            "events": [
                event("wanted", 2026, 2, 1),
                event("wrong-week", 2026, 2, 2),
                event("wrong-season", 2025, 2, 1),
            ],
        }

        result = espn.nfl_schedule_week_games(2026, 2, 1)

        self.assertEqual([game["game_id"] for game in result], ["wanted"])


class NflScheduleApiTests(unittest.TestCase):
    @patch.object(games.espn, "nfl_schedule_weeks", return_value=PHASES)
    def test_catalog_defaults_to_next_current_or_latest_week(self, catalog):
        before = json.loads(games.get_nfl_schedule_weeks(2026, "2026-07-21").body)
        current = json.loads(games.get_nfl_schedule_weeks(2026, "2026-08-14").body)
        after = json.loads(games.get_nfl_schedule_weeks(2026, "2027-02-20").body)

        self.assertEqual(before["contract"], "nfl-schedule-weeks-v1")
        self.assertEqual(before["navigation"], "week")
        self.assertEqual(before["default_week_key"], "1:1")
        self.assertEqual(before["default_reason"], "next")
        self.assertEqual(current["default_week_key"], "1:2")
        self.assertEqual(current["default_reason"], "current")
        self.assertEqual(after["default_week_key"], "3:5")
        self.assertEqual(after["default_reason"], "latest")
        self.assertEqual(catalog.call_count, 3)

    @patch.object(games.espn, "nfl_schedule_week_games")
    @patch.object(games.espn, "nfl_schedule_weeks", return_value=PHASES)
    def test_selected_week_returns_shared_game_shape(self, catalog, week_games):
        week_games.return_value = [{
            "game_id": "401873271",
            "date": "2026-08-07T00:00Z",
            "state": "pre",
            "home": {"abbrev": "ARI"},
            "away": {"abbrev": "CAR"},
        }]

        payload = json.loads(games.get_nfl_schedule_week(2026, 1, 1).body)

        self.assertEqual(payload["contract"], "nfl-schedule-week-v1")
        self.assertEqual(payload["selected_week"]["label"], "Hall of Fame Weekend")
        self.assertEqual(payload["games"][0]["game_id"], "401873271")
        week_games.assert_called_once_with(2026, 1, 1)

    @patch.object(games.espn, "nfl_schedule_weeks", return_value=PHASES)
    def test_unknown_week_and_invalid_filters_fail_closed(self, catalog):
        with self.assertRaises(HTTPException) as missing:
            games.get_nfl_schedule_week(2026, 2, 18)
        self.assertEqual(missing.exception.status_code, 404)

        with self.assertRaises(HTTPException) as bad_type:
            games.get_nfl_schedule_week(2026, 4, 1)
        self.assertEqual(bad_type.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_season:
            games.get_nfl_schedule_weeks(1999, "2026-07-21")
        self.assertEqual(bad_season.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
