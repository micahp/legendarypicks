#!/usr/bin/env python3
"""Hockey's three player types must each come out described by their own job.

The bug these pin: every goalie row in the database read 0 goals, 0 assists,
0 shots, because the only mapping that existed was forward-shaped.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import urllib.parse
from unittest import mock

import ingest_nhl_season_stats as ingest


GOALIE_ROW = {
    "playerId": 8481611,
    "goalieFullName": "Pyotr Kochetkov",
    "teamAbbrevs": "CAR",
    "gamesPlayed": 9,
    "gamesStarted": 8,
    "goalsAgainst": 19,
    "goalsAgainstAverage": 2.32581,
    "losses": 2,
    "otLosses": 0,
    "savePct": 0.89947,
    "saves": 170,
    "shotsAgainst": 189,
    "shutouts": 1,
    "wins": 6,
}

DEFENCEMAN_ROW = {
    "playerId": 8476882,
    "skaterFullName": "Moritz Seider",
    "positionCode": "D",
    "teamAbbrevs": "DET",
    "gamesPlayed": 82,
    "goals": 10,
    "assists": 50,
    "points": 60,
    "shots": 150,
    "shootingPct": 0.0667,
    "plusMinus": 15,
    "penaltyMinutes": 40,
    "ppGoals": 3,
    "ppPoints": 20,
    "shGoals": 0,
    "timeOnIcePerGame": 1540.0,
    "faceoffWinPct": None,
}

REALTIME_ROW = {
    "playerId": 8476882,
    "blockedShots": 180,
    "hits": 128,
    "takeaways": 45,
    "giveaways": 60,
}


class GoalieMappingTest(unittest.TestCase):
    def test_a_goalie_is_described_by_goaltending(self):
        values = ingest.goalie_values(GOALIE_ROW)
        self.assertEqual(values["saves"], 170)
        self.assertEqual(values["shots_against"], 189)
        self.assertEqual(values["goals_against"], 19)
        self.assertEqual(values["shutouts"], 1)
        self.assertEqual(values["wins"], 6)
        self.assertEqual(values["losses"], 2)
        self.assertEqual(values["games_started"], 8)
        self.assertEqual(values["nhl_position"], "G")

    def test_saves_is_taken_from_the_publisher_not_derived(self):
        # shotsAgainst - goalsAgainst would also give 170 here, so a derivation
        # would look correct. Change the published value alone and the mapping
        # must follow it, which only a read of `saves` can do.
        row = dict(GOALIE_ROW, saves=171)
        self.assertEqual(ingest.goalie_values(row)["saves"], 171)

    def test_percentages_are_published_as_fractions(self):
        self.assertEqual(ingest.goalie_values(GOALIE_ROW)["save_pct"], 89.9)
        self.assertEqual(ingest.goalie_values(GOALIE_ROW)["gaa"], 2.33)

    def test_a_missing_published_value_stays_missing(self):
        values = ingest.goalie_values(dict(GOALIE_ROW, saves=None, shutouts=None))
        self.assertIsNone(values["saves"])
        self.assertIsNone(values["shutouts"])


class SkaterMappingTest(unittest.TestCase):
    def test_a_defenceman_gets_the_stats_defencemen_are_judged_on(self):
        values = ingest.skater_values(DEFENCEMAN_ROW, REALTIME_ROW)
        self.assertEqual(values["nhl_position"], "D")
        self.assertEqual(values["blocked_shots"], 180)
        self.assertEqual(values["hits"], 128)
        self.assertEqual(values["takeaways"], 45)
        self.assertEqual(values["giveaways"], 60)
        self.assertEqual(values["goals"], 10)
        self.assertEqual(values["assists"], 50)

    def test_no_realtime_row_means_no_invented_zeroes(self):
        values = ingest.skater_values(DEFENCEMAN_ROW, None)
        self.assertNotIn("blocked_shots", values)
        self.assertNotIn("hits", values)

    def test_time_on_ice_is_published_in_seconds(self):
        self.assertEqual(ingest.skater_values(DEFENCEMAN_ROW, None)["toi"], "25:40")
        self.assertIsNone(ingest._toi(None))


class FetchReportTest(unittest.TestCase):
    """The report must be complete, and it must be the regular season."""

    def test_it_asks_for_the_regular_season_explicitly(self):
        seen = []

        def fake_get(url):
            seen.append(url)
            return {"data": [GOALIE_ROW], "total": 1}

        with mock.patch.object(ingest, "_get", fake_get):
            ingest.fetch_report("goalie/summary", 20252026)
        self.assertIn("gameTypeId%3D2", seen[0].replace("+", "%20"))

    def test_it_uses_a_stable_player_id_order_across_pages(self):
        seen = []

        def fake_get(url):
            seen.append(url)
            return {"data": [GOALIE_ROW], "total": 1}

        with mock.patch.object(ingest, "_get", fake_get):
            ingest.fetch_report("goalie/summary", 20252026)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0]).query)
        self.assertEqual(
            json.loads(query["sort"][0]),
            [{"property": "playerId", "direction": "ASC"}],
        )

    def test_a_short_page_run_fails_closed(self):
        # The publisher says 500 rows exist and hands back 1. Publishing that
        # as a league snapshot is how a partial pull becomes "the season".
        def fake_get(_url):
            return {"data": [GOALIE_ROW], "total": 500}

        with mock.patch.object(ingest, "_get", fake_get):
            with self.assertRaisesRegex(
                ingest.NHLStatsIngestError, "the report ended early"
            ):
                ingest.fetch_report("goalie/summary", 20252026)

    def test_it_pages_to_completion(self):
        pages = [
            {"data": [dict(GOALIE_ROW, playerId=i) for i in range(100)], "total": 150},
            {"data": [dict(GOALIE_ROW, playerId=i) for i in range(50)], "total": 150},
        ]

        def fake_get(_url):
            return pages.pop(0)

        with mock.patch.object(ingest, "_get", fake_get):
            rows = ingest.fetch_report("goalie/summary", 20252026)
        self.assertEqual(len(rows), 150)


def _skater(pid, name, team="NYR", pos="C"):
    return dict(DEFENCEMAN_ROW, playerId=pid, skaterFullName=name,
                teamAbbrevs=team, positionCode=pos)


def _goalie(pid, name, team="NYR"):
    return dict(GOALIE_ROW, playerId=pid, goalieFullName=name, teamAbbrevs=team)


class IdentityAtIngestTest(unittest.TestCase):
    """A published player with no owner must be resolved by the ingest itself,
    so the next run cannot re-create the gap and one player cannot block the rest."""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              league TEXT NOT NULL, team TEXT, position TEXT, active INTEGER,
              updated_at TEXT, espn_id TEXT, nhl_id TEXT);
            CREATE TABLE player_source_ids(
              id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              league TEXT NOT NULL, source_player_key TEXT NOT NULL,
              player_id INTEGER NOT NULL, first_seen TEXT, last_seen TEXT,
              UNIQUE(source, league, source_player_key));
            CREATE TABLE player_stats(
              id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER,
              league TEXT, season TEXT);
        """)
        con.commit()
        con.close()
        self.published = []
        self.addCleanup(os.remove, self.db)

    def seed(self, *rows):
        con = sqlite3.connect(self.db)
        for name, team, pos, nhl_id in rows:
            con.execute("INSERT INTO players(name,league,team,position,nhl_id,active)"
                        " VALUES(?,'nhl',?,?,?,0)", (name, team, pos, nhl_id))
        con.commit()
        con.close()

    def run_ingest(self, skaters=(), goalies=(), dry_run=False):
        skaters = list(skaters)
        realtime = [dict(REALTIME_ROW, playerId=r["playerId"]) for r in skaters]
        reports = {"goalie/summary": list(goalies), "skater/summary": skaters,
                   "skater/realtime": realtime}
        self.published = []

        def fake_publish(_con, **kw):
            self.published.append(kw["player_id"])

        with mock.patch.object(ingest, "fetch_report", lambda r, s: reports[r]), \
                mock.patch.object(ingest, "publish_player_stats", fake_publish), \
                mock.patch("builtins.print"):
            return ingest.refresh(self.db, season=20252026, dry_run=dry_run)

    def players(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM players ORDER BY id").fetchall()
        crosswalk = con.execute("SELECT * FROM player_source_ids").fetchall()
        con.close()
        return rows, crosswalk

    def test_an_unbound_row_with_team_evidence_is_bound_not_duplicated(self):
        self.seed(("Kevin Gravel", "NYR", "D", None))
        counts = self.run_ingest([_skater(8475857, "Kevin Gravel", "NYR", "D")])
        rows, crosswalk = self.players()
        self.assertEqual((counts["bound"], counts["minted"], counts["skipped"]), (1, 0, 0))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nhl_id"], "8475857")
        self.assertEqual(rows[0]["active"], 0)  # identity only, membership untouched
        self.assertEqual(self.published, [rows[0]["id"]])
        self.assertEqual([r["source_player_key"] for r in crosswalk], ["8475857"])

    def test_a_player_the_spine_never_had_is_minted_inactive(self):
        counts = self.run_ingest([_skater(8475784, "Jeff Skinner", "BUF", "L")])
        rows, _ = self.players()
        self.assertEqual((counts["bound"], counts["minted"]), (0, 1))
        self.assertEqual((rows[0]["name"], rows[0]["nhl_id"], rows[0]["active"]),
                         ("Jeff Skinner", "8475784", 0))
        self.assertEqual(self.published, [rows[0]["id"]])

    def test_a_same_name_row_with_another_nhl_id_is_a_different_person(self):
        self.seed(("Sebastian Aho", "CAR", "C", "8478427"))
        counts = self.run_ingest([_skater(8480222, "Sebastian Aho", "NYI", "D")])
        rows, _ = self.players()
        self.assertEqual((counts["bound"], counts["minted"]), (0, 1))
        self.assertEqual(sorted(r["nhl_id"] for r in rows), ["8478427", "8480222"])

    def test_an_ambiguous_player_is_skipped_loudly_and_the_rest_still_publish(self):
        self.seed(("Sam Smith", "NYR", "C", None), ("Sam Smith", "NYR", "C", None),
                  ("Known Guy", "NYR", "C", "8470001"))
        counts = self.run_ingest([_skater(8479999, "Sam Smith", "NYR", "C"),
                                  _skater(8470001, "Known Guy", "NYR", "C")])
        rows, _ = self.players()
        self.assertEqual((counts["skipped"], counts["forwards"]), (1, 1))
        self.assertEqual(len(rows), 3)                       # nothing guessed or minted
        self.assertTrue(all(r["nhl_id"] != "8479999" for r in rows))
        self.assertEqual(len(self.published), 1)
        with mock.patch.object(ingest, "refresh", return_value=counts):
            with mock.patch("builtins.print"):
                self.assertEqual(ingest.main(["--season", "20252026"]), 2)

    def test_a_name_match_with_no_team_or_position_evidence_is_not_bound(self):
        self.seed(("Pat Jones", "BOS", "G", None))
        counts = self.run_ingest([_skater(8470002, "Pat Jones", "NYR", "C")])
        self.assertEqual((counts["bound"], counts["skipped"]), (0, 1))
        self.assertEqual(self.players()[0][0]["nhl_id"], None)

    def test_a_stranded_crosswalk_is_skipped(self):
        self.seed(("Old Owner", "NYR", "C", None))
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO player_source_ids(source,league,source_player_key,"
                    "player_id) VALUES('nhle.com','nhl','8470003',1)")
        con.commit()
        con.close()
        counts = self.run_ingest([_skater(8470003, "Old Owner", "NYR", "C")])
        self.assertEqual((counts["skipped"], counts["bound"], counts["minted"]), (1, 0, 0))

    def test_a_spelling_variant_of_an_unbound_row_is_not_minted_beside_it(self):
        self.seed(("Sammy Blais", "OTT", "LW", None), ("Mike Benning", "CGY", "D", None))
        counts = self.run_ingest([_skater(8477493, "Samuel Blais", "TOR", "L"),
                                  _skater(8480000, "Matthew Benning", "TOR", "D")])
        rows, _ = self.players()
        # Blais shares last name and "sam" with an unbound row: held. Benning does
        # not share the first three letters with Mike, so he is a new person.
        self.assertEqual((counts["skipped"], counts["minted"]), (1, 1))
        self.assertEqual(sorted(r["name"] for r in rows),
                         ["Matthew Benning", "Mike Benning", "Sammy Blais"])

    def test_a_dry_run_writes_nothing(self):
        self.seed(("Kevin Gravel", "NYR", "D", None))
        counts = self.run_ingest([_skater(8475857, "Kevin Gravel", "NYR", "D"),
                                  _skater(8475784, "Jeff Skinner", "BUF", "L")],
                                 dry_run=True)
        rows, crosswalk = self.players()
        self.assertEqual((counts["bound"], counts["minted"]), (1, 1))
        self.assertEqual((len(rows), rows[0]["nhl_id"], len(crosswalk)), (1, None, 0))
        self.assertEqual(self.published, [])

    def test_the_second_run_resolves_by_id_and_a_new_player_adds_one_row(self):
        # The point of fixing this at the ingest: a repeat run is a no-op for
        # identity, and next season's new player is handled without a repair job.
        self.seed(("Kevin Gravel", "NYR", "D", None))
        first = [_skater(8475857, "Kevin Gravel", "NYR", "D"),
                 _skater(8475784, "Jeff Skinner", "BUF", "L")]
        goalie = [_goalie(8477405, "Marcus Hogberg", "OTT")]
        self.run_ingest(first, goalie)
        after_first, _ = self.players()
        again = self.run_ingest(first, goalie)
        after_second, crosswalk = self.players()
        self.assertEqual((again["bound"], again["minted"], again["skipped"]), (0, 0, 0))
        self.assertEqual([tuple(r) for r in after_first], [tuple(r) for r in after_second])
        self.assertEqual(len(crosswalk), 3)
        third = self.run_ingest(first + [_skater(8484409, "Hoyt Stanley", "NYR", "C")], goalie)
        rows, crosswalk = self.players()
        self.assertEqual((third["minted"], third["bound"]), (1, 0))
        self.assertEqual((len(rows), len(crosswalk)), (4, 4))
        self.assertEqual(len(self.published), 4)

    def test_a_goalie_is_bound_on_position_g(self):
        self.seed(("Spencer Martin", "NYR", "G", None))
        counts = self.run_ingest(goalies=[_goalie(8477484, "Spencer Martin", "NYR")])
        self.assertEqual((counts["bound"], counts["goalies"]), (1, 1))


class CurrentSeasonTest(unittest.TestCase):
    def test_current_means_the_season_the_league_publishes_as_current(self):
        seen = {}

        def fake_refresh(db, *, season, dry_run):
            seen["season"] = season
            return {"skipped": 0}

        with mock.patch.object(ingest, "_get", lambda url: {"currentSeason": 20262027}), \
                mock.patch.object(ingest, "refresh", fake_refresh), \
                mock.patch("builtins.print"):
            self.assertEqual(ingest.main(["--season", "current", "--db", "x"]), 0)
        self.assertEqual(seen["season"], 20262027)

    def test_an_unreadable_current_season_fails_instead_of_guessing(self):
        with mock.patch.object(ingest, "_get", lambda url: {"currentSeason": None}):
            with self.assertRaisesRegex(ingest.NHLStatsIngestError, "invalid current"):
                ingest.main(["--season", "current", "--db", "x"])


class RegistryTest(unittest.TestCase):
    def test_it_is_scheduled_on_its_own_with_a_freshness_target(self):
        import ingest_registry
        job = {j["id"]: j for j in ingest_registry.JOBS}["nhl_season_stats"]
        self.assertEqual(job["steps"], [["ingest_nhl_season_stats.py", "--season", "current"]])
        self.assertEqual(job["freshness"][0]["table"], "ingest_runs")
        # A held player must not stop the roster -> logs -> shares chain.
        chain = {j["id"]: j for j in ingest_registry.JOBS}["nhl_current"]["steps"]
        self.assertNotIn("ingest_nhl_season_stats.py", [step[0] for step in chain])


if __name__ == "__main__":
    unittest.main(verbosity=2)
