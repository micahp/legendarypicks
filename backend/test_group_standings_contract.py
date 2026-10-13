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


class TeamStrengthStandingsSeasonTest(unittest.TestCase):
    """The flat W-L table must name the season it is actually serving.

    Measured against the live publisher 2026-08-17: on a request with no season,
    NBA, MLB and NHL all reported `season.year` = 2027 while returning the 2026
    table (MLB's Brewers 77-48 through 125 games — a season in progress). 2027 is
    absent from their own `seasons[]`, because it has no standings table yet, so
    the pointer names the NEXT season rather than the served one. NFL and MLS
    agreed with their payloads. Labelling from `season.year` would have put
    "2027" on a live 2026 table.
    """

    @staticmethod
    def payload(pointer_year, published_years):
        return {
            "season": {"year": pointer_year, "displayName": str(pointer_year)},
            "seasons": [
                {"year": year, "displayName": f"{year - 1}-{str(year)[2:]}",
                 "types": [{"name": "Regular Season", "hasStandings": True}]}
                for year in published_years
            ],
            "children": [{"standings": {"entries": [entry(
                "OKC", "Oklahoma City Thunder", wins=64, losses=18,
                gamesPlayed=82, winPercent=0.78,
            )]}}],
        }

    def test_a_pointer_past_the_published_years_is_corrected_to_the_served_one(self):
        with patch.object(espn, "_get", return_value=self.payload(2027, [2026, 2025])):
            out = espn.team_strength_standings("nba")

        self.assertEqual(out["season"], 2026)
        self.assertEqual(out["season_label"], "2025-26")
        self.assertEqual(out["available_seasons"], [2026, 2025])
        self.assertEqual(out["teams"][0]["abbrev"], "OKC")

    def test_a_pointer_the_publisher_lists_is_left_alone(self):
        """NFL in August: 2026 is the current season AND a published one."""
        with patch.object(espn, "_get", return_value=self.payload(2026, [2026, 2025])):
            out = espn.team_strength_standings("nfl")

        self.assertEqual(out["season"], 2026)

    def test_an_explicit_season_is_never_second_guessed(self):
        """?season=2015 is accurate at the publisher, so it is copied as-is even
        though it is not the newest published year."""
        seen = {}

        def fake_get(url, ttl=None):
            seen["url"] = url
            return self.payload(2015, [2026, 2015])

        with patch.object(espn, "_get", fake_get):
            out = espn.team_strength_standings("nba", season=2015)

        self.assertIn("season=2015", seen["url"])
        self.assertEqual(out["season"], 2015)

    def test_the_default_request_pins_no_year(self):
        seen = {}

        def fake_get(url, ttl=None):
            seen["url"] = url
            return self.payload(2026, [2026])

        with patch.object(espn, "_get", fake_get):
            espn.team_strength_standings("nba")

        self.assertNotIn("season=", seen["url"])


class NcaafPublishedSeasonTest(unittest.TestCase):
    @staticmethod
    def payload(year=2026):
        return {
            "season": {"year": year, "displayName": str(year)},
            "seasons": [
                {"year": 2026, "types": [{"hasStandings": True}]},
                {"year": 2025, "types": [{"hasStandings": True}]},
                {"year": 2024, "types": [{"hasStandings": False}]},
            ],
            "children": [{
                "name": "Big Ten Conference",
                "standings": {"entries": [{
                    "team": {"abbreviation": "OSU", "displayName": "Ohio State Buckeyes"},
                    "stats": [{"name": "overall", "displayValue": "12-2"}],
                }]},
            }],
        }

    def test_names_the_published_season_and_offerable_years(self):
        with patch.object(espn, "_get", return_value=self.payload()):
            out = espn.ncaaf_conference_standings()

        self.assertEqual(out["season"], 2026)
        self.assertEqual(out["available_seasons"], [2026, 2025])
        self.assertEqual(out["groups"][0]["rows"][0]["wins"], 12)

    def test_an_explicit_year_reaches_the_publisher(self):
        seen = {}

        def fake_get(url, ttl=None):
            seen["url"] = url
            return self.payload(2025)

        with patch.object(espn, "_get", fake_get):
            out = espn.ncaaf_conference_standings(season=2025)

        self.assertIn("season=2025", seen["url"])
        self.assertEqual(out["season"], 2025)


