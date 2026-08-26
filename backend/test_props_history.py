#!/usr/bin/env python3

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_IMPORT_DB = tempfile.NamedTemporaryFile(
    prefix="props-history-import-", suffix=".db", delete=False
)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import props  # noqa: E402


class PropHistoryVenueTests(unittest.TestCase):
    """Preserve unknown venue instead of publishing it as an away game."""

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="props-history-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT
            );
            CREATE TABLE player_game_logs(
              player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
              game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER,
              game_type TEXT,
              -- The real table has this and these fixtures did not, so they
              -- described a world where the reader cannot pick a provider.
              source TEXT
            );
            """
        )
        con.execute("INSERT INTO players VALUES(1,'Alex Ready','AAA','nba','G')")
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (1, "nba", 2026, json.dumps({"PTS": 24}), "2026-07-20", "OPP1", "home", 1, None, "espn"),
                (1, "nba", 2026, json.dumps({"PTS": 18}), "2026-07-21", "OPP2", "away", 2, None, "espn"),
                (1, "nba", 2026, json.dumps({"PTS": 21}), "2026-07-22", "OPP3", None, 3, None, "espn"),
            ],
        )
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = mock.patch.object(props, "_db", side_effect=connection)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_home_away_and_null_venue_serialize_tri_state(self):
        result = props.prop_history(
            player_id=1, market="points", line=20.5, side="over", league="nba"
        )

        self.assertEqual(3, len(result["games"]))
        self.assertEqual([None, False, True], [g["home"] for g in result["games"]])
        self.assertEqual(
            ["OPP3", "OPP2", "OPP1"],
            [g["opponent"] for g in result["games"]],
        )
        self.assertEqual([21, 18, 24], [g["value"] for g in result["games"]])


if __name__ == "__main__":
    unittest.main()


class LeaguesCupChartsAcrossTheSpines(unittest.TestCase):
    """A cross-border tournament's chart is about the PLAYER, not the competition.

    Reading `league='lcup'` alone gave a Liga MX player his three group games and
    an MLS player three games instead of a season, because the athletes keep
    their domestic logs. Measured on real data 2026-08-25: Brooks Lennon charts
    28 games under the union and 3 without it.
    """

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="props-history-lcup-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT
            );
            CREATE TABLE player_game_logs(
              player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
              game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER,
              game_type TEXT,
              -- The real table has this and these fixtures did not, so they
              -- described a world where the reader cannot pick a provider.
              source TEXT
            );
            """
        )
        # A Leagues Cup athlete is owned by a DOMESTIC spine; players.league is
        # never 'lcup'.
        con.execute("INSERT INTO players VALUES(1,'Liga MX Forward','AME','ligamx','F')")
        con.execute("INSERT INTO players VALUES(2,'MLS Winger','CLB','mls','M')")
        con.execute("INSERT INTO players VALUES(3,'Deep Row Midfielder','MTY','ligamx','M')")
        con.execute("INSERT INTO players VALUES(4,'Bench Player','AME','ligamx','F')")
        con.execute("INSERT INTO players VALUES(5,'Summary Bench','LEO','ligamx','M')")
        rows = [
            # The Liga MX player has ONLY tournament games -- there is no ligamx
            # game-log ingest, so this is everything we hold for him.
            (1, "lcup", 2026, json.dumps({"shots": 3, "goals": 1, "assists": 0,
                                          "fouls_committed": 2}),
             "2026-08-14", "ATX", "home", 1, "REG", "espn"),
            (1, "lcup", 2026, json.dumps({"shots": 6, "goals": 0, "assists": 1,
                                          "fouls_committed": 1}),
             "2026-08-10", "POR", "home", 2, "REG", "espn"),
            # The MLS player carries a domestic season alongside the tournament.
            (2, "lcup", 2026, json.dumps({"shots": 1}),
             "2026-08-12", "MTY", "away", 1, "REG", "espn"),
            (2, "mls", 2026, json.dumps({"shots": 2}),
             "2026-07-20", "NE", "home", 2, "REG", "espn"),
            (2, "mls", 2026, json.dumps({"shots": 0}),
             "2026-07-13", "NYC", "away", 3, "REG", "espn"),
            # A player whose deep fields came from FotMob's own row.
            (3, "lcup", 2026, json.dumps({"shots": 2, "tackles": 3,
                                          "clearances": 4,
                                          "passes_attempted": 55}),
             "2026-08-14", "ATX", "home", 1, "REG", "fotmob"),
            (3, "lcup", 2026, json.dumps({"shots": 1, "tackles": 1,
                                          "clearances": 0,
                                          "passes_attempted": 40}),
             "2026-08-10", "POR", "away", 2, "REG", "fotmob"),
            # Two matches this player never entered. Stored, because the row is
            # a real record of not playing -- but they are not zeroes.
            (4, "ligamx", 2026, json.dumps({"shots": 0, "tackles": 0,
                                            "minutes": 0}),
             "2026-08-22", "JUA", "away", 3, "REG", "fotmob"),
            (4, "ligamx", 2026, json.dumps({"shots": 0, "tackles": 0,
                                            "minutes": 0}),
             "2026-08-02", "SAN", "home", 4, "REG", "fotmob"),
            (4, "ligamx", 2026, json.dumps({"shots": 2, "tackles": 3,
                                            "minutes": 90}),
             "2026-08-16", "ASL", "home", 5, "REG", "fotmob"),
            # The summary ingest signals the same thing with `appearances`.
            (5, "lcup", 2026, json.dumps({"shots": 0, "appearances": 0}),
             "2026-08-14", "ATX", "home", 6, "REG", "espn"),
            (5, "lcup", 2026, json.dumps({"shots": 4, "appearances": 1}),
             "2026-08-10", "POR", "away", 7, "REG", "espn"),
        ]
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = mock.patch.object(props, "_db", side_effect=connection)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_a_liga_mx_player_charts_his_tournament_games(self):
        result = props.prop_history(
            player_id=1, market="shots", line=1.5, side="over", league="lcup")
        self.assertEqual([g["value"] for g in result["games"]], [3.0, 6.0])
        self.assertEqual(result["hit_rate"]["season"], 1.0)

    def test_an_mls_player_keeps_his_domestic_season(self):
        result = props.prop_history(
            player_id=2, market="shots", line=0.5, side="over", league="lcup")
        # Three games, not the one tournament appearance.
        self.assertEqual(len(result["games"]), 3)
        self.assertEqual([g["value"] for g in result["games"]], [1.0, 2.0, 0.0])

    def test_a_compound_market_sums_the_published_fields(self):
        result = props.prop_history(
            player_id=1, market="goal_or_assist", line=0.5, side="over",
            league="lcup")
        self.assertEqual([g["value"] for g in result["games"]], [1.0, 1.0])

    def test_a_market_espn_does_not_publish_is_refused_not_drawn(self):
        # Corrected twice in one night, and the shrinking list is the point.
        #
        # First it held seven markets, on the measurement "ESPN publishes none
        # of them" -- which measured the SUMMARY endpoint. ESPN's CORE api
        # publishes five of them, so those became chartable.
        #
        # Then `dribbles` came off it too: ESPN has groundDuels and duelWinPct,
        # which are not take-ons, but FotMob publishes `dribbles_succeeded` per
        # appearance and ingest_fotmob_soccer_logs merges it in. "No source
        # publishes this" kept meaning "no source we had asked".
        #
        # first_goal_scorer is the only one left, and it is different in kind:
        # it is an ORDER market, and no per-game stat line answers it at any
        # depth from any provider.
        for market in ("first_goal_scorer",):
            result = props.prop_history(
                player_id=1, market=market, line=0.5, side="over", league="lcup")
            self.assertEqual(result["games"], [], market)
            self.assertIn("not chartable", result["error"], market)

    def test_a_deep_market_charts_when_the_row_carries_it(self):
        # Written by `ingest_soccer_logs --deep`. A shallow row simply lacks the
        # key and yields no games, rather than charting as a zero.
        result = props.prop_history(
            player_id=3, market="tackles", line=1.5, side="over", league="lcup")
        self.assertEqual([g["value"] for g in result["games"]], [3.0, 1.0])
        self.assertEqual(result["hit_rate"]["season"], 0.5)

    def test_a_shallow_row_is_absent_not_zero(self):
        result = props.prop_history(
            player_id=1, market="tackles", line=0.5, side="over", league="lcup")
        self.assertEqual(result["games"], [])


