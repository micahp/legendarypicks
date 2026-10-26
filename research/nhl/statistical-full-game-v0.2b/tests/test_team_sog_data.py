"""Read-only tests for cutoff-valid team-game SOG inputs."""

import datetime as dt
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nhl_game_state_sim as sim


class TeamGameSogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "nhl.db"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE team_game_results(
                league TEXT, game_id TEXT, team TEXT, game_date TEXT, opponent TEXT,
                season INTEGER, ingested_at TEXT, status TEXT, source TEXT,
                PRIMARY KEY(league,game_id,team));
            CREATE TABLE team_game_stats(
                league TEXT, game_id TEXT, team_abbrev TEXT, captured_at TEXT,
                shots INTEGER, source TEXT,
                PRIMARY KEY(league,game_id,team_abbrev));
            CREATE TABLE team_stats_coverage(league TEXT,season INTEGER,source TEXT);
        """)
        self._add_game(con, "g1", "2025-10-10", 2026, 30, 20,
                       "espn_site_api:scoreboard+summary")
        self._add_game(con, "g2", "2026-04-20", 2026, 40, 25,
                       "espn_site_api:scoreboard+summary")
        self._add_game(con, "g3", "2026-10-13", 2027, 32, 22,
                       "nhle.com:gamecenter/right-rail+landing")
        # A same-day result is excluded even though its records were captured early.
        self._add_game(con, "same-day", "2026-10-25", 2027, 60, 10,
                       "nhle.com:gamecenter/right-rail+landing")
        # A prior-date result ingested after cutoff is also excluded.
        self._add_game(con, "late-ingest", "2026-10-20", 2027, 70, 5,
                       "nhle.com:gamecenter/right-rail+landing",
                       ingested_at="2026-10-26T00:00:01Z")
        # Prod can have a null row-level source and retain provenance at season level.
        self._add_game(con, "coverage-source", "2026-10-14", 2027, 34, 24,
                       None)
        con.execute("INSERT INTO team_stats_coverage VALUES('nhl',2027,'reconcile_totals+espn_core_api')")
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _add_game(con, game_id, date, season, a_shots, b_shots, source,
                  ingested_at="2026-10-15T00:00:00Z"):
        for team, opponent, shots in (("AAA", "BBB", a_shots), ("BBB", "AAA", b_shots)):
            con.execute(
                "INSERT INTO team_game_results VALUES('nhl',?,?,?,?,?,?,?,?)",
                (game_id, team, date, opponent, season, ingested_at, "completed", source),
            )
            con.execute(
                "INSERT INTO team_game_stats VALUES('nhl',?,?,?,?,?)",
                (game_id, team, "2026-10-15T00:00:00Z", shots, source),
            )

    def test_nhl_database_season_uses_ending_year_key(self):
        self.assertEqual(sim._nhl_db_season_key("2026-10-25"), 2027)
        self.assertEqual(sim._nhl_db_season_key("2027-03-10"), 2027)
        self.assertEqual(sim._nhl_db_season_key("2027-09-28"), 2028)

    def test_rates_use_reciprocal_native_ids_and_strict_cutoffs(self):
        cutoff = dt.datetime.fromisoformat("2026-10-25T23:25:19+00:00")
        result = sim.load_team_game_sog_rates(
            self.db, ("AAA", "BBB"), "2026-10-25", cutoff)
        self.assertEqual(result["eligible_season_keys"], [2026, 2027])
        a = result["team_rates"]["AAA"]
        b = result["team_rates"]["BBB"]
        self.assertEqual(a["games"], 4)
        self.assertEqual(b["games"], 4)
        self.assertAlmostEqual(a["shots_for_per_game"], 34.0)
        self.assertAlmostEqual(a["shots_against_per_game"], 22.75)
        self.assertAlmostEqual(b["shots_for_per_game"], 22.75)
        self.assertAlmostEqual(b["shots_against_per_game"], 34.0)
        self.assertEqual(a["games_by_nhl_db_season_key"], {2026: 2, 2027: 2})
        self.assertIn("reconcile_totals+espn_core_api", a["source_counts"])
        self.assertTrue(result["filters"]["reciprocal_teams_on_same_native_game_id"])

        # The helper opened SQLite read-only; neither excluded row was changed or removed.
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM team_game_results").fetchone()[0], 12)
        con.close()

    def test_missing_eligible_population_fails_closed(self):
        cutoff = dt.datetime.fromisoformat("2026-10-25T23:25:19+00:00")
        with self.assertRaisesRegex(ValueError, "no paired, source-eligible"):
            sim.load_team_game_sog_rates(self.db, ("AAA", "CCC"), "2026-10-25", cutoff)


if __name__ == "__main__":
    unittest.main()