class OfferOnlySeasonsWeHoldTest(unittest.TestCase):
    """The year picker offers seasons the rest of the app can follow up on.

    ESPN serves 24-25 years of standings for every league. Measured 2026-08-17
    against picks.db we hold one to three seasons each (NFL player_stats 2025;
    NBA 2026+2025; MLB/NHL 2026 only), so the picker was offering two decades of
    tables attached to nothing — pick 2003 and the Stats tab, the game logs and
    the props all have nothing to say about it.
    """

    def envelope(self, served, offered):
        return {"league": "nba", "season": served, "season_label": str(served),
                "available_seasons": list(offered), "teams": []}

    def test_years_without_data_behind_them_are_not_offered(self):
        with patch.object(games, "seasons_we_hold", return_value={2026, 2025}):
            out = games._offer_only_seasons_we_hold(
                self.envelope(2026, [2026, 2025, 2024, 2023, 2003]), "nba")
        self.assertEqual(out["available_seasons"], [2026, 2025])

    def test_the_served_season_is_always_offered(self):
        """NFL in August serves 2026 (preseason) while our newest ingested season
        is 2025. The pill must not name a year absent from its own options."""
        with patch.object(games, "seasons_we_hold", return_value={2025}):
            out = games._offer_only_seasons_we_hold(
                self.envelope(2026, [2026, 2025, 2024]), "nfl")
        self.assertEqual(out["available_seasons"], [2026, 2025])

    def test_holding_nothing_leaves_just_the_season_on_screen(self):
        with patch.object(games, "seasons_we_hold", return_value=set()):
            out = games._offer_only_seasons_we_hold(
                self.envelope(2026, [2026, 2025, 2024]), "nba")
        self.assertEqual(out["available_seasons"], [2026])

    def test_a_historical_pick_keeps_the_current_season_as_a_way_back(self):
        with patch.object(games, "seasons_we_hold", return_value={2025}):
            out = games._offer_only_seasons_we_hold(
                self.envelope(2025, [2026, 2025, 2024]), "ncaaf")
        self.assertEqual(out["available_seasons"], [2026, 2025])

    def test_a_degraded_payload_is_left_alone(self):
        """The snapshot fallback carries no season and no year list. Filtering an
        empty list must not invent one."""
        payload = {"league": "nba", "season": None, "available_seasons": [], "teams": [{}]}
        with patch.object(games, "seasons_we_hold", return_value={2026}):
            out = games._offer_only_seasons_we_hold(payload, "nba")
        self.assertEqual(out["available_seasons"], [])

    def test_an_unreadable_database_does_not_shrink_the_picker_to_nothing(self):
        """`seasons_we_hold` returning empty because it could not READ is not the
        same as us holding nothing — but both land here, so the served season
        still survives and the table still renders."""
        with patch.object(games, "seasons_we_hold", return_value=set()):
            out = games._offer_only_seasons_we_hold(
                self.envelope(2026, [2026, 2025]), "nba")
        self.assertIn(2026, out["available_seasons"])


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

    def test_a_past_season_can_be_requested_and_the_years_come_from_the_publisher(self):
        """The picker's options must be years we can actually serve, so they are
        read off the payload's own `seasons[]` rather than a generated range."""
        payload = mls_payload()
        payload["seasons"].append({
            "year": 2019,
            "types": [{"name": "Regular Season", "hasStandings": True,
                       "startDate": "2019-01-01T05:00Z", "endDate": "2019-11-09T04:59Z"}],
        })
        payload["seasons"].append({   # no standings table -> not offerable
            "year": 2018,
            "types": [{"name": "Combined", "hasStandings": False,
                       "startDate": "2018-01-01T05:00Z", "endDate": "2018-11-09T04:59Z"}],
        })
        seen = {}

        def fake_get(url, ttl=None):
            seen["url"] = url
            return payload

        with patch.object(espn, "_get", fake_get):
            out = espn.mls_conference_standings(season=2019)

        self.assertIn("season=2019", seen["url"])
        self.assertEqual(out["available_seasons"], [2026, 2019])

    def test_the_default_request_pins_no_year(self):
        """No `season` means "whatever the publisher calls current" — the default
        view must not hardcode a year that goes stale next season."""
        seen = {}

        def fake_get(url, ttl=None):
            seen["url"] = url
            return mls_payload()

        with patch.object(espn, "_get", fake_get):
            espn.mls_conference_standings()

        self.assertNotIn("season=", seen["url"])

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

    def test_ncaaf_uses_its_own_conference_endpoint_and_other_leagues_name_their_season(self):
        """A flat W-L table must arrive carrying the season it belongs to.

        This used to serve `team_strength`'s bare row list, so the standings tab
        rendered a table with nothing on the page naming its season — and for
        NBA, MLB and NHL the table on screen in August was the PREVIOUS season's
        with no way to tell. `/api/{league}/strength` keeps the list shape; the
        standings route serves the envelope.
        """
        grouped = {"league": "ncaaf", "season": 2026,
                   "available_seasons": [2026, 2025],
                   "groups": [{"group": "Sun Belt - East", "rows": []}]}
        seasoned = {"league": "mlb", "season": 2026, "season_label": "2026",
                    "available_seasons": [2026, 2025], "teams": [{"abbrev": "BOS"}]}
        with patch.object(games.espn, "ncaaf_conference_standings", return_value=grouped) as ncaaf_call, \
             patch.object(games.espn, "team_strength_standings", return_value=seasoned) as strength_call, \
             patch.object(games.espn, "team_strength") as bare_call:
            self.assertEqual(games.get_standings("ncaaf"), grouped)
            self.assertEqual(games.get_standings("mlb"), seasoned)

        ncaaf_call.assert_called_once_with(season=None)
        strength_call.assert_called_once_with("mlb", season=None)
        # The bare row list is no longer what standings serves.
        bare_call.assert_not_called()

    def test_a_requested_standings_season_reaches_the_publisher(self):
        with patch.object(games.espn, "team_strength_standings",
                          return_value={"teams": []}) as strength_call:
            games.get_standings("nba", season=2015)
        strength_call.assert_called_once_with("nba", season=2015)

    def test_a_requested_ncaaf_season_reaches_the_publisher(self):
        payload = {"league": "ncaaf", "season": 2025,
                   "available_seasons": [2026, 2025], "groups": []}
        with patch.object(games.espn, "ncaaf_conference_standings",
                          return_value=payload) as standings_call:
            games.get_standings("ncaaf", season=2025)
        standings_call.assert_called_once_with(season=2025)

    def test_mls_serves_the_published_seasoned_table(self):
        seasoned = {"league": "mls", "season": 2026, "in_progress": True,
                    "groups": [{"group": "Eastern Conference", "rows": []}]}
        with patch.object(games.espn, "mls_conference_standings",
                          return_value=seasoned) as mls_call, \
             patch.object(games.espn, "group_standings") as group_call, \
             patch.object(games.espn, "team_strength") as strength_call:
            self.assertEqual(games.get_standings("mls"), seasoned)

        mls_call.assert_called_once_with(season=None)
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
