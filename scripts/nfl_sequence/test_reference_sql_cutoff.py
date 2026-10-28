import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402

CUTOFF = (2024, 8)


class BoundaryRule(unittest.TestCase):
    def test_the_cutoff_week_itself_is_excluded_and_the_week_before_is_kept(self):
        self.assertTrue(mk.before_cutoff(2024, 7, CUTOFF))
        self.assertFalse(mk.before_cutoff(2024, 8, CUTOFF))
        self.assertFalse(mk.before_cutoff(2025, 1, CUTOFF))
        self.assertTrue(mk.before_cutoff(2023, 18, CUTOFF))

    def test_no_cutoff_keeps_everything(self):
        self.assertTrue(mk.before_cutoff(2026, 1, None))

    def test_the_reference_loader_uses_the_same_rule(self):
        self.assertIs(er._before_cutoff, mk.before_cutoff)


class PositionUsageCutoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'pbp.sqlite3')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE nfl_pbp (season INTEGER, week INTEGER, play_type TEXT, rusher_player_id TEXT, '
                    'receiver_player_id TEXT)')
        con.execute('CREATE TABLE players (nfl_gsis_id TEXT, position TEXT, league TEXT)')
        con.execute("INSERT INTO players VALUES ('R1', 'RB', 'nfl')")
        con.execute("INSERT INTO players VALUES ('W1', 'WR', 'nfl')")
        for week in (5, 9):
            con.execute("INSERT INTO nfl_pbp VALUES (2024, ?, 'run', 'R1', NULL)", (week,))
            con.execute("INSERT INTO nfl_pbp VALUES (2024, ?, 'pass', NULL, 'W1')", (week,))
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_plays_at_or_after_the_cutoff_are_not_counted(self):
        full = er.load_position_usage(self.db)
        cut = er.load_position_usage(self.db, eligible_before=CUTOFF)
        self.assertNotEqual(full, cut)
        self.assertEqual(full, er.load_position_usage(self.db, eligible_before=None))


class MissedFieldGoalCutoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'pbp.sqlite3')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE nfl_pbp (game_id TEXT, play_id INTEGER, season INTEGER, week INTEGER, qtr INTEGER, '
                    'drive INTEGER, posteam TEXT, defteam TEXT, play_type TEXT, series_result TEXT, '
                    'yardline_100 REAL)')
        for game, season, week in (('2024_05_AAA_BBB', 2024, 5), ('2025_01_AAA_BBB', 2025, 1)):
            con.execute('INSERT INTO nfl_pbp VALUES (?, 1, ?, ?, 2, 4, ?, ?, ?, ?, 40)',
                        (game, season, week, 'AAA', 'BBB', 'field_goal', 'Missed field goal'))
            con.execute('INSERT INTO nfl_pbp VALUES (?, 2, ?, ?, 2, 5, ?, ?, ?, NULL, 30)',
                        (game, season, week, 'BBB', 'AAA', 'run'))
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_miss_at_or_after_the_cutoff_is_not_in_the_pool(self):
        def total(pools):
            return sum(len(v) for v in pools.values())
        self.assertEqual(total(er.load_missed_field_goal_pool(self.db)), 2)
        self.assertEqual(total(er.load_missed_field_goal_pool(self.db, eligible_before=CUTOFF)), 1)


if __name__ == '__main__':
    unittest.main()