class AnAbsenceIsNotAZero(unittest.TestCase):
    """A match the player never entered must not chart as 0.

    2026-08-25: the lazy form read-through stores every match it reads,
    including bench appearances, and a bench player then charted five games as
    0/0/0/0/0 shots. Four of those were matches he did not play. Counting an
    absence as a measured performance drags every hit-rate window down and is
    indistinguishable afterwards from a genuine goalless game.
    """

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    setUp = LeaguesCupChartsAcrossTheSpines.setUp

    def test_minutes_zero_is_excluded(self):
        result = props.prop_history(
            player_id=4, market="shots", line=0.5, side="over", league="lcup")
        self.assertEqual([g["value"] for g in result["games"]], [2.0])
        self.assertEqual(result["hit_rate"]["season"], 1.0)

    def test_appearances_zero_is_excluded(self):
        result = props.prop_history(
            player_id=5, market="shots", line=0.5, side="over", league="lcup")
        self.assertEqual([g["value"] for g in result["games"]], [4.0])

    def test_a_row_carrying_neither_signal_is_kept(self):
        # The MLS fixtures in this file store neither key. Absence of a signal
        # is not evidence of absence from the match.
        result = props.prop_history(
            player_id=2, market="shots", line=0.5, side="over", league="lcup")
        self.assertEqual(len(result["games"]), 3)


