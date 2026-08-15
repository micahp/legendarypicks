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
    def test_mls_and_ncaaf_use_groups_while_other_leagues_keep_strength(self):
        grouped = [{"group": "Eastern Conference", "rows": []}]
        flat = [{"abbrev": "BOS"}]
        with patch.object(games.espn, "group_standings", return_value=grouped) as group_call, \
             patch.object(games.espn, "team_strength", return_value=flat) as strength_call:
            self.assertEqual(games.get_standings("mls"), grouped)
            self.assertEqual(games.get_standings("ncaaf"), grouped)
            self.assertEqual(games.get_standings("mlb"), flat)

        self.assertEqual(group_call.call_args_list[0].args, ("mls",))
        self.assertEqual(group_call.call_args_list[1].args, ("ncaaf",))
        strength_call.assert_called_once_with("mlb")
