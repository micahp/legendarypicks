#!/usr/bin/env python3
"""Tests for the generic spine merge.

The point of this file is the REFUSALS and the column discovery. A merge that runs is
easy; a merge that quietly orphans rows in a table nobody remembered is the failure mode
that five one-off dedupers already shipped.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import spine_merge as sm

REAL_DB = os.path.join(HERE, "data", "picks.db")


def _fixture(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE players(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          team TEXT, league TEXT NOT NULL, espn_id TEXT, UNIQUE(espn_id, league));
        CREATE TABLE props(id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER REFERENCES players(id), market TEXT);
        -- No foreign key, on purpose: 9 of the 14 real tables are like this, so the
        -- discovery must not depend on one being declared.
        CREATE TABLE nfl_snap_counts(id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER, snaps INTEGER);
        -- A publisher's id, NOT ours. Rewriting it would corrupt the identity this
        -- repair exists to consolidate.
        CREATE TABLE nfl_adp(id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER, espn_player_id TEXT);
        """
    )
    con.commit()
    return con


class ColumnDiscoveryTests(unittest.TestCase):
    def test_discovery_finds_unenforced_columns_not_just_foreign_keys(self):
        con = _fixture(":memory:")
        found = sm.referencing_columns(con)
        self.assertIn(("props", "player_id"), found)
        self.assertIn(("nfl_snap_counts", "player_id"), found)

    def test_a_publishers_id_column_is_never_rewritten(self):
        con = _fixture(":memory:")
        found = sm.referencing_columns(con)
        self.assertIn(("nfl_adp", "player_id"), found)
        self.assertNotIn(("nfl_adp", "espn_player_id"), found)

    def test_players_itself_is_not_a_target(self):
        con = _fixture(":memory:")
        self.assertEqual([t for t, _c in sm.referencing_columns(con) if t == "players"], [])

    @unittest.skipUnless(os.path.isfile(REAL_DB), "needs the real database")
    def test_the_installed_schemas_are_pinned_and_agree(self):
        """Pinned deliberately, and checked on BOTH databases.

        When someone adds a table with a player_id this fails and they have to decide
        whether the merge should reach it; a repair that silently stops covering a new
        table is the defect being fixed here.

        Measured 2026-08-24: prod had 14 and dev 15. Dev alone carries
        `nfl_published_fantasy_points.player_id`, so a repair verified on dev touches a
        table prod does not have, and one verified on prod has never exercised that
        column. That asymmetry is recorded here rather than averaged away.

        2026-08-26, +1 each: `player_game_logs_fotmob.player_id`. FotMob moved to its
        own table so `player_game_logs` could go back to one row per appearance, and
        this gate is what forced the question it exists to force -- should the merge
        reach it? Yes. Its rows are keyed to the same spine by an accent-folded name,
        and a merge that skipped them would strand every FotMob appearance on a
        player_id nothing points at any more. `referencing_columns` finds it without a
        change, because it discovers columns rather than reading a list.

        2026-08-27, dev +1: `player_game_logs_rotowire.player_id` is another
        provider-separated appearance table and must participate in an identity
        merge. The worktree production-shaped database also gained
        `tennis_ranking_snapshots.player_id`, so its independently pinned total is
        now 16."""
        expected = {"picks.db": 16, "picks.dev.db": 17}
        for name, count in expected.items():
            path = os.path.join(HERE, "data", name)
            if not os.path.isfile(path):
                continue
            con = sqlite3.connect("file:{}?mode=ro".format(path), uri=True)
            try:
                found = sm.referencing_columns(con)
                self.assertEqual(len(found), count,
                                 "{} has {} player_id columns, expected {}: {}".format(
                                     name, len(found), count, found))
            finally:
                con.close()


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.con = _fixture(":memory:")

    def _players(self, *rows):
        self.con.executemany(
            "INSERT INTO players(name, league, espn_id) VALUES(?,?,?)", rows)
        self.con.commit()

    def test_the_id_less_row_merges_into_the_resolved_one(self):
        self._players(("Aleksandr Rakic", "ufc", None), ("Aleksandr Rakic", "ufc", "4079314"))
        self.con.execute("INSERT INTO props(player_id, market) VALUES(1,'m')")
        self.con.execute("INSERT INTO nfl_snap_counts(player_id, snaps) VALUES(1,5)")
        self.con.commit()
        plan = sm.build_plan(self.con)
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual((plan.merges[0].keep_id, plan.merges[0].drop_id), (2, 1))
        with self.con:
            counts = sm.apply_plan(self.con, plan)
        self.assertEqual(counts["merged"], 1)
        self.assertEqual(self.con.execute("SELECT player_id FROM props").fetchone()[0], 2)
        self.assertEqual(
            self.con.execute("SELECT player_id FROM nfl_snap_counts").fetchone()[0], 2,
            "a table with no foreign key must still be repointed")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)

    def test_no_reference_is_left_pointing_at_the_deleted_row(self):
        self._players(("A", "ufc", None), ("A", "ufc", "1"))
        for t in ("props", "nfl_snap_counts", "nfl_adp"):
            self.con.execute("INSERT INTO {}(player_id) VALUES(1)".format(t))
        self.con.commit()
        plan = sm.build_plan(self.con)
        with self.con:
            sm.apply_plan(self.con, plan)
        for table, col in plan.columns:
            orphans = self.con.execute(
                "SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c} NOT IN "
                "(SELECT id FROM players)".format(t=table, c=col)).fetchone()[0]
            self.assertEqual(orphans, 0, "{}.{} left an orphan".format(table, col))

    def test_two_real_players_with_distinct_ids_are_left_alone(self):
        """NFL has 442 such groups and NCAAF 171. They are the spine working."""
        self._players(("Josh Allen", "nfl", "1"), ("Josh Allen", "nfl", "2"))
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertEqual(plan.refused, [])

    def test_two_id_carrying_rows_and_one_without_refuses(self):
        self._players(("A", "nfl", "1"), ("A", "nfl", "2"), ("A", "nfl", None))
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertIn("which one survives is a guess", plan.refused[0][2])

    def test_two_id_less_rows_refuse_because_the_direction_is_a_guess(self):
        self._players(("A", "nfl", "1"), ("A", "nfl", None), ("A", "nfl", None))
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertIn("which merges in is a guess", plan.refused[0][2])

    def test_all_unresolved_refuses_because_there_is_nothing_to_merge_into(self):
        self._players(("A", "nfl", None), ("A", "nfl", None))
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertIn("nothing to merge into", plan.refused[0][2])

    def test_a_different_league_with_the_same_name_is_a_different_person(self):
        self._players(("A", "nfl", None), ("A", "mlb", "1"))
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])

    def test_running_twice_is_a_no_op(self):
        self._players(("A", "ufc", None), ("A", "ufc", "1"))
        plan = sm.build_plan(self.con)
        with self.con:
            sm.apply_plan(self.con, plan)
        second = sm.build_plan(self.con)
        self.assertEqual(second.merges, [])

    def test_league_filter_restricts_the_plan(self):
        self._players(("A", "ufc", None), ("A", "ufc", "1"),
                      ("B", "nfl", None), ("B", "nfl", "2"))
        self.assertEqual({m.league for m in sm.build_plan(self.con, league="ufc").merges},
                         {"ufc"})

    def test_a_dry_run_writes_nothing(self):
        self._players(("A", "ufc", None), ("A", "ufc", "1"))
        path = os.path.join(tempfile.mkdtemp(), "d.db")
        disk = _fixture(path)
        disk.executemany("INSERT INTO players(name, league, espn_id) VALUES(?,?,?)",
                         [("A", "ufc", None), ("A", "ufc", "1")])
        disk.commit()
        disk.close()
        self.assertEqual(sm.main(["--db", path]), 0)
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)
        con.close()


