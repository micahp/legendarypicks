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


class StandingsRouteContractTest(unittest.TestCase):
    """Routing contract, updated 2026-08-16 when MLS standings became DB-first.

    The previous version asserted MLS and NCAAF both went through
    `espn.group_standings`. That is no longer the contract and asserting it
    would lock in a live ESPN call on every standings pageview. The invariant
    worth holding is stronger: MLS is served from our own rows and touches no
    ESPN host at all.
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

    def test_mls_is_served_from_our_own_rows_and_never_calls_espn(self):
        grouped = [{"group": "Eastern Conference", "rows": []}]
        with patch.object(games, "_mls_standings_season", return_value=2025), \
             patch.object(games, "_mls_standings_from_db", return_value=grouped) as db_call, \
             patch.object(games.espn, "group_standings") as group_call, \
             patch.object(games.espn, "team_strength") as strength_call:
            self.assertEqual(games.get_standings("mls"), grouped)

        db_call.assert_called_once_with(2025)
        # The point of the change: a standings pageview spends no ESPN budget.
        group_call.assert_not_called()
        strength_call.assert_not_called()

    def test_mls_without_rows_is_an_honest_503_not_a_500(self):
        """A database holding no MLS rows must say so, loudly.

        The fallback query used to raise a bare sqlite3.OperationalError on a
        database with no team_game_results table, which reached the user as a
        500 that said nothing. Absence of data is a 503 with a reason.
        """
        from fastapi import HTTPException
        with patch.object(games, "_mls_standings_season", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                games.get_standings("mls")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("mls", str(caught.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
