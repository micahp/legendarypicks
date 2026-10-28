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

def _real_data_dir():
    """The data directory holding the real databases, even from a worktree.

    A worktree's backend/data can hold a placeholder picks.db (an empty schema stub), and
    pinning against that measured the stub, not the schema that ships. So a picks.db with
    no players rows is not real; fall back to the main checkout via git's common dir.
    """
    local = os.path.join(HERE, "data")
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(os.path.join(local, "picks.db")), uri=True)
        try:
            if con.execute("SELECT COUNT(*) FROM players").fetchone()[0] > 0:
                return local
        finally:
            con.close()
    except sqlite3.Error:
        pass
    try:
        import subprocess
        # --path-format=absolute needs git 2.31; this host's git is older, so resolve the
        # (possibly relative) answer against HERE ourselves.
        common = subprocess.run(
            ["git", "-C", HERE, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return local
    common = os.path.normpath(os.path.join(HERE, common))
    return os.path.join(os.path.dirname(common), "backend", "data")


# REAL_DB is spine_merge's own default path (the fallback test asserts it); REAL_DATA is
# where the schema pins read the real databases, which differs inside a worktree.
REAL_DB = os.path.join(HERE, "data", "picks.db")
REAL_DATA = _real_data_dir()


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

    def test_sportsdataverse_log_player_id_is_discovered(self):
        import migrate_schema

        con = _fixture(":memory:")
        migration = next(
            item for item in migrate_schema.MIGRATIONS
            if item.migration_id == "20261020_001_nba_sportsdataverse_history_view"
        )
        table = next(
            item for item in migration.objects
            if item.object_type == "table"
            and item.name == "player_game_logs_sportsdataverse"
        )
        con.execute(table.sql)
        self.assertIn(
            ("player_game_logs_sportsdataverse", "player_id"),
            sm.referencing_columns(con),
        )

    @unittest.skipUnless(os.path.isfile(os.path.join(REAL_DATA, "picks.db")),
                         "needs the real database")
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
        now 16.

        2026-08-29, sport-first merge: `tennis_ranking_snapshots.player_id`
        reached dev (+1) and `player_game_logs_ufcstats.player_id` arrived with
        the UFCStats history work (+1) — a provider-separated appearance table
        that must participate like FotMob's. dev pins 18; prod holds 16 until
        the ufcstats migration runs there (16 already includes tennis)."""
        # Re-pinned 2026-09-06. This assertion is the guardrail spine_merge's docstring
        # promises: it fails when the schema grows, so a new table cannot be missed by a
        # merge. It HAD been failing, red among the "pre-existing" suite failures nobody
        # re-read, which is the same disease as an alarm that is red every run. prod gained
        # player_game_logs_usopen and tennis_ranking_snapshots; dev additionally carries
        # nfl_published_fantasy_points. All are real players.id references and are now
        # covered by discovery.
        # 2026-09-07: both gained `published_roster.player_id`, the roster-owned identity
        # binding v0.9.3 added. Discovery picking it up is the point: a merge that did not
        # repoint it would leave roster rows naming a player id that no longer exists.
        # 2026-10-21: re-pinned as exact SETS, measured on the real databases (prod 27,
        # dev 30). The 19/20 counts had been red against both since well before this, and
        # in worktrees they ran against a placeholder picks.db with 5 columns, so the
        # failure read as "environment". A count says the schema changed; a set says
        # which column, and that is the question this test exists to force.
        # dev-only: nfl_player_birth_dates and nfl_published_fantasy_points.
        # The NBA migration creates the provider-owned SportsDataverse table on both
        # databases, empty on prod until the separately approved promotion.
        shared = {
            "injury_reports", "name_alias", "nfl_adp", "nfl_depth_chart",
            "nfl_draft_notes", "nfl_dst_stats", "nfl_mock_draft_picks",
            "nfl_player_projections", "nfl_snap_counts", "player_game_availability",
            "player_game_logs", "player_game_logs_fotmob", "player_game_logs_ufcstats",
            "player_game_logs_sportsdataverse", "player_game_logs_usopen",
            "player_game_shares", "player_projection_grades",
            "player_projections", "player_source_ids", "player_stats",
            "player_team_shares", "props", "published_roster", "roster_memberships",
            "roster_snap", "tennis_atp_players", "tennis_ranking_snapshots",
            "tennis_wta_players",
        }
        expected = {
            "picks.db": shared,
            "picks.dev.db": shared | {
                "nfl_player_birth_dates", "nfl_published_fantasy_points",
            },
        }
        checked = 0
        for name, tables in expected.items():
            path = os.path.join(REAL_DATA, name)
            if not os.path.isfile(path):
                continue
            con = sqlite3.connect("file:{}?mode=ro".format(path), uri=True)
            try:
                found = sm.referencing_columns(con)
            finally:
                con.close()
            want = {(table, "player_id") for table in tables}
            self.assertEqual(set(found), want,
                             "{} player_id columns differ: added {}, missing {}".format(
                                 name, sorted(set(found) - want), sorted(want - set(found))))
            checked += 1
        self.assertGreater(checked, 0, "no real database found under {}".format(REAL_DATA))


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

    def test_apply_refuses_to_combine_conflicting_nfl_espn_and_gsis_ids(self):
        self.con.execute("ALTER TABLE players ADD COLUMN nfl_gsis_id TEXT")
        self._players(
            ("Mike Washington", "nfl", "4686658"),
            ("Mike Washington", "nfl", None),
        )
        self.con.execute(
            "UPDATE players SET nfl_gsis_id='WAS569019' WHERE id=2"
        )
        self.con.commit()
        plan = sm.MergePlan(
            merges=[sm.Merge("nfl", "Mike Washington", 1, 2, "espn_id=4686658", {})],
            columns=sm.referencing_columns(self.con),
        )

        with self.assertRaisesRegex(ValueError, "conflicting ESPN/GSIS IDs"):
            sm.apply_plan(self.con, plan)

        self.assertEqual(
            [tuple(row) for row in self.con.execute(
                "SELECT id,espn_id,nfl_gsis_id FROM players ORDER BY id"
            )],
            [(1, "4686658", None), (2, None, "WAS569019")],
        )

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

    def test_a_unique_publisher_id_is_cleared_before_it_moves(self):
        """The published spelling can be the id-less survivor.

        Assigning the drop row's id first violates UNIQUE(espn_id, league) before the
        following clear can run. The whole clone rehearsal hit this exact ordering.
        """
        self._players(("Published Spelling", "mls", None),
                      ("Alternate Spelling", "mls", "185897"))
        self.con.row_factory = sqlite3.Row
        plan = sm.MergePlan(
            merges=[sm.Merge("mls", "fotmob=1", 1, 2, "fotmob=1", {})],
            columns=sm.referencing_columns(self.con))
        with self.con:
            counts = sm.apply_plan(self.con, plan)
        self.assertEqual(counts["merged"], 1)
        self.assertEqual(
            self.con.execute("SELECT espn_id FROM players WHERE id=1").fetchone()[0],
            "185897")
        self.assertIsNone(self.con.execute("SELECT 1 FROM players WHERE id=2").fetchone())

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


class APublisherIdIsAnyPublisher(unittest.TestCase):
    """espn_id was never special; it is the one this file happened to be written around.

    player_source_ids already holds 1,470 rotowire, 131 underdog and 44 ufcstats bindings,
    and esports is 100% keyless by nature (227 cs2 and 14 valorant active on dev), so the
    espn_id-only rule could never merge an esports duplicate at all.
    """

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT,
                espn_id TEXT, mlbam_id TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, player_id INT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT);
        """)
        self.con.commit()

    def _player(self, pid, name, league="mls", espn=None, mlbam=None):
        self.con.execute("INSERT INTO players VALUES(?,?,?,?,?)",
                         (pid, name, league, espn, mlbam))

    def _bind(self, pid, source, key, league="mls"):
        self.con.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,player_id) "
            "VALUES(?,?,?,?)", (source, league, key, pid))

    def test_a_fotmob_binding_makes_a_row_resolved(self):
        """The Giovanny Sequera case: two rows, neither with an espn_id, one now carrying a
        FotMob id. Before this, spine_merge refused with 'nothing to merge into'."""
        self._player(1, "Giovanny Sequera")
        self._player(2, "Giovanny Sequera")
        self._bind(1, "fotmob", "1483557")
        self.con.execute("INSERT INTO props VALUES(10, 2)")
        self.con.commit()
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.refused, [])
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual((plan.merges[0].keep_id, plan.merges[0].drop_id), (1, 2))

    def test_a_non_espn_publisher_column_also_counts(self):
        self._player(1, "Some Batter", league="mlb", mlbam="12345")
        self._player(2, "Some Batter", league="mlb")
        self.con.commit()
        plan = sm.build_plan(self.con)
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual(plan.merges[0].keep_id, 1)

    def test_two_rows_bound_to_different_publishers_are_two_people(self):
        """Different published ids means the publisher says they are different humans."""
        self._player(1, "Common Name")
        self._player(2, "Common Name")
        self._bind(1, "fotmob", "111")
        self._bind(2, "fotmob", "222")
        self.con.commit()
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertEqual(plan.refused, [])

    def test_still_refuses_when_nothing_is_resolved(self):
        self._player(1, "Nobody Knows")
        self._player(2, "Nobody Knows")
        self.con.commit()
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.merges, [])
        self.assertIn("nothing to merge into", plan.refused[0][2])

    def test_a_database_without_player_source_ids_does_not_raise(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, player_id INT);
            INSERT INTO players VALUES(1,'A','nfl','7'), (2,'A','nfl',NULL);
        """)
        con.commit()
        self.assertEqual(len(sm.build_plan(con).merges), 1)


class APublishersSquadFindsTheDuplicateANameCannot(unittest.TestCase):
    """`Willy Kumado` and `William Kumado` are one San Diego defender.

    Grouping by name never sees them. The publisher's own squad does, and saying two rows are
    the same person because ONE publisher names them as one squad member is stricter than
    saying so because their names match.
    """

    def setUp(self):
        self.con = _fixture(":memory:")
        self.con.executescript("""
            ALTER TABLE players ADD COLUMN active INTEGER DEFAULT 1;
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
              league TEXT, source_player_key TEXT, player_id INTEGER,
              UNIQUE(source, league, source_player_key));
        """)
        import published_roster
        published_roster.ensure(self.con)
        self.con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES('mls','fotmob','1305746','William Kumado',?, 'San Diego FC','D',"
            "'Defender','now')", (published_roster.fold("William Kumado"),))
        self.con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES('mls','mlssoccer','M1','Willy Kumado',?, 'San Diego FC','D',"
            "'Defender','now')", (published_roster.fold("Willy Kumado"),))
        self.con.executemany(
            "INSERT INTO published_roster_name(league,source,source_player_key,name,name_folded) "
            "VALUES('mls','mlssoccer','M1',?,?)",
            [(name, published_roster.fold(name))
             for name in ("Willy Kumado", "William Kumado")])
        self.con.commit()

    def _two_rows(self):
        self.con.executemany(
            "INSERT INTO players(name, team, league, espn_id, active) VALUES(?,?,?,?,1)",
            [("Willy Kumado", "SD", "mls", None), ("William Kumado", "SD", "mls", "329734")])
        self.con.execute(
            "INSERT INTO player_source_ids(source, league, source_player_key, player_id) "
            "VALUES('fotmob','mls','1305746',1)")
        self.con.commit()

    def test_the_two_spellings_are_planned_as_one_merge(self):
        self._two_rows()
        plan = sm.build_plan(self.con, league="mls")
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual(plan.merges[0].drop_id, 1,
                         "the row carrying the espn_id has to be the one that survives")
        self.assertEqual(plan.merges[0].keep_id, 2)

    def test_the_merge_carries_every_identity_onto_the_survivor(self):
        """A merge that loses a publisher id leaves the person HARDER to resolve."""
        self._two_rows()
        plan = sm.build_plan(self.con, league="mls")
        with self.con:
            sm.apply_plan(self.con, plan)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
        survivor = self.con.execute("SELECT id, name, espn_id FROM players").fetchone()
        self.assertEqual(survivor[1], "William Kumado")
        self.assertEqual(survivor[2], "329734")
        self.assertEqual(
            self.con.execute("SELECT player_id FROM player_source_ids").fetchone()[0],
            survivor[0], "the fotmob binding has to follow the person")

    def test_two_keys_from_the_SAME_publisher_are_two_people(self):
        self._two_rows()
        self.con.execute("UPDATE players SET espn_id='111' WHERE id=1")
        self.con.commit()
        plan = sm.build_plan(self.con, league="mls")
        self.assertEqual(plan.merges, [])
        self.assertTrue(any("espn_id" in reason for _, _, reason in plan.refused))

    def test_a_name_in_no_published_squad_is_left_to_the_name_pass(self):
        self.con.executemany(
            "INSERT INTO players(name, team, league, espn_id, active) VALUES(?,?,?,?,1)",
            [("Nobody Published", "SD", "mls", None)])
        self.con.commit()
        self.assertEqual(sm.build_plan(self.con, league="mls").merges, [])


class RosterFilesOneNameTwice(unittest.TestCase):
    """A publisher can list one squad member twice. The roster says so; the name alone does not."""

    def setUp(self):
        self.con = _fixture(":memory:")
        self.con.executescript("""
            ALTER TABLE players ADD COLUMN active INTEGER DEFAULT 1;
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
              league TEXT, source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT,
              UNIQUE(source, league, source_player_key));
        """)
        import published_roster
        published_roster.ensure(self.con)
        self.fold = published_roster.fold

    def _player(self, name, team, espn=None):
        return self.con.execute(
            "INSERT INTO players(name, team, league, espn_id, active) VALUES(?,?,'mls',?,1)",
            (name, team, espn)).lastrowid

    def _key(self, source, key, name, roster_team, player_id=None, bind=False, code=None):
        self.con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, "
            "position, position_group, updated_at, player_id, team_code) "
            "VALUES('mls',?,?,?,?,?,'M','Midfield','now',?,?)",
            (source, key, name, self.fold(name), roster_team, player_id, code))
        if bind and player_id is not None:
            self.con.execute(
                "INSERT INTO player_source_ids(source, league, source_player_key, player_id, first_seen, last_seen) "
                "VALUES(?,'mls',?,?,'now','now')", (source, key, player_id))
        self.con.commit()

    def test_two_rows_the_roster_files_under_one_name_at_one_club_are_one_person(self):
        # The David Ruiz case: one row resolved to Miami, one to New York, the roster puts both at New York.
        old = self._player("David Ruiz", "MIA", espn="229289")
        new = self._player("David Ruiz", "Red Bull New York")
        self._key("fotmob", "1348286", "David Ruiz", "Red Bull New York", old, bind=True)
        self._key("fotmob", "1787871", "David Ruiz", "Red Bull New York", new, bind=True)
        self._key("mlssoccer", "541416", "David Ruíz", "Red Bull New York", new, bind=True)
        plan = sm.build_plan(self.con, "mls")
        self.assertEqual([(m.keep_id, m.drop_id) for m in plan.merges], [(new, old)])
        with self.con:
            sm.apply_plan(self.con, plan)
        self.assertEqual(self.con.execute("SELECT espn_id FROM players WHERE id=?", (new,)).fetchone()[0],
                         "229289", "the ESPN id travels to the survivor")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players WHERE id=?", (old,)).fetchone()[0], 0)
        self.assertEqual(self.con.execute(
            "SELECT player_id FROM player_source_ids WHERE source_player_key='1348286'").fetchone()[0], new)

    def test_two_rows_with_different_espn_ids_are_two_people_whatever_the_roster_says(self):
        old = self._player("David Ruiz", "MIA", espn="229289")
        new = self._player("David Ruiz", "Red Bull New York", espn="999111")
        self._key("fotmob", "1348286", "David Ruiz", "Red Bull New York", old, bind=True)
        self._key("fotmob", "1787871", "David Ruiz", "Red Bull New York", new, bind=True)
        plan = sm.build_plan(self.con, "mls")
        self.assertEqual(plan.merges, [])
        self.assertTrue(any("differ on these rows" in why for _, _, why in plan.refused))

    def test_a_name_the_roster_files_at_two_clubs_is_not_one_person(self):
        old = self._player("David Ruiz", "MIA")
        new = self._player("David Ruiz", "Red Bull New York")
        self._key("fotmob", "1348286", "David Ruiz", "Inter Miami CF", old, bind=True)
        self._key("fotmob", "1787871", "David Ruiz", "Red Bull New York", new, bind=True)
        self.assertEqual(sm.build_plan(self.con, "mls").merges, [])

    def test_an_unlinked_key_is_not_bound_on_name_and_club_alone(self):
        # The Zambrano case: mlssoccer lists him twice and only one of the two keys has a player row.
        # The publisher is already on him, which says only that the name and club match, so the key waits for review.
        player = self._player("Marcos Zambrano", "NE")
        self._key("fotmob", "1794408", "Marcos Zambrano", "New England Revolution", player, bind=True)
        self._key("mlssoccer", "315191673", "Marcos Zambrano", "New England Revolution", player, bind=True)
        self._key("mlssoccer", "540256", "Marcos Zambrano", "New England Revolution", None)
        plan = sm.build_plan(self.con, "mls")
        self.assertEqual(plan.merges, [])
        self.assertEqual(plan.binds, [])
        self.assertTrue(any("540256" in why and "name and club only" in why for _, _, why in plan.refused))
        self.assertIsNone(self.con.execute(
            "SELECT player_id FROM published_roster WHERE source_player_key='540256'").fetchone()[0])

    def test_the_name_and_club_bind_is_kept_behind_a_switch(self):
        player = self._player("Marcos Zambrano", "NE")
        self._key("fotmob", "1794408", "Marcos Zambrano", "New England Revolution", player, bind=True)
        self._key("mlssoccer", "315191673", "Marcos Zambrano", "New England Revolution", player, bind=True)
        self._key("mlssoccer", "540256", "Marcos Zambrano", "New England Revolution", None)
        sm.BIND_BY_NAME_AND_CLUB = True
        try:
            plan = sm.build_plan(self.con, "mls")
        finally:
            sm.BIND_BY_NAME_AND_CLUB = False
        self.assertEqual([(b.source, b.key, b.player_id) for b in plan.binds],
                         [("mlssoccer", "540256", player)])

    def test_an_unlinked_key_from_a_publisher_the_player_does_not_hold_is_not_bound(self):
        player = self._player("Marcos Zambrano", "NE")
        self._key("fotmob", "1794408", "Marcos Zambrano", "New England Revolution", player, bind=True)
        self._key("sportsdataverse", "77", "Marcos Zambrano", "New England Revolution", None)
        plan = sm.build_plan(self.con, "mls")
        self.assertEqual(plan.binds, [])
        self.assertTrue(any("lists no key" in why for _, _, why in plan.refused))

    def test_a_row_is_on_its_roster_club_by_code_as_well_as_by_name(self):
        # Real rows: players.team is the club code (RBNY) and the roster carries both the code and the name.
        old = self._player("David Ruiz", "MIA", espn="229289")
        new = self._player("David Ruiz", "RBNY")
        self._key("fotmob", "1348286", "David Ruiz", "Red Bull New York", old, bind=True, code="RBNY")
        self._key("fotmob", "1787871", "David Ruiz", "Red Bull New York", new, bind=True, code="RBNY")
        plan = sm.build_plan(self.con, "mls")
        self.assertEqual([(m.keep_id, m.drop_id) for m in plan.merges], [(new, old)])


class LeaguesCupBorrowsItsOwner(unittest.TestCase):
    """Leagues Cup has no players of its own. Its keys bind to the MLS or Liga MX player they name."""

    def setUp(self):
        self.con = _fixture(":memory:")
        self.con.executescript("""
            ALTER TABLE players ADD COLUMN active INTEGER DEFAULT 1;
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
              league TEXT, source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT,
              UNIQUE(source, league, source_player_key));
        """)
        import published_roster
        published_roster.ensure(self.con)
        self.fold = published_roster.fold

    def _player(self, name, team, league):
        return self.con.execute(
            "INSERT INTO players(name, team, league, active) VALUES(?,?,?,1)", (name, team, league)).lastrowid

    def _key(self, league, source, key, name, team, player_id):
        self.con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, "
            "position, position_group, updated_at, player_id) VALUES(?,?,?,?,?,?,'F','Forward','now',?)",
            (league, source, key, name, self.fold(name), team, player_id))
        self.con.commit()

    def test_a_leagues_cup_key_is_not_bound_to_the_mls_player_on_name_and_club_alone(self):
        owner = self._player("Thayllon", "LAFC", "mls")
        self._key("mls", "fotmob", "1259117", "Thayllon", "Los Angeles FC", owner)
        self._key("lcup", "fotmob", "1259117", "Thayllon", "Los Angeles FC", owner)
        self._key("lcup", "fotmob", "1738398", "Thayllon", "Los Angeles FC", None)
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.binds, [])
        self.assertTrue(any("1738398" in why and "name and club only" in why for _, _, why in plan.refused))
        self.assertIsNone(self.con.execute(
            "SELECT player_id FROM published_roster WHERE league='lcup' AND source_player_key='1738398'"
        ).fetchone()[0])

    def test_a_key_that_names_a_player_in_another_league_is_reported_not_skipped(self):
        owner = self._player("Hugo Rodriguez", "Club Leon", "ligamx")
        self._key("ligamx", "fotmob", "900", "Hugo Rodriguez", "Club Leon", owner)
        self._key("mls", "fotmob", "901", "Hugo Rodriguez", "Club Leon", None)
        plan = sm.build_plan(self.con)
        self.assertEqual(plan.binds, [])
        self.assertTrue(any("not bound across leagues" in why for _, _, why in plan.refused))
