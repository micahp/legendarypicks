"""Regression tests for the MLS/NCAAF published grouped-standings contract."""
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, __file__.rsplit("/", 1)[0])

import espn_client as espn
from routers import games


def entry(abbrev, name, **stats):
    return {
        "team": {"abbreviation": abbrev, "displayName": name},
        "stats": [{"name": key, "value": value} for key, value in stats.items()],
    }


class GroupStandingsContractTest(unittest.TestCase):
    def test_mls_copies_published_draws_and_points(self):
        source = {
            "children": [{
                "name": "Eastern Conference",
                "standings": {"entries": [entry(
                    "MIA", "Inter Miami CF", rank=2, gamesPlayed=18, wins=11,
                    ties=5, losses=2, pointsFor=45, pointsAgainst=32,
                    pointDifferential=13, points=38,
                )]},
            }],
        }
        with patch.object(espn, "_get", return_value=source):
            groups = espn.group_standings("mls")

        self.assertEqual(groups, [{
            "group": "Eastern Conference",
            "rows": [{
                "rank": 2, "abbrev": "MIA", "name": "Inter Miami CF",
                "played": 18, "wins": 11, "draws": 5, "losses": 2,
                "gf": 45, "ga": 32, "gd": 13, "points": 38,
            }],
        }])

    def test_ncaaf_descends_into_published_leaf_divisions_and_keeps_nulls(self):
        source = {
            "children": [{
                "name": "Sun Belt Conference",
                "children": [{
                    "name": "Sun Belt - East",
                    "standings": {"entries": [entry("JMU", "James Madison Dukes", wins=0)]},
                }, {
                    "name": "Sun Belt - West",
                    "standings": {"entries": [entry("USA", "South Alabama Jaguars", wins=0)]},
                }],
            }],
        }
        with patch.object(espn, "_get", return_value=source):
            groups = espn.group_standings("ncaaf")

        self.assertEqual([group["group"] for group in groups], ["Sun Belt - East", "Sun Belt - West"])
        row = groups[0]["rows"][0]
        self.assertEqual(row["wins"], 0)
        for field in ("rank", "played", "draws", "losses", "gf", "ga", "gd", "points"):
            self.assertIsNone(row[field], field)


def mls_payload(year=2026, phase_start="2026-01-01T05:00Z",
                phase_end="2026-11-09T04:59Z", played=18):
    """A published /standings payload in ESPN's real shape (measured 2026-08-17)."""
    return {
        "season": {"year": year, "displayName": f"{year} MLS"},
        "seasons": [{
            "year": year,
            "types": [
                {"name": "Combined", "hasStandings": False,
                 "startDate": phase_start, "endDate": phase_end},
                {"name": "Regular Season", "hasStandings": True,
                 "startDate": phase_start, "endDate": phase_end},
            ],
        }],
        "children": [{
            "name": "Eastern Conference",
            "standings": {"entries": [entry(
                "NSH", "Nashville SC", rank=1, gamesPlayed=played, wins=13,
                ties=4, losses=2, pointsFor=39, pointsAgainst=15,
                pointDifferential=24, points=43,
            )]},
        }],
    }


