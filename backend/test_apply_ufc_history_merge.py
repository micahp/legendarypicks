#!/usr/bin/env python3

import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import apply_ufc_history_merge as apply_merge
import plan_ufc_history_merge as merge
from test_plan_ufc_history_merge import _insert_log, _make_db


class UfcHistoryApplyTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        for _ in range(2):
            handle = tempfile.NamedTemporaryFile(
                prefix="ufc-apply-", suffix=".db", delete=False
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

    def test_apply_fills_identity_creates_player_and_inserts_logs(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute(
            """
            INSERT INTO players(id,name,league,espn_id)
            VALUES(1,'Current Fighter','ufc',NULL)
            """
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

        result = apply_merge.apply_merge_plan(self.prod_path, plan)

        self.assertEqual(
            {"identity_fills": 1, "players_created": 1, "logs_inserted": 2},
            result,
        )
        con = sqlite3.connect(self.prod_path)
        players = con.execute(
            "SELECT name,espn_id FROM players ORDER BY name"
        ).fetchall()
        logs = con.execute(
            """
            SELECT p.name,l.source_player_key,l.game_no
            FROM player_game_logs l JOIN players p ON p.id=l.player_id
            ORDER BY p.name
            """
        ).fetchall()
        con.close()
        self.assertEqual(
            [("Current Fighter", "111"), ("Prior Fighter", "222")],
            players,
        )
        self.assertEqual(
            [
                ("Current Fighter", "111", "2026-01-01"),
                ("Prior Fighter", "222", "2026-02-02"),
            ],
            logs,
        )

    def test_apply_refuses_identity_conflict_without_writing(self):
        plan = merge.MergePlan(
            identity_conflicts=["conflict"],
            identity_actions={
                "111": merge.IdentityAction("111", "Fighter", "create_player", None)
            },
        )

        with self.assertRaisesRegex(RuntimeError, "validation failed"):
            apply_merge.apply_merge_plan(self.prod_path, plan)

        con = sqlite3.connect(self.prod_path)
        count = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        con.close()
        self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
