"""Tests for additive NFL play-by-play retention.

No network: nfl_data_py.import_pbp_data is replaced with a synthetic frame. Backfill tests write a small parquet with pyarrow.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nfl_pbp_logs as mod


def _play(play_id, **overrides):
    row = {column: None for column in mod._PLAY_COLS}
    row.update({
        "game_id": "2025_01_ARI_SEA",
        "play_id": play_id,
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "posteam": "SEA",
        "defteam": "ARI",
        "home_team": "SEA",
        "away_team": "ARI",
        "game_date": "2025-09-07",
        "qtr": 1,
        "down": 1,
        "ydstogo": 10,
        "yardline_100": 75,
        "game_seconds_remaining": 3600,
        "play_type": "pass",
        "epa": 0.5,
        "wpa": 0.02,
        "qb_epa": 0.5,
        "air_yards": 12.0,
        "yards_gained": 12,
        "cpoe": 3.1,
        "passer_player_id": "00-0000001",
        "receiver_player_id": "00-0000002",
        "pass_location": "left",
        "complete_pass": 1,
        "touchdown": 0,
        "series": 1,
        "series_result": "First down",
        "drive": 1,
        "success": 1,
        "shotgun": 1,
        "sack": 0,
        "two_point_attempt": 0,
        "pass_attempt": 1,
        "rush_attempt": 0,
        "passing_yards": 12.0,
        "rushing_yards": 0.0,
        "receiving_yards": 12.0,
        "pass_touchdown": 0,
        "rush_touchdown": 0,
        "interception": 0,
    })
    row.update(overrides)
    return row


def _frame():
    import pandas as pd

    return pd.DataFrame([
        _play(1),
        _play(
            2,
            play_type="run",
            epa=-0.2,
            wpa=-0.01,
            qb_epa=0.0,
            air_yards=None,
            yards_gained=3,
            cpoe=None,
            passer_player_id=None,
            rusher_player_id="00-0000003",
            receiver_player_id=None,
            pass_location=None,
            run_location="middle",
            run_gap="guard",
            complete_pass=0,
            success=0,
            shotgun=0,
            pass_attempt=0,
            rush_attempt=1,
            passing_yards=0.0,
            rushing_yards=3.0,
            receiving_yards=0.0,
        ),
        _play(
            3,
            posteam="ARI",
            defteam="SEA",
            passer_player_id="00-0000004",
            receiver_player_id="00-0000005",
            air_yards=5.0,
            yards_gained=8,
            passing_yards=8.0,
            receiving_yards=8.0,
        ),
        _play(4, season_type="POST"),
    ])


class PbpRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.original_db = mod.DB
        mod.DB = self.db

        import nfl_data_py

        self.original_import = nfl_data_py.import_pbp_data
        nfl_data_py.import_pbp_data = lambda years: _frame()

    def tearDown(self):
        import nfl_data_py

        nfl_data_py.import_pbp_data = self.original_import
        mod.DB = self.original_db
        self.tmp.cleanup()

    def _run(self):
        retained = mod.ingest(2025)
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return retained, con

    def test_plays_are_retained_and_regular_season_only(self):
        retained, con = self._run()
        self.assertEqual(3, retained)
        self.assertEqual(3, con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0])
        self.assertEqual(
            [2025],
            [row[0] for row in con.execute("SELECT DISTINCT season FROM nfl_pbp")],
        )
        con.close()

    def test_retained_table_has_the_curated_fifty_six_columns(self):
        _, con = self._run()
        columns = [
            row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)").fetchall()
        ]
        con.close()
        self.assertEqual(56, len(columns))
        self.assertEqual(mod._PLAY_COLS, columns)

    def test_retained_play_keeps_chart_fields(self):
        _, con = self._run()
        row = con.execute("SELECT * FROM nfl_pbp WHERE play_id=1").fetchone()
        con.close()
        self.assertEqual(0.5, row["epa"])
        self.assertEqual(12.0, row["air_yards"])
        self.assertEqual(1, row["down"])
        self.assertEqual(10, row["ydstogo"])
        self.assertIsNone(row["run_gap"])
        self.assertEqual("00-0000002", row["receiver_player_id"])
        self.assertEqual("First down", row["series_result"])

    def test_missing_source_column_fails_loud(self):
        import nfl_data_py

        nfl_data_py.import_pbp_data = lambda years: _frame().drop(
            columns=["run_gap"]
        )
        with self.assertRaises(RuntimeError) as ctx:
            mod.ingest(2025)
        self.assertIn("run_gap", str(ctx.exception))

    def test_rerunning_does_not_duplicate_plays(self):
        mod.ingest(2025)
        retained = mod.ingest(2025)
        self.assertEqual(3, retained)
        con = sqlite3.connect(self.db)
        self.assertEqual(3, con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0])
        con.close()

    def test_ingest_does_not_create_player_game_logs(self):
        _, con = self._run()
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        con.close()
        self.assertNotIn("player_game_logs", tables)


# xpass and pass_oe came after the four flags; an old table lacks all six, and ensure_pbp_table widens it.
_NEWER = ["xpass", "pass_oe"]
OLD_COLS = [c for c in mod._PLAY_COLS if c not in mod._ADDED_COLS and c not in _NEWER]
STORED = [
    {"game_id": "2025_01_ARI_SEA", "play_id": 1.0, "season": 2025, "play_type": "pass", "epa": 0.5},
    {"game_id": "2025_01_ARI_SEA", "play_id": 2.0, "season": 2025, "play_type": "run", "epa": -0.2},
    {"game_id": "2025_01_ARI_SEA", "play_id": 3.0, "season": 2025, "play_type": None, "epa": None},
]
FILE = [
    {"game_id": "2025_01_ARI_SEA", "play_id": 1.0, "season": 2025,
     "qb_hit": 1.0, "qb_scramble": 0.0, "qb_dropback": 1.0, "no_huddle": 0.0},
    {"game_id": "2025_01_ARI_SEA", "play_id": 2.0, "season": 2025,
     "qb_hit": 0.0, "qb_scramble": 1.0, "qb_dropback": 1.0, "no_huddle": 1.0},
    {"game_id": "2025_01_ARI_SEA", "play_id": 3.0, "season": 2025,
     "qb_hit": None, "qb_scramble": 0.0, "qb_dropback": None, "no_huddle": 0.0},
    {"game_id": "2025_19_ARI_SEA", "play_id": 1.0, "season": 2025, "season_type": "POST",
     "qb_hit": 1.0, "qb_scramble": 0.0, "qb_dropback": 1.0, "no_huddle": 0.0},
]


def _old_table(db, plays):
    """nfl_pbp as the dev DB stores it before the added columns."""
    con = sqlite3.connect(db)
    quoted = ", ".join('"{}"'.format(c) for c in OLD_COLS)
    con.execute("CREATE TABLE nfl_pbp ({}, UNIQUE(game_id, play_id))".format(quoted))
    for play in plays:
        row = {c: None for c in OLD_COLS}
        row.update(play)
        con.execute("INSERT INTO nfl_pbp ({}) VALUES ({})".format(
            quoted, ", ".join("?" for _ in OLD_COLS)), [row[c] for c in OLD_COLS])
    con.commit()
    con.close()


def _file(path, plays):
    """A published-shaped parquet. epa is 9.9 so a writer that copies whole rows is caught."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = ["game_id", "play_id", "season", "season_type", "epa"] + mod._ADDED_COLS
    data = {c: [] for c in cols}
    for play in plays:
        row = {"season_type": "REG", "epa": 9.9}
        row.update(play)
        for c in cols:
            data[c].append(row.get(c))
    pq.write_table(pa.table(data), path)


class PbpBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "dev.db")
        self.file = os.path.join(self.tmp.name, "play_by_play_2025.parquet")

    def tearDown(self):
        self.tmp.cleanup()

    def _con(self):
        return sqlite3.connect(self.db, isolation_level=None)

    def _columns(self):
        con = sqlite3.connect(self.db)
        cols = [row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)")]
        con.close()
        return cols

    def _rows(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        rows = {row["play_id"]: dict(row) for row in con.execute("SELECT * FROM nfl_pbp")}
        con.close()
        return rows

    def test_widening_an_old_table_appends_the_added_columns_last(self):
        _old_table(self.db, STORED)
        con = self._con()
        mod.ensure_pbp_table(con)
        con.close()
        self.assertEqual(mod._PLAY_COLS, self._columns())
        self.assertEqual(0.5, self._rows()[1.0]["epa"])
        self.assertIsNone(self._rows()[1.0]["qb_hit"])

    def test_dry_run_writes_nothing(self):
        _old_table(self.db, STORED)
        _file(self.file, FILE)
        con = self._con()
        report = mod.backfill_columns(con, self.file, 2025)
        con.close()
        self.assertEqual(3, report["matched"])
        self.assertEqual(OLD_COLS, self._columns())

    def test_apply_fills_only_the_added_columns(self):
        _old_table(self.db, STORED)
        _file(self.file, FILE)
        con = self._con()
        report = mod.backfill_columns(con, self.file, 2025, apply=True)
        con.close()
        rows = self._rows()
        self.assertEqual(3, len(rows))  # the POST play is not inserted
        added = lambda pid: tuple(rows[pid][c] for c in mod._ADDED_COLS)
        self.assertEqual((1.0, 0.0, 1.0, 0.0), added(1.0))
        self.assertEqual((0.0, 1.0, 1.0, 1.0), added(2.0))
        self.assertEqual((None, 0.0, None, 0.0), added(3.0))
        self.assertEqual(0.5, rows[1.0]["epa"])  # the file's 9.9 is not copied
        self.assertEqual({"null": 1, "one": 1}, report["qb_hit"])
        self.assertEqual(1.0, report["aligned_qb_hit"])

    def test_a_stored_play_missing_from_the_file_writes_nothing(self):
        _old_table(self.db, STORED)
        _file(self.file, FILE[:2] + FILE[3:])
        con = self._con()
        with self.assertRaises(RuntimeError) as ctx:
            mod.backfill_columns(con, self.file, 2025, apply=True)
        con.close()
        self.assertIn("stored plays are not in the file", str(ctx.exception))
        self.assertEqual(OLD_COLS, self._columns())

    def test_unstored_file_plays_need_allow_new_games_and_a_new_game(self):
        _old_table(self.db, STORED)
        _file(self.file, FILE + [dict(FILE[0], game_id="2025_02_SEA_ARI")])
        con = self._con()
        with self.assertRaises(RuntimeError):
            mod.backfill_columns(con, self.file, 2025)
        report = mod.backfill_columns(con, self.file, 2025, apply=True, allow_new_games=True)
        con.close()
        self.assertEqual(["2025_02_SEA_ARI"], report["new_games_skipped"])
        self.assertEqual(3, len(self._rows()))

    def test_a_missing_play_inside_a_stored_game_is_refused_even_with_allow_new_games(self):
        _old_table(self.db, STORED)
        _file(self.file, FILE + [dict(FILE[0], play_id=99.0)])
        con = self._con()
        with self.assertRaises(RuntimeError) as ctx:
            mod.backfill_columns(con, self.file, 2025, apply=True, allow_new_games=True)
        con.close()
        self.assertIn("missing from stored games", str(ctx.exception))

    def test_a_value_outside_zero_one_null_is_refused(self):
        _old_table(self.db, STORED)
        _file(self.file, [dict(FILE[0], qb_hit=2.0)] + FILE[1:])
        con = self._con()
        with self.assertRaises(RuntimeError):
            mod.backfill_columns(con, self.file, 2025)
        con.close()

    def test_a_file_from_another_season_is_refused(self):
        _old_table(self.db, STORED)
        _file(self.file, [dict(play, season=2024) for play in FILE])
        con = self._con()
        with self.assertRaises(RuntimeError):
            mod.backfill_columns(con, self.file, 2025)
        con.close()

    def test_values_on_the_wrong_kind_of_play_roll_back(self):
        _old_table(self.db, [dict(STORED[0], play_type="kickoff")] + STORED[1:])
        _file(self.file, FILE)
        con = self._con()
        with self.assertRaises(RuntimeError) as ctx:
            mod.backfill_columns(con, self.file, 2025, apply=True)
        con.close()
        self.assertIn("qb_hit", str(ctx.exception))
        self.assertTrue(all(row["qb_hit"] is None for row in self._rows().values()))

    def test_cli_refuses_picks_db(self):
        _file(self.file, FILE)
        old = os.environ.get("LP_DB_PATH")
        os.environ["LP_DB_PATH"] = os.path.join(self.tmp.name, "picks.db")
        try:
            with self.assertRaises(SystemExit):
                mod.main(["--backfill-file", self.file, "--season", "2025"])
        finally:
            if old is None:
                os.environ.pop("LP_DB_PATH")
            else:
                os.environ["LP_DB_PATH"] = old


if __name__ == "__main__":
    unittest.main()
