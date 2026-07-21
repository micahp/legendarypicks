#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Importing the esports router initializes the pick ledger.  Point that isolated
# import-time side effect at a disposable database, never a dev/prod database.
_TEST_DB = tempfile.NamedTemporaryFile(prefix="predict-api-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import predict  # noqa: E402


def _match(title, team_a, team_b, start, *, live=False, finished=False):
    return {
        "matchKey": "{}||{}||{}||Test League".format(team_a, team_b, title),
        "teamA": team_a,
        "teamB": team_b,
        "title": title,
        "league": "Test League",
        "startTime": start,
        "logoA": "a.png",
        "logoB": "b.png",
        "live": live,
        "finished": finished,
        "favorite": {"name": team_a, "pct": 55},
        "psId": 123,
        "watch": {"url": "large detail must not leak into the list"},
        "score": {"a": 1, "b": 0},
    }


class EsportsPredictApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_TEST_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        self.upcoming = {
            "source": "fixture",
            "matches": [
                _match("LoL", "Live A", "Live B", 3000, live=True),
                _match("Call of Duty", "COD A", "COD B", 1000),
                _match("Call of Duty", "Old A", "Old B", 500, finished=True),
                _match("CS2", "CS A", "CS B", 2000),
                _match("Valorant", "", "Missing team", 1500),
            ],
        }

    def test_title_alias_returns_only_open_lightweight_rows(self):
        result = predict.build_predict_slate(self.upcoming, title="cod")

        self.assertEqual("call-of-duty", result["selected_title"]["slug"])
        self.assertEqual(1, result["match_count"])
        self.assertEqual("COD A", result["matches"][0]["teamA"])
        self.assertNotIn("watch", result["matches"][0])
        self.assertNotIn("score", result["matches"][0])

    def test_default_selects_a_title_with_a_live_match(self):
        result = predict.build_predict_slate(self.upcoming)

        self.assertEqual("league-of-legends", result["selected_title"]["slug"])
        self.assertEqual(["Live A"], [row["teamA"] for row in result["matches"]])

    def test_all_supported_titles_are_stable_even_when_empty(self):
        result = predict.build_predict_slate(self.upcoming, title="overwatch")
        options = {row["slug"]: row for row in result["titles"]}

        self.assertIn("overwatch", options)
        self.assertEqual(0, options["overwatch"]["match_count"])
        self.assertEqual([], result["matches"])

    def test_invalid_title_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            predict.build_predict_slate(self.upcoming, title="not-a-game")

    def test_route_reuses_existing_upcoming_cache(self):
        with mock.patch.object(predict, "esports_upcoming", return_value=self.upcoming):
            result = predict.predict_slate(title="cs2")

        self.assertEqual("counter-strike-2", result["selected_title"]["slug"])
        self.assertEqual(["CS A"], [row["teamA"] for row in result["matches"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