class TheRowReachesTheChartLabelledByThePlayersLeague(unittest.TestCase):
    """/api/props returns pl.league, so a Leagues Cup prop arrives as `ligamx`.

    2026-08-25, reported from the dev board: Juan Dominguez (LEO) rendered
    "No history" with nothing to click, while MLS players on the same card
    charted normally. _MARKET_STAT_KEY had `mls` and `lcup` and no `ligamx` at
    all, so every Liga MX row answered "market not chartable".

    One competition's props reach this table under three labels -- lcup for the
    game, mls and ligamx for the athletes -- and all three must chart.
    """

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    setUp = LeaguesCupChartsAcrossTheSpines.setUp

    def test_a_ligamx_labelled_request_charts(self):
        result = props.prop_history(
            player_id=1, market="shots", line=1.5, side="over", league="ligamx")
        self.assertNotIn("error", result)
        self.assertEqual([g["value"] for g in result["games"]], [3.0, 6.0])

    def test_ligamx_reaches_the_tournament_rows_too(self):
        # His only logs ARE the tournament ones; scoping to `ligamx` alone
        # would chart nothing.
        result = props.prop_history(
            player_id=1, market="goal_or_assist", line=0.5, side="over",
            league="ligamx")
        self.assertEqual(len(result["games"]), 2)

    def test_the_three_labels_agree_on_a_deep_market(self):
        for label in ("lcup", "ligamx"):
            result = props.prop_history(
                player_id=3, market="tackles", line=1.5, side="over",
                league=label)
            self.assertEqual([g["value"] for g in result["games"]], [3.0, 1.0],
                             label)


class OneRowPerAppearance(unittest.TestCase):
    """Providers keep separate rows; the READER picks one.

    2026-08-25: FotMob stopped merging into the ESPN row, so a player with both
    charted the same match twice -- Federico Vinas showed 12 games,
    [7,7,4,4,3,3,1,1,1,1,1,1], for six he actually played. 1,901 appearances
    were double counted on prod.
    """

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="one-row-", suffix=".db",
                                             delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
              position TEXT
            );
            CREATE TABLE player_game_logs(
              player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
              game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER,
              game_type TEXT, source TEXT
            );
        """)
        con.execute("INSERT INTO players VALUES(1,'Both Providers','AME','ligamx','F')")
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                # The SAME appearance, from two providers, with different
                # numbers so the tie-break is observable.
                (1, "ligamx", 2026, json.dumps({"shots": 3, "minutes": 90}),
                 "2026-08-24", "TOL", "home", 1, "REG", "espn"),
                (1, "ligamx", 2026,
                 json.dumps({"shots": 9, "tackles": 4, "minutes": 90}),
                 "2026-08-24", "TOL", "home", 1, "REG", "fotmob"),
                # A second appearance only FotMob has.
                (1, "ligamx", 2026,
                 json.dumps({"shots": 2, "tackles": 1, "minutes": 90}),
                 "2026-08-17", "NCX", "away", 2, "REG", "fotmob"),
            ])
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        patch = mock.patch.object(props, "_db", side_effect=connection)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_match_both_providers_cover_is_charted_once(self):
        result = props.prop_history(
            player_id=1, market="shots", line=0.5, side="over", league="ligamx")
        self.assertEqual(len(result["games"]), 2, "one row per appearance")
        # ESPN wins the tie: it is the identity spine every player_id is keyed
        # on. 3, not 9.
        self.assertEqual([g["value"] for g in result["games"]], [3.0, 2.0])

    def test_a_market_only_one_provider_has_still_charts(self):
        # Rows without the stat are excluded by the WHERE, so the rank falls
        # through to FotMob rather than charting nothing.
        result = props.prop_history(
            player_id=1, market="tackles", line=0.5, side="over",
            league="ligamx")
        self.assertEqual([g["value"] for g in result["games"]], [4.0, 1.0])
