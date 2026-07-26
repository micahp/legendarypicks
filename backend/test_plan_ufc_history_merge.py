#!/usr/bin/env python3

import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import plan_ufc_history_merge as merge


def _make_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          team TEXT,
          league TEXT NOT NULL,
          espn_id TEXT,
          active INTEGER DEFAULT 1
        );
        CREATE TABLE player_game_logs(
          id INTEGER PRIMARY KEY,
          player_id INTEGER,
          league TEXT NOT NULL,
          season INTEGER NOT NULL,
          game_no TEXT,
          game_id TEXT,
          game_date TEXT,
          team TEXT,
          opponent TEXT,
          home_away TEXT,
          stats TEXT NOT NULL,
          source TEXT,
          source_player_key TEXT,
          ingested_at TEXT,
          UNIQUE(league, source_player_key, season, game_no)
        );
        """
    )
    con.close()


def _insert_log(
    con,
    row_id,
    player_id,
    athlete_id,
    game_no,
    stats='{"sigStrikesLanded":10}',
    game_id=None,
):
    con.execute(
        """
        INSERT INTO player_game_logs
          (id,player_id,league,season,game_no,game_id,game_date,opponent,stats,
           source,source_player_key)
        VALUES(?,?,'ufc',2026,?,?,?,?,?,'espn_mma_stats',?)
        """,
        (
            row_id,
            player_id,
            game_no,
            game_id or "fight-{}".format(row_id),
            game_no,
            "Opponent",
            stats,
            athlete_id,
        ),
    )


class UfcHistoryMergePlanTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        for _ in range(2):
            handle = tempfile.NamedTemporaryFile(
                prefix="ufc-merge-", suffix=".db", delete=False
            )
            handle.close()
            self.paths.append(handle.name)
            _make_db(handle.name)
        self.prod_path, self.dev_path = self.paths
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in self.paths:
            if os.path.exists(path):
                os.unlink(path)

    def _plan(self):
        prod = sqlite3.connect(self.prod_path)
        prod.row_factory = sqlite3.Row
        dev = sqlite3.connect(self.dev_path)
        dev.row_factory = sqlite3.Row
        try:
            return merge.build_merge_plan(prod, dev)
        finally:
            prod.close()
            dev.close()

    def test_plans_identity_fill_new_fighter_and_additive_rows(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute(
            "INSERT INTO players(id,name,league,espn_id) VALUES(1,'Current Fighter','ufc',NULL)"
        )
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.executemany(
            "INSERT INTO players(id,name,league,espn_id) VALUES(?,?,'ufc',?)",
            [
                (10, "Current Fighter", None),
                (20, "Prior Fighter", "222"),
            ],
        )
        _insert_log(dev, 100, 10, "111", "2026-01-01")
        _insert_log(dev, 200, 20, "222", "2026-02-02")
        dev.commit()
        dev.close()

        plan = self._plan()

        self.assertEqual(2, plan.source_rows)
        self.assertEqual(2, plan.source_fighters)
        self.assertEqual(1, len(plan.identity_fills))
        self.assertEqual("111", plan.identity_fills[0].athlete_id)
        self.assertEqual(1, len(plan.new_players))
        self.assertEqual("222", plan.new_players[0].athlete_id)
        self.assertEqual(2, len(plan.planned_logs))
        self.assertEqual([], plan.identity_conflicts)

    def test_existing_identical_row_is_not_planned_again(self):
        for path in (self.prod_path, self.dev_path):
            con = sqlite3.connect(path)
            con.execute(
                "INSERT INTO players(id,name,league,espn_id) VALUES(1,'Fighter','ufc','111')"
            )
            _insert_log(con, 1, 1, "111", "2026-01-01")
            con.commit()
            con.close()

        plan = self._plan()

        self.assertEqual(1, plan.exact_identity_matches)
        self.assertEqual(1, plan.existing_identical)
        self.assertEqual([], plan.planned_logs)

    def test_existing_collision_is_reported_and_production_wins(self):
        for path, stats in (
            (self.prod_path, '{"value":"prod"}'),
            (self.dev_path, '{"value":"dev"}'),
        ):
            con = sqlite3.connect(path)
            con.execute(
                "INSERT INTO players(id,name,league,espn_id) VALUES(1,'Fighter','ufc','111')"
            )
            _insert_log(con, 1, 1, "111", "2026-01-01", stats=stats)
            con.commit()
            con.close()

        plan = self._plan()

        self.assertEqual(1, len(plan.skipped_collisions))
        self.assertEqual([], plan.planned_logs)

    def test_conflicting_production_identity_blocks_source_fighter(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute(
            "INSERT INTO players(id,name,league,espn_id) VALUES(1,'Fighter','ufc','different')"
        )
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.execute(
            "INSERT INTO players(id,name,league,espn_id) VALUES(2,'Fighter','ufc',NULL)"
        )
        _insert_log(dev, 2, 2, "111", "2026-01-01")
        dev.commit()
        dev.close()

        plan = self._plan()

        self.assertEqual(1, len(plan.identity_conflicts))
        self.assertEqual([], plan.planned_logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