if __name__ == "__main__":
    unittest.main()


class DatabaseSelectionTests(unittest.TestCase):
    """Which database a destructive tool resolves to is part of its contract.

    Shipped 2026-08-24 defaulting to data/picks.db and ignoring LP_DB_PATH, the
    variable every other tool on this box is pointed with. So
    `LP_DB_PATH=data/picks.dev.db spine_merge.py --apply` read as a dev
    rehearsal and would have merged rows in PROD. It went unnoticed because
    both environments answered, and answering is not the same as answering
    about the right database: dev plans 259 merges and prod 447, and the bug
    reported 447 for both.
    """

    def setUp(self):
        self._saved = os.environ.get("LP_DB_PATH")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("LP_DB_PATH", None)
        else:
            os.environ["LP_DB_PATH"] = self._saved

    def _parsed(self, argv):
        """Parse exactly as main() does, without connecting to anything."""
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--db", default=(os.environ.get("LP_DB_PATH")
                                         or os.path.join(sm.HERE, "data", "picks.db")))
        return ap.parse_args(argv)

    def test_lp_db_path_is_honoured(self):
        os.environ["LP_DB_PATH"] = "/tmp/some-dev.db"
        self.assertEqual(self._parsed([]).db, "/tmp/some-dev.db")

    def test_an_explicit_db_flag_still_wins(self):
        os.environ["LP_DB_PATH"] = "/tmp/some-dev.db"
        self.assertEqual(self._parsed(["--db", "/tmp/other.db"]).db, "/tmp/other.db")

    def test_the_fallback_is_prod_only_when_nothing_was_said(self):
        os.environ.pop("LP_DB_PATH", None)
        self.assertEqual(self._parsed([]).db, REAL_DB)

    def test_main_reads_the_database_lp_db_path_names(self):
        """The end-to-end version: main() must plan against the named DB.

        The parser tests above would still pass if main() built its own
        connection from somewhere else, which is exactly the shape that made
        this bug invisible.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "named.db")
            _fixture(path)
            os.environ["LP_DB_PATH"] = path
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = sm.main([])
            self.assertEqual(rc, 0)
            self.assertIn(os.path.abspath(path), buf.getvalue())
            self.assertNotIn("picks.db", buf.getvalue())

    def test_the_reported_path_is_absolute(self):
        """A relative path in a log does not identify a database.

        `data/picks.dev.db` resolves against the cwd, and telling two
        environments apart by how good their data looks is how a frozen
        snapshot passed for dev once already.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "named.db")
            _fixture(path)
            os.environ["LP_DB_PATH"] = os.path.relpath(path)
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sm.main([])
            printed = [ln for ln in buf.getvalue().splitlines() if ln.startswith("db: ")][0]
            self.assertTrue(printed[4:].startswith("/"), printed)
