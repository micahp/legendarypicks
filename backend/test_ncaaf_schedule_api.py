import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
from routers import games


PHASES = [{
    "season_type": 2, "label": "Regular Season",
    "start_time": "2026-08-22T07:00Z", "end_time": "2026-12-13T07:59Z",
    "weeks": [{
        "key": "2:1", "season_type": 2, "week": 1, "label": "Week 1",
        "alternate_label": "Week 1", "detail": "Aug 22-Sep 7",
        "start_time": "2026-08-22T07:00Z", "end_time": "2026-09-08T06:59Z",
    }],
}]


class NcaafScheduleApiTests(unittest.TestCase):
    @patch.object(games.espn, "ncaaf_schedule_weeks", return_value=PHASES)
    def test_catalog_uses_start_year_and_publisher_week_identity(self, catalog):
        payload = json.loads(games.get_ncaaf_schedule_weeks(None, "2026-08-21").body)
        self.assertEqual(payload["contract"], "ncaaf-schedule-weeks-v1")
        self.assertEqual(payload["season"], 2026)
        self.assertEqual(payload["default_week_key"], "2:1")
        self.assertEqual(payload["default_reason"], "next")
        catalog.assert_called_once_with(2026)

    @patch.object(games.espn, "ncaaf_schedule_week_games", return_value=[{"game_id": "401856766"}])
    @patch.object(games.espn, "ncaaf_schedule_weeks", return_value=PHASES)
    def test_week_endpoint_returns_only_an_catalogued_week(self, catalog, week_games):
        payload = json.loads(games.get_ncaaf_schedule_week(2026, 2, 1).body)
        self.assertEqual(payload["selected_week"]["key"], "2:1")
        self.assertEqual(payload["games"][0]["game_id"], "401856766")
        week_games.assert_called_once_with(2026, 2, 1)
        with self.assertRaises(HTTPException) as missing:
            games.get_ncaaf_schedule_week(2026, 2, 99)
        self.assertEqual(missing.exception.status_code, 404)
