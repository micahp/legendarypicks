import sqlite3
import unittest

import league_feature_matrix as subject


class FeatureMatrixYearTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript(
            """
            CREATE TABLE player_game_logs(league TEXT, season INTEGER);
            CREATE TABLE player_stats(league TEXT, season INTEGER);
            CREATE TABLE team_game_results(league TEXT, game_id TEXT, season INTEGER);
            CREATE TABLE team_game_stats(league TEXT, game_id TEXT);
            INSERT INTO player_game_logs VALUES
                ('mls', 2026), ('mls', 2025), ('mls', 2026), ('mls', NULL);
            INSERT INTO player_stats VALUES ('mls', 2025), ('mls', 2026);
            INSERT INTO team_game_results VALUES
                ('mls', 'g1', 2025), ('mls', 'g2', 2026), ('mls', 'g3', NULL);
            INSERT INTO team_game_stats VALUES
                ('mls', 'g1'), ('mls', 'g2'), ('mls', 'g3'), ('mls', 'missing');
            """
        )
        self.tables = subject._tables(self.connection)

    def test_explicit_years_are_a_set_and_null_rows_stay_visible(self):
        result = subject._years(
            self.connection, "player game logs", "mls", self.tables
        )
        self.assertEqual(result["years"], (2025, 2026))
        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(subject._format_years(result), "2025,2026 +1?")

    def test_team_stats_derive_only_from_same_game_result(self):
        result = subject._years(self.connection, "team stats", "mls", self.tables)
        self.assertEqual(result["years"], (2025, 2026))
        self.assertEqual(result["unassigned"], 2)
        self.assertEqual(result["basis"], "result join")

    def test_missing_table_is_unavailable_not_empty(self):
        self.connection.execute("DROP TABLE player_stats")
        result = subject._years(
            self.connection, "player stats", "mls", subject._tables(self.connection)
        )
        self.assertIsNone(result)
        self.assertEqual(subject._format_years(result), "n/a")


if __name__ == "__main__":
    unittest.main()
