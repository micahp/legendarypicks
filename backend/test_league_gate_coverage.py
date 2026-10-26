"""NBA club alignment, scored-game standings, and roster freshness in the readiness gate; rosters and standings in the
feature matrix, where tennis and MMA are not applicable. Run: python3 -m pytest backend/test_league_gate_coverage.py
"""
import datetime as dt
import unittest

import league_feature_matrix
import league_readiness
from test_league_readiness import database

AS_OF = dt.date(2026, 10, 26)
PUBLISHED = "nba.com:division-standings"
HAND_ENTERED = "alignment: hand-entered six-division alignment, checked against nba_model_history 2026"


def nba_database(*, clubs=30, source=PUBLISHED, scored=43, unscored=0, roster_captured="2026-10-03T00:53:26+00:00"):
    con = database()
    con.executescript(
        """
        CREATE TABLE nba_teams(season INTEGER, team TEXT, team_name TEXT, conference TEXT,
                               division TEXT, source TEXT);
        CREATE TABLE nba_schedule(season INTEGER, season_type TEXT, game_id TEXT,
                                  home_score INTEGER, away_score INTEGER);
        """
    )
    con.executemany(
        "INSERT INTO nba_teams VALUES (?,?,?,?,?,?)",
        [(2027, f"T{i:02d}", f"Club {i}", "East" if i < clubs // 2 else "West", "Atlantic", source)
         for i in range(clubs)],
    )
    con.executemany(
        "INSERT INTO nba_schedule VALUES (2027, 'REG', ?, ?, ?)",
        [(f"g{i}", 101, 99) for i in range(scored)]
        + [(f"u{i}", None, None) for i in range(unscored)],
    )
    con.execute(
        "INSERT INTO roster_snapshots VALUES (NULL, 'nba', 2027, 'nba.com:team-roster', ?, 30, 620, 'published')",
        (roster_captured,),
    )
    con.commit()
    return con


def nba_gates(con):
    payload = league_readiness.build_readiness(con, AS_OF)
    return next(item for item in payload["leagues"] if item["league"] == "nba")


class NBAClubAlignment(unittest.TestCase):
    def test_a_published_division_source_with_thirty_clubs_is_available(self):
        check = nba_gates(nba_database())["checks"]["division_alignment"]
        self.assertEqual(check["status"], "available")
        self.assertEqual((check["clubs"], check["expected_clubs"]), (30, 30))

    def test_a_hand_entered_division_source_is_unverified_and_says_so(self):
        gates = nba_gates(nba_database(source=HAND_ENTERED))
        self.assertEqual(gates["checks"]["division_alignment"]["status"], "unverified")
        self.assertIn("hand-entered", " ".join(gates["reasons"]))

    def test_a_club_list_that_is_not_thirty_is_incomplete(self):
        gates = nba_gates(nba_database(clubs=29))
        self.assertEqual(gates["checks"]["division_alignment"]["status"], "incomplete")
        self.assertIn("lists 29 clubs", " ".join(gates["reasons"]))


class NBAStandingsFromScoredGames(unittest.TestCase):
    def test_scored_regular_season_games_make_standings_available(self):
        check = nba_gates(nba_database(scored=43))["checks"]["standings_games"]
        self.assertEqual((check["status"], check["count"], check["source"]), ("available", 43, "nba_schedule"))

    def test_no_scored_regular_season_game_is_missing_and_named_as_a_reason(self):
        gates = nba_gates(nba_database(scored=0, unscored=5))
        self.assertEqual(gates["checks"]["standings_games"]["status"], "missing")
        self.assertIn("standings cannot be derived", " ".join(gates["reasons"]))


class NBARosterFreshness(unittest.TestCase):
    def test_a_roster_captured_before_the_window_is_stale_with_its_age(self):
        check = nba_gates(nba_database(roster_captured="2026-10-03T00:53:26+00:00"))["checks"]["roster_snapshot"]
        self.assertEqual(check["status"], "stale")
        self.assertEqual(check["stale_after_days"], 7)
        self.assertIn("maximum is 7", check["reason"])

    def test_a_roster_captured_inside_the_window_is_ready(self):
        check = nba_gates(nba_database(roster_captured="2026-10-24T12:00:00+00:00"))["checks"]["roster_snapshot"]
        self.assertEqual(check["status"], "ready")


class NotApplicableLeagues(unittest.TestCase):
    def test_tennis_and_mma_have_no_club_or_standings_gap(self):
        con = database()
        tables = league_readiness._tables(con)
        for league in ("atp", "wta", "ufc"):
            self.assertEqual(league_readiness._alignment_check(con, tables, league, 2026)["status"],
                             "not_applicable", league)
            self.assertEqual(league_readiness._standings_games_check(con, tables, league, 2026, "regular_season")["status"],
                             "not_applicable", league)
        for league in ("atp", "wta", "ufc"):
            self.assertEqual(league_feature_matrix.mark("rosters", league, 0), "n/a", league)
            self.assertEqual(league_feature_matrix.mark("standings", league, 0), "n/a", league)

    def test_an_nba_league_with_no_stored_standings_reads_as_a_dash_not_as_not_applicable(self):
        self.assertEqual(league_feature_matrix.mark("standings", "nba", 0), "--")
        self.assertEqual(league_feature_matrix.mark("rosters", "nba", 4), "4")
        self.assertIn("live ESPN standings", league_feature_matrix.UNPROBED)


if __name__ == "__main__":
    unittest.main()
