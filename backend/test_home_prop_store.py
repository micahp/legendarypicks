"""The stored homepage prop preview: the endpoint reads it, and the refresh script writes it on a 7-day cycle.

Temp DB only. Each test plants a stored row, then checks what the endpoint or the refresh does with it.
"""
import contextlib
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="home-store-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import home_prop_refresh as refresh  # noqa: E402
import migrate_schema  # noqa: E402
from routers import home  # noqa: E402

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)


def block(reason):
    return {"prop": None, "history": None, "reason": reason}


def keep_open(con):
    return contextlib.nullcontext(con)


class StoredPreview(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(prefix="home-store-", suffix=".db", delete=False)
        tmp.close()
        self.path = tmp.name
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        migration = next(
            item for item in migrate_schema.MIGRATIONS
            if item.migration_id == "20261017_001_home_prop_cache"
        )
        self.con.execute(migration.create_sql)

    def tearDown(self):
        self.con.close()
        os.unlink(self.path)

    def test_endpoint_serves_the_stored_preview_and_selects_nothing(self):
        home.prop_cache_write(self.con, NOW, block("stored"))
        with mock.patch.object(home, "featured_prop", side_effect=AssertionError("selected on request")), \
             mock.patch.object(home, "featured_game", return_value={"game": None, "reason": "none"}), \
             mock.patch.object(home, "featured_playoffs", return_value={"playoff_odds": None, "reason": "none"}), \
             mock.patch.object(home, "featured_record", return_value={"record": None, "reason": "none"}), \
             mock.patch.object(home, "_db", return_value=self.con), \
             mock.patch.object(home, "closing", keep_open), \
             mock.patch.dict(home._cache, {"at": 0.0, "payload": None}):
            body = json.loads(home.home_featured().body)
        self.assertIsNone(body["prop"])
        self.assertEqual(body["absent"]["prop"], "stored")

    def test_endpoint_says_no_preview_is_stored_yet(self):
        with mock.patch.object(home, "featured_prop", side_effect=AssertionError("selected on request")), \
             mock.patch.object(home, "featured_game", return_value={"game": None, "reason": "none"}), \
             mock.patch.object(home, "featured_playoffs", return_value={"playoff_odds": None, "reason": "none"}), \
             mock.patch.object(home, "featured_record", return_value={"record": None, "reason": "none"}), \
             mock.patch.object(home, "_db", return_value=self.con), \
             mock.patch.object(home, "closing", keep_open), \
             mock.patch.dict(home._cache, {"at": 0.0, "payload": None}):
            body = json.loads(home.home_featured().body)
        self.assertIsNone(body["prop"])
        self.assertEqual(body["absent"]["prop"], home.NO_PREVIEW["reason"])

    def run_refresh(self, args, now, reason):
        with mock.patch.object(refresh, "_db", return_value=self.con), \
             mock.patch.object(refresh, "closing", keep_open), \
             mock.patch.object(home, "_now", return_value=now), \
             mock.patch.object(home, "featured_prop", return_value=block(reason)) as select:
            code = refresh.main(args)
        return code, select.call_count

    def test_refresh_leaves_a_preview_under_seven_days_old(self):
        home.prop_cache_write(self.con, NOW - dt.timedelta(days=6), block("old"))
        code, calls = self.run_refresh(["--apply"], NOW, "new")
        self.assertEqual((code, calls), (0, 0))
        self.assertEqual(home.prop_cache_read(self.con)[1]["reason"], "old")

    def test_refresh_replaces_a_preview_over_seven_days_old(self):
        home.prop_cache_write(self.con, NOW - dt.timedelta(days=8), block("old"))
        code, calls = self.run_refresh(["--apply"], NOW, "new")
        self.assertEqual((code, calls), (0, 1))
        stored_at, stored = home.prop_cache_read(self.con)
        self.assertEqual(stored["reason"], "new")
        self.assertEqual(stored_at, home._iso(NOW))

    def test_dry_run_selects_but_stores_nothing(self):
        code, calls = self.run_refresh([], NOW, "new")
        self.assertEqual((code, calls), (0, 1))
        self.assertIsNone(home.prop_cache_read(self.con))

    def test_registry_dry_run_does_not_store_even_with_apply_flag(self):
        code, calls = self.run_refresh(["--apply", "--dry-run"], NOW, "new")
        self.assertEqual((code, calls), (0, 1))
        self.assertIsNone(home.prop_cache_read(self.con))


if __name__ == "__main__":
    unittest.main()
