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
            CREATE TABLE nfl_snap_team_sources(
                season INTEGER, week INTEGER, team TEXT,
                source_rows INTEGER, resolved_rows INTEGER, unresolved_rows INTEGER
            );
            CREATE TABLE player_game_logs(
                league TEXT, season INTEGER, game_no TEXT, player_id INTEGER,
                team TEXT, source TEXT, game_type TEXT
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

    def count_source(self, week, team, resolved=0, unresolved=0):
        updated = self.connection.execute(
            "UPDATE nfl_snap_team_sources SET source_rows=source_rows+?, "
            "resolved_rows=resolved_rows+?, unresolved_rows=unresolved_rows+? "
            "WHERE season=2026 AND week=? AND team=?",
            (resolved + unresolved, resolved, unresolved, week, team),
        ).rowcount
        if not updated:
            self.connection.execute(
                "INSERT INTO nfl_snap_team_sources VALUES (2026,?,?,?,?,?)",
                (week, team, resolved + unresolved, resolved, unresolved),
            )

    def add_snap(self, player_id, week, team, off=0, defense=0, special=0):
        self.connection.execute(
            "INSERT INTO nfl_snap_counts VALUES (?,2026,?,?,?,NULL,?,NULL,?)",
            (player_id, week, team, off, defense, special),
        )
        self.count_source(week, team, resolved=1)

    def add_unresolved_snap(self, week, team):
        self.count_source(week, team, unresolved=1)

    def add_log(self, player_id, week, team):
        self.connection.execute(
            "INSERT INTO player_game_logs VALUES ('nfl',2026,?,?,?,'nflverse_weekly','REG')",
            (week, player_id, team),
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

    def test_unresolved_snap_rows_block_completeness_for_both_teams(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_unresolved_snap(1, "AAA")
        self.add_snap(90, 1, "BBB", defense=1)
        self.add_unresolved_snap(1, "BBB")
        self.add_injury(3, 1, "AAA", "Out")
        self.add_injury(4, 1, "BBB", "Out")

        mod.build(self.connection)

        self.assertEqual([(r[0], r[1], r[3]) for r in self.rows()], [
            (1, 1, "played"),
            (3, None, "unknown"),
            (4, None, "unknown"),
            (90, 1, "played"),
        ])

    def test_unattributed_source_rows_block_every_game_in_the_season(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_snap(90, 1, "BBB", defense=1)
        self.connection.execute(
            "INSERT INTO nfl_snap_team_sources VALUES (2026,NULL,NULL,1,0,1)"
        )
        self.add_injury(3, 1, "AAA", "Out")

        mod.build(self.connection)

        self.assertEqual(self.rows()[1][1:4], (None, "Out", "unknown"))

    def test_log_only_player_game_is_unknown_not_absent(self):
        self.add_game("g1", 1)
        self.add_snap(1, 1, "AAA", off=1)
        self.add_snap(90, 1, "BBB", defense=1)
        self.add_log(7, 1, "AAA")

        result = mod.build(self.connection)

        self.assertEqual(result["stored"], 3)
        self.assertEqual(
            [r for r in self.rows() if r[0] == 7],
            [(7, None, None, "unknown", "nflverse_weekly_logs")],
        )

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


    def test_a_gap_between_two_snap_weeks_is_a_recorded_absence(self):
        for week in (1, 2, 4):
            self.add_game("g%d" % week, week)
        # week 3 is a bye for AAA: no schedule row, so nothing to record
        self.add_snap(1, 1, "AAA", off=30)
        self.add_snap(1, 4, "AAA", off=30)
        self.add_snap(2, 2, "AAA", off=30)    # another player keeps week 2 complete for the team
        self.add_snap(99, 1, "AAA", off=30)
        self.add_snap(99, 4, "AAA", off=30)
        for week in (1, 2, 4):
            self.add_snap(80, week, "BBB", off=30)   # the opponent's file, so each game is complete
        mod.build(self.connection)
        got = self.connection.execute(
            "SELECT week,played,reason,source FROM player_game_availability "
            "WHERE player_id=1 ORDER BY week").fetchall()
        self.assertEqual([(1, 1, "played", "nflverse_snap_counts"),
                          (2, 0, "inactive_no_report", "nflverse_snap_counts_bracketed"),
                          (4, 1, "played", "nflverse_snap_counts")], got)

    def test_a_gap_before_the_first_or_after_the_last_snap_stays_unknown(self):
        for week in (1, 2, 3):
            self.add_game("g%d" % week, week)
        self.add_snap(1, 2, "AAA", off=30)
        self.add_snap(2, 1, "AAA", off=30)
        self.add_snap(2, 3, "AAA", off=30)
        mod.build(self.connection)
        weeks = [w for (w,) in self.connection.execute(
            "SELECT week FROM player_game_availability WHERE player_id=1")]
        self.assertEqual([2], weeks)   # no row for weeks 1 and 3

    def test_a_bracketed_gap_in_an_incomplete_game_is_unknown_not_out(self):
        for week in (1, 2, 3):
            self.add_game("g%d" % week, week)
        self.add_snap(1, 1, "AAA", off=30)
        self.add_snap(1, 3, "AAA", off=30)
        self.add_snap(2, 2, "AAA", off=30)
        self.add_unresolved_snap(2, "AAA")      # an unmapped snap row in week 2: the file is not complete
        mod.build(self.connection)
        got = self.connection.execute(
            "SELECT played,reason FROM player_game_availability WHERE player_id=1 AND week=2").fetchall()
        self.assertEqual([(None, "unknown")], got)


if __name__ == "__main__":
    unittest.main()