class MlsPublishedSeasonTest(unittest.TestCase):
    """MLS standings must name the season they are, and must be the live one.

    Added 2026-08-17. In mid-August 2026 this surface served the 2025 FINAL
    table — 34 games played, every team — with no season label anywhere on it,
    because the season was chosen as `MAX(season)` of what our tables held and
    our tables only ever hold a completed season. The arithmetic was never the
    bug (the old rollup reproduced ESPN's published 2025 table for 30/30 teams
    with zero disagreements); the season selection was.
    """

    def test_season_and_phase_come_from_the_publisher(self):
        with patch.object(espn, "_get", return_value=mls_payload()):
            out = espn.mls_conference_standings()

        self.assertEqual(out["season"], 2026)
        self.assertEqual(out["season_label"], "2026 MLS")
        self.assertEqual(out["phase"], "Regular Season")
        self.assertTrue(out["in_progress"])
        self.assertEqual(out["groups"][0]["rows"][0]["points"], 43)

    def test_points_and_rank_are_copied_not_recomputed(self):
        """A 3W+D recomputation would give 43 here too, which is exactly why the
        old derivation looked correct. Publish a row where the published points
        DISAGREE with 3W+D (deductions are a real MLS mechanic) and assert we
        serve the publisher's number, not our arithmetic."""
        payload = mls_payload()
        stats = payload["children"][0]["standings"]["entries"][0]["stats"]
        for stat in stats:
            if stat["name"] == "points":
                stat["value"] = 40      # 3(13)+4 = 43; publisher says 40
        with patch.object(espn, "_get", return_value=payload):
            out = espn.mls_conference_standings()

        self.assertEqual(out["groups"][0]["rows"][0]["points"], 40)

    def test_a_finished_phase_is_not_reported_as_in_progress(self):
        """November: the regular season has ended. The table is still the right
        table, but `in_progress` must say it is done so the UI can label it
        Final rather than implying matches are still being played."""
        payload = mls_payload(phase_start="2025-01-01T05:00Z",
                              phase_end="2025-11-09T04:59Z", year=2025, played=34)
        with patch.object(espn, "_get", return_value=payload):
            out = espn.mls_conference_standings()

        self.assertEqual(out["season"], 2025)
        self.assertFalse(out["in_progress"])

    def test_an_empty_publisher_table_raises_instead_of_serving_nothing(self):
        payload = mls_payload()
        payload["children"] = []
        with patch.object(espn, "_get", return_value=payload):
            with self.assertRaises(ValueError):
                espn.mls_conference_standings()


class StandingsRouteContractTest(unittest.TestCase):
    """Routing contract, updated 2026-08-17.

    2026-08-16 made MLS standings DB-first and this test asserted MLS "touches
    no ESPN host at all". That invariant is withdrawn deliberately: it is what
    guaranteed a stale table, because our rows only ever cover a finished
    season. What that change was actually protecting — no ESPN request per
    pageview — still holds, via the 900s TTL, the same way NCAAF has always
    worked.
    """

    def test_ncaaf_uses_its_own_conference_endpoint_and_other_leagues_keep_strength(self):
        grouped = [{"group": "Sun Belt - East", "rows": []}]
        flat = [{"abbrev": "BOS"}]
        with patch.object(games.espn, "ncaaf_conference_standings", return_value=grouped) as ncaaf_call, \
             patch.object(games.espn, "team_strength", return_value=flat) as strength_call:
            self.assertEqual(games.get_standings("ncaaf"), grouped)
            self.assertEqual(games.get_standings("mlb"), flat)

        ncaaf_call.assert_called_once_with()
        strength_call.assert_called_once_with("mlb")

    def test_mls_serves_the_published_seasoned_table(self):
        seasoned = {"league": "mls", "season": 2026, "in_progress": True,
                    "groups": [{"group": "Eastern Conference", "rows": []}]}
        with patch.object(games.espn, "mls_conference_standings",
                          return_value=seasoned) as mls_call, \
             patch.object(games.espn, "group_standings") as group_call, \
             patch.object(games.espn, "team_strength") as strength_call:
            self.assertEqual(games.get_standings("mls"), seasoned)

        mls_call.assert_called_once_with()
        group_call.assert_not_called()
        strength_call.assert_not_called()

    def test_mls_upstream_failure_is_a_503_and_never_falls_back_to_last_season(self):
        """The whole defect in one assertion.

        When the publisher cannot be read, the tempting behaviour is to serve
        the table we already have. That table is a finished season, and serving
        it is what put a 34-games-played 2025 table on screen in August. A 503
        with a reason is the honest answer; a stale table is the plausible one.
        """
        from fastapi import HTTPException
        for boom in (ValueError("publisher named no season"), RuntimeError("timeout")):
            with self.subTest(boom=type(boom).__name__):
                with patch.object(games.espn, "mls_conference_standings",
                                  side_effect=boom):
                    with self.assertRaises(HTTPException) as caught:
                        games.get_standings("mls")
                self.assertEqual(caught.exception.status_code, 503)
                self.assertIn("mls", str(caught.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
