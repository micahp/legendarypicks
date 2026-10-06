import unittest
from unittest import mock

import run_mlb_daily_history_ingest as mod

# statsapi /schedule for 2026-09-22..23 as published: 824785 (TOR @ BAL) is listed under its
# original date as Final/Postponed and under its played date as Final/Final.
PAYLOAD = {"dates": [
    {"date": "2026-09-22", "games": [
        {"gamePk": 824785, "officialDate": "2026-09-23",
         "status": {"abstractGameState": "Final", "detailedState": "Postponed"}},
        {"gamePk": 824700, "officialDate": "2026-09-22",
         "status": {"abstractGameState": "Final", "detailedState": "Final"}},
    ]},
    {"date": "2026-09-23", "games": [
        {"gamePk": 824785, "officialDate": "2026-09-23",
         "status": {"abstractGameState": "Final", "detailedState": "Final"}},
        {"gamePk": 824801, "officialDate": "2026-09-23",
         "status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
    ]},
]}


class FinalSchedule(unittest.TestCase):
    def test_a_postponed_game_belongs_to_the_day_it_was_played(self):
        with mock.patch.object(mod, "_request_json", return_value=PAYLOAD):
            got = mod.fetch_final_schedule(mod.dt.date(2026, 9, 22), mod.dt.date(2026, 9, 23))
        self.assertEqual({"2026-09-22": {"824700"}, "2026-09-23": {"824785"}}, got)


if __name__ == "__main__":
    unittest.main()
