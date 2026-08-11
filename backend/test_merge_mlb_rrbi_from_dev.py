#!/usr/bin/env python3

import json
import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import merge_mlb_rrbi_from_dev as merge


def _create_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,
          name TEXT,
          league TEXT,
          mlbam_id INTEGER
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
          UNIQUE(league,source_player_key,season,game_no)
        );
        """
    )
    con.close()


def _insert_log(con, row_id, player_id, key, game_no, stats, source="statcast"):
    con.execute(
        """
        INSERT INTO player_game_logs
          (id,player_id,league,season,game_no,game_id,game_date,stats,source,
           source_player_key,ingested_at)
        VALUES(?,?,'mlb',2026,?,?,?, ?,?,?, '2026-07-26T00:00:00Z')
        """,
        (
            row_id,
            player_id,
            game_no,
            "game-{}".format(row_id),
            game_no,
            json.dumps(stats),
            source,
            key,
        ),
    )


class MlbMergeTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        for _ in range(2):
            handle = tempfile.NamedTemporaryFile(
                prefix="mlb-merge-", suffix=".db", delete=False
            )
            handle.close()
            self.paths.append(handle.name)
            _create_db(handle.name)
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
            return merge.build_plan(prod, dev)
        finally:
            prod.close()
            dev.close()

    def test_json_union_adds_missing_keys_and_production_wins_collision(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute("INSERT INTO players VALUES(1,'Two Way','mlb',111)")
        _insert_log(
            prod,
            1,
            1,
            "111",
            "2026-07-01",
            {"K": 0, "outs": 3, "hits_allowed": 0},
            source="statcast_pitcher",
        )
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.execute("INSERT INTO players VALUES(10,'Two Way','mlb',111)")
        _insert_log(
            dev,
            10,
            10,
            "111",
            "2026-07-01",
            {"H": 1, "K": 2, "R": 1, "RBI": 2},
        )
        dev.commit()
        dev.close()

        plan = self._plan()

        self.assertEqual(1, len(plan.updates))
        self.assertEqual(1, len(plan.collision_rows))
        merged = json.loads(plan.updates[0].new_stats)
        self.assertEqual(
            {"H": 1, "K": 0, "R": 1, "RBI": 2, "hits_allowed": 0, "outs": 3},
            merged,
        )

    def test_exact_rrbi_update_and_unresolved_insert_remains_null(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute("INSERT INTO players VALUES(1,'Resolved','mlb',111)")
        _insert_log(prod, 1, 1, "111", "2026-07-01", {"H": 2})
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.executemany(
            "INSERT INTO players VALUES(?,?, 'mlb',?)",
            [(10, "Resolved", 111), (20, "Unresolved", 222)],
        )
        _insert_log(
            dev,
            10,
            10,
            "111",
            "2026-07-01",
            {"H": 2, "R": 1, "RBI": 3},
        )
        _insert_log(
            dev,
            20,
            20,
            "222",
            "2026-07-02",
            {"H": 1, "R": 0, "RBI": 0},
        )
        dev.commit()
        dev.close()

        plan = self._plan()

        self.assertEqual(1, plan.exact_rrbi_updates)
        self.assertEqual(1, len(plan.inserts))
        self.assertIsNone(plan.inserts[0].player_id)
        self.assertEqual({"222": "Unresolved"}, plan.unresolved_player_keys)

    def test_existing_log_link_selects_canonical_duplicate_mlbam_player(self):
        prod = sqlite3.connect(self.prod_path)
        prod.executemany(
            "INSERT INTO players VALUES(?,?, 'mlb',111)",
            [(1, "Duplicate"), (2, "Existing Log Spine")],
        )
        _insert_log(prod, 1, 2, "111", "2026-07-01", {"H": 2})
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.execute("INSERT INTO players VALUES(10,'Dev Player','mlb',111)")
        _insert_log(
            dev,
            10,
            10,
            "111",
            "2026-07-01",
            {"H": 2, "R": 1, "RBI": 3},
        )
        _insert_log(
            dev,
            11,
            10,
            "111",
            "2026-07-02",
            {"H": 1, "R": 0, "RBI": 1},
        )
        dev.commit()
        dev.close()

        plan = self._plan()

        self.assertEqual([], plan.player_identity_conflicts)
        self.assertEqual(1, plan.resolved_player_keys)
        self.assertEqual(2, plan.inserts[0].player_id)

    def test_apply_executes_planned_union_and_insert(self):
        prod = sqlite3.connect(self.prod_path)
        prod.execute("INSERT INTO players VALUES(1,'Resolved','mlb',111)")
        _insert_log(prod, 1, 1, "111", "2026-07-01", {"H": 2})
        prod.commit()
        prod.close()

        dev = sqlite3.connect(self.dev_path)
        dev.execute("INSERT INTO players VALUES(10,'Resolved','mlb',111)")
        _insert_log(
            dev,
            10,
            10,
            "111",
            "2026-07-01",
            {"H": 2, "R": 1, "RBI": 3},
        )
        _insert_log(
            dev,
            11,
            10,
            "111",
            "2026-07-02",
            {"H": 1, "R": 0, "RBI": 1},
        )
        dev.commit()
        dev.close()
        plan = self._plan()

        result = merge.apply_plan(self.prod_path, plan)

        self.assertEqual({"updated": 1, "inserted": 1}, result)
        con = sqlite3.connect(self.prod_path)
        rows = con.execute(
            "SELECT game_no,stats FROM player_game_logs ORDER BY game_no"
        ).fetchall()
        con.close()
        self.assertEqual(2, len(rows))
        self.assertEqual({"H": 2, "R": 1, "RBI": 3}, json.loads(rows[0][1]))
        self.assertEqual({"H": 1, "R": 0, "RBI": 1}, json.loads(rows[1][1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
