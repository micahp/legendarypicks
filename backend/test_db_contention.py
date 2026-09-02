"""Prod served HTTP 500 because SQLite gave up waiting for a lock after 5 seconds.

Measured 2026-08-19. `legendarypicks-props-prod` exited 3 with "2 of 14 mlb games
failed to POST"; underneath was `sqlite3.OperationalError: database is locked` coming
back out of the API as a 500. It was contention, not a standing condition: the unit ran
clean nine times in a row and then failed on the first run that overlapped other writes
to `picks.db`. Two things were true at once, and both are pinned here.

1. Prod was in `journal_mode=delete` while dev was in `wal`. Under `delete` a writer
   takes an exclusive lock on the whole database and every reader waits, so prod's
   API reads, the per-minute `scoreboard_snapshots` writer and the 30-minute props
   ingest all serialised against each other. Dev never reproduced it, which is the
   `dev_fix_prod_never_ran` shape wearing a different hat.
2. Every connection took SQLite's default 5-second busy timeout, so whoever lost the
   race raised rather than waited.

The tests below are deliberately about OBSERVABLE state, not about the constants. A
test that asserts `BUSY_TIMEOUT_SECONDS == 30` passes even if nothing ever passes it to
`connect()`, which is the defect it is supposed to catch.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The default this whole file exists because of. If a future SQLite changes it, these
# tests should still be measuring "longer than the default", not "longer than 5".
SQLITE_DEFAULT_BUSY_TIMEOUT_MS = 5000


def _busy_timeout_ms(connection):
    return int(connection.execute("PRAGMA busy_timeout").fetchone()[0])


class BusyTimeoutTests(unittest.TestCase):
    """The two helpers on the hot path must wait rather than raise.

    `_core._db` is the API's connection helper, imported by 61 non-test modules, and
    `scoreboard_store._db` is the per-minute writer. Those are the two ends of the
    contention that produced the 500s, which is why these two are pinned by name
    rather than all 176 `sqlite3.connect(` sites in the tree.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="lp-contention-", suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self._previous = os.environ.get("LP_DB_PATH")
        os.environ["LP_DB_PATH"] = self.db_path

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("LP_DB_PATH", None)
        else:
            os.environ["LP_DB_PATH"] = self._previous

    def test_scoreboard_store_waits_longer_than_the_sqlite_default(self):
        import scoreboard_store

        with scoreboard_store._db() as connection:
            self.assertGreater(
                _busy_timeout_ms(connection),
                SQLITE_DEFAULT_BUSY_TIMEOUT_MS,
                "the per-minute snapshot writer is back on the 5s default that made "
                "prod's props ingest 500",
            )

    def test_core_db_waits_longer_than_the_sqlite_default(self):
        # _core imports fastapi and the whole router surface, so it is imported inside
        # the test rather than at module scope: a collection-time ImportError here would
        # take the file down for a reason that has nothing to do with locking.
        import _core

        # _core.DB is read at import time, so point the helper at the temp file the
        # same way the module itself resolves it.
        previous = _core.DB
        _core.DB = self.db_path
        self.addCleanup(setattr, _core, "DB", previous)

        with _core._db() as connection:
            self.assertGreater(
                _busy_timeout_ms(connection),
                SQLITE_DEFAULT_BUSY_TIMEOUT_MS,
                "the API's connection helper is back on the 5s default; this is the "
                "one that surfaced as HTTP 500 to the props scraper",
            )


class WalSelfHealTests(unittest.TestCase):
    """A database the API opens must end up in WAL, even if it arrives in `delete`.

    Prod was flipped by hand. Nothing in code held that invariant, so a restore from a
    pre-2026-08-19 backup would have put it straight back to `delete` and reopened the
    500s with no diff to point at. `_init_db` now repairs it on startup.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="lp-wal-heal-", suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        self.addCleanup(self._cleanup)

        # Arrive in the mode prod was actually in, so this test starts where the
        # defect started rather than where we want to end up.
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=delete")
        connection.execute("CREATE TABLE canary(id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()

    def _cleanup(self):
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_a_delete_mode_database_is_repaired_to_wal(self):
        import _core

        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        self.assertEqual(
            "delete",
            connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
            "fixture is not in delete mode; test proves nothing",
        )

        self.assertEqual("wal", _core.ensure_wal(connection))

        # And it must persist on the file, not just on this connection.
        connection.close()
        reopened = sqlite3.connect(self.db_path)
        self.addCleanup(reopened.close)
        self.assertEqual(
            "wal", reopened.execute("PRAGMA journal_mode").fetchone()[0].lower()
        )


class JournalModeGuardTests(unittest.TestCase):
    """A scheduled apply must not refuse a WAL production database.

    `apply_plan` and `apply_merge_plan` both asserted `journal_mode == "delete"` before
    `BEGIN IMMEDIATE`. That was never a durability property -- BEGIN IMMEDIATE behaves
    the same in both modes -- it was an environment assertion, true only because prod
    happened to be `delete` and dev happened to be `wal`. Moving prod to WAL would have
    failed every scheduled history refresh for a property nobody was testing.
    """

    def setUp(self):
        from test_run_mlb_daily_history_ingest import _create_db

        handle = tempfile.NamedTemporaryFile(
            prefix="lp-wal-guard-", suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        self.addCleanup(self._cleanup)
        _create_db(self.db_path)

        # _create_db sets journal_mode=delete, which is what prod used to be. Flip it to
        # what prod actually is now.
        connection = sqlite3.connect(self.db_path)
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        connection.close()
        self.assertEqual("wal", mode, "fixture failed to enter WAL; test proves nothing")

    def _cleanup(self):
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_mlb_history_apply_accepts_a_wal_production_database(self):
        import run_mlb_daily_history_ingest as runner

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        plan = runner.build_plan(connection, "2026-07-25", set(), [])
        connection.close()

        # The assertion is simply that this does not raise. Against the old guard it
        # raised RuntimeError("production journal_mode is wal, expected delete").
        result = runner.apply_plan(self.db_path, plan)

        self.assertEqual({"updated": 0, "inserted": 0, "queued": 0}, result)

    def test_off_is_still_refused(self):
        """The guard must not have been widened into no guard at all.

        `journal_mode=off` discards the journal, so a crash mid-apply leaves a
        half-written production database with no way back. That is the case the check
        was worth having for.
        """
        from history_refresh_common import ROLLBACK_SAFE_JOURNAL_MODES

        self.assertNotIn("off", ROLLBACK_SAFE_JOURNAL_MODES)
        self.assertIn("wal", ROLLBACK_SAFE_JOURNAL_MODES)
        self.assertIn("delete", ROLLBACK_SAFE_JOURNAL_MODES)


if __name__ == "__main__":
    unittest.main()
