import json
import sqlite3
import unittest

import player_splits as mod


class Splits(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE player_game_logs (player_id INTEGER, league TEXT, season INTEGER,
                game_no TEXT, game_id TEXT, game_type TEXT, team TEXT, stats TEXT, source TEXT);
            CREATE TABLE player_game_shares (league TEXT, season INTEGER, week INTEGER,
                game_id TEXT, team TEXT, player_id INTEGER, metric TEXT, share REAL,
                player_value REAL, team_value REAL, source TEXT, built_at TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER,
                game_type TEXT, home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER);
            CREATE TABLE player_game_availability (league TEXT, season INTEGER, week INTEGER,
                game_id TEXT, team TEXT, player_id INTEGER, played INTEGER, reason TEXT,
                PRIMARY KEY (league, game_id, team, player_id));
        """)

    def play(self, pid, week, team="NO", game_type="REG", **stats):
        gid = "2025_%02d_%s_X" % (week, team)
        self.con.execute("INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?,?,?)",
                         (pid, "nfl", 2025, str(week), gid, game_type, team,
                          json.dumps(stats), "nflverse_weekly"))
        return gid

    def avail(self, pid, week, played, team="NO"):
        self.con.execute("INSERT INTO player_game_availability VALUES (?,?,?,?,?,?,?,?)",
                         ("nfl", 2025, week, "2025_%02d_%s_X" % (week, team), team, pid,
                          played, "played" if played else "injury_out" if played == 0 else "unknown"))

    def test_without_splits_games_by_teammate_out(self):
        for week in (1, 2, 3):
            self.play(1, week, targets=6)
        self.avail(2, 1, 0)
        self.avail(2, 2, 1)
        self.avail(2, 3, 0)
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual([1, 3], [r["week"] for r in res["matched"]])
        self.assertEqual([2], [r["week"] for r in res["not_matched"]])
        self.assertEqual(0, res["excluded_unknown"])

    def test_unknown_teammate_is_excluded_and_counted_not_matched(self):
        self.play(1, 1, targets=6)
        self.play(1, 2, targets=4)
        self.avail(2, 1, None)
        self.avail(2, 2, 1)
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual(([], [2], 1), ([r["week"] for r in res["matched"]],
                                        [r["week"] for r in res["not_matched"]],
                                        res["excluded_unknown"]))
        self.play(1, 3, targets=2)
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual(2, res["excluded_unknown"])

    def test_missing_availability_row_is_unknown(self):
        self.play(1, 1, targets=6)
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual((0, 0, 1), (len(res["matched"]), len(res["not_matched"]),
                                     res["excluded_unknown"]))

    def test_with_requires_the_teammate_to_play(self):
        self.play(1, 1, targets=6)
        self.play(1, 2, targets=3)
        self.avail(2, 1, 1)
        self.avail(2, 2, 0)
        res = mod.splits(self.con, 1, with_=[2])
        self.assertEqual([1], [r["week"] for r in res["matched"]])
        self.assertEqual([2], [r["week"] for r in res["not_matched"]])

    def test_known_contradiction_wins_over_an_unknown_teammate(self):
        self.play(1, 1, targets=6)
        self.avail(2, 1, 1)
        res = mod.splits(self.con, 1, without=[2, 3])
        self.assertEqual(([], [1], 0), ([], [r["week"] for r in res["not_matched"]],
                                        res["excluded_unknown"]))

    def test_games_for_a_team_the_teammate_never_wore_are_not_teammate_games(self):
        self.play(1, 1, team="NO", targets=6)
        self.play(1, 2, team="SEA", targets=4)
        self.avail(2, 1, 0, team="NO")
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual([1], [r["week"] for r in res["matched"]])
        self.assertEqual(([], 1), (res["not_matched"], res["excluded_not_teammate"]))

    def test_postseason_games_are_left_out(self):
        self.play(1, 1, targets=6)
        self.play(1, 19, game_type="POST", targets=9)
        res = mod.splits(self.con, 1, without=[])
        self.assertEqual(1, len(res["matched"]))

    def schedule(self, week, team="NO", final=True):
        gid = "2025_%02d_%s_X" % (week, team)
        scores = (20, 17) if final else (None, None)
        self.con.execute("INSERT INTO nfl_schedule VALUES (?,2025,?,'REG',?,'XXX',?,?)",
                         (gid, week, team, *scores))
        return gid

    def test_scheduled_game_without_a_box_score_is_unknown_not_dropped(self):
        self.play(1, 1, targets=6)
        self.schedule(1)
        self.schedule(2)
        self.avail(1, 2, None)
        self.schedule(3)
        self.avail(1, 3, 0)
        self.schedule(4, final=False)
        res = mod.splits(self.con, 1, without=[])
        self.assertEqual((1, 1), (len(res["matched"]), res["excluded_unknown"]))

    def test_per_game_shares_ride_along(self):
        gid = self.play(1, 1, targets=6)
        self.con.execute("INSERT INTO player_game_shares VALUES "
                         "('nfl',2025,1,?,'NO',1,'targets',0.5,6,12,'nflverse_weekly','t')", (gid,))
        self.avail(2, 1, 0)
        res = mod.splits(self.con, 1, without=[2])
        self.assertEqual(0.5, res["matched"][0]["shares"]["targets"])


if __name__ == "__main__":
    unittest.main()
