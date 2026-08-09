#!/usr/bin/env python3
"""Tests for migrate_league_position_groups: NFL/NBA group-column split."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import migrate_league_position_groups as m


def _make_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE players(
            id INTEGER PRIMARY KEY,
            name TEXT, league TEXT NOT NULL, team TEXT,
            position TEXT, position_group TEXT, active INTEGER,
            entity_type TEXT, espn_id TEXT, nba_id TEXT, nfl_gsis_id TEXT,
            nhl_id TEXT
        );
    """)
    return con


class PositionGroupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="posgroup-test-")
        self.db = os.path.join(self.tempdir.name, "picks.db")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_group_map_has_the_overlap_pairs(self):
        nfl = m._group_map("nfl")
        nba = m._group_map("nba")
        # The two gate failures must be resolved:
        self.assertEqual(nfl["FB"], "Offense")   # FB was "under RB"
        self.assertEqual(nba["PF"], "Forward")   # PF was "under F"
        # Top-level categories:
        self.assertEqual(nfl["WR"], "Offense")
        self.assertEqual(nfl["CB"], "Defense")
        self.assertEqual(nfl["PK"], "Special Teams")
        self.assertEqual(nba["SG"], "Guard")
        self.assertEqual(nba["C"], "Center")

    def test_apply_populates_all_active_players(self):
        con = _make_db(self.db)
        for position in ("WR", "FB", "PK", "CB", "C", "G", "QB", "RB", "TE", "LS", "P"):
            con.execute("INSERT INTO players(name, league, team, position, active, entity_type) "
                        "VALUES(?, 'nfl', 'X', ?, 1, 'player')", ("P", position))
        # a fantasy construct: no position, no group, not a blank
        con.execute("INSERT INTO players(name, league, team, position, active, entity_type) "
                    "VALUES('D/ST', 'nfl', 'BUF', NULL, 1, 'team_defense')")
        con.commit()
        con.close()

        result = m.migrate(self.db, apply=True)
        self.assertEqual(result, 0)

        con = sqlite3.connect(self.db)
        blank = con.execute(
            "SELECT COUNT(*) FROM players WHERE league='nfl' AND active=1 "
            "AND entity_type='player' AND (position_group IS NULL OR TRIM(position_group)='')"
        ).fetchone()[0]
        self.assertEqual(blank, 0)
        self.assertEqual(con.execute(
            "SELECT position_group FROM players WHERE position='FB'").fetchone()[0], "Offense")
        self.assertEqual(con.execute(
            "SELECT position_group FROM players WHERE position='PK'").fetchone()[0], "Special Teams")
        con.close()

    def test_dry_run_writes_nothing(self):
        con = _make_db(self.db)
        con.execute("INSERT INTO players(name, league, team, position, active, entity_type) "
                    "VALUES('P', 'nfl', 'X', 'WR', 1, 'player')")
        con.commit()
        con.close()
        result = m.migrate(self.db, apply=False)
        self.assertEqual(result, 0)
        con = sqlite3.connect(self.db)
        self.assertIsNone(con.execute(
            "SELECT position_group FROM players WHERE position='WR'").fetchone()[0])
        con.close()

    def test_idempotent(self):
        con = _make_db(self.db)
        con.execute("INSERT INTO players(name, league, team, position, active, entity_type) "
                    "VALUES('P', 'nfl', 'X', 'WR', 1, 'player')")
        con.commit()
        con.close()
        self.assertEqual(m.migrate(self.db, apply=True), 0)
        self.assertEqual(m.migrate(self.db, apply=True), 0)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute(
            "SELECT position_group FROM players WHERE position='WR'").fetchone()[0], "Offense")
        con.close()

    def test_missing_column_refused(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, "
                    "league TEXT, position TEXT, active INTEGER)")
        con.close()
        self.assertEqual(m.migrate(self.db, apply=True), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
