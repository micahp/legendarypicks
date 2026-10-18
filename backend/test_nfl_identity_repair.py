import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

import nfl_identity_repair as repair  # noqa: E402


REGISTER = [
    {
        "gsis_id": "00-0000001", "espn_id": "100", "esb_id": "ESB-100",
        "nfl_id": None, "pfr_id": None, "pff_id": None, "otc_id": None,
        "smart_id": None, "display_name": "A Player", "position": "WR",
    },
    {
        "gsis_id": "00-0000002", "espn_id": "200", "esb_id": "ESB-200",
        "nfl_id": None, "pfr_id": None, "pff_id": None, "otc_id": None,
        "smart_id": None, "display_name": "B Player", "position": "RB",
    },
    {
        "gsis_id": "00-0000003", "espn_id": None, "esb_id": None,
        "nfl_id": None, "pfr_id": None, "pff_id": None, "otc_id": None,
        "smart_id": None, "display_name": "Already Valid", "position": "WR",
    },
    {
        "gsis_id": "00-0000004", "espn_id": "400", "esb_id": None,
        "nfl_id": None, "pfr_id": None, "pff_id": None, "otc_id": None,
        "smart_id": None, "display_name": "C Player", "position": "TE",
    },
    {
        "gsis_id": "00-0000005", "espn_id": "500", "esb_id": None,
        "nfl_id": None, "pfr_id": None, "pff_id": None, "otc_id": None,
        "smart_id": None, "display_name": "Old Player", "position": "RB",
    },
]


SCHEMA = """
CREATE TABLE players(
  id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT,
  nfl_gsis_id TEXT, position TEXT
);
CREATE TABLE player_source_ids(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, league TEXT NOT NULL,
  source_player_key TEXT NOT NULL, player_id INTEGER NOT NULL,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  UNIQUE(source,league,source_player_key)
);
CREATE TABLE player_game_logs(
  id INTEGER PRIMARY KEY, player_id INTEGER, league TEXT, season INTEGER,
  stats TEXT, source TEXT, source_player_key TEXT
);
CREATE TABLE player_game_shares(
  league TEXT, season INTEGER, week INTEGER, game_id TEXT, team TEXT,
  player_id INTEGER, metric TEXT, share REAL, player_value REAL,
  team_value REAL, source TEXT, built_at TEXT,
  PRIMARY KEY(league,game_id,team,player_id,metric)
);
CREATE TABLE player_stats(id INTEGER PRIMARY KEY, player_id INTEGER, stats TEXT);
CREATE TABLE props(id INTEGER PRIMARY KEY, player_id INTEGER, line REAL);
"""


class NFLIdentityRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nfl-identity-repair-")
        self.addCleanup(self.temp.cleanup)
        self.source_path = os.path.join(self.temp.name, "source.db")
        self.copy_path = os.path.join(self.temp.name, "copy.db")
        self.register_path = os.path.join(self.temp.name, "players.parquet")
        with open(self.register_path, "wb") as handle:
            handle.write(b"test register checksum")
        self.con = sqlite3.connect(self.source_path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?,?)",
            [
                (1, "A Player", "nfl", "100", "old-espn-key", "WR"),
                (2, "B Player", "nfl", None, "ESB-200", "RB"),
                (3, "C Player", "nfl", None, "opaque-key", "TE"),
                # A name match without a stable source ID is not a repair bridge.
                (4, "A Player", "nfl", None, "name-only-key", "WR"),
                (5, "Already Valid", "nfl", None, "00-0000003", "WR"),
            ],
        )
        self.con.execute(
            "INSERT INTO player_game_logs VALUES(1,1,'nfl',2026,'{}','nflverse_weekly','00-0000001')"
        )
        self.con.execute(
            "INSERT INTO player_game_shares VALUES"
            "('nfl',2026,1,'g1','AAA',1,'targets',0.5,5,10,'nflverse_weekly','now')"
        )
        self.con.execute("INSERT INTO player_stats VALUES(1,1,'{}')")
        self.con.execute("INSERT INTO props VALUES(1,1,10.5)")
        self.con.commit()

    def _plan(self):
        return repair.build_plan(
            self.con, self.source_path, self.register_path, REGISTER
        )

    def test_plan_uses_source_ids_and_never_name_matches(self):
        plan = self._plan()
        actions = {row["player_id"]: row for row in plan["actions"]}

        self.assertEqual("00-0000001", actions[1]["new_gsis_id"])
        self.assertEqual(["espn_id"], actions[1]["matched_by"])
        self.assertEqual(repair.LEGACY_SOURCE, actions[1]["legacy_source"])
        self.assertEqual("00-0000002", actions[2]["new_gsis_id"])
        self.assertEqual(["esb_id"], actions[2]["matched_by"])
        self.assertEqual("esb", actions[2]["legacy_source"])
        self.assertIsNone(actions[3]["new_gsis_id"])
        self.assertIsNone(actions[4]["new_gsis_id"])
        self.assertNotIn(5, actions)
        self.assertEqual(0, plan["scope"]["blocked"])

    def test_copy_apply_preserves_legacy_ids_shares_and_player_references(self):
        plan = self._plan()
        baseline_shares = repair._table_fingerprint(self.con, "player_game_shares")
        copy_con = sqlite3.connect(self.copy_path)
        self.con.backup(copy_con)
        copy_con.close()

        result = repair.apply_plan_to_copy(self.copy_path, plan, REGISTER)

        self.assertEqual("ok", result["quick_check"])
        self.assertEqual(4, result["updated_players"])
        self.assertEqual(4, result["inserted_crosswalk_rows"])
        check = sqlite3.connect(self.copy_path)
        self.addCleanup(check.close)
        self.assertEqual(
            baseline_shares,
            repair._table_fingerprint(check, "player_game_shares"),
        )
        self.assertEqual(
            [(1, "00-0000001"), (2, "00-0000002"), (3, None), (4, None),
             (5, "00-0000003")],
            check.execute("SELECT id,nfl_gsis_id FROM players ORDER BY id").fetchall(),
        )
        self.assertEqual(
            [("legacy_nfl_gsis_id", "old-espn-key", 1),
             ("esb", "ESB-200", 2),
             ("legacy_nfl_gsis_id", "opaque-key", 3),
             ("legacy_nfl_gsis_id", "name-only-key", 4)],
            check.execute(
                "SELECT source,source_player_key,player_id FROM player_source_ids "
                "ORDER BY player_id"
            ).fetchall(),
        )

    def test_duplicate_target_owner_blocks_instead_of_reparenting(self):
        self.con.execute(
            "INSERT INTO players VALUES(6,'Other Row','nfl',NULL,'00-0000001','WR')"
        )
        self.con.commit()
        plan = self._plan()

        self.assertEqual(1, plan["scope"]["blocked"])
        self.assertIn("spine_merge", plan["blocked"][0]["reason"])
        with self.assertRaisesRegex(repair.RepairError, "identity/ownership conflicts"):
            repair.apply_plan_to_copy(self.source_path, plan, REGISTER)

    def test_stable_id_name_disagreement_is_cleared_not_forced(self):
        self.con.execute(
            "UPDATE players SET name='Different Person' WHERE id=1"
        )
        self.con.commit()
        plan = self._plan()
        action = next(row for row in plan["actions"] if row["player_id"] == 1)

        self.assertIsNone(action["new_gsis_id"])
        self.assertIn("publisher name does not match", action["reason"])

    def test_publisher_valid_but_wrong_gsis_is_reconciled_by_espn_id(self):
        self.con.execute(
            "UPDATE players SET name='C Player',espn_id='400',"
            "nfl_gsis_id='00-0000005',position='TE' WHERE id=4"
        )
        self.con.commit()
        plan = self._plan()
        action = next(row for row in plan["actions"] if row["player_id"] == 4)

        self.assertEqual("00-0000004", action["new_gsis_id"])
        self.assertEqual("legacy_nfl_gsis_id", action["legacy_source"])
        self.assertEqual(
            "existing published GSIS belongs to another publisher identity",
            action["reason"],
        )


if __name__ == "__main__":
    unittest.main()
