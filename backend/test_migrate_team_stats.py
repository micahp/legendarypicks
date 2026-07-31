"""test_migrate_team_stats.py -- fail-closed + scope tests for the Team Stats
migration (v0.6.13 scope item 4).

Proves:
- the migration refuses a production-looking target;
- a dry run writes nothing;
- a happy-path migration copies exactly the approved windows and commits
  atomically (results + stats + coverage for all three leagues);
- an induced failure mid-copy rolls back EVERYTHING (no partial replacement);
- a re-run on an already-populated target is a no-op.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import migrate_team_stats_from_dev as mts

DEV_DB = "/root/legendarypicks/backend/data/picks.dev.db"


def _count(con: sqlite3.Connection, table: str, where: str = "1=1",
            params: tuple = ()) -> int:
    return con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


class MigrationScopeTests(unittest.TestCase):
    def test_refuses_production_looking_target(self):
        with tempfile.NamedTemporaryFile(suffix="picks.db", delete=False) as f:
            fake = f.name
        try:
            rc = mts.main(["--target", fake, "--source", DEV_DB])
            self.assertEqual(rc, 2)
        finally:
            os.unlink(fake)

    def test_dry_run_writes_nothing(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            target = f.name
        try:
            rc = mts.main(["--target", target, "--source", DEV_DB, "--dry-run"])
            self.assertEqual(rc, 0)
            con = sqlite3.connect(target)
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "team_game_results" in tables:
                self.assertEqual(
                    _count(con, "team_game_results"), 0,
                    "dry run must not write data rows")
            con.close()
        finally:
            os.unlink(target)


@unittest.skipUnless(os.path.exists(DEV_DB), "DEV data set not present")
class MigrationCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.unlink(cls.tmp.name)
        cls.target = cls.tmp.name
        rc = mts.main(["--target", cls.target, "--source", DEV_DB])
        assert rc == 0, f"migration failed rc={rc}"

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.target)

    def test_approved_windows_copied_exactly(self):
        con = sqlite3.connect(self.target)
        for league, spec in mts.APPROVED.items():
            n_results = _count(
                con, "team_game_results",
                f"league='{league}' AND season={spec['season']}")
            self.assertEqual(n_results, spec["results"],
                             f"{league} results")
            n_coverage = _count(
                con, "team_stats_coverage",
                f"league='{league}' AND season={spec['season']}")
            self.assertEqual(n_coverage, 1, f"{league} coverage")
            # every stats row belongs to an approved game
            game_ids = [r[0] for r in con.execute(
                "SELECT DISTINCT game_id FROM team_game_results "
                f"WHERE league='{league}' AND season={spec['season']}")]
            ph = ",".join("?" for _ in game_ids)
            n_stats = _count(
                con, "team_game_stats",
                f"league='{league}' AND game_id IN ({ph})", tuple(game_ids))
            self.assertEqual(n_stats, spec["results"], f"{league} stats")
            # no stats rows outside the approved games
            n_outside = con.execute(
                f"SELECT COUNT(*) FROM team_game_stats s WHERE s.league='{league}' "
                f"AND s.game_id NOT IN ({ph})", game_ids).fetchone()[0]
            self.assertEqual(n_outside, 0, f"{league} stats outside window")
        con.close()

    def test_unique_index_built(self):
        con = sqlite3.connect(self.target)
        idx = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_tgs_unique'").fetchone()
        self.assertIsNotNone(idx)
        # inserting a duplicate key must fail (constraint is live)
        row = con.execute(
            "SELECT * FROM team_game_stats WHERE league='nba' LIMIT 1").fetchone()
        cols = [d[1] for d in con.execute("PRAGMA table_info(team_game_stats)")]
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                f"INSERT INTO team_game_stats ({','.join(cols)}) "
                f"VALUES ({','.join('?' for _ in cols)})", tuple(row))
        con.close()

    def test_re_run_is_noop(self):
        con = sqlite3.connect(self.target)
        before = _count(con, "team_game_results")
        con.close()
        rc = mts.main(["--target", self.target, "--source", DEV_DB])
        self.assertEqual(rc, 0)
        con = sqlite3.connect(self.target)
        after = _count(con, "team_game_results")
        con.close()
        self.assertEqual(before, after)


@unittest.skipUnless(os.path.exists(DEV_DB), "DEV data set not present")
class MigrationRollbackTests(unittest.TestCase):
    def test_midcopy_failure_rolls_back_everything(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            target = f.name
        try:
            # Copy DEV to a temp SOURCE and break only the copy — never DEV.
            import shutil
            broken_src = target + ".broken-src.db"
            shutil.copy(DEV_DB, broken_src)
            bcon = sqlite3.connect(broken_src)
            bcon.execute("DELETE FROM team_game_results WHERE league='nhl'")
            bcon.commit()
            bcon.close()

            con = sqlite3.connect(target)
            mts._ensure_schema(con)
            con.close()

            rc = mts.main(["--target", target, "--source", broken_src])
            self.assertNotEqual(rc, 0)
            con = sqlite3.connect(target)
            nba = _count(con, "team_game_results", "league='nba' AND season=2026")
            nfl = _count(con, "team_game_results", "league='nfl' AND season=2025")
            nhl = _count(con, "team_game_results", "league='nhl' AND season=2026")
            self.assertEqual((nba, nfl, nhl), (0, 0, 0),
                             "partial copy survived a rollback")
            con.close()
            os.unlink(broken_src)
        finally:
            os.unlink(target)


if __name__ == "__main__":
    unittest.main()
