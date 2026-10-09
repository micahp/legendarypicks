import sqlite3
import unittest

import migrate_player_game_availability as mod


class PlayerGameAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(
            """
            CREATE TABLE nfl_snap_counts(
                player_id INTEGER, season INTEGER, week INTEGER, team TEXT,
                off_snaps INTEGER, off_pct REAL, def_snaps INTEGER,
                def_pct REAL, st_snaps INTEGER
            );
            CREATE TABLE injury_reports(
                league TEXT, season INTEGER, week INTEGER, team TEXT,
                player_id INTEGER, report_status TEXT
            );
            CREATE TABLE nfl_schedule(
                game_id TEXT, season INTEGER, week INTEGER,
                home_team TEXT, away_team TEXT,
                home_score INTEGER, away_score INTEGER
            );
            """
        )

    def tearDown(self):
        self.connection.close()

    def add_game(self, game_id, week, home="AAA", away="BBB", final=True):
        scores = (20, 17) if final else (None, None)
        self.connection.execute(
            "INSERT INTO nfl_schedule VALUES (?,2026,?,?,?,?,?)",
            (game_id, week, home, away, *scores),
        )

    def add_snap(self, player_id, week, team, off=0, defense=0, special=0):
        self.connection.execute(
            "INSERT INTO nfl_snap_counts VALUES (?,2026,?,?,?,NULL,?,NULL,?)",
            (player_id, week, team, off, defense, special),
        )

    def add_injury(self, player_id, week, team, status):
        self.connection.execute(
            "INSERT INTO injury_reports VALUES ('nfl',2026,?,?,?,?)",
            (week, team, player_id, status),
        )

    def rows(self):
        return self.connection.execute(
            "SELECT player_id,played,report_status,reason,source "
            "FROM player_game_availability ORDER BY player_id"
        ).fetchall()

    def test_migration_is_idempotent(self):
        mod.migrate(self.connection)
        mod.migrate(self.connection)
        columns = self.connection.execute(
            "PRAGMA table_info(player_game_availability)"
        ).fetchall()
        self.assertEqual(len(columns), 16)

    def test_final_complete_game_classifies_presence_and_absence(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=12)
        self.add_snap(2, 1, "AAA")
        self.add_snap(90, 1, "BBB", defense=4)
        self.add_injury(3, 1, "AAA", "Out")
        self.add_injury(4, 1, "AAA", "Questionable")
        self.add_injury(1, 1, "AAA", "Questionable")
        self.add_snap(5, 1, "AAA", special=2)
        self.add_injury(5, 1, "AAA", None)

        result = mod.build(self.connection)

        self.assertEqual(result["stored"], 6)
        self.assertEqual(self.rows(), [
            (1, 1, "Questionable", "played",
             "nflverse_snap_counts+nflverse_injuries"),
            (2, 0, None, "inactive_no_report", "nflverse_snap_counts"),
            (3, 0, "Out", "injury_out", "nflverse_injuries"),
            (4, 0, "Questionable", "inactive_no_report", "nflverse_injuries"),
            (5, 1, None, "played",
             "nflverse_snap_counts+nflverse_injuries"),
            (90, 1, None, "played", "nflverse_snap_counts"),
        ])

    def test_pregame_and_incomplete_snap_game_stay_unknown(self):
        self.add_game("future", 2, final=False)
        self.add_injury(1, 2, "AAA", "Out")
        self.add_game("partial", 3, final=True)
        self.add_snap(2, 3, "AAA")
        self.add_injury(3, 3, "AAA", "Out")

        mod.build(self.connection)

        self.assertEqual(self.rows(), [
            (1, None, "Out", "unknown", "nflverse_injuries"),
            (2, None, None, "unknown", "nflverse_snap_counts"),
            (3, None, "Out", "unknown", "nflverse_injuries"),
        ])

    def test_unresolved_injury_is_counted_and_not_invented(self):
        self.add_game("g1", 1)
        self.add_injury(None, 1, "AAA", "Out")

        result = mod.build(self.connection)

        self.assertEqual(result["unresolved_injury_rows"], 1)
        self.assertEqual(result["stored"], 0)

    def test_rebuild_exactly_replaces_owned_rows(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_snap(90, 1, "BBB", defense=1)
        mod.build(self.connection)
        self.connection.execute("DELETE FROM nfl_snap_counts WHERE player_id=1")

        mod.build(self.connection)

        self.assertEqual(self.rows(), [
            (90, 1, None, "played", "nflverse_snap_counts"),
        ])

    def test_cross_source_team_conflict_stays_on_separate_games(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_snap(90, 1, "BBB", defense=1)
        self.add_game("g2", 1, home="CCC", away="DDD")
        self.add_snap(91, 1, "CCC", defense=1)
        self.add_snap(92, 1, "DDD", defense=1)
        self.add_injury(1, 1, "CCC", "Out")

        result = mod.build(self.connection)

        self.assertEqual(result["team_conflicts"], 1)
        player_rows = self.connection.execute(
            "SELECT game_id,team,played,reason FROM player_game_availability "
            "WHERE player_id=1 ORDER BY game_id"
        ).fetchall()
        self.assertEqual(player_rows, [
            ("g1", "AAA", 1, "played"),
            ("g2", "CCC", 0, "injury_out"),
        ])

    def test_ambiguous_schedule_fails_before_replacing_rows(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_snap(90, 1, "BBB", defense=1)
        mod.build(self.connection)
        before = self.rows()
        self.add_game("g2", 1, home="AAA", away="CCC")

        with self.assertRaisesRegex(RuntimeError, "ambiguous schedule team-week"):
            mod.build(self.connection)
        self.assertEqual(self.rows(), before)


if __name__ == "__main__":
    unittest.main()
