#!/usr/bin/env python3
"""The retired duplicate NFL aggregate writer can never mutate a DB."""

import os
import sqlite3
import tempfile
import unittest

import ingest_nfl


class RetiredNflAggregateIngestTests(unittest.TestCase):
    def test_call_leaves_existing_database_unchanged(self):
        handle = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        handle.close()
        try:
            with sqlite3.connect(handle.name) as connection:
                connection.execute(
                    "CREATE TABLE sentinel(value TEXT)"
                )
                connection.execute(
                    "INSERT INTO sentinel VALUES('keep')"
                )
            with open(handle.name, "rb") as database:
                before = database.read()
            self.assertEqual(ingest_nfl.ingest_nfl(2025), 0)
            with open(handle.name, "rb") as database:
                after = database.read()
            self.assertEqual(after, before)
        finally:
            os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main()
