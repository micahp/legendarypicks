#!/usr/bin/env python3
"""NFL transaction refresh materializes before writing."""

import sqlite3
import unittest
import urllib.error
from unittest import mock

import nfl_transactions_sync as transactions


def _transaction(description="Signed Fixture Player"):
    return {
        "date": "2026-07-28",
        "description": description,
        "team": {
            "id": "22",
            "abbreviation": "ARI",
            "displayName": "Arizona Cardinals",
        },
    }


class NflTransactionsSyncTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def _table_exists(self):
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='nfl_transactions'"
        ).fetchone() is not None

    def test_later_page_failure_writes_nothing(self):
        def fetch(page):
            if page == 1:
                return {
                    "pageCount": 2,
                    "transactions": [_transaction()],
                }
            raise urllib.error.URLError("upstream down")

        with mock.patch.object(
            transactions, "_fetch_page", side_effect=fetch
        ):
            result = transactions.sync(
                self.connection, full=True
            )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["inserted"], 0)
        self.assertFalse(self._table_exists())

    def test_invalid_row_writes_nothing(self):
        with mock.patch.object(
            transactions,
            "_fetch_page",
            return_value={
                "pageCount": 1,
                "transactions": [{"date": "2026-07-28"}],
            },
        ):
            result = transactions.sync(self.connection, pages=1)
        self.assertEqual(result["status"], "error")
        self.assertFalse(self._table_exists())

    def test_success_commits_complete_deduplicated_snapshot(self):
        rows = [_transaction(), _transaction()]
        with mock.patch.object(
            transactions,
            "_fetch_page",
            return_value={"pageCount": 1, "transactions": rows},
        ):
            result = transactions.sync(self.connection, pages=1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["total_rows"], 1)


if __name__ == "__main__":
    unittest.main()
