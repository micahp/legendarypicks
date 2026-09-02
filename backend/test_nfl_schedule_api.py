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


NCAAF_PHASES = [
    {
        "season_type": 2,
        "label": "Regular Season",
        "start_time": "2026-08-22T07:00Z",
        "end_time": "2026-12-13T07:59Z",
        "weeks": [{
            "key": "2:1", "season_type": 2, "week": 1,
            "label": "Week 1", "alternate_label": "Week 1",
            "detail": "Aug 22-Sep 7",
            "start_time": "2026-08-22T07:00Z",
            "end_time": "2026-09-08T06:59Z",
        }],
    },
    {
        "season_type": 3,
        "label": "Postseason",
        "start_time": "2026-12-13T08:00Z",
        "end_time": "2027-01-28T07:59Z",
        "weeks": [{
            "key": "3:999", "season_type": 3, "week": 999,
            "label": "CFP", "alternate_label": "CFP",
            "detail": "Dec 18-Jan 28",
            "start_time": "2026-12-18T08:00Z",
            "end_time": "2027-01-28T07:59Z",
        }],
    },
]


class NcaafScheduleTests(unittest.TestCase):
    @patch.object(espn, "_get")
    def test_catalog_uses_ncaaf_path_and_excludes_offseason(self, get):
        get.return_value = {
            "leagues": [{
                "season": {"year": 2026},
                "calendar": [{
                    "label": "Regular Season", "value": "2",
                    "entries": [{
                        "label": "Week 1", "value": "1",
                        "startDate": "2026-08-22T07:00Z",
                        "endDate": "2026-09-08T06:59Z",
                    }],
                }, {
                    "label": "Off Season", "value": "4",
                    "entries": [{
                        "label": "All-Star", "value": "1",
                        "startDate": "2027-01-28T08:00Z",
                        "endDate": "2027-02-01T07:59Z",
                    }],
                }],
            }],
        }

        phases = espn.football_schedule_weeks("ncaaf", 2026)

        self.assertEqual([phase["season_type"] for phase in phases], [2])
        self.assertIn("football/college-football", get.call_args.args[0])

    @patch.object(espn, "_get")
    def test_ncaaf_week_uses_published_date_window_not_capped_week_query(self, get):
        def event(event_id, season, season_type, week):
            return {
                "id": event_id,
                "date": "2026-08-29T19:00Z",
                "season": {"year": season, "type": season_type},
                "week": {"number": week},
                "competitions": [{
                    "status": {"type": {"state": "pre", "description": "Scheduled"}},
                    "competitors": [],
                }],
            }
        get.return_value = {"events": [
            event("wanted", 2026, 2, 1),
            event("wrong-week", 2026, 2, 2),
        ]}

        games_for_week = espn.football_schedule_week_games(
            "ncaaf", 2026, 2, 1,
            "2026-08-22T07:00Z", "2026-09-08T06:59Z",
        )

        self.assertEqual([game["game_id"] for game in games_for_week], ["wanted"])
        url = get.call_args.args[0]
        self.assertIn("dates=20260822-20260908", url)
        self.assertIn("groups=80", url)
        self.assertNotIn("week=1", url)

    @patch.object(games.espn, "football_schedule_weeks", return_value=NCAAF_PHASES)
    def test_ncaaf_catalog_defaults_to_published_week(self, catalog):
        payload = json.loads(games.get_ncaaf_schedule_weeks(2026, "2026-08-29").body)
        self.assertEqual(payload["contract"], "ncaaf-schedule-weeks-v1")
        self.assertEqual(payload["league"], "ncaaf")
        self.assertEqual(payload["default_week_key"], "2:1")

    @patch.object(games.espn, "football_schedule_week_games")
    @patch.object(games.espn, "football_schedule_weeks", return_value=NCAAF_PHASES)
    def test_ncaaf_week_supports_cfp_999_and_passes_calendar_bounds(self, catalog, week_games):
        week_games.return_value = []

        payload = json.loads(games.get_ncaaf_schedule_week(2026, 3, 999).body)

        self.assertEqual(payload["contract"], "ncaaf-schedule-week-v1")
        self.assertEqual(payload["selected_week"]["label"], "CFP")
        week_games.assert_called_once_with(
            "ncaaf", 2026, 3, 999,
            "2026-12-18T08:00Z", "2027-01-28T07:59Z",
        )


if __name__ == "__main__":
    unittest.main()
