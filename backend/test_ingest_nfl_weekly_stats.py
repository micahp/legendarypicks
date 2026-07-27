"""Tests for the nflverse weekly box-score ingest.

No network: each source artifact is a small synthetic parquet file, and writes
go to a throwaway SQLite database.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nfl_weekly_stats as mod


def _artifact_row(**overrides):
    row = {
        "player_id": "00-0000001",
        "player_display_name": "Quarterback One",
        "position": "QB",
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "game_id": "2025_01_ARI_SEA",
        "team": "SEA",
        "opponent_team": "ARI",
        "attempts": 3,
        "completions": 2,
        "passing_yards": 25,
        "passing_tds": 0,
        "passing_interceptions": 0,
        "passing_air_yards": 18,
        "passing_epa": 0.6254,
        "passing_cpoe": None,
        "sacks_suffered": 1,
        "carries": 0,
        "rushing_yards": 0,
        "rushing_tds": 0,
        "targets": 0,
        "target_share": 0.0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
        "fantasy_points": 1,
        "fantasy_points_ppr": 1,
        "passing_2pt_conversions": 0,
        "rushing_2pt_conversions": 0,
        "receiving_2pt_conversions": 0,
    }
    row.update(overrides)
    return row


def _write_artifact(path, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(rows), path)


class BuildRowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "stats.parquet")

    def tearDown(self):
        self.tmp.cleanup()

    def test_num_distinguishes_null_from_zero(self):
        self.assertIsNone(mod._num(None))
        self.assertIsNone(mod._num(float("nan")))
        self.assertEqual(0, mod._num(0.0))
        self.assertEqual(2, mod._num(2.0))
        self.assertEqual(0.626, mod._num(0.6256))

    def test_inactive_groups_do_not_add_zero_lines(self):
        _write_artifact(self.path, [_artifact_row()])

        rows = mod.build_rows(self.path)

        self.assertEqual(1, len(rows))
        stats = rows[0]["stats"]
        self.assertEqual(3, stats["att"])
        self.assertEqual(4, stats["dropbacks"])
        self.assertEqual(0, stats["pass_td"])
        self.assertNotIn("targets", stats)
        self.assertNotIn("target_share", stats)
        self.assertNotIn("rec", stats)
        self.assertNotIn("rec_yds", stats)
        self.assertNotIn("carries", stats)

    def test_reused_week_across_season_types_fails_loud(self):
        _write_artifact(self.path, [
            _artifact_row(),
            _artifact_row(
                player_id="00-0000002",
                player_display_name="Quarterback Two",
                season_type="POST",
                game_id="2025_POST_01_X_Y",
            ),
        ])

        with self.assertRaises(RuntimeError) as ctx:
            mod.build_rows(self.path)

        message = str(ctx.exception)
        self.assertIn("week 1", message)
        self.assertIn("POST", message)
        self.assertIn("REG", message)

    def test_conversion_only_player_lands_without_a_receiving_line(self):
        _write_artifact(self.path, [_artifact_row(
            player_id="00-0000002",
            player_display_name="Conversion Receiver",
            position="TE",
            attempts=0,
            completions=0,
            passing_yards=0,
            sacks_suffered=0,
            passing_air_yards=0,
            passing_epa=0,
            carries=0,
            targets=0,
            receiving_2pt_conversions=1,
            fantasy_points=2,
            fantasy_points_ppr=2,
        )])

        rows = mod.build_rows(self.path)

        self.assertEqual(1, len(rows))
        self.assertEqual({"fpts": 2, "fpts_ppr": 2}, rows[0]["stats"])

    def test_duplicate_player_week_fails_loud(self):
        _write_artifact(self.path, [
            _artifact_row(),
            _artifact_row(game_id="2025_01_OTHER_GAME"),
        ])

        with self.assertRaises(RuntimeError) as ctx:
            mod.build_rows(self.path)

        self.assertIn("duplicate player/week", str(ctx.exception))


class UpsertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.con = sqlite3.connect(self.db)
        self.con.execute(
            """CREATE TABLE players (
                   id INTEGER PRIMARY KEY,
                   league TEXT,
                   name TEXT,
                   nfl_gsis_id TEXT
               )"""
        )
        self.con.execute(
            "INSERT INTO players VALUES (1, 'nfl', 'Quarterback One', '00-0000001')"
        )
        self.con.commit()
        mod.ensure_table(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_upsert_replaces_box_score_and_preserves_snap_ngs_keys(self):
        old_stats = {
            "attempts": 99,
            "passing_yards": 999,
            "interceptions": 9,
            "fantasy_points": 99,
            "pass_yds": 998,
            "fpts": 98,
            "off_snaps": 42,
            "off_pct": 0.8,
            "adot": 12.3,
            "separation": 2.4,
        }
        cursor = self.con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, team, opponent,
                stats, source, source_player_key)
               VALUES (1, 'nfl', 2025, '1', 'old-game', 'OLD', 'OLD', ?,
                       'nflverse_pbp', '00-0000001')""",
            (json.dumps(old_stats),),
        )
        original_id = cursor.lastrowid
        self.con.commit()
        rows = [{
            "gsis": "00-0000001",
            "week": 1,
            "game_id": "2025_01_ARI_SEA",
            "team": "SEA",
            "opponent": "ARI",
            "position": "QB",
            "stats": {
                "att": 3,
                "cmp": 2,
                "pass_yds": 25,
                "dropbacks": 4,
                "fpts": 1,
                "fpts_ppr": 1,
            },
        }]

        written, preserved_rows = mod.upsert_rows(self.con, 2025, rows)

        row = self.con.execute(
            """SELECT id, player_id, game_id, team, opponent, stats, source
               FROM player_game_logs
               WHERE league='nfl' AND season=2025
                 AND source_player_key='00-0000001' AND game_no='1'"""
        ).fetchone()
        stats = json.loads(row[5])
        self.assertEqual((1, 1), (written, preserved_rows))
        self.assertEqual(original_id, row[0])
        self.assertEqual(1, row[1])
        self.assertEqual("2025_01_ARI_SEA", row[2])
        self.assertEqual(("SEA", "ARI"), (row[3], row[4]))
        self.assertEqual(mod.SOURCE, row[6])
        self.assertEqual(25, stats["pass_yds"])
        self.assertEqual(1, stats["fpts"])
        for key in ("attempts", "passing_yards", "interceptions",
                    "fantasy_points"):
            self.assertNotIn(key, stats)
        self.assertEqual(42, stats["off_snaps"])
        self.assertEqual(0.8, stats["off_pct"])
        self.assertEqual(12.3, stats["adot"])
        self.assertEqual(2.4, stats["separation"])

    def test_postseason_rows_land_with_numeric_week_keys(self):
        artifact = os.path.join(self.tmp.name, "stats.parquet")
        rows = [_artifact_row(week=18, game_id="2025_18_A_B")]
        rows.extend(
            _artifact_row(
                player_id="00-000000{}".format(week),
                player_display_name="Postseason Player {}".format(week),
                week=week,
                season_type="POST",
                game_id="2025_{}_A_B".format(week),
            )
            for week in range(19, 23)
        )
        _write_artifact(artifact, rows)

        built = mod.build_rows(artifact)
        written, _ = mod.upsert_rows(self.con, 2025, built)

        self.assertEqual(5, written)
        landed = self.con.execute(
            """SELECT game_no, source FROM player_game_logs
               WHERE league='nfl' AND season=2025
                 AND CAST(game_no AS INTEGER) BETWEEN 19 AND 22
               ORDER BY CAST(game_no AS INTEGER)"""
        ).fetchall()
        self.assertEqual(["19", "20", "21", "22"], [row[0] for row in landed])
        self.assertEqual({mod.SOURCE}, {row[1] for row in landed})


if __name__ == "__main__":
    unittest.main()
