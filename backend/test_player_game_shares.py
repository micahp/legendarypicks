import json
import sqlite3
import unittest

import build_player_game_shares as mod
import build_player_shares
from migrate_player_game_shares import migrate

NOW = "2026-10-09T00:00:00+00:00"


def team_row(season, week, team, game_id, carries, targets, air, season_type="REG"):
    return {"season": season, "week": week, "team": team, "season_type": season_type,
            "game_id": game_id, "carries": carries, "targets": targets,
            "receiving_air_yards": air}


class Totals(unittest.TestCase):
    def test_vocabulary_maps_published_codes_once(self):
        totals = mod.totals_from_rows(
            [team_row(2026, 1, "LA", "2026_01_LA_SF", 20, 30, 200),
             team_row(2026, 1, "WAS", "2026_01_WAS_NYG", 18, 28, 190)], 2026)
        self.assertIn(("2026_01_LA_SF", "LAR"), totals)
        self.assertIn(("2026_01_WAS_NYG", "WSH"), totals)
        self.assertEqual(1, totals[("2026_01_LA_SF", "LAR")]["week"])

    def test_postseason_and_other_seasons_are_left_out(self):
        totals = mod.totals_from_rows(
            [team_row(2026, 1, "NO", "2026_01_NO_TB", 20, 30, 200),
             team_row(2026, 19, "NO", "2026_19_NO_PHI", 20, 30, 200, season_type="POST"),
             team_row(2025, 1, "NO", "2025_01_NO_TB", 20, 30, 200)], 2026)
        self.assertEqual([("2026_01_NO_TB", "NO")], list(totals))

    def test_null_published_total_raises(self):
        with self.assertRaises(RuntimeError):
            mod.totals_from_rows([team_row(2026, 1, "NO", "2026_01_NO_TB", None, 30, 200)], 2026)


class GameRows(unittest.TestCase):
    def setUp(self):
        self.totals = mod.totals_from_rows(
            [team_row(2026, 1, "NO", "2026_01_NO_TB", 20, 40, 200)], 2026)

    def log(self, player_id, team="NO", game_id="2026_01_NO_TB", **stats):
        return (player_id, team, game_id, json.dumps(stats))

    def test_targets_and_air_yards_are_copied_and_validated(self):
        rows, report = mod.build_game_rows(
            [self.log(1, targets=10, target_share=0.25, rec_air_yds=50,
                      air_yards_share=0.25)], self.totals, 2026, NOW)
        by_metric = {r[6]: r for r in rows}
        self.assertEqual(0.25, by_metric["targets"][7])
        self.assertEqual(0.25, by_metric["air_yards"][7])
        self.assertEqual("nflverse_weekly", by_metric["targets"][10])
        self.assertEqual(2, report["metrics"]["targets"]["copied"] +
                         report["metrics"]["air_yards"]["copied"])

    def test_published_share_that_disagrees_with_our_count_raises(self):
        with self.assertRaises(RuntimeError):
            mod.build_game_rows([self.log(1, targets=10, target_share=0.5)],
                                self.totals, 2026, NOW)

    def test_carry_share_is_derived_from_published_team_carries(self):
        rows, _ = mod.build_game_rows([self.log(1, carries=5)], self.totals, 2026, NOW)
        carries = [r for r in rows if r[6] == "carries"][0]
        self.assertEqual(0.25, carries[7])
        self.assertEqual("derived_carries", carries[10])

    def test_team_game_missing_from_publisher_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            mod.build_game_rows([self.log(1, team="ATL", game_id="2026_01_ATL_X", carries=3)],
                                self.totals, 2026, NOW)

    def test_null_player_id_counts_in_team_total_but_writes_no_row(self):
        rows, report = mod.build_game_rows([self.log(None, carries=5)], self.totals, 2026, NOW)
        self.assertEqual([], rows)
        self.assertEqual((1, 1), (report["joined"], report["no_player"]))


class SeasonRows(unittest.TestCase):
    def test_season_share_is_a_sum_ratio_not_an_average_of_weeks(self):
        totals = mod.totals_from_rows(
            [team_row(2026, 1, "NO", "2026_01_NO_TB", 20, 10, 100),
             team_row(2026, 2, "NO", "2026_02_NO_CAR", 20, 30, 100)], 2026)
        logs = [(1, "NO", "2026_01_NO_TB", json.dumps({"targets": 9, "target_share": 0.9})),
                (1, "NO", "2026_02_NO_CAR", json.dumps({"targets": 1, "target_share": 1 / 30}))]
        game_rows, _ = mod.build_game_rows(logs, totals, 2026, NOW)
        out = {r[4]: r for r in mod.season_rows(game_rows, totals, 2026, NOW)
               if r[2] == "NO"}
        row = out["targets"]
        self.assertEqual((10, 40), (row[5], row[6]))
        self.assertAlmostEqual(0.25, row[7])
        self.assertEqual((2, 2), (row[8], row[9]))


class Writes(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE player_game_logs (player_id INTEGER, league TEXT, season INTEGER,
                game_no TEXT, game_id TEXT, game_type TEXT, team TEXT, stats TEXT, source TEXT);
            CREATE TABLE player_team_shares (league TEXT, season INTEGER, team TEXT,
                player_id INTEGER, metric TEXT, player_value REAL, team_value REAL,
                share REAL, games INTEGER, team_games INTEGER, through TEXT, source TEXT,
                computed_at TEXT, PRIMARY KEY (league, season, team, player_id, metric));
        """)
        migrate(self.con)
        totals = mod.totals_from_rows(
            [team_row(2026, 1, "NO", "2026_01_NO_TB", 20, 40, 200)], 2026)
        logs = [(1, "NO", "2026_01_NO_TB", json.dumps({"targets": 10, "target_share": 0.25,
                                                        "carries": 5, "rec_td": 2}))]
        self.game_rows, _ = mod.build_game_rows(logs, totals, 2026, NOW)
        self.totals = totals
        self.season = mod.season_rows(self.game_rows, totals, 2026, NOW)

    def test_write_is_idempotent(self):
        meta = ("", "abc", 0, NOW)
        for _ in range(2):
            mod.write(self.con, 2026, self.totals, meta, self.game_rows, self.season)
        self.assertEqual(2, self.con.execute("SELECT COUNT(*) FROM player_game_shares").fetchone()[0])
        self.assertEqual(1, self.con.execute("SELECT COUNT(*) FROM nfl_team_game_totals").fetchone()[0])

    def test_touchdown_builder_keeps_per_game_metrics(self):
        mod.write(self.con, 2026, self.totals, ("", "abc", 0, NOW), self.game_rows, self.season)
        build_player_shares.write(self.con, "nfl", 2026,
                                  [("nfl", 2026, "NO", 1, "rec_td", 2, 2, 1.0, 1, 1, "1",
                                    "nflverse_weekly", NOW)])
        metrics = {r[0] for r in self.con.execute(
            "SELECT metric FROM player_team_shares WHERE league='nfl' AND season=2026")}
        self.assertEqual({"targets", "carries", "rec_td"}, metrics)


if __name__ == "__main__":
    unittest.main()
