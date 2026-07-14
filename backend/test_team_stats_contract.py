#!/usr/bin/env python3
"""Fixture-backed tests for team-stat extraction and coverage gates."""
import json
import os
import sqlite3
import unittest

from team_stats_contract import build_team_aggregates, extract_espn_team_stats


HERE = os.path.dirname(os.path.abspath(__file__))


def create_contract_schema(connection):
    connection.executescript("""
        CREATE TABLE team_game_results(
          league TEXT, game_id TEXT, team TEXT, game_date TEXT, opponent TEXT,
          score_for REAL, score_against REAL, win INTEGER);
        CREATE TABLE team_game_stats(
          league TEXT, game_id TEXT, captured_at TEXT, team_abbrev TEXT, home_away TEXT,
          fgm_fga TEXT, tpm_tpa TEXT, ftm_fta TEXT, rebounds INTEGER,
          off_rebounds INTEGER, def_rebounds INTEGER, assists INTEGER,
          steals INTEGER, blocks INTEGER, turnovers INTEGER,
          first_downs INTEGER, total_offensive_plays INTEGER, total_yards INTEGER,
          net_passing_yards INTEGER, rushing_yards INTEGER,
          defensive_special_teams_tds INTEGER);
        CREATE TABLE team_stats_coverage(
          league TEXT, season INTEGER, season_start TEXT, season_end TEXT,
          status TEXT, expected_teams INTEGER, fetched_teams INTEGER,
          expected_games INTEGER, fetched_games INTEGER, source TEXT,
          completed_at TEXT);
    """)


class TeamStatsContractTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        create_contract_schema(self.connection)

    def tearDown(self):
        self.connection.close()

    def populate_nba(self, *, complete_manifest=True, null_metric=False):
        teams = [f"N{index:02d}" for index in range(30)]
        for index in range(0, 30, 2):
            game_id = f"nba-{index}"
            first, second = teams[index:index + 2]
            game_date = "2025-11-01" if index < 16 else "2026-04-01"
            self.connection.executemany(
                "INSERT INTO team_game_results VALUES(?,?,?,?,?,?,?,?)",
                [
                    ("nba", game_id, first, game_date, second, 110, 100, 1),
                    ("nba", game_id, second, game_date, first, 100, 110, 0),
                ],
            )
            for team, side in ((first, "home"), (second, "away")):
                assists = None if null_metric and team == "N00" else 25
                self.connection.execute(
                    "INSERT INTO team_game_stats(league,game_id,captured_at,team_abbrev,home_away,"
                    "fgm_fga,tpm_tpa,ftm_fta,rebounds,off_rebounds,def_rebounds,assists,steals,blocks,turnovers) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("nba", game_id, "2026-04-02T00:00:00Z", team, side,
                     "40-80", "10-30", "20-25", 45, 10, 35, assists, 8, 5, 12),
                )
        if complete_manifest:
            self.connection.execute(
                "INSERT INTO team_stats_coverage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("nba", 2026, "2025-10-01", "2026-06-30", "complete", 30, 30, 15, 15,
                 "espn_team_schedules+espn_boxscores", "2026-04-02T01:00:00Z"),
            )

    def test_cross_year_nba_manifest_returns_the_complete_season(self):
        self.populate_nba()

        response = build_team_aggregates(self.connection, "nba")

        self.assertTrue(response["supported"])
        self.assertEqual(response["coverage"]["paired_games"], 15)
        self.assertEqual(response["coverage"]["paired_stat_games"], 15)
        self.assertEqual(response["coverage"]["first_game_date"], "2025-11-01")
        self.assertEqual(response["coverage"]["last_game_date"], "2026-04-01")
        self.assertEqual(response["coverage"]["season_start"], "2025-10-01")
        self.assertEqual(response["coverage"]["season_end"], "2026-06-30")
        self.assertTrue(response["coverage"]["external_schedule_reconciled"])
        self.assertEqual(len(response["teams"]), 30)
        leader = next(row for row in response["teams"] if row["team"] == "N00")
        self.assertEqual(leader["points_per_game"], 110)
        self.assertEqual(leader["fg_pct"], 0.5)
        self.assertEqual(leader["assist_turnover_ratio"], 2.083)

    def test_manifest_is_required_even_when_rows_look_complete(self):
        self.populate_nba(complete_manifest=False)

        response = build_team_aggregates(self.connection, "nba")

        self.assertFalse(response["supported"])
        self.assertEqual(response["reason"], "season_bounds_unavailable")
        self.assertFalse(response["coverage"]["external_schedule_reconciled"])
        self.assertEqual(response["teams"], [])

    def test_null_required_stat_fails_closed(self):
        self.populate_nba(null_metric=True)

        response = build_team_aggregates(self.connection, "nba")

        self.assertFalse(response["supported"])
        self.assertEqual(response["reason"], "incomplete_stat_fields")
        self.assertEqual(response["coverage"]["invalid_stat_rows"], 1)

    def test_nonreciprocal_stat_sides_fail_closed(self):
        self.populate_nba()
        self.connection.execute(
            "UPDATE team_game_stats SET home_away='home' "
            "WHERE game_id='nba-0' AND team_abbrev='N01'"
        )

        response = build_team_aggregates(self.connection, "nba")

        self.assertFalse(response["supported"])
        self.assertEqual(response["reason"], "invalid_stat_pairs")
        self.assertEqual(response["coverage"]["invalid_stat_games"], 1)

    def test_nfl_fixture_uses_official_summary_field_names(self):
        fixture_path = os.path.join(HERE, "fixtures", "espn_nfl_summary_401772830.json")
        with open(fixture_path, encoding="utf-8") as fixture:
            rows = extract_espn_team_stats("nfl", json.load(fixture))

        self.assertEqual([row["team_abbrev"] for row in rows], ["TB", "ATL"])
        self.assertEqual(rows[0]["home_away"], "away")
        self.assertEqual(rows[0]["stats"]["total_yards"], 260)
        self.assertEqual(rows[0]["stats"]["net_passing_yards"], 159)
        self.assertEqual(rows[1]["stats"]["rushing_yards"], 69)
        self.assertEqual(rows[1]["stats"]["defensive_special_teams_tds"], 0)

    def test_espn_percentage_display_value_is_normalized(self):
        summary = {
            "boxscore": {"teams": [{
                "team": {"abbreviation": "TOR"}, "homeAway": "home",
                "statistics": [{"name": "faceoffPercent", "displayValue": "52.8%"}],
            }]},
        }

        rows = extract_espn_team_stats("nhl", summary)

        self.assertEqual(rows[0]["stats"]["faceoff_pct"], 52.8)


if __name__ == "__main__":
    unittest.main()
