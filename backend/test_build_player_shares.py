import json
import sqlite3
import unittest

import build_player_shares as mod


class NflShares(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute(
            "CREATE TABLE player_game_logs (player_id INTEGER, league TEXT, season INTEGER, "
            "game_no TEXT, game_id TEXT, game_type TEXT, team TEXT, stats TEXT, source TEXT)")

    def log(self, pid, team, week, game_type="REG", **stats):
        self.con.execute("INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?,?,?)",
                         (pid, "nfl", 2026, str(week), "g%s%s" % (team, week), game_type,
                          team, json.dumps(stats), "nflverse_weekly"))

    def shares(self):
        return {(r[2], r[3], r[4]): r for r in mod.nfl_shares(self.con, 2026)}

    def test_season_share_is_a_sum_ratio_not_an_average_of_weeks(self):
        # week 1: A 9 of 10 targets; week 2: A 1 of 30. Averaging weeks says 48%.
        self.log(1, "NO", 1, targets=9)
        self.log(2, "NO", 1, targets=1)
        self.log(1, "NO", 2, targets=1)
        self.log(2, "NO", 2, targets=29)
        row = self.shares()[("NO", 1, "targets")]
        self.assertEqual((10, 40), (row[5], row[6]))
        self.assertAlmostEqual(0.25, row[7])

    def test_traded_player_gets_one_row_per_team(self):
        self.log(1, "NO", 1, targets=5)
        self.log(1, "ATL", 2, targets=3)
        s = self.shares()
        self.assertEqual(5, s[("NO", 1, "targets")][5])
        self.assertEqual(3, s[("ATL", 1, "targets")][5])

    def test_unresolved_players_count_in_the_team_total_only(self):
        self.log(1, "NO", 1, targets=2)
        self.log(None, "NO", 1, targets=2)
        row = self.shares()[("NO", 1, "targets")]
        self.assertAlmostEqual(0.5, row[7])

    def test_postseason_and_zero_values_are_left_out(self):
        self.log(1, "NO", 1, targets=4, carries=0)
        self.log(1, "NO", 19, game_type="POST", targets=10)
        s = self.shares()
        self.assertEqual(4, s[("NO", 1, "targets")][5])
        self.assertNotIn(("NO", 1, "carries"), s)

    def test_scrimmage_td_adds_receiving_and_rushing(self):
        self.log(1, "NO", 1, rec_td=1, rush_td=1)
        self.log(2, "NO", 1, rec_td=2)
        row = self.shares()[("NO", 1, "scrimmage_td")]
        self.assertEqual((2, 4), (row[5], row[6]))


if __name__ == "__main__":
    unittest.main()
